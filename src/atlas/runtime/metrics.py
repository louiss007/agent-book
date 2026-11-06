from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import Lock
from time import perf_counter
from typing import Callable

from atlas.llm.base import LLM
from atlas.types import LLMResponse, Message, ToolSpec, Usage


@dataclass(frozen=True)
class ModelPrice:
    """按每千 token 计价的模型价格表。

    缓存命中的输入 token 通常有折扣；未提供 ``cached_prompt_per_1k``
    时按普通输入价计算，宁可高估也不要漏算。
    """

    prompt_per_1k: float
    completion_per_1k: float
    cached_prompt_per_1k: float | None = None

    def cost(self, usage: Usage) -> float:
        cached = min(max(usage.cached_tokens, 0), max(usage.prompt_tokens, 0))
        uncached = max(usage.prompt_tokens - cached, 0)
        cached_price = (
            self.prompt_per_1k
            if self.cached_prompt_per_1k is None
            else self.cached_prompt_per_1k
        )
        return (
            uncached / 1000 * self.prompt_per_1k
            + cached / 1000 * cached_price
            + usage.completion_tokens / 1000 * self.completion_per_1k
        )


@dataclass(frozen=True)
class RuntimeSnapshot:
    llm_calls: int = 0
    llm_errors: int = 0
    retries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    fallbacks: int = 0
    rate_limit_waits: int = 0
    rate_limit_wait_seconds: float = 0.0
    tool_calls: int = 0
    idempotent_replays: int = 0
    total_latency_ms: float = 0.0
    total_tool_latency_ms: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    total_cost_usd: float = 0.0
    routes: dict[str, int] = field(default_factory=dict)

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0

    @property
    def avg_llm_latency_ms(self) -> float:
        return self.total_latency_ms / self.llm_calls if self.llm_calls else 0.0

    @property
    def avg_tool_latency_ms(self) -> float:
        return (
            self.total_tool_latency_ms / self.tool_calls if self.tool_calls else 0.0
        )

    @property
    def cache_token_ratio(self) -> float:
        total = self.total_prompt_tokens
        return self.total_cached_tokens / total if total else 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class RuntimeMetrics:
    """线程安全的运行时计数器。

    指标只做旁路累计，不参与控制流；任何记录失败都不应改变调用结果。
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._llm_calls = 0
        self._llm_errors = 0
        self._retries = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._fallbacks = 0
        self._rate_limit_waits = 0
        self._rate_limit_wait_seconds = 0.0
        self._tool_calls = 0
        self._idempotent_replays = 0
        self._total_latency_ms = 0.0
        self._total_tool_latency_ms = 0.0
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_cached_tokens = 0
        self._total_cost_usd = 0.0
        self._routes: dict[str, int] = {}

    def record_llm_call(
        self,
        *,
        latency_ms: float = 0.0,
        usage: Usage | None = None,
        route: str | None = None,
    ) -> None:
        with self._lock:
            self._llm_calls += 1
            self._total_latency_ms += max(0.0, latency_ms)
            if usage is not None:
                self._total_prompt_tokens += usage.prompt_tokens
                self._total_completion_tokens += usage.completion_tokens
                self._total_cached_tokens += usage.cached_tokens
                self._total_cost_usd += usage.cost_usd
            if route is not None:
                self._routes[route] = self._routes.get(route, 0) + 1

    def record_llm_error(self) -> None:
        with self._lock:
            self._llm_errors += 1

    def record_retry(self) -> None:
        with self._lock:
            self._retries += 1

    def record_cache(self, *, hit: bool) -> None:
        with self._lock:
            if hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1

    def record_fallback(self) -> None:
        with self._lock:
            self._fallbacks += 1

    def record_rate_limit_wait(self, seconds: float) -> None:
        with self._lock:
            self._rate_limit_waits += 1
            self._rate_limit_wait_seconds += max(0.0, seconds)

    def record_tool_call(self, *, latency_ms: float = 0.0, replay: bool = False) -> None:
        with self._lock:
            self._tool_calls += 1
            if replay:
                self._idempotent_replays += 1
            self._total_tool_latency_ms += max(0.0, latency_ms)

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(
                llm_calls=self._llm_calls,
                llm_errors=self._llm_errors,
                retries=self._retries,
                cache_hits=self._cache_hits,
                cache_misses=self._cache_misses,
                fallbacks=self._fallbacks,
                rate_limit_waits=self._rate_limit_waits,
                rate_limit_wait_seconds=self._rate_limit_wait_seconds,
                tool_calls=self._tool_calls,
                idempotent_replays=self._idempotent_replays,
                total_latency_ms=self._total_latency_ms,
                total_tool_latency_ms=self._total_tool_latency_ms,
                total_prompt_tokens=self._total_prompt_tokens,
                total_completion_tokens=self._total_completion_tokens,
                total_cached_tokens=self._total_cached_tokens,
                total_cost_usd=self._total_cost_usd,
                routes=dict(self._routes),
            )


class MeteredLLM:
    """测量模型调用的延迟与费用；可选按价格表覆盖 usage.cost_usd。"""

    def __init__(
        self,
        inner: LLM,
        *,
        metrics: RuntimeMetrics | None = None,
        price: ModelPrice | None = None,
        route: str | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self.inner = inner
        self.metrics = metrics
        self.price = price
        self.route = route
        self.clock = clock

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        started = self.clock()
        try:
            response = self.inner.complete(
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception:
            if self.metrics is not None:
                self.metrics.record_llm_error()
            raise

        if self.price is not None:
            response.usage.cost_usd = self.price.cost(response.usage)
        if self.metrics is not None:
            self.metrics.record_llm_call(
                latency_ms=(self.clock() - started) * 1000,
                usage=response.usage,
                route=self.route,
            )
            if response.finish_reason == "error":
                self.metrics.record_llm_error()
        return response
