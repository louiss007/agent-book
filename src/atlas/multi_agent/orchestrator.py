from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

from atlas.agent.policy import BudgetStopPolicy, RunState
from atlas.agent.runner import AgentRunner
from atlas.llm.base import LLM
from atlas.multi_agent.board import SharedBoard
from atlas.types import (
    Budget,
    Message,
    RunContext,
    Step,
    StopReason,
    Trajectory,
    Usage,
    utcnow,
)

Strategy = Literal["pipeline", "supervisor", "debate", "chat"]
Synthesizer = Callable[[str, list[tuple[str, str]]], str]

_FINAL_MARKER = re.compile(
    r"^\s*(?:FINAL|FINAL_ANSWER)\s*[:：]\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)


class Supervisor(Protocol):
    """编排决策：根据任务、共享黑板与已完成角色，选择下一个执行者。"""

    def choose(
        self,
        task: str,
        board: SharedBoard,
        done: set[str],
    ) -> str | None:
        ...


class ScriptedSupervisor:
    """按脚本返回角色名；用于离线演示与测试。"""

    def __init__(self, decisions: Sequence[str]) -> None:
        self._decisions = list(decisions)
        self.calls: list[tuple[str, ...]] = []
        self.decisions: list[str] = []

    def choose(
        self,
        task: str,
        board: SharedBoard,
        done: set[str],
    ) -> str | None:
        self.calls.append(tuple(sorted(done)))
        if not self._decisions:
            return None
        decision = self._decisions.pop(0).strip()
        if decision.lower() in {"", "done", "stop"}:
            return None
        self.decisions.append(decision)
        return decision


class LLMSupervisor:
    """用一次模型调用做编排决策；解析失败时退回可用角色中的第一个。"""

    def __init__(
        self,
        llm: LLM,
        roles: Sequence[str],
        *,
        max_decisions: int = 8,
    ) -> None:
        self.llm = llm
        self.roles = tuple(roles)
        self.max_decisions = max_decisions
        self.decisions: list[str] = []

    def choose(
        self,
        task: str,
        board: SharedBoard,
        done: set[str],
    ) -> str | None:
        available = [name for name in self.roles if name not in done]
        if not available or len(self.decisions) >= self.max_decisions:
            return None

        response = self.llm.complete(
            [
                Message(
                    role="system",
                    content=(
                        "你是多智能体编排器。只决定下一个执行角色，"
                        "不直接回答用户任务。只输出 JSON。"
                    ),
                ),
                Message(
                    role="user",
                    content=(
                        f"任务：{task}\n\n"
                        f"可用角色：{', '.join(available)}\n"
                        f"已完成：{', '.join(sorted(done)) or '（无）'}\n\n"
                        "当前共享产物：\n"
                        f"{board.render(max_entries=8, max_chars=300)}\n\n"
                        '输出格式：{"next": "角色名"}；'
                        '任务已足够时输出 {"next": "done"}。'
                    ),
                ),
            ]
        )
        decision = self._parse(response.content or "", available)
        self.decisions.append(decision or "done")
        return decision

    @staticmethod
    def _parse(text: str, available: list[str]) -> str | None:
        match = re.search(r'"next"\s*:\s*"([^"]+)"', text)
        if not match:
            return available[0]
        value = match.group(1).strip()
        if value.lower() in {"done", "stop"}:
            return None
        return value if value in available else available[0]


@dataclass
class _RunStats:
    steps: list[Step] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    step_count: int = 0
    tool_calls: int = 0
    last_error: str | None = None


class Orchestrator:
    """多智能体编排器，本身实现 `AgentRunner`，因此可以嵌套。"""

    def __init__(
        self,
        roles: dict[str, AgentRunner],
        *,
        tracer: Any = None,
        strategy: Strategy = "pipeline",
        supervisor: Supervisor | None = None,
        judge: AgentRunner | None = None,
        board: SharedBoard | None = None,
        max_rounds: int = 2,
        continue_on_error: bool = True,
        synthesizer: Synthesizer | None = None,
    ) -> None:
        if not roles:
            raise ValueError("Orchestrator requires at least one role")
        if strategy not in {"pipeline", "supervisor", "debate", "chat"}:
            raise ValueError(f"unknown strategy: {strategy}")
        if strategy == "supervisor" and supervisor is None:
            raise ValueError("supervisor strategy requires a supervisor")
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")

        self.roles = roles
        self.tracer = tracer
        self.strategy = strategy
        self.supervisor = supervisor
        self.judge = judge
        self.board = board or SharedBoard()
        self.max_rounds = max_rounds
        self.continue_on_error = continue_on_error
        self.synthesizer = synthesizer

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        ctx = ctx or RunContext(run_id=f"orch-{uuid4().hex[:12]}")
        started_at = utcnow()
        stats = _RunStats()
        trajectory = Trajectory(task=task, run_id=ctx.run_id, started_at=started_at)
        final_answer: str | None = None
        stop_reason: StopReason = "final_answer"
        self._emit("on_run_start", task, ctx)

        try:
            if self.strategy == "pipeline":
                final_answer, stop_reason = self._run_pipeline(
                    task, ctx, stats, self.board, started_at
                )
            elif self.strategy == "supervisor":
                final_answer, stop_reason = self._run_supervisor(
                    task, ctx, stats, self.board, started_at
                )
            elif self.strategy == "debate":
                final_answer, stop_reason = self._run_debate(
                    task, ctx, stats, self.board, started_at
                )
            else:
                final_answer, stop_reason = self._run_chat(
                    task, ctx, stats, self.board, started_at
                )
        except Exception as exc:
            self._append_step(
                stats,
                f"[orchestrator] 编排失败：{type(exc).__name__}: {exc}",
            )
            final_answer = None
            stop_reason = "error"
        finally:
            trajectory.steps = stats.steps
            trajectory.usage = stats.usage
            trajectory.final_answer = final_answer
            trajectory.stop_reason = stop_reason
            trajectory.ended_at = utcnow()
            self._emit("on_run_end", trajectory, ctx)

        return trajectory

    def _emit(self, method: str, *args: Any) -> None:
        if self.tracer is None:
            return
        try:
            getattr(self.tracer, method)(*args)
        except Exception:
            return

    def _run_pipeline(
        self,
        task: str,
        ctx: RunContext,
        stats: _RunStats,
        board: SharedBoard,
        started_at,
    ) -> tuple[str | None, StopReason]:
        artifacts: list[tuple[str, str]] = []
        final_answer: str | None = None

        for role, runner in self.roles.items():
            reason = self._budget_reason(ctx, stats, started_at)
            if reason is not None:
                return final_answer, reason

            child = self._run_role(
                role,
                runner,
                self._pipeline_prompt(task, role, artifacts),
                ctx,
                stats,
                started_at,
            )
            if child is None:
                self._record_failure(
                    board, ctx, role, stats.last_error or "执行失败"
                )
                if not self.continue_on_error:
                    return final_answer, "error"
                continue

            answer = (child.final_answer or "").strip()
            if child.stop_reason != "final_answer" or not answer:
                reason = (
                    child.stop_reason
                    if child.stop_reason != "final_answer"
                    else "error"
                )
                self._record_failure(
                    board, ctx, role, answer or f"stop_reason={reason}"
                )
                if not self.continue_on_error:
                    return final_answer, reason
                continue

            board.write(
                f"artifact/{role}",
                answer,
                author=role,
                run_id=ctx.run_id,
            )
            artifacts.append((role, answer))
            final_answer = answer

        if not artifacts:
            return None, "error"
        if self.synthesizer is not None:
            final_answer = self.synthesizer(task, artifacts)
        return final_answer, "final_answer"

    def _run_supervisor(
        self,
        task: str,
        ctx: RunContext,
        stats: _RunStats,
        board: SharedBoard,
        started_at,
    ) -> tuple[str | None, StopReason]:
        artifacts: list[tuple[str, str]] = []
        done: set[str] = set()
        final_answer: str | None = None
        decisions = 0
        max_decisions = max(len(self.roles) * 2, 1)

        while decisions < max_decisions:
            try:
                role = self.supervisor.choose(task, board, done)  # type: ignore[union-attr]
            except Exception as exc:
                stats.last_error = f"{type(exc).__name__}: {exc}"
                return final_answer, "error"
            if role is None:
                break
            if role not in self.roles:
                self._record_failure(
                    board, ctx, "supervisor", f"未知角色：{role}"
                )
                return final_answer, "error"
            if role in done:
                break

            reason = self._budget_reason(ctx, stats, started_at)
            if reason is not None:
                return final_answer, reason

            child = self._run_role(
                role,
                self.roles[role],
                self._supervisor_prompt(task, role, board),
                ctx,
                stats,
                started_at,
            )
            done.add(role)
            decisions += 1

            if child is None:
                self._record_failure(
                    board, ctx, role, stats.last_error or "执行失败"
                )
                if not self.continue_on_error:
                    return final_answer, "error"
                continue

            answer = (child.final_answer or "").strip()
            if child.stop_reason != "final_answer" or not answer:
                reason = (
                    child.stop_reason
                    if child.stop_reason != "final_answer"
                    else "error"
                )
                self._record_failure(
                    board, ctx, role, answer or f"stop_reason={reason}"
                )
                if not self.continue_on_error:
                    return final_answer, reason
                continue

            board.write(
                f"artifact/{role}",
                answer,
                author=role,
                run_id=ctx.run_id,
            )
            artifacts.append((role, answer))
            final_answer = answer

        if not artifacts:
            return None, "error"
        if self.synthesizer is not None:
            final_answer = self.synthesizer(task, artifacts)
        return final_answer, "final_answer"

    def _run_debate(
        self,
        task: str,
        ctx: RunContext,
        stats: _RunStats,
        board: SharedBoard,
        started_at,
    ) -> tuple[str | None, StopReason]:
        artifacts: list[tuple[str, str]] = []
        final_answer: str | None = None

        for round_no in range(1, self.max_rounds + 1):
            round_artifacts: list[tuple[str, str]] = []
            for role, runner in self.roles.items():
                reason = self._budget_reason(ctx, stats, started_at)
                if reason is not None:
                    return final_answer, reason

                child = self._run_role(
                    role,
                    runner,
                    self._debate_prompt(task, role, round_no, board),
                    ctx,
                    stats,
                    started_at,
                )
                if child is None:
                    self._record_failure(
                        board, ctx, role, stats.last_error or "执行失败"
                    )
                    if not self.continue_on_error:
                        return final_answer, "error"
                    continue

                answer = (child.final_answer or "").strip()
                if child.stop_reason != "final_answer" or not answer:
                    reason = (
                        child.stop_reason
                        if child.stop_reason != "final_answer"
                        else "error"
                    )
                    self._record_failure(
                        board, ctx, role, answer or f"stop_reason={reason}"
                    )
                    if not self.continue_on_error:
                        return final_answer, reason
                    continue

                board.write(
                    f"debate/{role}/r{round_no}",
                    answer,
                    author=role,
                    run_id=ctx.run_id,
                    metadata={"round": round_no},
                )
                artifacts.append((role, answer))
                round_artifacts.append((role, answer))
                final_answer = answer

            if not round_artifacts:
                break

        if not artifacts:
            return None, "error"
        if self.judge is None:
            if self.synthesizer is not None:
                final_answer = self.synthesizer(task, artifacts)
            return final_answer, "final_answer"

        reason = self._budget_reason(ctx, stats, started_at)
        if reason is not None:
            return final_answer, reason

        child = self._run_role(
            "judge",
            self.judge,
            self._judge_prompt(task, board),
            ctx,
            stats,
            started_at,
        )
        if child is None:
            return final_answer, "error"

        answer = (child.final_answer or "").strip()
        if child.stop_reason != "final_answer" or not answer:
            reason = (
                child.stop_reason
                if child.stop_reason != "final_answer"
                else "error"
            )
            return final_answer, reason

        board.write(
            "verdict",
            answer,
            author="judge",
            run_id=ctx.run_id,
        )
        return answer, "final_answer"

    def _run_chat(
        self,
        task: str,
        ctx: RunContext,
        stats: _RunStats,
        board: SharedBoard,
        started_at,
    ) -> tuple[str | None, StopReason]:
        artifacts: list[tuple[str, str]] = []
        final_answer: str | None = None

        for round_no in range(1, self.max_rounds + 1):
            round_artifacts: list[tuple[str, str]] = []
            for role, runner in self.roles.items():
                reason = self._budget_reason(ctx, stats, started_at)
                if reason is not None:
                    return final_answer, reason

                child = self._run_role(
                    role,
                    runner,
                    self._chat_prompt(task, role, round_no, board),
                    ctx,
                    stats,
                    started_at,
                )
                if child is None:
                    self._record_failure(
                        board, ctx, role, stats.last_error or "执行失败"
                    )
                    if not self.continue_on_error:
                        return final_answer, "error"
                    continue

                answer = (child.final_answer or "").strip()
                if child.stop_reason != "final_answer" or not answer:
                    reason = (
                        child.stop_reason
                        if child.stop_reason != "final_answer"
                        else "error"
                    )
                    self._record_failure(
                        board, ctx, role, answer or f"stop_reason={reason}"
                    )
                    if not self.continue_on_error:
                        return final_answer, reason
                    continue

                board.write(
                    f"chat/{role}/r{round_no}",
                    answer,
                    author=role,
                    run_id=ctx.run_id,
                    metadata={"round": round_no},
                )
                artifacts.append((role, answer))
                round_artifacts.append((role, answer))
                final_answer = answer

                marker = self._final_marker(answer)
                if marker is not None:
                    board.write(
                        "final",
                        marker,
                        author=role,
                        run_id=ctx.run_id,
                    )
                    return marker, "final_answer"

            if not round_artifacts:
                break

        if not artifacts:
            return None, "error"
        if self.synthesizer is not None:
            final_answer = self.synthesizer(task, artifacts)
        return final_answer, "final_answer"

    def _run_role(
        self,
        role: str,
        runner: AgentRunner,
        prompt: str,
        ctx: RunContext,
        stats: _RunStats,
        started_at,
    ) -> Trajectory | None:
        child_ctx = self._child_context(ctx, role, stats, started_at)
        try:
            child = runner.run(prompt, child_ctx)
        except Exception as exc:
            stats.last_error = f"{type(exc).__name__}: {exc}"
            self._append_step(
                stats, f"[{role}] 执行异常：{stats.last_error}"
            )
            return None

        self._merge_child(role, child, stats)
        return child

    def _merge_child(
        self,
        role: str,
        child: Trajectory,
        stats: _RunStats,
    ) -> None:
        if not child.steps:
            self._append_step(
                stats, f"[{role}] {child.final_answer or ''}".strip()
            )
        else:
            for step in child.steps:
                stats.step_count += 1
                stats.tool_calls += len(step.tool_calls)
                thought = f"[{role}] {step.thought}" if step.thought else f"[{role}]"
                stats.steps.append(
                    Step(
                        index=stats.step_count,
                        thought=thought,
                        tool_calls=list(step.tool_calls),
                        tool_results=list(step.tool_results),
                        usage=step.usage,
                    )
                )
        stats.usage = stats.usage + child.usage

    @staticmethod
    def _append_step(stats: _RunStats, thought: str) -> None:
        stats.step_count += 1
        stats.steps.append(Step(index=stats.step_count, thought=thought))

    def _child_context(
        self,
        ctx: RunContext,
        role: str,
        stats: _RunStats,
        started_at,
    ) -> RunContext:
        elapsed = (utcnow() - started_at).total_seconds()
        remaining = Budget(
            max_steps=max(0, ctx.budget.max_steps - stats.step_count),
            max_tokens=max(0, ctx.budget.max_tokens - stats.usage.total_tokens),
            max_cost_usd=max(
                0.0, ctx.budget.max_cost_usd - stats.usage.cost_usd
            ),
            max_seconds=max(0.0, ctx.budget.max_seconds - elapsed),
            max_tool_calls=max(
                0, ctx.budget.max_tool_calls - stats.tool_calls
            ),
        )
        return RunContext(
            run_id=f"{ctx.run_id}:{role}",
            budget=remaining,
            user_id=ctx.user_id,
            deadline_at=ctx.deadline_at,
            metadata={
                **ctx.metadata,
                "parent_run_id": ctx.run_id,
                "role": role,
                "strategy": self.strategy,
            },
        )

    @staticmethod
    def _budget_reason(
        ctx: RunContext,
        stats: _RunStats,
        started_at,
    ) -> StopReason | None:
        state = RunState(
            step=stats.step_count,
            tool_calls=stats.tool_calls,
            usage=stats.usage,
            started_at=started_at,
            now=utcnow(),
        )
        return BudgetStopPolicy(ctx.budget).check(state)

    @staticmethod
    def _record_failure(
        board: SharedBoard,
        ctx: RunContext,
        role: str,
        value: str,
    ) -> None:
        board.write(
            f"error/{role}",
            value,
            author=role,
            run_id=ctx.run_id,
        )

    @staticmethod
    def _pipeline_prompt(
        task: str,
        role: str,
        artifacts: list[tuple[str, str]],
    ) -> str:
        if artifacts:
            upstream = "\n\n".join(
                f"[{author}]\n{value[:1200]}" for author, value in artifacts
            )
        else:
            upstream = "（无，你是第一个角色）"
        return (
            f"任务：{task}\n\n"
            f"上游产物：\n{upstream}\n\n"
            f"你是「{role}」。只完成你这一环：基于上游产物工作，"
            "不重复已完成的内容；输出可交给下游直接使用的结构化产物；"
            "信息不足时明确说明缺口，不要编造。"
        )

    @staticmethod
    def _supervisor_prompt(task: str, role: str, board: SharedBoard) -> str:
        return (
            f"任务：{task}\n\n"
            "当前共享产物：\n"
            f"{board.render(max_entries=12, max_chars=600)}\n\n"
            f"编排器把这一轮交给你（{role}）。请完成你的职责，"
            "输出可复用的结论；不要重复其他角色已经完成的工作。"
        )

    @staticmethod
    def _debate_prompt(
        task: str,
        role: str,
        round_no: int,
        board: SharedBoard,
    ) -> str:
        positions = board.render(
            prefix="debate/", max_entries=12, max_chars=500
        )
        return (
            f"任务：{task}\n\n"
            f"第 {round_no} 轮辩论。当前各方观点：\n{positions}\n\n"
            f"你是「{role}」。请指出其他观点中最关键的漏洞，"
            "修正或强化自己的结论，给出可被裁判直接比较的明确主张。"
            "不要只复述对方。"
        )

    @staticmethod
    def _judge_prompt(task: str, board: SharedBoard) -> str:
        record = board.render(
            prefix="debate/", max_entries=20, max_chars=600
        )
        return (
            f"任务：{task}\n\n"
            f"辩论记录：\n{record}\n\n"
            "你是裁判。请比较各方主张，区分被证据支持的结论、"
            "仍有分歧的部分和共同盲点，给出最终答案。不要只做折中。"
        )

    @staticmethod
    def _chat_prompt(
        task: str,
        role: str,
        round_no: int,
        board: SharedBoard,
    ) -> str:
        discussion = board.render(
            prefix="chat/", max_entries=20, max_chars=500
        )
        return (
            f"任务：{task}\n\n"
            f"第 {round_no} 轮讨论。当前记录：\n{discussion}\n\n"
            f"你是「{role}」。基于讨论给出你的意见。"
            '若你判断已经可以收敛，输出以 "FINAL: " 开头的最终答案；'
            "否则继续讨论。"
        )

    @staticmethod
    def _final_marker(answer: str) -> str | None:
        match = _FINAL_MARKER.match(answer)
        return match.group(1).strip() if match else None
