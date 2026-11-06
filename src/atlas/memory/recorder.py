from __future__ import annotations

from uuid import uuid4

from atlas.agent.runner import AgentRunner
from atlas.memory.writer import MemoryWriter
from atlas.types import RunContext, Trajectory


class MemoryRecorder:
    """在任务结束后写记忆；不侵入 Agent 循环，也不改变轨迹。"""

    def __init__(
        self,
        inner: AgentRunner,
        writer: MemoryWriter,
        *,
        scope: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self.inner = inner
        self.writer = writer
        self.scope = scope
        self.user_id = user_id

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        ctx = ctx or RunContext(run_id=f"mem-{uuid4().hex[:12]}")
        trajectory = self.inner.run(task, ctx)
        self.writer.remember_task(
            task,
            trajectory,
            user_id=ctx.user_id or self.user_id,
            scope=self.scope or ctx.metadata.get("scope"),
        )
        return trajectory
