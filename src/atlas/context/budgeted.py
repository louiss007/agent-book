from __future__ import annotations

from atlas.context.base import ContextBuilder
from atlas.context.budget import ContextBudget, ContextReport
from atlas.context.compactor import ContextCompactor
from atlas.context.progressive import (
    ExpandContextTool,
    ProgressiveDisclosure,
)
from atlas.context.summarize import Summarizer
from atlas.types import Message, RunContext

DEFAULT_SYSTEM_PROMPT = (
    "你是一个能调用工具的助手。需要外部信息或精确计算时，先调用合适的工具；"
    "拿到足够信息后，用简洁的中文给出最终答案。"
)


class BudgetedContextBuilder:
    """包装任意 ContextBuilder：先组装，再按预算压缩，最后交给模型。"""

    def __init__(
        self,
        inner: ContextBuilder | None = None,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tokens: int = 32_000,
        reserve_tokens: int = 2_000,
        keep_recent: int = 6,
        max_tool_chars: int = 1200,
        preview_chars: int = 240,
        summarizer: Summarizer | None = None,
    ) -> None:
        self.inner = inner
        self.system_prompt = system_prompt
        self.budget = ContextBudget(
            max_tokens=max_tokens,
            reserve_tokens=reserve_tokens,
        )
        self.disclosure = ProgressiveDisclosure()
        self.compactor = ContextCompactor(
            max_tool_chars=max_tool_chars,
            preview_chars=preview_chars,
            keep_recent=keep_recent,
            summarizer=summarizer,
            disclosure=self.disclosure,
        )
        self.last_report = ContextReport(before_tokens=0, after_tokens=0)
        self._expand_tool: ExpandContextTool | None = None

    @property
    def expand_tool(self) -> ExpandContextTool:
        if self._expand_tool is None:
            self._expand_tool = ExpandContextTool(self.disclosure.store)
        return self._expand_tool

    def build(
        self,
        task: str,
        history: list[Message],
        step: int,
        ctx: RunContext,
    ) -> list[Message]:
        if self.inner is not None:
            messages = self.inner.build(task, history, step, ctx)
        else:
            messages = [
                Message(role="system", content=self.system_prompt),
                *history,
            ]

        compacted = self.compactor.compact(messages, self.budget)
        self.last_report = self.compactor.last_report
        return compacted
