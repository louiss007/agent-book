from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import uuid4

from atlas.memory.base import MemoryItem
from atlas.types import utcnow

_WORD = re.compile(r"[a-zA-Z0-9_]+")
_CJK = re.compile(r"[一-鿿]+")


def _tokens(text: str) -> set[str]:
    """英文按词、中文按二元组切分，够用的轻量词法，不依赖第三方分词器。"""
    lowered = text.lower()
    tokens = set(_WORD.findall(lowered))
    for run in _CJK.findall(lowered):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class InMemoryStore:
    """标准库实现的记忆存储：词法相关性 + 重要性 + 时间衰减。"""

    def __init__(self, *, half_life_days: float = 30.0) -> None:
        self.half_life_days = half_life_days
        self._items: dict[str, MemoryItem] = {}

    def add(self, item: MemoryItem) -> str:
        if not item.id:
            item.id = f"mem-{uuid4().hex[:12]}"
        if item.id in self._items:
            raise ValueError(f"duplicate memory id: {item.id}")
        self._items[item.id] = item
        return item.id

    def get(self, item_id: str) -> MemoryItem | None:
        return self._items.get(item_id)

    def all(self) -> list[MemoryItem]:
        return list(self._items.values())

    def search(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        now = utcnow()
        query_tokens = _tokens(query)
        scored: list[tuple[float, MemoryItem]] = []
        for item in self._items.values():
            if not self._matches(item, filters):
                continue
            scored.append((self._score(item, query_tokens, now), item))

        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        results = [item for _, item in scored[: max(0, k)]]
        for item in results:
            item.last_accessed_at = now
        return results

    def forget(self, item_id: str) -> None:
        self._items.pop(item_id, None)

    def clear(self, scope: str | None = None) -> None:
        if scope is None:
            self._items.clear()
            return
        for item_id, item in list(self._items.items()):
            metadata = item.metadata
            if metadata.get("scope") == scope or metadata.get("user_id") == scope:
                del self._items[item_id]

    def retention(
        self,
        item: MemoryItem,
        *,
        now: datetime | None = None,
    ) -> float:
        """保留分数：重要性乘以时间衰减，不修改已存的重要性。"""
        now = now or utcnow()
        age_days = max(0.0, (now - item.created_at).total_seconds() / 86400.0)
        return _clamp(item.importance) * (0.5 ** (age_days / self.half_life_days))

    def prune(
        self,
        *,
        now: datetime | None = None,
        ttl_days: float | None = None,
        min_retention: float | None = None,
        max_items: int | None = None,
    ) -> list[MemoryItem]:
        """按 TTL、保留分数与容量删除记忆，返回被删除的条目。"""
        now = now or utcnow()
        removed: list[MemoryItem] = []

        for item_id, item in list(self._items.items()):
            age_days = max(0.0, (now - item.created_at).total_seconds() / 86400.0)
            if ttl_days is not None and age_days > ttl_days:
                removed.append(item)
                del self._items[item_id]
                continue
            if min_retention is not None and self.retention(item, now=now) < min_retention:
                removed.append(item)
                del self._items[item_id]

        if max_items is not None and len(self._items) > max_items:
            ranked = sorted(
                self._items.values(),
                key=lambda item: self.retention(item, now=now),
                reverse=True,
            )
            for item in ranked[max_items:]:
                removed.append(item)
                del self._items[item.id]

        return removed

    def _matches(
        self,
        item: MemoryItem,
        filters: dict[str, Any] | None,
    ) -> bool:
        filters = filters or {}
        if item.metadata.get("superseded") and not filters.get("include_superseded"):
            return False
        for key, expected in filters.items():
            if key == "include_superseded" or expected is None:
                continue
            if key == "kind":
                if item.kind != expected:
                    return False
            elif key == "since":
                if item.created_at < expected:
                    return False
            elif key == "until":
                if item.created_at > expected:
                    return False
            elif key == "min_importance":
                if item.importance < expected:
                    return False
            elif item.metadata.get(key) != expected:
                return False
        return True

    def _score(
        self,
        item: MemoryItem,
        query_tokens: set[str],
        now: datetime,
    ) -> float:
        if query_tokens:
            item_tokens = _tokens(item.content)
            overlap = len(query_tokens & item_tokens)
            relevance = (
                overlap / ((len(query_tokens) ** 0.5) * (len(item_tokens) ** 0.5))
                if item_tokens
                else 0.0
            )
        else:
            relevance = 0.0

        age_days = max(0.0, (now - item.created_at).total_seconds() / 86400.0)
        recency = 0.5 ** (age_days / self.half_life_days)
        return 0.65 * relevance + 0.25 * _clamp(item.importance) + 0.10 * recency
