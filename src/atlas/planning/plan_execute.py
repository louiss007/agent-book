from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from atlas.agent.policy import BudgetStopPolicy, RunState
from atlas.agent.runner import AgentRunner
from atlas.planning.base import Plan, PlanStep, Planner
from atlas.planning.reflect import Reflection, Reflector
from atlas.types import Budget, Message, RunContext, Step, Trajectory, Usage, utcnow

Synthesizer = Callable[[str, list[tuple[PlanStep, str]]], str]


class PlanExecuteAgent:
    """先规划、再逐步执行；失败时反思、重试或重规划。"""

    def __init__(
        self,
        planner: Planner,
        executor: AgentRunner,
        *,
        reflector: Reflector | None = None,
        max_replans: int = 2,
        max_step_retries: int = 1,
        synthesizer: Synthesizer | None = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.reflector = reflector
        self.max_replans = max_replans
        self.max_step_retries = max_step_retries
        self.synthesizer = synthesizer or self._default_synthesize
        self.last_plan: Plan | None = None

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        ctx = ctx or RunContext(run_id=f"plan-{uuid4().hex[:12]}")
        started_at = utcnow()
        trajectory = Trajectory(task=task, run_id=ctx.run_id, started_at=started_at)
        history: list[Message] = [Message(role="user", content=task)]
        results: list[tuple[PlanStep, str]] = []
        usage = Usage()
        llm_steps = 0
        tool_calls = 0
        parent_steps = 0
        replans = 0
        stop_reason = "final_answer"

        try:
            plan = self._initial_plan(task, history)
            self.last_plan = plan

            while True:
                pending = [step for step in plan.steps if step.status == "pending"]
                if not pending:
                    break

                reason = self._budget_reason(
                    ctx, started_at, llm_steps, tool_calls, usage
                )
                if reason is not None:
                    stop_reason = reason
                    break

                step = pending[0]
                step.status = "running"
                children, ok, reflection = self._run_step(
                    ctx,
                    task,
                    plan,
                    step,
                    results,
                    history,
                    started_at,
                    llm_steps,
                    tool_calls,
                    usage,
                )

                for child in children:
                    usage = usage + child.usage
                    llm_steps += len(child.steps)
                    tool_calls += sum(len(item.tool_calls) for item in child.steps)
                child = children[-1]
                answer = (child.final_answer or "").strip()
                parent_steps += 1
                trajectory.steps.append(
                    Step(
                        index=parent_steps,
                        thought=(
                            f"[计划步骤 {step.id}] {step.description}"
                            f"（尝试 {len(children)} 次）\n{answer}"
                        ),
                        tool_calls=[
                            call
                            for attempt in children
                            for item in attempt.steps
                            for call in item.tool_calls
                        ],
                        tool_results=[
                            result
                            for attempt in children
                            for item in attempt.steps
                            for result in item.tool_results
                        ],
                        usage=sum((item.usage for item in children), Usage()),
                    )
                )

                if ok:
                    step.status = "done"
                    results.append((step, answer))
                    history.append(
                        Message(
                            role="assistant",
                            content=f"步骤 {step.id} 完成：{answer}",
                        )
                    )
                    continue

                step.status = "failed"
                critique = (
                    reflection.critique
                    if reflection is not None
                    else "结果为空或执行未正常结束"
                )
                history.append(
                    Message(
                        role="user",
                        content=(
                            f"步骤 {step.id} 失败：{critique}。"
                            f"已完成结果：{self._results_digest(results)}"
                        ),
                    )
                )
                replans += 1
                if replans > self.max_replans:
                    stop_reason = "error"
                    break
                try:
                    new_plan = self.planner.plan(task, history)
                except Exception as exc:
                    history.append(
                        Message(role="user", content=f"重规划失败：{exc}")
                    )
                    stop_reason = "error"
                    break
                plan = self._merge_plan(plan, new_plan)
                self.last_plan = plan
                history.append(
                    Message(
                        role="user",
                        content=(
                            "已重规划。当前计划："
                            f"{self._plan_digest(plan)}"
                        ),
                    )
                )
                if not any(item.status == "pending" for item in plan.steps):
                    stop_reason = "error"
                    break

            if stop_reason == "final_answer":
                trajectory.final_answer = self.synthesizer(task, results)
        except Exception as exc:
            parent_steps += 1
            trajectory.steps.append(
                Step(
                    index=parent_steps,
                    thought=f"规划执行失败：{type(exc).__name__}: {exc}",
                )
            )
            stop_reason = "error"
        finally:
            trajectory.usage = usage
            trajectory.stop_reason = stop_reason
            trajectory.ended_at = utcnow()

        return trajectory

    def _initial_plan(self, task: str, history: list[Message]) -> Plan:
        try:
            plan = self.planner.plan(task, history)
        except Exception as exc:
            history.append(
                Message(
                    role="user",
                    content=f"规划失败，退化为单步执行：{exc}",
                )
            )
            plan = Plan(goal=task, steps=[PlanStep(id="1", description=task)])
        if not plan.goal:
            plan.goal = task
        if not plan.steps:
            plan.steps = [PlanStep(id="1", description=task)]
        return plan

    def _run_step(
        self,
        ctx: RunContext,
        task: str,
        plan: Plan,
        step: PlanStep,
        results: list[tuple[PlanStep, str]],
        history: list[Message],
        started_at,
        llm_steps: int,
        tool_calls: int,
        usage: Usage,
    ) -> tuple[list[Trajectory], bool, Reflection | None]:
        children: list[Trajectory] = []
        reflection: Reflection | None = None
        feedback: str | None = None
        attempt = 0
        attempt_usage = usage
        attempt_steps = llm_steps
        attempt_tool_calls = tool_calls

        while True:
            prompt = self._step_prompt(plan, step, results, feedback=feedback)
            child_ctx = self._child_context(
                ctx, step, started_at, attempt_steps, attempt_tool_calls, attempt_usage
            )
            child = self.executor.run(prompt, child_ctx)
            children.append(child)
            attempt_usage = attempt_usage + child.usage
            attempt_steps += len(child.steps)
            attempt_tool_calls += sum(len(item.tool_calls) for item in child.steps)
            answer = (child.final_answer or "").strip()
            ok = child.stop_reason == "final_answer" and bool(answer)

            if ok and self.reflector is not None:
                try:
                    reflection = self.reflector.reflect(task, step, answer, history)
                except Exception as exc:
                    reflection = Reflection(
                        ok=True,
                        critique=f"反思器异常，按通过处理：{exc}",
                    )
                ok = reflection.ok

            if ok:
                return children, True, reflection
            if attempt >= self.max_step_retries:
                return children, False, reflection
            if child.stop_reason != "final_answer":
                return children, False, reflection

            attempt += 1
            critique = reflection.critique if reflection else "结果为空"
            suggestion = (
                reflection.suggestion if reflection else "重新执行并给出完整结果"
            )
            feedback = f"{critique}。建议：{suggestion}"
            history.append(
                Message(
                    role="user",
                    content=f"步骤 {step.id} 未通过检查：{feedback}。请重试。",
                )
            )

    def _child_context(
        self,
        ctx: RunContext,
        step: PlanStep,
        started_at,
        llm_steps: int,
        tool_calls: int,
        usage: Usage,
    ) -> RunContext:
        elapsed = (utcnow() - started_at).total_seconds()
        remaining = Budget(
            max_steps=max(0, ctx.budget.max_steps - llm_steps),
            max_tokens=max(0, ctx.budget.max_tokens - usage.total_tokens),
            max_cost_usd=max(0.0, ctx.budget.max_cost_usd - usage.cost_usd),
            max_seconds=max(0.0, ctx.budget.max_seconds - elapsed),
            max_tool_calls=max(0, ctx.budget.max_tool_calls - tool_calls),
        )
        return RunContext(
            run_id=f"{ctx.run_id}:{step.id}",
            budget=remaining,
            user_id=ctx.user_id,
            deadline_at=ctx.deadline_at,
            metadata={
                **ctx.metadata,
                "parent_run_id": ctx.run_id,
                "plan_step": step.id,
            },
        )

    def _budget_reason(
        self,
        ctx: RunContext,
        started_at,
        llm_steps: int,
        tool_calls: int,
        usage: Usage,
    ) -> str | None:
        state = RunState(
            step=llm_steps,
            tool_calls=tool_calls,
            usage=usage,
            started_at=started_at,
            now=utcnow(),
        )
        return BudgetStopPolicy(ctx.budget).check(state)

    def _step_prompt(
        self,
        plan: Plan,
        step: PlanStep,
        results: list[tuple[PlanStep, str]],
        *,
        feedback: str | None = None,
    ) -> str:
        lines = [
            f"总目标：{plan.goal}",
            f"当前步骤（{step.id}）：{step.description}",
            "已完成步骤：",
        ]
        if results:
            for done_step, answer in results:
                lines.append(f"- {done_step.id} {done_step.description}：{answer}")
        else:
            lines.append("（无）")
        if feedback:
            lines.extend(["", f"上一次尝试的问题：{feedback}"])
        lines.extend(
            [
                "",
                "请完成当前步骤。需要外部信息时调用工具；完成后给出可验证的结论。",
            ]
        )
        return "\n".join(lines)

    def _merge_plan(self, old: Plan, new: Plan) -> Plan:
        done = [step for step in old.steps if step.status == "done"]
        failed = [step for step in old.steps if step.status == "failed"]
        done_desc = {step.description.strip() for step in done}
        replacement = [
            step for step in new.steps if step.description.strip() not in done_desc
        ]
        steps = done + failed + replacement
        seen: set[str] = set()
        for index, step in enumerate(steps, start=1):
            if not step.id or step.id in seen:
                step.id = f"s{index}"
            seen.add(step.id)
        return Plan(goal=new.goal or old.goal, steps=steps)

    @staticmethod
    def _results_digest(results: list[tuple[PlanStep, str]]) -> str:
        if not results:
            return "（无）"
        return "；".join(
            f"{step.id}={answer[:120]}" for step, answer in results
        )

    @staticmethod
    def _plan_digest(plan: Plan) -> str:
        return " -> ".join(
            f"{step.id}:{step.description}[{step.status}]" for step in plan.steps
        )

    @staticmethod
    def _default_synthesize(
        task: str, results: list[tuple[PlanStep, str]]
    ) -> str | None:
        if not results:
            return None
        sections = [f"# {task}", ""]
        for step, answer in results:
            sections.extend(
                [f"## {step.id} {step.description}", answer, ""]
            )
        return "\n".join(sections).strip()
