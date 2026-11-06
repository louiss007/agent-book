from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from atlas.trace.events import redact_text, redact_value
from atlas.types import RunContext, Step, Trajectory, utcnow

_GENESIS = "GENESIS"


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    run_id: str
    timestamp: datetime
    actor: str
    action: str
    tool: str | None
    tool_call_id: str | None
    decision: str | None
    reason: str | None
    detail: dict[str, Any]
    prev_hash: str
    hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "actor": self.actor,
            "action": self.action,
            "tool": self.tool,
            "tool_call_id": self.tool_call_id,
            "decision": self.decision,
            "reason": self.reason,
            "detail": self.detail,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


def _record_hash(
    *,
    seq: int,
    run_id: str,
    timestamp: datetime,
    actor: str,
    action: str,
    tool: str | None,
    tool_call_id: str | None,
    decision: str | None,
    reason: str | None,
    detail: dict[str, Any],
    prev_hash: str,
) -> str:
    payload = {
        "seq": seq,
        "run_id": run_id,
        "timestamp": timestamp.isoformat(),
        "actor": actor,
        "action": action,
        "tool": tool,
        "tool_call_id": tool_call_id,
        "decision": decision,
        "reason": reason,
        "detail": detail,
        "prev_hash": prev_hash,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class AuditLog:
    """只追加、带哈希链的审计日志；检测篡改而非提供保密。"""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = Lock()

    @property
    def records(self) -> list[AuditRecord]:
        return list(self._records)

    @property
    def last_hash(self) -> str:
        return self._records[-1].hash if self._records else _GENESIS

    def append(
        self,
        run_id: str,
        actor: str,
        action: str,
        *,
        tool: str | None = None,
        tool_call_id: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditRecord:
        with self._lock:
            seq = len(self._records) + 1
            timestamp = utcnow()
            clean_detail = redact_value(dict(detail or {}), max_chars=2000)
            prev_hash = self.last_hash
            digest = _record_hash(
                seq=seq,
                run_id=run_id,
                timestamp=timestamp,
                actor=actor,
                action=action,
                tool=tool,
                tool_call_id=tool_call_id,
                decision=decision,
                reason=reason,
                detail=clean_detail,
                prev_hash=prev_hash,
            )
            record = AuditRecord(
                seq=seq,
                run_id=run_id,
                timestamp=timestamp,
                actor=actor,
                action=action,
                tool=tool,
                tool_call_id=tool_call_id,
                decision=decision,
                reason=reason,
                detail=clean_detail,
                prev_hash=prev_hash,
                hash=digest,
            )
            self._records.append(record)
            return record

    def for_run(self, run_id: str) -> list[AuditRecord]:
        return [record for record in self._records if record.run_id == run_id]

    def verify(self) -> bool:
        previous = _GENESIS
        for record in self._records:
            if record.prev_hash != previous:
                return False
            expected = _record_hash(
                seq=record.seq,
                run_id=record.run_id,
                timestamp=record.timestamp,
                actor=record.actor,
                action=record.action,
                tool=record.tool,
                tool_call_id=record.tool_call_id,
                decision=record.decision,
                reason=record.reason,
                detail=record.detail,
                prev_hash=record.prev_hash,
            )
            if record.hash != expected:
                return False
            previous = record.hash
        return True

    def export_jsonl(self, path: str | Path) -> None:
        with Path(path).open("w", encoding="utf-8") as handle:
            for record in self._records:
                handle.write(
                    json.dumps(record.to_dict(), ensure_ascii=False, default=str) + "\n"
                )


@dataclass
class AuditTracer:
    """把轨迹中的安全决策写成审计记录；可直接传给 Agent 的 tracer。"""

    log: AuditLog
    actor: str = "agent"
    max_chars: int = 500

    def on_run_start(self, task: str, ctx: RunContext) -> None:
        self.log.append(
            ctx.run_id,
            self.actor,
            "run_start",
            detail={
                "task": redact_text(task, max_chars=self.max_chars),
                "user_id": ctx.user_id,
            },
        )

    def on_step(self, step: Step, ctx: RunContext) -> None:
        names = {call.id: call.name for call in step.tool_calls}
        for call in step.tool_calls:
            self.log.append(
                ctx.run_id,
                self.actor,
                "tool_call",
                tool=call.name,
                tool_call_id=call.id,
                detail={"arguments": redact_value(call.arguments, max_chars=self.max_chars)},
            )
        for result in step.tool_results:
            metadata = result.metadata or {}
            decision = _decision_of(metadata, result.is_error)
            detail: dict[str, Any] = {
                "is_error": result.is_error,
                "error_type": metadata.get("error_type"),
                "guard_decisions": metadata.get("guard_decisions"),
                "injection_suspected": metadata.get("injection_suspected"),
                "redacted": metadata.get("redacted"),
                "skipped": metadata.get("skipped"),
                "approved_by": metadata.get("approved_by"),
                "content_chars": len(result.content or ""),
                "content_sha256": hashlib.sha256(
                    (result.content or "").encode("utf-8")
                ).hexdigest(),
            }
            self.log.append(
                ctx.run_id,
                self.actor,
                "tool_result",
                tool=names.get(result.tool_call_id),
                tool_call_id=result.tool_call_id,
                decision=decision,
                reason=metadata.get("reason"),
                detail=detail,
            )

    def on_run_end(self, trajectory: Trajectory, ctx: RunContext) -> None:
        self.log.append(
            ctx.run_id,
            self.actor,
            "run_end",
            decision=trajectory.stop_reason,
            detail={
                "steps": len(trajectory.steps),
                "stop_reason": trajectory.stop_reason,
                "total_tokens": trajectory.usage.total_tokens,
                "cost_usd": trajectory.usage.cost_usd,
            },
        )


def _decision_of(metadata: dict[str, Any], is_error: bool) -> str:
    if metadata.get("denied"):
        return "deny"
    if metadata.get("approval") == "approved":
        return "approve"
    if metadata.get("sanitized") or metadata.get("redacted"):
        return "modify"
    if is_error:
        return "error"
    return "allow"
