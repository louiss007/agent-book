from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

Capability = Literal[
    "tools",
    "mcp",
    "memory",
    "multi_agent",
    "durability",
    "human_in_loop",
    "guardrails",
    "streaming",
    "tracing",
    "evaluation",
    "low_code",
]
Maturity = Literal["experimental", "stable", "mature"]

_MATURITY_ORDER: dict[str, int] = {
    "experimental": 0,
    "stable": 1,
    "mature": 2,
}


@dataclass(frozen=True)
class FrameworkProfile:
    """框架能力的结构化画像，用于选型比较而不是替代试用。"""

    name: str
    kind: Literal["code", "platform"]
    supports: frozenset[str] = frozenset()
    model_binding: Literal["open", "vendor"] = "open"
    self_hosted: bool = True
    maturity: Maturity = "stable"
    strengths: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

    def missing(self, required: Iterable[str]) -> set[str]:
        return set(required) - self.supports


@dataclass(frozen=True)
class Requirements:
    """选型需求。required 是硬约束，preferred 参与排序。"""

    required: frozenset[str] = frozenset()
    preferred: frozenset[str] = frozenset()
    must_self_host: bool = False
    must_support_open_models: bool = False
    min_maturity: Maturity = "experimental"


@dataclass(frozen=True)
class FrameworkChoice:
    profile: FrameworkProfile
    score: float
    matched: frozenset[str]
    reasons: tuple[str, ...]


def select_frameworks(
    profiles: Iterable[FrameworkProfile],
    requirements: Requirements,
    *,
    limit: int = 3,
) -> list[FrameworkChoice]:
    """按硬约束过滤、按偏好排序；不声称绝对优劣，只给出候选顺序。"""
    if limit < 1:
        raise ValueError("limit must be >= 1")

    choices: list[FrameworkChoice] = []
    for profile in profiles:
        missing = profile.missing(requirements.required)
        if missing:
            continue
        if requirements.must_self_host and not profile.self_hosted:
            continue
        if (
            requirements.must_support_open_models
            and profile.model_binding != "open"
        ):
            continue
        if (
            _MATURITY_ORDER[profile.maturity]
            < _MATURITY_ORDER[requirements.min_maturity]
        ):
            continue

        matched = requirements.preferred & profile.supports
        reasons = [f"满足硬约束：{len(requirements.required)} 项"]
        if matched:
            reasons.append(f"命中偏好：{', '.join(sorted(matched))}")
        if profile.self_hosted:
            reasons.append("可自托管")
        score = (
            len(matched) * 2.0
            + _MATURITY_ORDER[profile.maturity] * 0.25
            + (0.25 if profile.model_binding == "open" else 0.0)
            + (0.25 if profile.self_hosted else 0.0)
        )
        choices.append(
            FrameworkChoice(
                profile=profile,
                score=round(score, 2),
                matched=frozenset(matched),
                reasons=tuple(reasons),
            )
        )

    choices.sort(key=lambda item: (-item.score, item.profile.name))
    return choices[:limit]
