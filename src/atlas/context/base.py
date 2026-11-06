from __future__ import annotations

from typing import Protocol

from atlas.types import Message, RunContext


class ContextBuilder(Protocol):
    def build(
        self,
        task: str,
        history: list[Message],
        step: int,
        ctx: RunContext,
    ) -> list[Message]:
        ...
