from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from atlas.types import Budget, LLMResponse, StopReason, Usage


@dataclass
class RunState:
    step: int
    tool_calls: int
    usage: Usage
    started_at: datetime
    now: datetime
    last_response: LLMResponse | None = None


class StopPolicy(Protocol):
    def check(self, state: RunState) -> StopReason | None:
        ...


class BudgetStopPolicy:
    def __init__(self, budget: Budget) -> None:
        self.budget = budget

    def check(self, state: RunState) -> StopReason | None:
        if (state.now - state.started_at).total_seconds() >= self.budget.max_seconds:
            return "timeout"
        if state.step >= self.budget.max_steps:
            return "max_steps"
        if state.usage.total_tokens >= self.budget.max_tokens:
            return "max_tokens"
        if state.usage.cost_usd >= self.budget.max_cost_usd:
            return "max_cost"
        if state.tool_calls >= self.budget.max_tool_calls:
            # StopReason 没有单独的工具调用终止值，v0.4.0 统一归入 max_steps。
            return "max_steps"
        return None
