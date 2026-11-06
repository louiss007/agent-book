from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from atlas.types import utcnow


@dataclass
class _Entry:
    value: str
    importance: float
    created_at: datetime


class WorkingMemory:
    """当前任务的结构化便签：有容量上限，按重要性淘汰。"""

    def __init__(self, *, max_items: int = 16, max_chars: int = 2000) -> None:
        self.max_items = max_items
        self.max_chars = max_chars
        self._entries: dict[str, _Entry] = {}

    def set(self, key: str, value: str, *, importance: float = 0.5) -> None:
        self._entries[key] = _Entry(
            value=value,
            importance=max(0.0, min(1.0, importance)),
            created_at=utcnow(),
        )
        self._evict()

    def get(self, key: str, default: str | None = None) -> str | None:
        entry = self._entries.get(key)
        return entry.value if entry else default

    def drop(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def snapshot(self) -> dict[str, str]:
        ordered = sorted(self._entries.items(), key=lambda pair: pair[1].created_at)
        return {key: entry.value for key, entry in ordered}

    def render(self) -> str:
        if not self._entries:
            return ""
        lines = ["[工作记忆]"]
        for key, value in self.snapshot().items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _evict(self) -> None:
        while len(self._entries) > self.max_items:
            self._evict_one()
        while self._size() > self.max_chars and self._entries:
            self._evict_one()

    def _evict_one(self) -> None:
        key = min(
            self._entries,
            key=lambda name: (
                self._entries[name].importance,
                self._entries[name].created_at,
            ),
        )
        del self._entries[key]

    def _size(self) -> int:
        return sum(len(key) + len(entry.value) for key, entry in self._entries.items())
