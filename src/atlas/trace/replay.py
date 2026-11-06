from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from atlas.trace.events import TraceEvent
from atlas.types import Step, ToolCall, ToolResult, Trajectory, Usage


class TraceFormatError(ValueError):
    """JSONL 行无法解析为合法事件。"""


def load_events(path: str | Path) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                events.append(TraceEvent.from_dict(data))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise TraceFormatError(f"line {line_no}: {exc}") from exc
    return events


def events_for_run(
    events: Sequence[TraceEvent],
    run_id: str | None = None,
) -> list[TraceEvent]:
    if run_id is None:
        for event in events:
            if event.type == "run_start":
                run_id = event.run_id
                break
    if run_id is None:
        return list(events)
    return [event for event in events if event.run_id == run_id]


def _usage_from_payload(payload: dict[str, Any]) -> Usage:
    return Usage(
        prompt_tokens=int(payload.get("prompt_tokens", 0)),
        completion_tokens=int(payload.get("completion_tokens", 0)),
        cached_tokens=int(payload.get("cached_tokens", 0)),
        cost_usd=float(payload.get("cost_usd", 0.0)),
    )


def replay_trajectory(
    events: Sequence[TraceEvent],
    run_id: str | None = None,
) -> Trajectory:
    selected = events_for_run(events, run_id)
    start = next((event for event in selected if event.type == "run_start"), None)
    end = next((event for event in reversed(selected) if event.type == "run_end"), None)
    if start is None:
        raise TraceFormatError("trace has no run_start event")

    resolved_run_id = start.run_id
    task = str(start.payload.get("task", ""))
    steps: list[Step] = []
    for event in selected:
        if event.type != "step":
            continue
        payload = event.payload
        calls: list[ToolCall] = []
        for raw in payload.get("tool_calls", []):
            calls.append(
                ToolCall(
                    id=str(raw.get("id", "")),
                    name=str(raw.get("name", "")),
                    arguments=dict(raw.get("arguments") or {}),
                )
            )
        results: list[ToolResult] = []
        for raw in payload.get("tool_results", []):
            content = str(raw.get("content", ""))
            metadata = dict(raw.get("metadata") or {})
            if raw.get("content_sha256") is not None:
                metadata.setdefault("content_sha256", raw["content_sha256"])
            results.append(
                ToolResult(
                    tool_call_id=str(raw.get("tool_call_id", "")),
                    content=content,
                    is_error=bool(raw.get("is_error", False)),
                    metadata=metadata,
                )
            )
        steps.append(
            Step(
                index=int(payload.get("index", len(steps) + 1)),
                thought=payload.get("thought"),
                tool_calls=calls,
                tool_results=results,
                usage=_usage_from_payload(payload.get("usage") or {}),
            )
        )

    answer = None
    stop_reason = "error"
    usage = Usage()
    ended_at = None
    if end is not None:
        answer = end.payload.get("content")
        stop_reason = str(end.payload.get("stop_reason", "error"))
        usage = _usage_from_payload(end.payload.get("usage") or {})
        ended_at = end.timestamp
    else:
        for step in steps:
            usage = usage + step.usage

    return Trajectory(
        task=task,
        run_id=resolved_run_id,
        steps=steps,
        final_answer=answer,
        stop_reason=stop_reason,  # type: ignore[arg-type]
        usage=usage,
        started_at=start.timestamp,
        ended_at=ended_at,
    )


@dataclass
class TraceSummary:
    run_id: str
    task: str
    stop_reason: str
    steps: int
    tool_calls: int
    tool_errors: int
    duplicate_tool_calls: int
    error_types: dict[str, int]
    total_tokens: int
    cost_usd: float
    duration_seconds: float
    signals: list[str] = field(default_factory=list)
    first_error_event_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "stop_reason": self.stop_reason,
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "duplicate_tool_calls": self.duplicate_tool_calls,
            "error_types": dict(self.error_types),
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "duration_seconds": self.duration_seconds,
            "signals": list(self.signals),
            "first_error_event_id": self.first_error_event_id,
        }


def summarize_trace(
    events: Sequence[TraceEvent],
    run_id: str | None = None,
) -> TraceSummary:
    selected = events_for_run(events, run_id)
    start = next((event for event in selected if event.type == "run_start"), None)
    end = next((event for event in reversed(selected) if event.type == "run_end"), None)
    if start is None:
        raise TraceFormatError("trace has no run_start event")

    step_events = [event for event in selected if event.type == "step"]
    seen: set[tuple[str, str]] = set()
    duplicate_calls = 0
    tool_calls = 0
    for event in selected:
        if event.type != "tool_call":
            continue
        tool_calls += 1
        key = (
            str(event.payload.get("name", "")),
            json.dumps(
                event.payload.get("arguments") or {},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ),
        )
        if key in seen:
            duplicate_calls += 1
        else:
            seen.add(key)

    errors: Counter[str] = Counter()
    tool_errors = 0
    first_error_event_id: str | None = None
    for event in selected:
        if event.type == "tool_result" and event.payload.get("is_error"):
            tool_errors += 1
            error_type = str(
                (event.payload.get("metadata") or {}).get("error_type", "unknown")
            )
            errors[error_type] += 1
            if first_error_event_id is None:
                first_error_event_id = event.event_id

    stop_reason = str(end.payload.get("stop_reason", "missing")) if end else "missing"
    total_tokens = 0
    cost_usd = 0.0
    duration_seconds = 0.0
    answer = ""
    if end is not None:
        usage = end.payload.get("usage") or {}
        total_tokens = int(usage.get("prompt_tokens", 0)) + int(
            usage.get("completion_tokens", 0)
        )
        cost_usd = float(usage.get("cost_usd", 0.0))
        duration_seconds = float(end.payload.get("duration_seconds", 0.0))
        answer = str(end.payload.get("content") or "")

    signals: list[str] = []
    if end is None:
        signals.append("missing_run_end")
    if stop_reason not in {"final_answer", "missing"}:
        signals.append(f"stop:{stop_reason}")
    if tool_errors:
        signals.append("tool_error")
    if duplicate_calls:
        signals.append("duplicate_tool_call")
    if not step_events:
        signals.append("no_steps")
    if end is not None and not answer:
        signals.append("empty_answer")

    return TraceSummary(
        run_id=start.run_id,
        task=str(start.payload.get("task", "")),
        stop_reason=stop_reason,
        steps=len(step_events),
        tool_calls=tool_calls,
        tool_errors=tool_errors,
        duplicate_tool_calls=duplicate_calls,
        error_types=dict(errors),
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        duration_seconds=duration_seconds,
        signals=signals,
        first_error_event_id=first_error_event_id,
    )


