from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from atlas.types import RunContext, Step, Trajectory, utcnow

FrameworkCall = Callable[[str, RunContext], Trajectory | str]


class CallableAgentRunner:
    """把外部框架的调用入口包装成 Atlas 的 `AgentRunner`。

    `func` 接收 `(task, ctx)`；返回 `Trajectory` 或纯文本答案。
    适配层只做契约归一化，不接管框架内部的循环。
    """

    def __init__(self, func: FrameworkCall, *, name: str = "framework") -> None:
        if not callable(func):
            raise TypeError("func must be callable")
        self.func = func
        self.name = name

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        ctx = ctx or RunContext(run_id=f"{self.name}-{uuid4().hex[:12]}")
        result = self.func(task, ctx)
        if isinstance(result, Trajectory):
            return _normalize(result, task, ctx)
        if isinstance(result, str):
            return Trajectory(
                task=task,
                run_id=ctx.run_id,
                steps=[Step(index=1, thought=result)],
                final_answer=result,
                stop_reason="final_answer",
                ended_at=utcnow(),
            )
        raise TypeError(
            f"{self.name} returned {type(result).__name__}; "
            "expected Trajectory or str"
        )


def as_agent_runner(func: FrameworkCall, *, name: str = "framework") -> CallableAgentRunner:
    return CallableAgentRunner(func, name=name)


def _normalize(trajectory: Trajectory, task: str, ctx: RunContext) -> Trajectory:
    if not trajectory.task:
        trajectory.task = task
    if not trajectory.run_id:
        trajectory.run_id = ctx.run_id
    if trajectory.ended_at is None:
        trajectory.ended_at = utcnow()
    return trajectory
