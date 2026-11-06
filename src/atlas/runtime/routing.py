from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from atlas.llm.base import LLM, LLMError
from atlas.runtime.metrics import RuntimeMetrics
from atlas.types import LLMResponse, Message, ToolSpec


class Router(Protocol):
    def choose(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        temperature: float,
    ) -> str:
        ...


@dataclass(frozen=True)
class LengthRouter:
    """按提示长度与显式标记选择路由的启发式策略。

    这不是“理解任务难度”，只是把明显的长上下文或人工标记交给强模型。
    生产环境应使用离线评测校准阈值，或训练一个轻量分类器。
    """

    cheap: str = "cheap"
    strong: str = "strong"
    threshold_chars: int = 2000
    strong_marker: str = "[deep]"

    def choose(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        temperature: float,
    ) -> str:
        text = "\n".join(message.content or "" for message in messages)
        if self.strong_marker and self.strong_marker in text:
            return self.strong
        return self.strong if len(text) > self.threshold_chars else self.cheap


class RoutingLLM:
    """把请求分发给不同模型，并按顺序回退。

    ``fallback_order`` 是全局回退顺序；某个路由失败后，会依次尝试其余
    路由。只捕获 ``LLMError``，避免把代码缺陷误当成上游故障。
    """

    def __init__(
        self,
        routes: dict[str, LLM],
        router: Router,
        *,
        fallback_order: Sequence[str] = (),
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        if not routes:
            raise ValueError("routes must not be empty")
        self.routes = dict(routes)
        self.router = router
        self.fallback_order = tuple(fallback_order)
        self.metrics = metrics
        self.counts: dict[str, int] = {name: 0 for name in self.routes}
        self.last_route: str | None = None

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        primary = self.router.choose(messages, tools, temperature)
        if primary not in self.routes:
            raise LLMError(f"unknown route: {primary}")

        order: list[str] = [primary]
        for name in self.fallback_order:
            if name in self.routes and name not in order:
                order.append(name)

        last_error: Exception | None = None
        for index, name in enumerate(order):
            try:
                response = self.routes[name].complete(
                    messages,
                    tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except LLMError as exc:
                last_error = exc
                continue
            self.last_route = name
            self.counts[name] = self.counts.get(name, 0) + 1
            if index > 0 and self.metrics is not None:
                self.metrics.record_fallback()
            return response

        raise LLMError(f"all routes failed: {last_error}")


class FallbackLLM:
    """主模型失败时切换到备用模型的最小实现。"""

    def __init__(
        self,
        primary: LLM,
        fallback: LLM,
        *,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.metrics = metrics
        self.last_route: str | None = None

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        try:
            response = self.primary.complete(
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            self.last_route = "primary"
            return response
        except LLMError:
            if self.metrics is not None:
                self.metrics.record_fallback()
            response = self.fallback.complete(
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            self.last_route = "fallback"
            return response
