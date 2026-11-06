from __future__ import annotations

import random
from dataclasses import dataclass
from time import sleep as default_sleep
from typing import Callable

from atlas.llm.base import LLM
from atlas.runtime.metrics import RuntimeMetrics
from atlas.tools.base import Tool
from atlas.types import LLMResponse, Message, ToolOutput, ToolSpec

_RETRYABLE_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectionError",
    "ConnectionResetError",
    "RateLimitError",
    "ServiceUnavailableError",
    "TimeoutError",
}
_RETRYABLE_TEXT = (
    "429",
    "502",
    "503",
    "504",
    "connection reset",
    "rate limit",
    "temporarily unavailable",
    "timed out",
    "timeout",
)


def is_retryable_error(exc: BaseException) -> bool:
    if type(exc).__name__ in _RETRYABLE_NAMES:
        return True
    text = str(exc).lower()
    return any(token in text for token in _RETRYABLE_TEXT)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 2.0
    jitter: bool = True
    retry_on: Callable[[BaseException], bool] | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must not be negative")

    def should_retry(self, exc: BaseException) -> bool:
        if self.retry_on is not None:
            return self.retry_on(exc)
        return is_retryable_error(exc)

    def delay(self, attempt: int, random_fn: Callable[[], float] = random.random) -> float:
        raw = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return raw * random_fn() if self.jitter else raw


class RetryingLLM:
    """指数退避加抖动的模型重试包装。

    如果底层 SDK 已经做了重试，避免在外层重复叠加；两层重试相乘
    会迅速放大延迟与费用。
    """

    def __init__(
        self,
        inner: LLM,
        policy: RetryPolicy | None = None,
        *,
        sleep: Callable[[float], None] = default_sleep,
        random_fn: Callable[[], float] = random.random,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.inner = inner
        self.policy = policy or RetryPolicy()
        self.sleep = sleep
        self.random_fn = random_fn
        self.metrics = metrics
        self.retries = 0

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                return self.inner.complete(
                    messages,
                    tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                if attempt >= self.policy.max_attempts or not self.policy.should_retry(exc):
                    raise
                self.retries += 1
                if self.metrics is not None:
                    self.metrics.record_retry()
                self.sleep(self.policy.delay(attempt, self.random_fn))
        raise RuntimeError("unreachable")


class RetryingTool:
    """只对显式声明幂等的工具做重试。

    非幂等工具的重试可能重复扣款、重复发信或重复发布；因此构造时
    就要求 ``idempotent=True``，而不是依赖调用方记得配置。
    """

    def __init__(
        self,
        inner: Tool,
        policy: RetryPolicy | None = None,
        *,
        idempotent: bool,
        sleep: Callable[[float], None] = default_sleep,
        random_fn: Callable[[], float] = random.random,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.inner = inner
        self.spec = inner.spec
        self.policy = policy or RetryPolicy()
        if self.policy.max_attempts > 1 and not idempotent:
            raise ValueError(
                "retrying a non-idempotent tool can duplicate side effects; "
                "pass idempotent=True only when the tool is safe to replay"
            )
        self.idempotent = idempotent
        self.sleep = sleep
        self.random_fn = random_fn
        self.metrics = metrics
        self.retries = 0

    def run(self, arguments: dict) -> ToolOutput:
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                return self.inner.run(arguments)
            except Exception as exc:
                if attempt >= self.policy.max_attempts or not self.policy.should_retry(exc):
                    raise
                self.retries += 1
                if self.metrics is not None:
                    self.metrics.record_retry()
                self.sleep(self.policy.delay(attempt, self.random_fn))
        raise RuntimeError("unreachable")
