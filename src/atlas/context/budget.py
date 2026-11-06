from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudget:
    """把窗口拆成预留、系统、记忆、历史与证据几块，比例只作分配依据。"""

    max_tokens: int = 32_000
    reserve_tokens: int = 2_000
    system_ratio: float = 0.20
    memory_ratio: float = 0.10
    history_ratio: float = 0.60
    evidence_ratio: float = 0.10

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.reserve_tokens < 0:
            raise ValueError("reserve_tokens must not be negative")
        for name in ("system_ratio", "memory_ratio", "history_ratio", "evidence_ratio"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must not be negative")

    @property
    def usable_tokens(self) -> int:
        return max(0, self.max_tokens - self.reserve_tokens)

    @property
    def summary_tokens(self) -> int:
        return max(128, self.usable_tokens // 20)

    def share(self, ratio: float) -> int:
        return max(0, int(self.usable_tokens * ratio))

    @property
    def system_tokens(self) -> int:
        return self.share(self.system_ratio)

    @property
    def memory_tokens(self) -> int:
        return self.share(self.memory_ratio)

    @property
    def history_tokens(self) -> int:
        return self.share(self.history_ratio)

    @property
    def evidence_tokens(self) -> int:
        return self.share(self.evidence_ratio)


@dataclass
class ContextReport:
    """一次上下文组装的压缩记录，便于评测与调试。"""

    before_tokens: int
    after_tokens: int
    dropped_messages: int = 0
    summarized_messages: int = 0
    folded_items: int = 0
    truncated_messages: int = 0
    summary_used: bool = False

    @property
    def saved_tokens(self) -> int:
        return max(0, self.before_tokens - self.after_tokens)

    @property
    def compression_ratio(self) -> float:
        if self.before_tokens <= 0:
            return 1.0
        return self.after_tokens / self.before_tokens

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "saved_tokens": self.saved_tokens,
            "compression_ratio": round(self.compression_ratio, 3),
            "dropped_messages": self.dropped_messages,
            "summarized_messages": self.summarized_messages,
            "folded_items": self.folded_items,
            "truncated_messages": self.truncated_messages,
            "summary_used": self.summary_used,
        }
