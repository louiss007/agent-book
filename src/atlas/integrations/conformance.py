from __future__ import annotations

from dataclasses import dataclass, field

from atlas.agent.runner import AgentRunner
from atlas.types import RunContext, Trajectory


@dataclass(frozen=True)
class ConformanceCase:
    task: str
    expect_answer: bool = True
    expect_stop_reason: str | None = "final_answer"


@dataclass
class ConformanceReport:
    runner: str
    passed: bool
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def check_runner(
    runner: AgentRunner,
    cases: list[ConformanceCase],
    *,
    name: str = "runner",
) -> ConformanceReport:
    """验证一个外部框架包装后是否符合 Atlas 的轨迹契约。"""
    checks: list[str] = []
    failures: list[str] = []

    for index, case in enumerate(cases, start=1):
        label = f"case {index}"
        ctx = RunContext(run_id=f"conformance:{index}")
        try:
            trajectory = runner.run(case.task, ctx)
        except Exception as exc:
            failures.append(f"{label}: raised {type(exc).__name__}: {exc}")
            continue

        if not isinstance(trajectory, Trajectory):
            failures.append(
                f"{label}: returned {type(trajectory).__name__}, expected Trajectory"
            )
            continue

        _check(label, "task", trajectory.task == case.task, failures)
        _check(label, "run_id", trajectory.run_id == ctx.run_id, failures)
        _check(
            label,
            "step_index",
            [step.index for step in trajectory.steps]
            == list(range(1, len(trajectory.steps) + 1)),
            failures,
        )
        if case.expect_stop_reason is not None:
            _check(
                label,
                "stop_reason",
                trajectory.stop_reason == case.expect_stop_reason,
                failures,
            )
        if case.expect_answer:
            _check(
                label,
                "final_answer",
                bool((trajectory.final_answer or "").strip()),
                failures,
            )
        checks.append(label)

    return ConformanceReport(
        runner=name,
        passed=not failures,
        checks=checks,
        failures=failures,
    )


def _check(label: str, name: str, ok: bool, failures: list[str]) -> None:
    if not ok:
        failures.append(f"{label}: {name} check failed")
