from typing import Protocol

from atlas.types import RunContext, Trajectory


class AgentRunner(Protocol):
    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        ...
