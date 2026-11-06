from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from atlas.types import MemoryKind, utcnow


@dataclass
class MemoryItem:
    id: str
    content: str
    kind: MemoryKind = "episodic"
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    last_accessed_at: datetime | None = None


class MemoryStore(Protocol):
    def add(self, item: MemoryItem) -> str: ...

    def search(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryItem]: ...

    def forget(self, item_id: str) -> None: ...

    def clear(self, scope: str | None = None) -> None: ...
