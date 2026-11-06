from __future__ import annotations

from typing import Protocol

from atlas.types import RunContext, Step, Trajectory


class Tracer(Protocol):
    """运行期事件接收器；实现方不得让异常影响 Agent 主流程。"""

    def on_run_start(self, task: str, ctx: RunContext) -> None:
        ...

    def on_step(self, step: Step, ctx: RunContext) -> None:
        ...

    def on_run_end(self, trajectory: Trajectory, ctx: RunContext) -> None:
        ...
