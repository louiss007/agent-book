from __future__ import annotations

import pytest

import atlas
from atlas.llm.base import LLMError
from atlas.runtime import (
    CachedLLM,
    ConcurrencyLimiter,
    FallbackLLM,
    IdempotentTool,
    InMemoryIdempotencyStore,
    InMemoryJobStore,
    InMemoryResponseCache,
    JobRunner,
    LengthRouter,
    MeteredLLM,
    ModelPrice,
    RateLimitedLLM,
    RetryPolicy,
    RetryingLLM,
    RetryingTool,
    RoutingLLM,
    RuntimeMetrics,
    TokenBucket,
    idempotency_key,
    response_cache_key,
)
from atlas.types import (
    LLMResponse,
    Message,
    RunContext,
    ToolCall,
    ToolOutput,
    ToolSpec,
    Trajectory,
    Usage,
)


def answer(text: str = "ok", *, cost: float = 0.0) -> LLMResponse:
    return LLMResponse(
        content=text,
        usage=Usage(prompt_tokens=10, completion_tokens=5, cost_usd=cost),
    )


class CountingLLM:
    def __init__(self, response: LLMResponse | None = None) -> None:
        self.response = response or answer()
        self.calls = 0

    def complete(self, messages, tools=None, *, temperature=0.0, max_tokens=None):
        self.calls += 1
        return self.response


