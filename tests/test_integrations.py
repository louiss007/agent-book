from __future__ import annotations

import pytest

from atlas.integrations import (
    CallableAgentRunner,
    ConformanceCase,
    FrameworkProfile,
    Requirements,
    as_agent_runner,
    check_runner,
    select_frameworks,
)
from atlas.types import RunContext, Step, Trajectory


def profile(
    name: str,
    *,
    supports: set[str] | None = None,
    self_hosted: bool = True,
    model_binding: str = "open",
    maturity: str = "stable",
) -> FrameworkProfile:
    return FrameworkProfile(
        name=name,
        kind="code",
        supports=frozenset(supports or set()),
        self_hosted=self_hosted,
        model_binding=model_binding,  # type: ignore[arg-type]
        maturity=maturity,  # type: ignore[arg-type]
    )


def test_select_filters_missing_required_capabilities():
    candidates = [
        profile("has-tools", supports={"tools"}),
        profile("no-tools", supports={"memory"}),
    ]

    choices = select_frameworks(
        candidates, Requirements(required=frozenset({"tools"}))
    )

    assert [choice.profile.name for choice in choices] == ["has-tools"]


def test_select_filters_self_host_and_model_binding():
    candidates = [
        profile("hosted", supports={"tools"}, self_hosted=False),
        profile("vendor", supports={"tools"}, model_binding="vendor"),
        profile("ok", supports={"tools"}),
    ]

    choices = select_frameworks(
        candidates,
        Requirements(
            required=frozenset({"tools"}),
            must_self_host=True,
            must_support_open_models=True,
        ),
    )

    assert [choice.profile.name for choice in choices] == ["ok"]


def test_select_filters_by_min_maturity():
    candidates = [
        profile("new", supports={"tools"}, maturity="experimental"),
        profile("stable", supports={"tools"}, maturity="stable"),
    ]

    choices = select_frameworks(
        candidates, Requirements(min_maturity="stable")
    )

    assert [choice.profile.name for choice in choices] == ["stable"]


def test_select_ranks_preferred_capabilities():
    candidates = [
        profile("one", supports={"tools", "tracing"}),
        profile("two", supports={"tools", "tracing", "evaluation"}),
    ]

    choices = select_frameworks(
        candidates,
        Requirements(preferred=frozenset({"tracing", "evaluation"})),
    )

    assert [choice.profile.name for choice in choices] == ["two", "one"]
    assert choices[0].matched == frozenset({"tracing", "evaluation"})


def test_select_is_deterministic_and_limited():
    candidates = [
        profile("b", supports={"tools"}),
        profile("a", supports={"tools"}),
        profile("c", supports={"tools"}),
    ]

    choices = select_frameworks(candidates, Requirements(), limit=2)

    assert [choice.profile.name for choice in choices] == ["a", "b"]


def test_select_rejects_bad_limit():
    with pytest.raises(ValueError):
        select_frameworks([], Requirements(), limit=0)


def test_callable_runner_wraps_string():
    runner = as_agent_runner(lambda task, ctx: f"echo:{task}", name="demo")

    result = runner.run("hello", RunContext(run_id="r"))

    assert result.task == "hello"
    assert result.run_id == "r"
    assert result.final_answer == "echo:hello"
    assert result.stop_reason == "final_answer"
    assert result.steps[0].index == 1


def test_callable_runner_normalizes_trajectory():
    def framework(task: str, ctx: RunContext) -> Trajectory:
        return Trajectory(task="", run_id="", final_answer="ok")

    result = CallableAgentRunner(framework).run(
        "task", RunContext(run_id="outer")
    )

    assert result.task == "task"
    assert result.run_id == "outer"
    assert result.ended_at is not None


def test_callable_runner_generates_run_id_without_context():
    result = as_agent_runner(lambda task, ctx: "ok", name="demo").run("task")

    assert result.run_id.startswith("demo-")


def test_callable_runner_rejects_unknown_return_type():
    runner = as_agent_runner(lambda task, ctx: 42, name="bad")

    with pytest.raises(TypeError, match="expected Trajectory or str"):
        runner.run("task", RunContext(run_id="r"))


def test_conformance_passes_for_well_behaved_runner():
    def framework(task: str, ctx: RunContext) -> Trajectory:
        return Trajectory(
            task=task,
            run_id=ctx.run_id,
            steps=[Step(index=1, thought=task)],
            final_answer="ok",
        )

    report = check_runner(
        as_agent_runner(framework),
        [ConformanceCase("task a"), ConformanceCase("task b")],
    )

    assert report.passed is True
    assert report.checks == ["case 1", "case 2"]
    assert report.failures == []


def test_conformance_reports_contract_violations():
    def framework(task: str, ctx: RunContext) -> Trajectory:
        return Trajectory(
            task=task,
            run_id="wrong",
            steps=[Step(index=2, thought="x")],
            final_answer="",
            stop_reason="max_steps",
        )

    report = check_runner(
        as_agent_runner(framework), [ConformanceCase("task")]
    )

    assert report.passed is False
    joined = "\n".join(report.failures)
    assert "run_id check failed" in joined
    assert "step_index check failed" in joined
    assert "stop_reason check failed" in joined
    assert "final_answer check failed" in joined


def test_conformance_reports_exception():
    def framework(task: str, ctx: RunContext) -> Trajectory:
        raise RuntimeError("boom")

    report = check_runner(
        as_agent_runner(framework), [ConformanceCase("task")]
    )

    assert report.passed is False
    assert "RuntimeError: boom" in report.failures[0]
