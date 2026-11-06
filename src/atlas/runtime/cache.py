from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic
from typing import Callable, Protocol

from atlas.llm.base import LLM
from atlas.runtime.metrics import RuntimeMetrics
from atlas.types import LLMResponse, Message, ToolSpec


class ResponseCache(Protocol):
    def get(self, key: str) -> LLMResponse | None:
        ...

    def set(
        self,
        key: str,
        value: LLMResponse,
        ttl: float | None = None,
    ) -> None:
        ...

    def clear(self) -> None:
        ...


def _message_payload(message: Message) -> dict:
    return {
        "role": message.role,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": [
            {
                "id": call.id,
                "name": call.name,
                "arguments": call.arguments,
            }
            for call in message.tool_calls
        ],
    }


def _tool_payload(spec: ToolSpec) -> dict:
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.parameters,
        "dangerous": spec.dangerous,
    }


def response_cache_key(
    namespace: str,
    messages: list[Message],
    tools: list[ToolSpec] | None,
    *,
    temperature: float,
    max_tokens: int | None,
) -> str:
    payload = {
        "namespace": namespace,
        "messages": [_message_payload(message) for message in messages],
        "tools": [_tool_payload(spec) for spec in (tools or [])],
        "temperature": round(float(temperature), 6),
        "max_tokens": max_tokens,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class InMemoryResponseCache:
    """带 TTL 与 LRU 淘汰的进程内响应缓存。

    它只负责“同样的输入返回同样的响应”，不负责跨进程共享。
    多租户场景必须把租户或权限范围放进 ``namespace``，不能共用键空间。
    """

    def __init__(
        self,
        *,
        max_entries: int = 1024,
        default_ttl: float | None = 300.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self.clock = clock
        self._entries: OrderedDict[str, tuple[float | None, LLMResponse]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> LLMResponse | None:
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
        value: LLMResponse,
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


class CachedLLM:
    """按完整请求精确匹配的响应缓存。

    默认不缓存带工具调用的响应：这类响应会触发外部副作用，复用提议
    不等于复用结果，容易把一次调用放大成多次。需要时显式打开
    ``cache_tool_calls``，并确保工具本身幂等。
    """

    def __init__(
        self,
        inner: LLM,
        cache: ResponseCache | None = None,
        *,
        namespace: str | Callable[[], str] = "default",
        ttl: float | None = None,
        cache_tool_calls: bool = False,
        fingerprint: str | None = None,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.inner = inner
        self.cache = cache or InMemoryResponseCache()
        self.namespace = namespace
        self.ttl = ttl
        self.cache_tool_calls = cache_tool_calls
        self.fingerprint = fingerprint or type(inner).__name__
        self.metrics = metrics
        self.last_cache_hit: bool | None = None

    def _scope(self) -> str:
        base = self.namespace() if callable(self.namespace) else self.namespace
        return f"{base}:{self.fingerprint}"

    def _cacheable(self, response: LLMResponse) -> bool:
        if response.finish_reason == "error":
            return False
        if response.tool_calls and not self.cache_tool_calls:
            return False
        return True

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        key = response_cache_key(
            self._scope(),
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        cached = self.cache.get(key)
        if cached is not None:
            self.last_cache_hit = True
            if self.metrics is not None:
                self.metrics.record_cache(hit=True)
            return cached

        self.last_cache_hit = False
        if self.metrics is not None:
            self.metrics.record_cache(hit=False)
        response = self.inner.complete(
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if self._cacheable(response):
            self.cache.set(key, response, self.ttl)
        return response
