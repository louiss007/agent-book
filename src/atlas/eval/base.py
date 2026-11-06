from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from atlas.types import Trajectory


@dataclass
class EvalTask:
    id: str
    question: str
    reference: str | None = None
    rubric: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    task_id: str
    trajectory: Trajectory
    score: float
    passed: bool
    detail: dict[str, Any] = field(default_factory=dict)


class Evaluator(Protocol):
    def score(self, task: EvalTask, trajectory: Trajectory) -> EvalResult:
        ...
