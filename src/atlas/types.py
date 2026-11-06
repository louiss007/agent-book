from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
MemoryKind = Literal["episodic", "semantic", "procedural", "preference"]
StopReason = Literal[
    "final_answer",
    "max_steps",
    "max_tokens",
    "max_cost",
    "timeout",
    "denied",
    "error",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    dangerous: bool = False


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolOutput:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: Role
    content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length", "error"] = "stop"
    usage: Usage = field(default_factory=Usage)


@dataclass
class Step:
    index: int
    thought: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class Trajectory:
    task: str
    run_id: str
    steps: list[Step] = field(default_factory=list)
    final_answer: str | None = None
    stop_reason: StopReason = "final_answer"
    usage: Usage = field(default_factory=Usage)
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None


@dataclass
class Budget:
    max_steps: int = 20
    max_tokens: int = 100_000
    max_cost_usd: float = 1.0
    max_seconds: float = 300.0
    max_tool_calls: int = 40


@dataclass
class RunContext:
    run_id: str
    budget: Budget = field(default_factory=Budget)
    user_id: str | None = None
    deadline_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
