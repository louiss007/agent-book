from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from atlas.types import RunContext, Step, Trajectory, utcnow

SCHEMA_VERSION = 1

EventType = Literal[
    "run_start",
    "step",
    "tool_call",
    "tool_result",
    "run_end",
    "note",
]

_SECRET_PATTERNS = (
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\b\s*[:=]\s*\S+"),
     r"\1=<redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "<redacted>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
)

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "secret",
}


def redact_text(text: str, *, max_chars: int = 4000) -> str:
    """先脱敏再截断；顺序不能反，否则密钥可能被截断成无法识别的片段。"""

    value = text
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    if max_chars >= 0 and len(value) > max_chars:
        omitted = len(value) - max_chars
        value = value[:max_chars] + f"...[truncated {omitted} chars]"
    return value


def redact_value(value: Any, *, max_chars: int = 4000) -> Any:
    if isinstance(value, str):
        return redact_text(value, max_chars=max_chars)
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                redacted[str(key)] = "<redacted>"
            else:
                redacted[str(key)] = redact_value(item, max_chars=max_chars)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_value(item, max_chars=max_chars) for item in value]
    return value


def content_fields(content: str | None, *, include_content: bool) -> dict[str, Any]:
    if content is None:
        return {"content": None}
    if include_content:
        return {"content": content}
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {"content_sha256": digest, "content_chars": len(content)}


@dataclass
class TraceEvent:
    run_id: str
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    parent_id: str | None = None
    timestamp: datetime = field(default_factory=utcnow)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "parent_id": self.parent_id,
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TraceEvent":
        return cls(
            run_id=str(data["run_id"]),
            type=str(data["type"]),  # type: ignore[arg-type]
            payload=dict(data.get("payload") or {}),
            event_id=str(data.get("event_id") or uuid4().hex),
            parent_id=data.get("parent_id"),
            timestamp=datetime.fromisoformat(str(data["timestamp"])),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )


def usage_dict(usage) -> dict[str, Any]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cached_tokens": usage.cached_tokens,
        "cost_usd": usage.cost_usd,
    }


def build_run_start(
    task: str,
    ctx: RunContext,
    *,
    max_chars: int = 4000,
    redact: bool = True,
) -> TraceEvent:
    payload: dict[str, Any] = {
        "task": redact_text(task, max_chars=max_chars) if redact else task[:max_chars],
        "user_id": ctx.user_id,
        "budget": {
            "max_steps": ctx.budget.max_steps,
            "max_tokens": ctx.budget.max_tokens,
            "max_cost_usd": ctx.budget.max_cost_usd,
            "max_seconds": ctx.budget.max_seconds,
            "max_tool_calls": ctx.budget.max_tool_calls,
        },
        "metadata": redact_value(ctx.metadata, max_chars=max_chars) if redact else ctx.metadata,
    }
    return TraceEvent(run_id=ctx.run_id, type="run_start", payload=payload)


def build_step_events(
    step: Step,
    ctx: RunContext,
    *,
    max_chars: int = 4000,
    redact: bool = True,
    include_content: bool = True,
) -> list[TraceEvent]:
    def clean(value: Any) -> Any:
        return redact_value(value, max_chars=max_chars) if redact else value

    def render_content(content: str) -> dict[str, Any]:
        return content_fields(
            redact_text(content, max_chars=max_chars) if redact else content[:max_chars],
            include_content=include_content,
        )

    step_event = TraceEvent(
        run_id=ctx.run_id,
        type="step",
        payload={
            "index": step.index,
            "thought": (
                redact_text(step.thought, max_chars=max_chars)
                if step.thought is not None and redact
                else step.thought
            ),
            "usage": usage_dict(step.usage),
            "tool_calls": [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": clean(call.arguments),
                }
                for call in step.tool_calls
            ],
            "tool_results": [
                {
                    "tool_call_id": result.tool_call_id,
                    "is_error": result.is_error,
                    "metadata": clean(result.metadata),
                    **render_content(result.content),
                }
                for result in step.tool_results
            ],
        },
    )

    events = [step_event]
    call_events: dict[str, TraceEvent] = {}
    for call in step.tool_calls:
        call_event = TraceEvent(
            run_id=ctx.run_id,
            type="tool_call",
            parent_id=step_event.event_id,
            payload={
                "tool_call_id": call.id,
                "name": call.name,
                "arguments": clean(call.arguments),
            },
        )
        call_events[call.id] = call_event
        events.append(call_event)

    for result in step.tool_results:
        parent = call_events.get(result.tool_call_id)
        events.append(
            TraceEvent(
                run_id=ctx.run_id,
                type="tool_result",
                parent_id=parent.event_id if parent is not None else step_event.event_id,
                payload={
                    "tool_call_id": result.tool_call_id,
                    "is_error": result.is_error,
                    "metadata": clean(result.metadata),
                    **render_content(result.content),
                },
            )
        )
    return events


def build_run_end(
    trajectory: Trajectory,
    *,
    max_chars: int = 4000,
    redact: bool = True,
    include_content: bool = True,
) -> TraceEvent:
    answer = trajectory.final_answer
    if answer is not None:
        answer = redact_text(answer, max_chars=max_chars) if redact else answer[:max_chars]
    duration = 0.0
    if trajectory.ended_at is not None:
        duration = max(0.0, (trajectory.ended_at - trajectory.started_at).total_seconds())
    payload: dict[str, Any] = {
        "stop_reason": trajectory.stop_reason,
        "usage": usage_dict(trajectory.usage),
        "steps": len(trajectory.steps),
        "duration_seconds": duration,
        **content_fields(answer, include_content=include_content),
    }
    return TraceEvent(run_id=trajectory.run_id, type="run_end", payload=payload)


def note_event(run_id: str, message: str, *, max_chars: int = 4000) -> TraceEvent:
    return TraceEvent(
        run_id=run_id,
        type="note",
        payload={"message": redact_text(message, max_chars=max_chars)},
    )


def event_to_json(event: TraceEvent) -> str:
    return json.dumps(event.to_dict(), ensure_ascii=False, default=str)
