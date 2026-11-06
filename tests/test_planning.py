from __future__ import annotations

import pytest

from atlas.llm.mock import MockLLM
from atlas.planning import (
    LLMPlanner,
    LLMReflector,
    Plan,
    PlanExecuteAgent,
    PlanParseError,
    PlanStep,
    Reflection,
    StaticPlanner,
)
from atlas.types import (
    Budget,
    LLMResponse,
    RunContext,
    Trajectory,
    Usage,
)


def trajectory(
    answer: str | None,
    *,
    stop_reason: str = "final_answer",
    usage: Usage | None = None,
) -> Trajectory:
    return Trajectory(
        task="",
        run_id="child",
        final_answer=answer,
        stop_reason=stop_reason,
        usage=usage or Usage(),
    )


class ScriptedRunner:
    def __init__(self, outcomes: list[Trajectory]) -> None:
        self.outcomes = list(outcomes)
        self.tasks: list[str] = []

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        self.tasks.append(task)
        return self.outcomes.pop(0)


class ScriptedReflector:
    def __init__(self, reflections: list[Reflection]) -> None:
        self.reflections = list(reflections)

    def reflect(self, task, step, answer, history):
        return self.reflections.pop(0)


def test_llm_planner_parses_fenced_json_and_caps_steps():
    content = (
        "```json\n"
        '{"goal": "g", "steps": ['
        '{"id": "a", "description": "one"}, '
        '{"description": "two"}, '
        '{"description": "three"}]}\n'
        "```"
    )
    planner = LLMPlanner(MockLLM([LLMResponse(content=content)]), max_steps=2)
    plan = planner.plan("task", [])

    assert plan.goal == "g"
    assert [step.id for step in plan.steps] == ["a", "2"]
    assert [step.description for step in plan.steps] == ["one", "two"]
    assert all(step.status == "pending" for step in plan.steps)


def test_llm_planner_rejects_invalid_json():
    planner = LLMPlanner(MockLLM([LLMResponse(content="不是 JSON")]))
    with pytest.raises(PlanParseError):
        planner.plan("task", [])


def test_llm_reflector_parses_verdict():
    reflector = LLMReflector(
        MockLLM(
            [
                LLMResponse(
                    content=(
                        '{"ok": false, "critique": "缺少来源", '
                        '"suggestion": "补充引用"}'
                    )
                )
            ]
        )
    )
    reflection = reflector.reflect("task", PlanStep("1", "写结论"), "答案", [])

    assert reflection.ok is False
    assert reflection.critique == "缺少来源"
    assert reflection.suggestion == "补充引用"


def test_llm_reflector_fails_open_on_bad_output():
    reflector = LLMReflector(MockLLM([LLMResponse(content="我觉得还行")]))
    reflection = reflector.reflect("task", PlanStep("1", "写结论"), "答案", [])

    assert reflection.ok is True
    assert "无法解析" in reflection.critique


def test_plan_execute_runs_steps_and_synthesizes():
    planner = StaticPlanner(
        [Plan(goal="g", steps=[PlanStep("1", "a"), PlanStep("2", "b")])]
    )
    runner = ScriptedRunner([trajectory("A"), trajectory("B")])
    agent = PlanExecuteAgent(planner, runner)

    result = agent.run("task")

    assert result.stop_reason == "final_answer"
    assert "A" in result.final_answer
    assert "B" in result.final_answer
    assert [step.status for step in agent.last_plan.steps] == ["done", "done"]
    assert len(runner.tasks) == 2
    assert "当前步骤（1）" in runner.tasks[0]
    assert "当前步骤（2）" in runner.tasks[1]


def test_reflection_triggers_retry_then_succeeds():
    planner = StaticPlanner([Plan(goal="g", steps=[PlanStep("1", "a")])])
    runner = ScriptedRunner([trajectory("short"), trajectory("long answer")])
    reflector = ScriptedReflector(
        [
            Reflection(ok=False, critique="太短", suggestion="展开"),
            Reflection(ok=True),
        ]
    )
    agent = PlanExecuteAgent(
        planner, runner, reflector=reflector, max_step_retries=1
    )

    result = agent.run("task")

    assert result.stop_reason == "final_answer"
    assert "long answer" in result.final_answer
    assert len(runner.tasks) == 2
    assert "上一次尝试的问题" in runner.tasks[1]
    assert agent.last_plan.steps[0].status == "done"


def test_failed_step_triggers_replan():
    planner = StaticPlanner(
        [
            Plan(goal="g", steps=[PlanStep("1", "a"), PlanStep("2", "b")]),
            Plan(goal="g", steps=[PlanStep("3", "c")]),
        ]
    )
    runner = ScriptedRunner([trajectory(None, stop_reason="error"), trajectory("C")])
    agent = PlanExecuteAgent(planner, runner, max_replans=1)

    result = agent.run("task")

    assert result.stop_reason == "final_answer"
    assert "C" in result.final_answer
    assert planner.calls == 2
    assert [step.status for step in agent.last_plan.steps] == ["failed", "done"]


def test_budget_is_shared_across_steps():
    planner = StaticPlanner(
        [Plan(goal="g", steps=[PlanStep("1", "a"), PlanStep("2", "b")])]
    )
    runner = ScriptedRunner(
        [trajectory("A", usage=Usage(prompt_tokens=100))]
    )
    agent = PlanExecuteAgent(planner, runner)
    ctx = RunContext(
        run_id="run",
        budget=Budget(
            max_steps=10,
            max_tokens=50,
            max_cost_usd=10.0,
            max_seconds=60.0,
            max_tool_calls=10,
        ),
    )

    result = agent.run("task", ctx)

    assert result.stop_reason == "max_tokens"
    assert len(runner.tasks) == 1
    assert agent.last_plan.steps[0].status == "done"
    assert agent.last_plan.steps[1].status == "pending"
