"""第 18 章：Atlas v1.4.0 的缓存、路由、重试、限流与任务队列。

运行：

    PYTHONPATH=src python3 examples/ch18_runtime.py

示例不访问网络：用脚本化模型模拟廉价/强模型、偶发 503、限流等待与
任务失败重试，所有时间都由可注入的时钟或 sleep 驱动，输出稳定。
"""

from __future__ import annotations

from typing import Any

from atlas import (
    CachedLLM,
    IdempotentTool,
    InMemoryIdempotencyStore,
    InMemoryJobStore,
    InMemoryResponseCache,
    JobRunner,
    LengthRouter,
    LLMError,
    LLMResponse,
    Message,
    MeteredLLM,
    ModelPrice,
    RateLimitedLLM,
    RetryPolicy,
    RetryingLLM,
    RoutingLLM,
    RunContext,
    RuntimeMetrics,
    TokenBucket,
    ToolOutput,
    ToolSpec,
    Trajectory,
    Usage,
)


class ScriptedLLM:
    """可配置失败次数的脚本化模型，用来观察重试与路由行为。"""

    def __init__(
        self,
        name: str,
        text: str,
        *,
        failures: int = 0,
        fail_message: str = "503 service unavailable",
        usage: Usage | None = None,
    ) -> None:
        self.name = name
        self.text = text
        self.failures = failures
        self.fail_message = fail_message
        self.usage = usage or Usage(
            prompt_tokens=120, completion_tokens=40, cached_tokens=80
        )
        self.calls = 0

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls += 1
        if self.calls <= self.failures:
            raise LLMError(self.fail_message)
        return LLMResponse(content=f"{self.name}: {self.text}", usage=self.usage)


class CreateTicketTool:
    spec = ToolSpec(
        "create_ticket",
        "创建工单；重复调用会创建重复工单。",
        {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
    )

    def __init__(self) -> None:
        self.calls = 0

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        self.calls += 1
        return ToolOutput(f"ticket-{self.calls:03d}")


class FlakyRunner:
    """第一次运行抛错的 AgentRunner 替身，用于演示任务重试。"""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("worker crashed")
        return Trajectory(
            task=task,
            run_id=ctx.run_id if ctx else "job-demo",
            stop_reason="final_answer",
            final_answer="报告已生成",
        )


def main() -> None:
    metrics = RuntimeMetrics()

    # 1. 路由 + 重试 + 计量 + 缓存，按“外层缓存、内层路由”组合。
    cheap = ScriptedLLM("cheap", "短回答")
    strong = ScriptedLLM("strong", "深度回答")
    router = RoutingLLM(
        {"cheap": cheap, "strong": strong},
        LengthRouter(threshold_chars=60),
        fallback_order=("strong",),
        metrics=metrics,
    )
    metered = MeteredLLM(
        router,
        metrics=metrics,
        price=ModelPrice(
            prompt_per_1k=1.0, completion_per_1k=2.0, cached_prompt_per_1k=0.5
        ),
        route="router",
    )
    retrying = RetryingLLM(
        metered,
        RetryPolicy(max_attempts=2, base_delay=0.0, jitter=False),
        metrics=metrics,
    )
    cached = CachedLLM(
        retrying,
        cache=InMemoryResponseCache(max_entries=128, default_ttl=300.0),
        namespace="tenant-a:atlas-demo",
        metrics=metrics,
    )

    short = [Message(role="user", content="怎么申请退款？")]
    long = [
        Message(
            role="user",
            content="请对比三份合同里的违约责任条款，并给出风险排序与修改建议。" * 3,
        )
    ]

    print("== 路由与缓存 ==")
    print("short ->", cached.complete(short).content, "| hit =", cached.last_cache_hit)
    print("short ->", cached.complete(short).content, "| hit =", cached.last_cache_hit)
    print("long  ->", cached.complete(long).content, "| hit =", cached.last_cache_hit)
    print(f"calls: cheap={cheap.calls} strong={strong.calls}")

    # 2. 指数退避：前两次 503，第三次成功；注入 sleep 避免真实等待。
    print("\n== 重试 ==")
    flaky = ScriptedLLM("flaky", "恢复成功", failures=2)
    delays: list[float] = []
    retrying = RetryingLLM(
        flaky,
        RetryPolicy(max_attempts=3, base_delay=0.1, jitter=False),
        sleep=delays.append,
        metrics=metrics,
    )
    print("result =", retrying.complete(short).content)
    print(f"attempts={flaky.calls} delays={delays}")

    # 3. 成本核算：1000 输入（其中 200 命中缓存）+ 500 输出。
    print("\n== 成本 ==")
    ticks = iter([0.0, 0.25])
    priced = MeteredLLM(
        ScriptedLLM(
            "priced",
            "计费回答",
            usage=Usage(prompt_tokens=1000, completion_tokens=500, cached_tokens=200),
        ),
        metrics=metrics,
        price=ModelPrice(
            prompt_per_1k=1.0, completion_per_1k=2.0, cached_prompt_per_1k=0.5
        ),
        route="strong",
        clock=lambda: next(ticks),
    )
    priced_response = priced.complete(short)
    print(f"cost=${priced_response.usage.cost_usd:.2f}")

    # 4. 幂等：同一用户重复提交只创建一张工单；换命名空间则重新执行。
    print("\n== 幂等工具 ==")
    tickets = CreateTicketTool()
    store = InMemoryIdempotencyStore()
    idempotent = IdempotentTool(tickets, store, namespace="user-1", metrics=metrics)
    first = idempotent.run({"title": "退款异常"})
    second = idempotent.run({"title": "退款异常"})
    other = IdempotentTool(tickets, store, namespace="user-2")
    other.run({"title": "退款异常"})
    print(f"user-1 first={first.content} replay={second.metadata['idempotent_replay']}")
    print(f"user-2 isolated -> real_calls={tickets.calls}")

    # 5. 令牌桶限流：容量 1、速率 1/s，第二次调用等待 1 秒。
    print("\n== 限流 ==")
    now = [0.0]
    bucket = TokenBucket(
        rate=1.0,
        capacity=1.0,
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    limited = RateLimitedLLM(
        ScriptedLLM("limited", "限流后返回"), bucket, metrics=metrics
    )
    limited.complete(short)
    limited.complete(short)
    snapshot = metrics.snapshot()
    print(f"waits={snapshot.rate_limit_waits} wait_seconds={snapshot.rate_limit_wait_seconds:.1f}")

    # 6. 长任务：worker 崩溃后任务回到 pending，重试成功。
    print("\n== 任务队列 ==")
    runner = FlakyRunner()
    jobs = JobRunner(runner, InMemoryJobStore(), max_attempts=2)
    jobs.submit("生成本周运营报告", job_id="job-42")
    processed = jobs.drain()
    job = processed[0]
    print(f"status={job.status} attempts={job.attempts} answer={job.result.final_answer}")

    # 7. 汇总指标：这些数字应接入监控，而不是只看单次调用。
    snapshot = metrics.snapshot()
    print("\n== 指标快照 ==")
    print(
        f"llm_calls={snapshot.llm_calls} cache_hit_rate={snapshot.cache_hit_rate:.2f} "
        f"retries={snapshot.retries} cost=${snapshot.total_cost_usd:.2f}"
    )
    print(f"routes={snapshot.routes}")


if __name__ == "__main__":
    main()
