from collections.abc import Callable, Sequence

from atlas.llm.base import LLMError
from atlas.types import LLMResponse, Message, ToolSpec


class MockLLM:
    """按脚本返回预设响应；脚本耗尽后抛错，避免测试悄悄跑偏。"""

    model = "mock"

    def __init__(
        self,
        script: Sequence[LLMResponse] | None = None,
        responder: Callable[[list[Message], list[ToolSpec] | None], LLMResponse] | None = None,
    ) -> None:
        self._script = list(script or [])
        self._responder = responder
        self.calls: list[list[Message]] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if self._responder is not None:
            return self._responder(messages, tools)
        if not self._script:
            raise LLMError("MockLLM script exhausted")
        return self._script.pop(0)
