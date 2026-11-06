from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.types import utcnow


@dataclass
class BoardEntry:
    key: str
    value: str
    author: str
    run_id: str = ""
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def render(self, *, max_chars: int = 600) -> str:
        body = self.value.strip()
        if len(body) > max_chars:
            body = body[:max_chars] + "…"
        return f"[{self.key}] {self.author} (v{self.version})\n{body}"


class SharedBoard:
    """按 run 隔离、按 key 版本化的共享黑板。

    写入只追加历史，不覆盖旧版本；读取默认返回最新一条。这样既能支持
    角色之间的产物交接，也能在冲突发生时回溯"谁在什么时候改了什么"。
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], list[BoardEntry]] = {}
        self._lock = threading.Lock()

    def write(
        self,
        key: str,
        value: str,
        *,
        author: str,
        run_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> BoardEntry:
        if not key.strip():
            raise ValueError("board key must not be empty")
        with self._lock:
            history = self._entries.setdefault((run_id, key), [])
            entry = BoardEntry(
                key=key,
                value=value,
                author=author,
                run_id=run_id,
                version=len(history) + 1,
                metadata=dict(metadata or {}),
            )
            history.append(entry)
            return entry

    def read(self, key: str, *, run_id: str | None = None) -> BoardEntry | None:
        with self._lock:
            if run_id is not None:
                history = self._entries.get((run_id, key), [])
                return history[-1] if history else None
            latest: BoardEntry | None = None
            for (_, entry_key), history in self._entries.items():
                if entry_key != key or not history:
                    continue
                candidate = history[-1]
                if latest is None or candidate.created_at >= latest.created_at:
                    latest = candidate
            return latest

    def history(self, key: str, *, run_id: str | None = None) -> list[BoardEntry]:
        with self._lock:
            if run_id is not None:
                return list(self._entries.get((run_id, key), []))
            return [
                entry
                for (_, entry_key), history in self._entries.items()
                if entry_key == key
                for entry in history
            ]

    def latest(
        self,
        *,
        run_id: str | None = None,
        author: str | None = None,
        prefix: str = "",
    ) -> list[BoardEntry]:
        with self._lock:
            entries: list[BoardEntry] = []
            for (entry_run, key), history in self._entries.items():
                if not history:
                    continue
                if run_id is not None and entry_run != run_id:
                    continue
                entry = history[-1]
                if author is not None and entry.author != author:
                    continue
                if prefix and not key.startswith(prefix):
                    continue
                entries.append(entry)
        entries.sort(key=lambda item: (item.created_at, item.key))
        return entries

    def snapshot(self, *, run_id: str | None = None) -> list[BoardEntry]:
        return self.latest(run_id=run_id)

    def render(
        self,
        *,
        run_id: str | None = None,
        prefix: str = "",
        max_entries: int = 20,
        max_chars: int = 600,
        exclude: set[str] | None = None,
    ) -> str:
        entries = self.latest(run_id=run_id, prefix=prefix)
        if exclude:
            entries = [entry for entry in entries if entry.key not in exclude]
        if not entries:
            return "（暂无共享产物）"
        entries = entries[-max_entries:]
        return "\n\n".join(entry.render(max_chars=max_chars) for entry in entries)

    def clear(self, *, run_id: str | None = None) -> None:
        with self._lock:
            if run_id is None:
                self._entries.clear()
                return
            for key in [item for item in self._entries if item[0] == run_id]:
                del self._entries[key]
