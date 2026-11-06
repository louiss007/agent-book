from __future__ import annotations

from threading import BoundedSemaphore, Lock
from time import monotonic
from time import sleep as default_sleep
from typing import Callable

from atlas.llm.base import LLM
from atlas.runtime.metrics import RuntimeMetrics
from atlas.tools.base import Tool
from atlas.types import LLMResponse, Message, ToolOutput, ToolSpec


class TokenBucket:
    """进程内令牌桶；用于限制请求速率，而不是精确计费。

    多进程或多实例部署时，每个实例各有自己的桶；需要全局限流时，
    应换成 Redis 令牌桶或 API 网关配额。
    """

    def __init__(
        self,
        rate: float,
        capacity: float,
        *,
        clock: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.rate = float(rate)
        self.capacity = float(capacity)
        self.clock = clock
        self.sleep = sleep
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = Lock()

    def _refill(self) -> None:
        now = self.clock()
        elapsed = max(0.0, now - self._last)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last = now

    def acquire(self, tokens: float = 1.0, *, timeout: float | None = None) -> float:
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        if tokens > self.capacity:
            raise ValueError("tokens exceed bucket capacity")
        waited = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                missing = tokens - self._tokens
                delay = missing / self.rate
            if timeout is not None and waited + delay > timeout:
                raise TimeoutError(
                    f"rate limit wait {waited + delay:.3f}s exceeds timeout {timeout:.3f}s"
                )
            self.sleep(delay)
            waited += delay

    def try_acquire(self, tokens: float = 1.0) -> bool:
        try:
            self.acquire(tokens, timeout=0)
        except TimeoutError:
            return False
        return True

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class ConcurrencyLimiter:
    """限制同时进行的调用数量；本身不排队，只决定是否立即获得名额。"""

    def __init__(self, limit: int) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        self.limit = limit
        self._semaphore = BoundedSemaphore(limit)

    def acquire(self, *, timeout: float | None = None) -> bool:
        if timeout is None:
            acquired = self._semaphore.acquire()
        else:
            acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError("concurrency limit wait timed out")
        return True

    def release(self) -> None:
        self._semaphore.release()

    def __enter__(self) -> "ConcurrencyLimiter":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class RateLimitedLLM:
    def __init__(
        self,
        inner: LLM,
        limiter: TokenBucket,
        *,
        cost: float | Callable[[list[Message], list[ToolSpec] | None], float] = 1.0,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.inner = inner
        self.limiter = limiter
        self.cost = cost
        self.metrics = metrics

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        amount = self.cost(messages, tools) if callable(self.cost) else float(self.cost)
        waited = self.limiter.acquire(amount)
        if self.metrics is not None and waited > 0:
            self.metrics.record_rate_limit_wait(waited)
        return self.inner.complete(
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class RateLimitedTool:
    def __init__(
        self,
        inner: Tool,
        limiter: TokenBucket,
        *,
        cost: float = 1.0,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.inner = inner
        self.spec = inner.spec
        self.limiter = limiter
        self.cost = float(cost)
        self.metrics = metrics

    def run(self, arguments: dict) -> ToolOutput:
        waited = self.limiter.acquire(self.cost)
        if self.metrics is not None and waited > 0:
            self.metrics.record_rate_limit_wait(waited)
        return self.inner.run(arguments)
