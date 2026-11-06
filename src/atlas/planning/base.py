from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from atlas.types import Message

PlanStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class PlanStep:
    id: str
    description: str
    status: PlanStatus = "pending"


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)


class Planner(Protocol):
    def plan(self, task: str, history: list[Message]) -> Plan:
        ...
