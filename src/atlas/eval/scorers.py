from __future__ import annotations

from collections.abc import Sequence

from atlas.eval.base import EvalResult, EvalTask, Evaluator
from atlas.eval.metrics import collect_metrics
from atlas.types import Trajectory


def _normalize(text: str, *, case_sensitive: bool) -> str:
    collapsed = " ".join(text.strip().split())
    return collapsed if case_sensitive else collapsed.lower()


class ExactMatchEvaluator:
    """答案必须与参考完全一致，适合有唯一可判定答案的任务。"""

    def __init__(self, *, case_sensitive: bool = False) -> None:
        self.case_sensitive = case_sensitive

    def score(self, task: EvalTask, trajectory: Trajectory) -> EvalResult:
        answer = trajectory.final_answer or ""
        if task.reference is None:
            return EvalResult(
                task_id=task.id,
                trajectory=trajectory,
                score=0.0,
                passed=False,
                detail={"error": "task has no reference"},
            )
        expected = task.reference
        ok = _normalize(answer, case_sensitive=self.case_sensitive) == _normalize(
            expected, case_sensitive=self.case_sensitive
        )
        return EvalResult(
            task_id=task.id,
            trajectory=trajectory,
            score=1.0 if ok else 0.0,
            passed=ok,
            detail={
                "expected": expected,
                "answer": answer,
                "stop_reason": trajectory.stop_reason,
            },
        )


class ContainsEvaluator:
    """参考文本或必需片段必须出现在最终答案中。"""

    def __init__(self, *, case_sensitive: bool = False) -> None:
        self.case_sensitive = case_sensitive

    def score(self, task: EvalTask, trajectory: Trajectory) -> EvalResult:
        answer = trajectory.final_answer or ""
        required = task.metadata.get("required_snippets")
        if required is None:
            required = [task.reference] if task.reference else []
        required = [str(item) for item in required if str(item).strip()]
        if not required:
            return EvalResult(
                task_id=task.id,
                trajectory=trajectory,
                score=0.0,
                passed=False,
                detail={"error": "task has no reference or required_snippets"},
            )

        haystack = _normalize(answer, case_sensitive=self.case_sensitive)
        matched = [
            item
            for item in required
            if _normalize(item, case_sensitive=self.case_sensitive) in haystack
        ]
        score = len(matched) / len(required)
        return EvalResult(
            task_id=task.id,
            trajectory=trajectory,
            score=score,
            passed=len(matched) == len(required),
            detail={
                "required": required,
                "matched": matched,
                "answer": answer,
                "stop_reason": trajectory.stop_reason,
            },
        )


class TrajectoryEvaluator:
    """检查过程约束，不判断答案内容是否正确。"""

    def __init__(
        self,
        *,
        require_final_answer: bool = True,
        max_steps: int | None = None,
        max_tool_calls: int | None = None,
        required_tools: Sequence[str] = (),
        forbidden_tools: Sequence[str] = (),
        allow_tool_errors: bool = True,
    ) -> None:
        self.require_final_answer = require_final_answer
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.required_tools = set(required_tools)
        self.forbidden_tools = set(forbidden_tools)
        self.allow_tool_errors = allow_tool_errors

    def score(self, task: EvalTask, trajectory: Trajectory) -> EvalResult:
        metrics = collect_metrics(trajectory)
        used_tools = set(metrics.tool_names)
        checks: dict[str, bool] = {}

        if self.require_final_answer:
            checks["final_answer"] = trajectory.stop_reason == "final_answer"
            checks["non_empty_answer"] = bool((trajectory.final_answer or "").strip())
        if self.max_steps is not None:
            checks["max_steps"] = metrics.steps <= self.max_steps
        if self.max_tool_calls is not None:
            checks["max_tool_calls"] = metrics.tool_calls <= self.max_tool_calls
        if self.required_tools:
            checks["required_tools"] = self.required_tools <= used_tools
        if self.forbidden_tools:
            checks["forbidden_tools"] = not (self.forbidden_tools & used_tools)
        if not self.allow_tool_errors:
            checks["no_tool_errors"] = metrics.failed_tool_calls == 0

        passed = all(checks.values())
        score = sum(checks.values()) / len(checks) if checks else 1.0
        return EvalResult(
            task_id=task.id,
            trajectory=trajectory,
            score=score,
            passed=passed,
            detail={"checks": checks, "metrics": metrics.as_dict()},
        )


class WeightedEvaluator:
    """把答案正确性与过程约束按权重合成一个分数。"""

    def __init__(
        self,
        parts: Sequence[tuple[Evaluator, float]],
        *,
        pass_threshold: float = 0.7,
    ) -> None:
        if not parts:
            raise ValueError("at least one evaluator is required")
        if any(weight < 0 for _, weight in parts):
            raise ValueError("weights must be non-negative")
        if sum(weight for _, weight in parts) <= 0:
            raise ValueError("total weight must be positive")
        self.parts = list(parts)
        self.pass_threshold = pass_threshold

    def score(self, task: EvalTask, trajectory: Trajectory) -> EvalResult:
        results = [evaluator.score(task, trajectory) for evaluator, _ in self.parts]
        total_weight = sum(weight for _, weight in self.parts)
        score = sum(
            result.score * weight
            for result, (_, weight) in zip(results, self.parts)
        ) / total_weight
        passed = score >= self.pass_threshold
        return EvalResult(
            task_id=task.id,
            trajectory=trajectory,
            score=score,
            passed=passed,
            detail={
                "threshold": self.pass_threshold,
                "parts": [
                    {
                        "score": result.score,
                        "passed": result.passed,
                        "detail": result.detail,
                    }
                    for result in results
                ],
            },
        )
