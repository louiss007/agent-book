from __future__ import annotations

import json
import math
import re

from atlas.types import Message

_CJK = re.compile(r"[一-鿿]")


def estimate_tokens(text: str | None) -> int:
    """轻量估算：中文按字、其他字符按四分之一计，不依赖分词器。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return max(1, cjk + math.ceil(other / 4))


def message_tokens(message: Message) -> int:
    total = 4 + estimate_tokens(message.content)
    total += estimate_tokens(message.name)
    total += estimate_tokens(message.tool_call_id)
    for call in message.tool_calls:
        total += 4 + estimate_tokens(call.name)
        total += estimate_tokens(json.dumps(call.arguments, ensure_ascii=False))
    return total


def messages_tokens(messages: list[Message]) -> int:
    return sum(message_tokens(message) for message in messages)
