from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import uuid4

from atlas.memory.base import MemoryItem, MemoryStore
from atlas.types import MemoryKind, Trajectory

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\b"
        r"\s*[:=]\s*[\"']?[^\s\"']+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+"),
)


def _redact(text: str) -> tuple[str, bool]:
    redacted = False
    for pattern in _SECRET_PATTERNS:
        new_text = pattern.sub("[REDACTED]", text)
        if new_text != text:
            redacted = True
            text = new_text
    return text, redacted


def redact_secrets(text: str) -> str:
    return _redact(text)[0]


class MemoryWriter:
    """把候选信息变成规范化记忆：过滤、脱敏、去重、冲突替换。"""

    def __init__(
        self,
        store: MemoryStore,
        *,
        min_importance: float = 0.3,
        default_scope: str | None = None,
    ) -> None:
        self.store = store
        self.min_importance = min_importance
        self.default_scope = default_scope

    def remember(
        self,
        content: str,
        *,
        kind: MemoryKind = "semantic",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        text, redacted = _redact(content.strip())
        if len(text) < 4 or importance < self.min_importance:
            return None

        data = dict(metadata or {})
        if self.default_scope and "scope" not in data:
            data["scope"] = self.default_scope
        if redacted:
            data["redacted"] = True

        key = data.get("key")
        new_id = f"mem-{uuid4().hex[:12]}"
        if key:
            existing = self._find_by_key(str(key), data)
            if existing is not None:
                if existing.content.strip() == text:
                    existing.importance = max(existing.importance, importance)
                    for name, value in data.items():
                        existing.metadata.setdefault(name, value)
                    return existing.id
                existing.metadata["superseded"] = True
                existing.metadata["superseded_by"] = new_id

        item = MemoryItem(
            id=new_id,
            content=text,
            kind=kind,
            importance=max(0.0, min(1.0, importance)),
            metadata=data,
        )
        return self.store.add(item)

    def remember_preference(
        self,
        content: str,
        *,
        key: str,
        user_id: str | None = None,
        scope: str | None = None,
        importance: float = 0.9,
    ) -> str | None:
        metadata: dict[str, Any] = {"key": key}
        if user_id is not None:
            metadata["user_id"] = user_id
        if scope is not None:
            metadata["scope"] = scope
        return self.remember(
            content,
            kind="preference",
            importance=importance,
            metadata=metadata,
        )

    def remember_task(
        self,
        task: str,
        trajectory: Trajectory,
        *,
        user_id: str | None = None,
        scope: str | None = None,
        importance: float | None = None,
    ) -> str | None:
        tool_calls = sum(len(step.tool_calls) for step in trajectory.steps)
        answer = (trajectory.final_answer or "").strip()
        lines = [
            f"任务：{task.strip()}",
            f"状态：{trajectory.stop_reason}",
            f"工具调用：{tool_calls} 次",
        ]
        if answer:
            lines.append(f"结果：{answer[:400]}")
        else:
            lines.append("结果：未完成或没有最终答案")

        if importance is None:
            importance = 0.6 if trajectory.stop_reason == "final_answer" else 0.4
        digest = hashlib.sha1(task.strip().lower().encode("utf-8")).hexdigest()[:12]
        metadata: dict[str, Any] = {
            "key": f"task:{digest}",
            "task": task.strip()[:120],
            "stop_reason": trajectory.stop_reason,
        }
        if user_id is not None:
            metadata["user_id"] = user_id
        if scope is not None:
            metadata["scope"] = scope
        return self.remember(
            "\n".join(lines),
            kind="episodic",
            importance=importance,
            metadata=metadata,
        )

    def _find_by_key(
        self,
        key: str,
        metadata: dict[str, Any],
    ) -> MemoryItem | None:
        filters: dict[str, Any] = {"key": key}
        for name in ("user_id", "scope"):
            if metadata.get(name) is not None:
                filters[name] = metadata[name]
        for item in self.store.search(key, k=50, filters=filters):
            if item.metadata.get("key") == key:
                return item
        return None
