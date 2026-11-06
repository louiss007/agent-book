from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from atlas.agent.runner import AgentRunner
from atlas.eval.base import EvalResult, EvalTask, Evaluator
from atlas.eval.metrics import EvalSummary, collect_metrics, summarize
from atlas.types import Budget, RunContext, Trajectory, utcnow


@dataclass
class EvalReport:
    name: str
    results: list[EvalResult]
    summary: EvalSummary
    metadata: dict[str, Any] = field(default_factory=dict)

    def by_task(self) -> dict[str, list[EvalResult]]:
        grouped: dict[str, list[EvalResult]] = defaultdict(list)
        for result in self.results:
            grouped[result.task_id].append(result)
        return dict(grouped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary.as_dict(),
            "metadata": dict(self.metadata),
            "results": [
                {
                    "task_id": result.task_id,
                    "score": result.score,
                    "passed": result.passed,
                    "detail": result.detail,
                    "metrics": collect_metrics(result.trajectory).as_dict(),
                }
                for result in self.results
            ],
        }


class EvalRunner:
    """按任务运行 Agent，聚合成败、轨迹与成本，并保留失败现场。"""

    def __init__(
        self,
        runner: AgentRunner,
        evaluator: Evaluator,
        *,
        name: str = "eval",
        budget: Budget | None = None,
        repeat: int = 1,
    ) -> None:
        if repeat < 1:
            raise ValueError("repeat must be at least 1")
        self.runner = runner
        self.evaluator = evaluator
        self.name = name
        self.budget = budget or Budget()
        self.repeat = repeat

    def run(
        self,
        tasks: Sequence[EvalTask],
        *,
        budget: Budget | None = None,
        repeat: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EvalReport:
        task_list = list(tasks)
        if not task_list:
            raise ValueError("at least one eval task is required")
        attempts = repeat or self.repeat
        if attempts < 1:
            raise ValueError("repeat must be at least 1")

        base_budget = budget or self.budget
        results: list[EvalResult] = []
        for task in task_list:
            for attempt in range(1, attempts + 1):
                ctx = RunContext(
                    run_id=f"{self.name}:{task.id}:{attempt}",
                    budget=replace(base_budget),
                    metadata={"eval_task_id": task.id, "attempt": attempt},
                )
                try:
                    trajectory = self.runner.run(task.question, ctx)
                except Exception as exc:  # 评测不能因单个任务崩溃而丢失整批数据
                    trajectory = Trajectory(
                        task=task.question,
                        run_id=ctx.run_id,
                        stop_reason="error",
                        ended_at=utcnow(),
                    )
                    results.append(
                        EvalResult(
                            task_id=task.id,
                            trajectory=trajectory,
                            score=0.0,
                            passed=False,
                            detail={
                                "error": f"{type(exc).__name__}: {exc}",
                                "attempt": attempt,
                            },
                        )
                    )
                    continue

                result = self.evaluator.score(task, trajectory)
                result.detail.setdefault("attempt", attempt)
                results.append(result)

        summary = summarize(results, k=attempts)
        return EvalReport(
            name=self.name,
            results=results,
            summary=summary,
            metadata={"repeat": attempts, **(metadata or {})},
        )


@dataclass
class TaskDelta:
    task_id: str
    baseline_score: float
    candidate_score: float
    baseline_pass_rate: float
    candidate_pass_rate: float
    delta: float


@dataclass
class RegressionReport:
    baseline_name: str
    candidate_name: str
    regressions: list[TaskDelta]
    improvements: list[TaskDelta]
    unchanged: int
    missing_task_ids: list[str]
    pass_rate_delta: float
    mean_score_delta: float
    cost_per_success_delta: float | None

    def ok(
        self,
        *,
        max_regressions: int = 0,
        min_pass_rate_delta: float = 0.0,
    ) -> bool:
        return (
            len(self.regressions) <= max_regressions
            and self.pass_rate_delta >= min_pass_rate_delta
            and not self.missing_task_ids
        )


def _task_stats(report: EvalReport) -> dict[str, tuple[float, float]]:
    stats: dict[str, tuple[float, float]] = {}
    for task_id, group in report.by_task().items():
        stats[task_id] = (
            sum(result.score for result in group) / len(group),
            sum(1 for result in group if result.passed) / len(group),
        )
    return stats


def compare_reports(
    baseline: EvalReport,
    candidate: EvalReport,
    *,
    tolerance: float = 0.0,
) -> RegressionReport:
    baseline_stats = _task_stats(baseline)
    candidate_stats = _task_stats(candidate)
    common = sorted(set(baseline_stats) & set(candidate_stats))
    missing = sorted(set(baseline_stats) - set(candidate_stats))

    regressions: list[TaskDelta] = []
    improvements: list[TaskDelta] = []
    unchanged = 0
    for task_id in common:
        base_score, base_pass = baseline_stats[task_id]
        cand_score, cand_pass = candidate_stats[task_id]
        delta = cand_score - base_score
        item = TaskDelta(
            task_id=task_id,
            baseline_score=base_score,
            candidate_score=cand_score,
            baseline_pass_rate=base_pass,
            candidate_pass_rate=cand_pass,
            delta=delta,
        )
        if delta < -tolerance:
            regressions.append(item)
        elif delta > tolerance:
            improvements.append(item)
        else:
            unchanged += 1

    def _cost_delta() -> float | None:
        base = baseline.summary.cost_per_success
        cand = candidate.summary.cost_per_success
        if base is None or cand is None:
            return None
        return cand - base

    return RegressionReport(
        baseline_name=baseline.name,
        candidate_name=candidate.name,
        regressions=regressions,
        improvements=improvements,
        unchanged=unchanged,
        missing_task_ids=missing,
        pass_rate_delta=candidate.summary.pass_rate - baseline.summary.pass_rate,
        mean_score_delta=candidate.summary.mean_score - baseline.summary.mean_score,
        cost_per_success_delta=_cost_delta(),
    )