@dataclass
class TraceDivergence:
    index: int | None
    reason: str
    baseline_step: dict[str, Any] | None = None
    candidate_step: dict[str, Any] | None = None

    @property
    def diverged(self) -> bool:
        return self.reason != "none"

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "reason": self.reason,
            "baseline_step": self.baseline_step,
            "candidate_step": self.candidate_step,
        }


def _step_signature(payload: dict[str, Any]) -> tuple[Any, Any]:
    calls = [
        (
            str(call.get("name", "")),
            json.dumps(
                call.get("arguments") or {},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ),
        )
        for call in payload.get("tool_calls", [])
    ]
    results = [
        (
            bool(result.get("is_error", False)),
            result.get("content_sha256") or result.get("content") or "",
        )
        for result in payload.get("tool_results", [])
    ]
    return calls, results


def compare_traces(
    baseline: Sequence[TraceEvent],
    candidate: Sequence[TraceEvent],
) -> TraceDivergence:
    base_steps = [event for event in baseline if event.type == "step"]
    cand_steps = [event for event in candidate if event.type == "step"]

    for index, (base, cand) in enumerate(zip(base_steps, cand_steps)):
        base_calls, base_results = _step_signature(base.payload)
        cand_calls, cand_results = _step_signature(cand.payload)
        if base_calls != cand_calls:
            return TraceDivergence(index, "tool_call", base.payload, cand.payload)
        if base_results != cand_results:
            return TraceDivergence(index, "tool_result", base.payload, cand.payload)

    if len(base_steps) != len(cand_steps):
        index = min(len(base_steps), len(cand_steps))
        base_payload = base_steps[index].payload if index < len(base_steps) else None
        cand_payload = cand_steps[index].payload if index < len(cand_steps) else None
        return TraceDivergence(index, "step_count", base_payload, cand_payload)

    def stop(events: Sequence[TraceEvent]) -> str | None:
        for event in reversed(events):
            if event.type == "run_end":
                return str(event.payload.get("stop_reason"))
        return None

    if stop(baseline) != stop(candidate):
        return TraceDivergence(None, "stop_reason")
    return TraceDivergence(None, "none")


@dataclass
class FailureDiagnosis:
    category: str
    evidence: list[str] = field(default_factory=list)
    recovered: bool = False
    first_error_event_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "evidence": list(self.evidence),
            "recovered": self.recovered,
            "first_error_event_id": self.first_error_event_id,
        }


def diagnose_trace(
    events: Sequence[TraceEvent],
    run_id: str | None = None,
) -> FailureDiagnosis:
    summary = summarize_trace(events, run_id)
    succeeded = summary.stop_reason == "final_answer" and "empty_answer" not in summary.signals
    evidence: list[str] = []

    if summary.tool_errors:
        evidence.append(
            f"{summary.tool_errors} tool errors: {summary.error_types}"
        )
        if succeeded:
            evidence.append("run recovered and produced a final answer")
            return FailureDiagnosis(
                "recovered_tool_error",
                evidence,
                recovered=True,
                first_error_event_id=summary.first_error_event_id,
            )
        return FailureDiagnosis(
            "tool_error",
            evidence,
            first_error_event_id=summary.first_error_event_id,
        )

    if summary.stop_reason in {"max_steps", "max_tokens", "max_cost"}:
        return FailureDiagnosis(
            "budget_stop",
            [f"stop_reason={summary.stop_reason}", f"steps={summary.steps}"],
        )
    if summary.stop_reason == "timeout":
        return FailureDiagnosis("timeout", [f"duration={summary.duration_seconds}s"])
    if summary.stop_reason == "denied":
        return FailureDiagnosis("policy_denied", ["stop_reason=denied"])
    if summary.stop_reason == "error":
        return FailureDiagnosis("runtime_error", ["stop_reason=error"])
    if summary.stop_reason == "missing":
        return FailureDiagnosis("incomplete_trace", ["missing run_end event"])
    if "empty_answer" in summary.signals:
        return FailureDiagnosis("empty_answer", ["final answer is empty"])
    if summary.duplicate_tool_calls:
        return FailureDiagnosis(
            "loop_suspected",
            [f"duplicate_tool_calls={summary.duplicate_tool_calls}"],
        )
    if succeeded:
        return FailureDiagnosis("healthy", evidence)
    return FailureDiagnosis("unknown", summary.signals)
