from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from atlas.trace.events import (
    TraceEvent,
    build_run_end,
    build_run_start,
    build_step_events,
    event_to_json,
)
from atlas.types import RunContext, Step, Trajectory


class InMemoryTracer:
    """把事件留在内存中，适合测试与一次性的根因分析。"""

    def __init__(
        self,
        *,
        max_chars: int = 4000,
        redact: bool = True,
        include_content: bool = True,
    ) -> None:
        self.events: list[TraceEvent] = []
        self.max_chars = max_chars
        self.redact = redact
        self.include_content = include_content

    def on_run_start(self, task: str, ctx: RunContext) -> None:
        self.events.append(
            build_run_start(
                task, ctx, max_chars=self.max_chars, redact=self.redact
            )
        )

    def on_step(self, step: Step, ctx: RunContext) -> None:
        self.events.extend(
            build_step_events(
                step,
                ctx,
                max_chars=self.max_chars,
                redact=self.redact,
                include_content=self.include_content,
            )
        )

    def on_run_end(self, trajectory: Trajectory, ctx: RunContext) -> None:
        self.events.append(
            build_run_end(
                trajectory,
                max_chars=self.max_chars,
                redact=self.redact,
                include_content=self.include_content,
            )
        )

    def events_for_run(self, run_id: str) -> list[TraceEvent]:
        return [event for event in self.events if event.run_id == run_id]

    def clear(self) -> None:
        self.events.clear()


class JSONLTracer:
    """追加写入 JSONL；按 run_id 确定性采样，写入失败由 Agent 侧隔离。"""

    def __init__(
        self,
        path: str | Path,
        *,
        max_chars: int = 4000,
        redact: bool = True,
        include_content: bool = True,
        sample_rate: float = 1.0,
    ) -> None:
        if not 0.0 <= sample_rate <= 1.0:
            raise ValueError("sample_rate must be between 0 and 1")
        self.path = Path(path)
        self.max_chars = max_chars
        self.redact = redact
        self.include_content = include_content
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._decisions: dict[str, bool] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _should_record(self, run_id: str) -> bool:
        cached = self._decisions.get(run_id)
        if cached is not None:
            return cached
        if self.sample_rate >= 1.0:
            decision = True
        elif self.sample_rate <= 0.0:
            decision = False
        else:
            digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
            bucket = int(digest[:8], 16) % 10_000
            decision = bucket < int(self.sample_rate * 10_000)
        self._decisions[run_id] = decision
        return decision

    def _write(self, events: Iterable[TraceEvent]) -> None:
        lines = [event_to_json(event) for event in events]
        if not lines:
            return
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(line + "\n")

    def on_run_start(self, task: str, ctx: RunContext) -> None:
        if not self._should_record(ctx.run_id):
            return
        self._write(
            [
                build_run_start(
                    task, ctx, max_chars=self.max_chars, redact=self.redact
                )
            ]
        )

    def on_step(self, step: Step, ctx: RunContext) -> None:
        if not self._should_record(ctx.run_id):
            return
        self._write(
            build_step_events(
                step,
                ctx,
                max_chars=self.max_chars,
                redact=self.redact,
                include_content=self.include_content,
            )
        )

    def on_run_end(self, trajectory: Trajectory, ctx: RunContext) -> None:
        if not self._should_record(ctx.run_id):
            return
        self._write(
            [
                build_run_end(
                    trajectory,
                    max_chars=self.max_chars,
                    redact=self.redact,
                    include_content=self.include_content,
                )
            ]
        )


class CompositeTracer:
    """把同一事件扇出给多个接收器；单个接收器失败不阻塞其他接收器。"""

    def __init__(self, tracers: Iterable[Any]) -> None:
        self.tracers = list(tracers)
        self.errors: list[tuple[str, str]] = []

    def _fan_out(self, method: str, *args: Any) -> None:
        for tracer in self.tracers:
            try:
                getattr(tracer, method)(*args)
            except Exception as exc:
                self.errors.append(
                    (type(tracer).__name__, f"{type(exc).__name__}: {exc}")
                )

    def on_run_start(self, task: str, ctx: RunContext) -> None:
        self._fan_out("on_run_start", task, ctx)

    def on_step(self, step: Step, ctx: RunContext) -> None:
        self._fan_out("on_step", step, ctx)

    def on_run_end(self, trajectory: Trajectory, ctx: RunContext) -> None:
        self._fan_out("on_run_end", trajectory, ctx)
