import json
from typing import Any

from atlas.llm.base import LLMError
from atlas.types import LLMResponse, Message, ToolCall, ToolSpec, Usage

_RETRYABLE = {"APITimeoutError", "APIConnectionError", "RateLimitError"}


class OpenAICompatLLM:
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        from openai import OpenAI

        self.model = model
        self._max_retries = max_retries
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload = self._to_payload(messages)
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=payload,
                    tools=self._to_tools(tools),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return self._from_response(response)
            except Exception as exc:
                retryable = type(exc).__name__ in _RETRYABLE
                if not retryable or attempt == self._max_retries:
                    raise LLMError(f"model call failed: {exc}") from exc
                last_error = exc

        raise LLMError(f"model call failed: {last_error}")

    @staticmethod
    def _to_payload(messages: list[Message]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for message in messages:
            item: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.name:
                item["name"] = message.name
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id
            payload.append(item)
        return payload

    @staticmethod
    def _to_tools(tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in tools
        ]

    def _from_response(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message
        calls = [
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=self._parse_arguments(call.function.arguments),
            )
            for call in (message.tool_calls or [])
        ]

        raw_usage = response.usage
        usage = Usage(
            prompt_tokens=getattr(raw_usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(raw_usage, "completion_tokens", 0) or 0,
            cached_tokens=(
                getattr(getattr(raw_usage, "prompt_tokens_details", None), "cached_tokens", 0)
                or 0
            ),
        )

        finish = choice.finish_reason
        if finish not in ("stop", "tool_calls", "length"):
            finish = "error"

        return LLMResponse(
            content=message.content,
            tool_calls=calls,
            finish_reason=finish,
            usage=usage,
        )

    @staticmethod
    def _parse_arguments(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
