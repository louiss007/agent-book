from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from atlas.eval.base import EvalResult
from atlas.types import Trajectory


@dataclass
class TrajectoryMetrics:
    steps: int = 0
    tool_calls: int = 0
    failed_tool_calls: int = 0
    duplicate_tool_calls: int = 0
    max_parallel_calls: int = 0
    unique_tools: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    stop_reason: str = "final_answer"
    tool_errors: dict[str, int] = field(default_factory=dict)
    tool_names: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "duplicate_tool_calls": self.duplicate_tool_calls,
            "max_parallel_calls": self.max_parallel_calls,
            "unique_tools": self.unique_tools,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "duration_seconds": self.duration_seconds,
            "stop_reason": self.stop_reason,
            "tool_errors": dict(self.tool_errors),
            "tool_names": list(self.tool_names),
        }


def collect_metrics(trajectory: Trajectory) -> TrajectoryMetrics:
    names: list[str] = []
    seen: set[tuple[str, str]] = set()
    duplicate_calls = 0
    failed_calls = 0
    max_parallel = 0
    errors: Counter[str] = Counter()

    for step in trajectory.steps:
        max_parallel = max(max_parallel, len(step.tool_calls))
        for call in step.tool_calls:
            names.append(call.name)
            key = (
                call.name,
                json.dumps(call.arguments, sort_keys=True, ensure_ascii=False, default=str),
            )
            if key in seen:
                duplicate_calls += 1
            else:
                seen.add(key)
        for result in step.tool_results:
            if result.is_error:
                failed_calls += 1
                errors[str(result.metadata.get("error_type", "unknown"))] += 1

    duration = 0.0
    if trajectory.ended_at is not None:
        duration = max(
            0.0,
            (trajectory.ended_at - trajectory.started_at).total_seconds(),
        )

    usage = trajectory.usage
    return TrajectoryMetrics(
        steps=len(trajectory.steps),
        tool_calls=len(names),
        failed_tool_calls=failed_calls,
        duplicate_tool_calls=duplicate_calls,
        max_parallel_calls=max_parallel,
        unique_tools=len(set(names)),
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        cost_usd=usage.cost_usd,
        duration_seconds=duration,
        stop_reason=trajectory.stop_reason,
        tool_errors=dict(errors),
        tool_names=names,
    )


@dataclass
class EvalSummary:
    task_count: int
    attempt_count: int
    passed_attempts: int
    pass_rate: float
    pass_at_k: float
    pass_pow_k: float
    mean_score: float
    total_tokens: int
    mean_tokens: float
    total_cost_usd: float
    cost_per_success: float | None
    mean_latency_seconds: float
    p95_latency_seconds: float
    stop_reasons: dict[str, int]
    failed_task_ids: list[str]
    k: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_count": self.task_count,
            "attempt_count": self.attempt_count,
            "passed_attempts": self.passed_attempts,
            "pass_rate": self.pass_rate,
            "pass_at_k": self.pass_at_k,
            "pass_pow_k": self.pass_pow_k,
            "mean_score": self.mean_score,
            "total_tokens": self.total_tokens,
            "mean_tokens": self.mean_tokens,
            "total_cost_usd": self.total_cost_usd,
            "cost_per_success": self.cost_per_success,
            "mean_latency_seconds": self.mean_latency_seconds,
            "p95_latency_seconds": self.p95_latency_seconds,
            "stop_reasons": dict(self.stop_reasons),
            "failed_task_ids": list(self.failed_task_ids),
            "k": self.k,
        }


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(q * len(ordered)) - 1)
    return ordered[index]


def summarize(results: Iterable[EvalResult], *, k: int | None = None) -> EvalSummary:
    rows = list(results)
    if not rows:
        raise ValueError("cannot summarize an empty result set")

    by_task: dict[str, list[EvalResult]] = defaultdict(list)
    for row in rows:
        by_task[row.task_id].append(row)

    k = k or max(len(group) for group in by_task.values())
    passed_attempts = sum(1 for row in rows if row.passed)
    any_pass = sum(1 for group in by_task.values() if any(r.passed for r in group))
    all_pass = sum(1 for group in by_task.values() if all(r.passed for r in group))
    task_count = len(by_task)
    attempt_count = len(rows)

    total_tokens = sum(collect_metrics(row.trajectory).total_tokens for row in rows)
    total_cost = sum(collect_metrics(row.trajectory).cost_usd for row in rows)
    latencies = [collect_metrics(row.trajectory).duration_seconds for row in rows]
    stop_reasons = Counter(row.trajectory.stop_reason for row in rows)

    return EvalSummary(
        task_count=task_count,
        attempt_count=attempt_count,
        passed_attempts=passed_attempts,
        pass_rate=passed_attempts / attempt_count,
        pass_at_k=any_pass / task_count,
        pass_pow_k=all_pass / task_count,
        mean_score=sum(row.score for row in rows) / attempt_count,
        total_tokens=total_tokens,
        mean_tokens=total_tokens / attempt_count,
        total_cost_usd=total_cost,
        cost_per_success=(total_cost / passed_attempts) if passed_attempts else None,
        mean_latency_seconds=sum(latencies) / attempt_count,
        p95_latency_seconds=_percentile(latencies, 0.95),
        stop_reasons=dict(stop_reasons),
        failed_task_ids=sorted(
            task_id for task_id, group in by_task.items() if not any(r.passed for r in group)
        ),
        k=k,
    )
