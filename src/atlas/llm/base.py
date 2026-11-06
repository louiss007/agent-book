from typing import Protocol

from atlas.types import LLMResponse, Message, ToolSpec


class LLMError(RuntimeError):
    """模型调用最终失败，Agent 会把它转换为 stop_reason='error'。"""


class LLM(Protocol):
    model: str

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        ...
