from __future__ import annotations

from typing import Protocol

from atlas.context.tokens import estimate_tokens


class Summarizer(Protocol):
    def summarize(self, text: str, *, max_tokens: int) -> str:
        ...


class ExtractiveSummarizer:
    """离线抽取式摘要：按行保留前若干条，适合演示，不替代模型摘要。"""

    def __init__(self, max_lines: int = 12) -> None:
        self.max_lines = max(1, max_lines)

    def summarize(self, text: str, *, max_tokens: int = 400) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""

        selected: list[str] = []
        used = 0
        for line in lines:
            if len(selected) >= self.max_lines:
                break
            cost = estimate_tokens(line)
            if selected and used + cost > max_tokens:
                break
            if not selected and cost > max_tokens:
                budget_chars = max(80, max_tokens * 2)
                selected.append(line[:budget_chars] + "…")
                break
            selected.append(line)
            used += cost

        suffix = "\n…" if len(selected) < len(lines) else ""
        return "\n".join(selected) + suffix
