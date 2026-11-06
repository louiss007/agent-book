from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic
from typing import Any, Callable, Protocol

from atlas.runtime.metrics import RuntimeMetrics
from atlas.tools.base import Tool
from atlas.types import ToolOutput


class IdempotencyStore(Protocol):
    def get(self, key: str) -> ToolOutput | None:
        ...

    def set(
        self,
        key: str,
        value: ToolOutput,
        ttl: float | None = None,
    ) -> None:
        ...

    def clear(self) -> None:
        ...


def idempotency_key(namespace: str, tool_name: str, arguments: dict[str, Any]) -> str:
    payload = {
        "namespace": namespace,
        "tool": tool_name,
        "arguments": arguments,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class InMemoryIdempotencyStore:
    """进程内幂等结果存储，带 TTL 与 LRU 淘汰。

    它不能提供跨进程的 exactly-once；生产环境应使用 Redis/数据库的
    原子 setnx 或唯一约束，并把租户与权限范围放进 ``namespace``。
    """

    def __init__(
        self,
        *,
        max_entries: int = 1024,
        default_ttl: float | None = 3600.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self.clock = clock
        self._entries: OrderedDict[str, tuple[float | None, ToolOutput]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> ToolOutput | None:
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at is not None and self.clock() >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return deepcopy(value)

    def set(
        self,
        key: str,
        value: ToolOutput,
        ttl: float | None = None,
    ) -> None:
        effective_ttl = self.default_ttl if ttl is None else ttl
        expires_at = None if effective_ttl is None else self.clock() + effective_ttl
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = (expires_at, deepcopy(value))
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class IdempotentTool:
    """按工具名与规范化参数去重的工具包装。

    只缓存成功结果；失败不缓存，避免把一次瞬时故障固化成永久失败。
    同一进程内的并发相同调用仍可能同时穿透，生产环境需要存储层
    提供原子占位。
    """

    def __init__(
        self,
        inner: Tool,
        store: IdempotencyStore | None = None,
        *,
        namespace: str | Callable[[], str] = "default",
        ttl: float | None = None,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.inner = inner
        self.spec = inner.spec
        self.store = store or InMemoryIdempotencyStore()
        self.namespace = namespace
        self.ttl = ttl
        self.metrics = metrics

    def _scope(self) -> str:
        return self.namespace() if callable(self.namespace) else self.namespace

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        key = idempotency_key(self._scope(), self.spec.name, arguments)
        cached = self.store.get(key)
        if cached is not None:
            if self.metrics is not None:
                self.metrics.record_tool_call(replay=True)
            replay = deepcopy(cached)
            replay.metadata["idempotent_replay"] = True
            return replay

        output = self.inner.run(arguments)
        if not output.is_error:
            self.store.set(key, output, self.ttl)
        if self.metrics is not None:
            self.metrics.record_tool_call(replay=False)
        return output
