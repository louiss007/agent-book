from __future__ import annotations

import re

_WORD = re.compile(r"[a-zA-Z0-9_]+")
_CJK = re.compile(r"[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """英文按词、中文按二元组切分；不依赖第三方分词器。"""
    lowered = text.lower()
    tokens = _WORD.findall(lowered)
    for run in _CJK.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens
