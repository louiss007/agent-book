from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from atlas.agent.policy import BudgetStopPolicy, RunState, StopPolicy
from atlas.llm.base import LLM, LLMError
from atlas.safety.base import ApprovalHandler, Guard, GuardDecision, denied_result
from atlas.tools.registry import ToolRegistry
from atlas.types import (
    Message,
    RunContext,
    Step,
    ToolCall,
    ToolResult,
    Trajectory,
    Usage,
    utcnow,
)

MAX_CONSECUTIVE_DENIALS = 3

DEFAULT_SYSTEM_PROMPT = (
    "你是一个能调用工具的助手。需要外部信息或精确计算时，先调用合适的工具；"
    "拿到足够信息后，用简洁的中文给出最终答案。"
)


@dataclass
class AgentConfig:
    system_prompt: str
    temperature: float = 0.0
    max_context_tokens: int = 32_000
    parallel_tools: bool = True


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        *,
        config: AgentConfig | None = None,
        policy: StopPolicy | None = None,
        context_builder: Any = None,
        tracer: Any = None,
        guards: Sequence[Guard] = (),
        approval: ApprovalHandler | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.config = config or AgentConfig(system_prompt=DEFAULT_SYSTEM_PROMPT)
        self.policy = policy
        self.context_builder = context_builder
        self.tracer = tracer
        self.guards = guards
        self.approval = approval

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        ctx = ctx or RunContext(run_id=f"run-{uuid4().hex[:12]}")
        policy = self.policy or BudgetStopPolicy(ctx.budget)

        started_at = utcnow()
        trajectory = Trajectory(task=task, run_id=ctx.run_id, started_at=started_at)
        history: list[Message] = [Message(role="user", content=task)]
        self._emit("on_run_start", task, ctx)

        total_usage = Usage()
        total_tool_calls = 0
        step_index = 0
        last_response = None
        denied_streak = 0

        try:
            while True:
                state = RunState(
                    step=step_index,
                    tool_calls=total_tool_calls,
                    usage=total_usage,
                    started_at=started_at,
                    now=utcnow(),
                    last_response=last_response,
                )
                reason = policy.check(state)
                if reason is not None:
                    trajectory.stop_reason = reason
                    break

                if self.context_builder is not None:
                    messages = self.context_builder.build(
                        task, history, step_index, ctx
                    )
                else:
                    messages = [
                        Message(role="system", content=self.config.system_prompt),
                        *history,
                    ]
                last_response = self.llm.complete(
                    messages,
                    self.tools.specs(),
                    temperature=self.config.temperature,
                )
                total_usage = total_usage + last_response.usage
                step_index += 1

                if not last_response.tool_calls:
                    trajectory.steps.append(
                        Step(
                            index=step_index,
                            thought=last_response.content,
                            usage=last_response.usage,
                        )
                    )
                    trajectory.final_answer = last_response.content
                    trajectory.stop_reason = "final_answer"
                    self._emit("on_step", trajectory.steps[-1], ctx)
                    break

                max_workers = 4 if self.config.parallel_tools else 1
                results, denied_streak, denied_stop = self._execute_tools(
                    last_response.tool_calls,
                    ctx,
                    denied_streak,
                    max_workers=max_workers,
                )
                trajectory.steps.append(
                    Step(
                        index=step_index,
                        thought=last_response.content,
                        tool_calls=last_response.tool_calls,
                        tool_results=results,
                        usage=last_response.usage,
                    )
                )
                self._emit("on_step", trajectory.steps[-1], ctx)
                if denied_stop:
                    trajectory.stop_reason = "denied"
                    break

                history.append(
                    Message(
                        role="assistant",
                        content=last_response.content,
                        tool_calls=last_response.tool_calls,
                    )
                )
                for call, result in zip(last_response.tool_calls, results):
                    history.append(
                        Message(
                            role="tool",
                            content=result.content,
                            name=call.name,
                            tool_call_id=call.id,
                        )
                    )
                total_tool_calls += len(last_response.tool_calls)

        except LLMError as exc:
            trajectory.steps.append(
                Step(index=step_index + 1, thought=f"LLM error: {exc}")
            )
            trajectory.stop_reason = "error"
            self._emit("on_step", trajectory.steps[-1], ctx)
        finally:
            trajectory.usage = total_usage
            trajectory.ended_at = utcnow()
            self._emit("on_run_end", trajectory, ctx)

        return trajectory

    def _execute_tools(
        self,
        calls: list[ToolCall],
        ctx: RunContext,
        denied_streak: int,
        *,
        max_workers: int,
    ) -> tuple[list[ToolResult], int, bool]:
        """先裁决、再执行、最后复核；拒绝不会把整批工具拖垮。"""

        results: dict[int, ToolResult] = {}
        decisions: dict[int, list[dict[str, Any]]] = {}
        pending_metadata: dict[int, dict[str, Any]] = {}
        allowed: list[int] = []
        stop = False

        for index, call in enumerate(calls):
            decision, records = self._before_tool(call, ctx)
            decisions[index] = records
            if decision.metadata:
                pending_metadata[index] = dict(decision.metadata)
            if decision.action == "deny":
                results[index] = self._denied(call, decision, records)
                denied_streak += 1
                if denied_streak >= MAX_CONSECUTIVE_DENIALS:
                    stop = True
                    for rest in range(index + 1, len(calls)):
                        results[rest] = denied_result(
                            calls[rest],
                            "连续拒绝达到阈值，运行已停止，本次调用未执行",
                            skipped=True,
                        )
                    break
                continue
            if decision.replacement is not None:
                replacement = decision.replacement
                replacement.tool_call_id = call.id
                if decision.metadata:
                    for key, value in decision.metadata.items():
                        replacement.metadata.setdefault(key, value)
                if records:
                    replacement.metadata.setdefault("guard_decisions", records)
                results[index] = replacement
                denied_streak = 0
                continue
            if decision.action == "approve":
                approved = ctx.metadata.get("approved_tool_calls")
                if not isinstance(approved, list):
                    approved = []
                    ctx.metadata["approved_tool_calls"] = approved
                approved.append(call.id)
            allowed.append(index)
            denied_streak = 0

        if not stop and allowed:
            allowed_results = self.tools.run_many(
                [calls[index] for index in allowed],
                ctx,
                max_workers=max_workers,
            )
            for index, result in zip(allowed, allowed_results):
                for key, value in pending_metadata.get(index, {}).items():
                    result.metadata.setdefault(key, value)
                results[index] = result

        if not stop:
            for index, call in enumerate(calls):
                decision, records = self._after_tool(call, results[index], ctx)
                decisions[index].extend(records)
                if decision.action == "deny":
                    results[index] = self._denied(
                        call, decision, decisions[index]
                    )
                    denied_streak += 1
                    if denied_streak >= MAX_CONSECUTIVE_DENIALS:
                        stop = True
                        break
                    continue
                if decision.replacement is not None:
                    replacement = decision.replacement
                    replacement.tool_call_id = call.id
                    replacement.metadata = {
                        **results[index].metadata,
                        **replacement.metadata,
                    }
                    if decisions[index]:
                        replacement.metadata.setdefault(
                            "guard_decisions", decisions[index]
                        )
                    results[index] = replacement
                    denied_streak = 0
                    continue
                if decisions[index]:
                    results[index].metadata.setdefault(
                        "guard_decisions", decisions[index]
                    )
                denied_streak = 0

        ordered: list[ToolResult] = []
        for index, call in enumerate(calls):
            if index in results:
                ordered.append(results[index])
            else:
                ordered.append(
                    denied_result(
                        call,
                        "运行在连续拒绝后停止，本次调用未执行",
                        skipped=True,
                    )
                )
        return ordered, denied_streak, stop

    def _before_tool(
        self,
        call: ToolCall,
        ctx: RunContext,
    ) -> tuple[GuardDecision, list[dict[str, Any]]]:
        action: str = "allow"
        reason = ""
        replacement: ToolResult | None = None
        records: list[dict[str, Any]] = []

        for guard in self.guards:
            try:
                decision = guard.before_tool(call, ctx)
            except Exception as exc:
                decision = GuardDecision(
                    "deny",
                    f"护栏执行失败：{type(exc).__name__}: {exc}",
                )
            records.append(self._guard_record(guard, decision, "before"))
            if decision.replacement is not None:
                replacement = decision.replacement
            if decision.action == "deny":
                return decision, records
            if decision.action == "approve":
                action = "approve"
                reason = decision.reason or reason

        if action != "approve":
            return GuardDecision("allow", reason, replacement), records

        if self.approval is None:
            return (
                GuardDecision(
                    "deny",
                    "该工具需要审批，但未配置审批处理器",
                    metadata={"approval": "unavailable"},
                ),
                records,
            )
        try:
            approved = bool(self.approval.request(call, ctx, reason))
        except Exception as exc:
            return (
                GuardDecision(
                    "deny",
                    f"审批处理器异常：{type(exc).__name__}: {exc}",
                    metadata={"approval": "error"},
                ),
                records,
            )
        approver = getattr(self.approval, "last_approver", None)
        if not approved:
            return (
                GuardDecision(
                    "deny",
                    f"审批未通过：{reason}",
                    metadata={"approval": "rejected", "approved_by": approver},
                ),
                records,
            )
        return (
            GuardDecision(
                "approve",
                reason,
                replacement,
                {"approval": "approved", "approved_by": approver},
            ),
            records,
        )

    def _after_tool(
        self,
        call: ToolCall,
        result: ToolResult,
        ctx: RunContext,
    ) -> tuple[GuardDecision, list[dict[str, Any]]]:
        current = result
        records: list[dict[str, Any]] = []
        for guard in self.guards:
            try:
                decision = guard.after_tool(current, ctx)
            except Exception as exc:
                decision = GuardDecision(
                    "deny",
                    f"护栏执行失败：{type(exc).__name__}: {exc}",
                )
            records.append(self._guard_record(guard, decision, "after"))
            if decision.action == "deny":
                return decision, records
            for key, value in decision.metadata.items():
                current.metadata.setdefault(key, value)
            if decision.replacement is not None:
                replacement = decision.replacement
                replacement.metadata = {
                    **current.metadata,
                    **replacement.metadata,
                }
                current = replacement
        replacement = current if current is not result else None
        return GuardDecision("allow", "", replacement), records

    def _guard_record(
        self,
        guard: Guard,
        decision: GuardDecision,
        stage: str,
    ) -> dict[str, Any]:
        return {
            "guard": getattr(guard, "name", type(guard).__name__),
            "stage": stage,
            "action": decision.action,
            "reason": decision.reason,
            **decision.metadata,
        }

    def _denied(
        self,
        call: ToolCall,
        decision: GuardDecision,
        records: list[dict[str, Any]],
        *,
        skipped: bool = False,
    ) -> ToolResult:
        guard_name = records[-1].get("guard") if records else None
        approval = decision.metadata.get("approval")
        return denied_result(
            call,
            decision.reason or "被安全策略拒绝",
            guard=str(guard_name) if guard_name else None,
            approval=str(approval) if approval else None,
            decisions=records,
            skipped=skipped,
            extra=dict(decision.metadata),
        )

    def _emit(self, method: str, *args: Any) -> None:
        """跟踪是旁路：任何导出失败都不能改变 Agent 的返回结果。"""

        if self.tracer is None:
            return
        try:
            getattr(self.tracer, method)(*args)
        except Exception:
            return