class FlakyLLM:
    def __init__(self, failures: int, response: LLMResponse | None = None) -> None:
        self.failures = failures
        self.response = response or answer()
        self.calls = 0

    def complete(self, messages, tools=None, *, temperature=0.0, max_tokens=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise LLMError("upstream timeout")
        return self.response


class FailingLLM:
    def __init__(self, message: str = "bad request") -> None:
        self.message = message
        self.calls = 0

    def complete(self, messages, tools=None, *, temperature=0.0, max_tokens=None):
        self.calls += 1
        raise LLMError(self.message)


class CountingTool:
    def __init__(
        self,
        name: str = "create_ticket",
        *,
        output: ToolOutput | None = None,
    ) -> None:
        self.spec = ToolSpec(
            name=name,
            description="测试工具",
            parameters={"type": "object", "additionalProperties": True},
        )
        self.output = output or ToolOutput("created-1")
        self.calls = 0

    def run(self, arguments):
        self.calls += 1
        return self.output


class FlakyTool(CountingTool):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def run(self, arguments):
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("tool timeout")
        return self.output


class StubRunner:
    def __init__(self, *, failures: int = 0, stop_reason: str = "final_answer") -> None:
        self.failures = failures
        self.stop_reason = stop_reason
        self.calls = 0

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("transient runner failure")
        return Trajectory(
            task=task,
            run_id=ctx.run_id if ctx else "stub",
            stop_reason=self.stop_reason,
            final_answer="done",
        )


def messages(text: str = "hello") -> list[Message]:
    return [Message(role="user", content=text)]


def test_response_cache_key_is_stable_and_scoped():
    base = response_cache_key(
        "tenant-a", messages(), None, temperature=0.0, max_tokens=None
    )
    same = response_cache_key(
        "tenant-a", messages(), None, temperature=0.0, max_tokens=None
    )
    other_tenant = response_cache_key(
        "tenant-b", messages(), None, temperature=0.0, max_tokens=None
    )
    other_temp = response_cache_key(
        "tenant-a", messages(), None, temperature=0.7, max_tokens=None
    )

    assert base == same
    assert base != other_tenant
    assert base != other_temp


def test_cached_llm_hits_and_returns_isolated_copy():
    inner = CountingLLM(answer("first"))
    metrics = RuntimeMetrics()
    llm = CachedLLM(inner, metrics=metrics)

    first = llm.complete(messages())
    first.content = "mutated"
    second = llm.complete(messages())

    assert inner.calls == 1
    assert second.content == "first"
    snapshot = metrics.snapshot()
    assert snapshot.cache_hits == 1
    assert snapshot.cache_misses == 1


def test_cached_llm_skips_tool_calls_by_default():
    inner = CountingLLM(
        LLMResponse(
            tool_calls=[ToolCall("c1", "search", {"q": "x"})],
            finish_reason="tool_calls",
        )
    )
    llm = CachedLLM(inner)

    llm.complete(messages())
    llm.complete(messages())
    assert inner.calls == 2

    cached = CachedLLM(inner, cache_tool_calls=True)
    cached.complete(messages())
    cached.complete(messages())
    assert inner.calls == 3


def test_response_cache_ttl_and_lru_eviction():
    now = [0.0]
    cache = InMemoryResponseCache(
        max_entries=2, default_ttl=10.0, clock=lambda: now[0]
    )
    cache.set("a", answer("a"))
    cache.set("b", answer("b"))
    assert cache.get("a") is not None

    cache.set("c", answer("c"))
    assert cache.get("b") is None
    assert cache.get("a") is not None

    now[0] = 11.0
    assert cache.get("a") is None


def test_length_router_and_routing_fallback():
    cheap = CountingLLM(answer("cheap"))
    strong = CountingLLM(answer("strong"))
    metrics = RuntimeMetrics()
    router = RoutingLLM(
        {"cheap": cheap, "strong": strong},
        LengthRouter(threshold_chars=10),
        metrics=metrics,
    )

    assert router.complete(messages("short")).content == "cheap"
    assert router.complete(messages("this prompt is definitely longer")).content == "strong"
    assert router.counts == {"cheap": 1, "strong": 1}


def test_routing_llm_falls_back_on_error():
    failing = FailingLLM("rate limit 429")
    backup = CountingLLM(answer("backup"))
    metrics = RuntimeMetrics()
    router = RoutingLLM(
        {"cheap": failing, "backup": backup},
        LengthRouter(cheap="cheap", strong="cheap"),
        fallback_order=("backup",),
        metrics=metrics,
    )

    assert router.complete(messages()).content == "backup"
    assert router.last_route == "backup"
    assert metrics.snapshot().fallbacks == 1


def test_fallback_llm_switches_primary_to_fallback():
    failing = FailingLLM("timeout")
    backup = CountingLLM(answer("fallback"))
    metrics = RuntimeMetrics()
    llm = FallbackLLM(failing, backup, metrics=metrics)

    assert llm.complete(messages()).content == "fallback"
    assert llm.last_route == "fallback"
    assert metrics.snapshot().fallbacks == 1


def test_retrying_llm_backoff_and_metrics():
    inner = FlakyLLM(failures=2)
    sleeps: list[float] = []
    metrics = RuntimeMetrics()
    llm = RetryingLLM(
        inner,
        RetryPolicy(max_attempts=3, base_delay=0.1, jitter=False),
        sleep=sleeps.append,
        metrics=metrics,
    )

    assert llm.complete(messages()).content == "ok"
    assert inner.calls == 3
    assert sleeps == pytest.approx([0.1, 0.2])
    assert metrics.snapshot().retries == 2


def test_retrying_llm_does_not_retry_non_retryable_error():
    inner = FailingLLM("401 unauthorized")
    sleeps: list[float] = []
    llm = RetryingLLM(inner, RetryPolicy(max_attempts=3), sleep=sleeps.append)

    with pytest.raises(LLMError):
        llm.complete(messages())
    assert inner.calls == 1
    assert sleeps == []


def test_retrying_llm_stops_at_max_attempts():
    inner = FlakyLLM(failures=5)
    metrics = RuntimeMetrics()
    llm = RetryingLLM(
        inner,
        RetryPolicy(max_attempts=2, base_delay=0.0),
        sleep=lambda _: None,
        metrics=metrics,
    )

    with pytest.raises(LLMError):
        llm.complete(messages())
    assert inner.calls == 2
    assert metrics.snapshot().retries == 1


def test_retrying_tool_requires_idempotency():
    with pytest.raises(ValueError):
        RetryingTool(CountingTool(), RetryPolicy(max_attempts=3), idempotent=False)

    inner = FlakyTool(failures=2)
    tool = RetryingTool(
        inner,
        RetryPolicy(max_attempts=3, base_delay=0.0),
        idempotent=True,
        sleep=lambda _: None,
    )

    assert tool.run({}).content == "created-1"
    assert inner.calls == 3


def test_idempotent_tool_dedupes_and_isolates_namespaces():
    inner = CountingTool()
    store = InMemoryIdempotencyStore()
    metrics = RuntimeMetrics()
    tool = IdempotentTool(inner, store, namespace="user-1", metrics=metrics)

    first = tool.run({"title": "A"})
    second = tool.run({"title": "A"})

    assert inner.calls == 1
    assert first.content == "created-1"
    assert second.metadata["idempotent_replay"] is True
    assert metrics.snapshot().idempotent_replays == 1

    other_user = IdempotentTool(inner, store, namespace="user-2")
    other_user.run({"title": "A"})
    assert inner.calls == 2


def test_idempotent_tool_does_not_cache_errors():
    inner = CountingTool(output=ToolOutput("bad", is_error=True))
    tool = IdempotentTool(inner)

    tool.run({})
    tool.run({})
    assert inner.calls == 2


def test_idempotency_key_is_canonical():
    left = idempotency_key("u", "create", {"a": 1, "b": [2, 3]})
    right = idempotency_key("u", "create", {"b": [2, 3], "a": 1})
    assert left == right


def test_token_bucket_rate_limit_and_timeout():
    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    bucket = TokenBucket(rate=1.0, capacity=1.0, clock=clock, sleep=sleep)

    assert bucket.acquire() == 0.0
    assert bucket.acquire() == pytest.approx(1.0)
    assert bucket.try_acquire() is False
    with pytest.raises(TimeoutError):
        bucket.acquire(timeout=0.1)


def test_concurrency_limiter_releases_slot():
    limiter = ConcurrencyLimiter(1)
    limiter.acquire()
    with pytest.raises(TimeoutError):
        limiter.acquire(timeout=0.01)
    limiter.release()
    assert limiter.acquire(timeout=0.01) is True
    limiter.release()


def test_rate_limited_llm_records_wait():
    now = [0.0]
    bucket = TokenBucket(
        rate=1.0,
        capacity=1.0,
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    metrics = RuntimeMetrics()
    inner = CountingLLM()
    llm = RateLimitedLLM(inner, bucket, metrics=metrics)

    llm.complete(messages())
    llm.complete(messages())

    snapshot = metrics.snapshot()
    assert inner.calls == 2
    assert snapshot.rate_limit_waits == 1
    assert snapshot.rate_limit_wait_seconds == pytest.approx(1.0)


def test_runtime_metrics_snapshot_aggregates():
    metrics = RuntimeMetrics()
    metrics.record_llm_call(
        latency_ms=100,
        usage=Usage(prompt_tokens=10, completion_tokens=5, cached_tokens=4, cost_usd=0.02),
        route="cheap",
    )
    metrics.record_llm_call(latency_ms=300, usage=Usage(cost_usd=0.03), route="cheap")
    metrics.record_cache(hit=True)
    metrics.record_cache(hit=False)
    metrics.record_retry()
    metrics.record_fallback()
    metrics.record_tool_call(latency_ms=50)

    snapshot = metrics.snapshot()
    assert snapshot.llm_calls == 2
    assert snapshot.avg_llm_latency_ms == pytest.approx(200.0)
    assert snapshot.cache_hit_rate == pytest.approx(0.5)
    assert snapshot.total_cost_usd == pytest.approx(0.05)
    assert snapshot.routes == {"cheap": 2}


def test_metered_llm_price_and_latency():
    ticks = iter([0.0, 0.5])
    metrics = RuntimeMetrics()
    inner = CountingLLM(
        LLMResponse(
            content="priced",
            usage=Usage(
                prompt_tokens=1000,
                completion_tokens=500,
                cached_tokens=200,
            ),
        )
    )
    llm = MeteredLLM(
        inner,
        metrics=metrics,
        price=ModelPrice(
            prompt_per_1k=1.0,
            completion_per_1k=2.0,
            cached_prompt_per_1k=0.5,
        ),
        route="strong",
        clock=lambda: next(ticks),
    )

    response = llm.complete(messages())

    assert response.usage.cost_usd == pytest.approx(1.9)
    snapshot = metrics.snapshot()
    assert snapshot.llm_calls == 1
    assert snapshot.avg_llm_latency_ms == pytest.approx(500.0)
    assert snapshot.routes == {"strong": 1}


def test_job_runner_retries_then_succeeds():
    runner = StubRunner(failures=1)
    store = InMemoryJobStore()
    jobs = JobRunner(runner, store, max_attempts=2)
    job = jobs.submit("整理报告", job_id="j1")

    processed = jobs.drain()

    assert job.id == "j1"
    assert processed[0].status == "succeeded"
    assert processed[0].attempts == 2
    assert runner.calls == 2
    assert store.stats()["succeeded"] == 1


def test_job_runner_retries_agent_error_stop_reason():
    runner = StubRunner(stop_reason="error")
    store = InMemoryJobStore()
    jobs = JobRunner(runner, store, max_attempts=2, retry_stop_reasons=("error",))

    jobs.submit("会失败的任务", job_id="j2")
    processed = jobs.drain()

    assert processed[0].status == "failed"
    assert processed[0].attempts == 2
    assert "agent stopped with error" in (processed[0].error or "")


def test_job_store_claim_is_exclusive():
    store = InMemoryJobStore()
    from atlas.runtime import Job

    store.save(Job(id="a", task="A"))
    store.save(Job(id="b", task="B"))

    first = store.claim()
    second = store.claim()
    third = store.claim()

    assert first is not None and second is not None
    assert {first.id, second.id} == {"a", "b"}
    assert third is None
    assert store.stats()["running"] == 2


def test_public_runtime_exports_and_version():
    assert atlas.__version__ == "1.4.0"
    for name in (
        "CachedLLM",
        "RoutingLLM",
        "RetryingLLM",
        "IdempotentTool",
        "TokenBucket",
        "JobRunner",
        "RuntimeMetrics",
    ):
        assert hasattr(atlas, name)
