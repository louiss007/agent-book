from __future__ import annotations

import os
from dataclasses import dataclass, field

from atlas.types import Budget

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(f"invalid boolean: {value!r}")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else int(raw)


@dataclass
class AtlasConfig:
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    offline: bool = False
    max_context_tokens: int = 32_000
    budget: Budget = field(default_factory=Budget)

    @classmethod
    def from_env(cls, prefix: str = "ATLAS_") -> "AtlasConfig":
        model = os.environ.get(f"{prefix}MODEL", "").strip()
        budget = Budget(
            max_steps=_env_int(f"{prefix}MAX_STEPS", Budget.max_steps),
            max_tokens=_env_int(f"{prefix}MAX_TOKENS", Budget.max_tokens),
            max_cost_usd=_env_float(f"{prefix}MAX_COST_USD", Budget.max_cost_usd),
            max_seconds=_env_float(f"{prefix}MAX_SECONDS", Budget.max_seconds),
            max_tool_calls=_env_int(
                f"{prefix}MAX_TOOL_CALLS", Budget.max_tool_calls
            ),
        )
        return cls(
            model=model or "gpt-4o-mini",
            api_key=os.environ.get(f"{prefix}API_KEY") or None,
            base_url=os.environ.get(f"{prefix}BASE_URL") or None,
            temperature=_env_float(f"{prefix}TEMPERATURE", 0.0),
            offline=_env_bool(os.environ.get(f"{prefix}OFFLINE"), False),
            max_context_tokens=_env_int(
                f"{prefix}MAX_CONTEXT_TOKENS", 32_000
            ),
            budget=budget,
        )
