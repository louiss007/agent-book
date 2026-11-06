from __future__ import annotations

import pytest

from atlas.llm.mock import MockLLM
from atlas.multi_agent import (
    LLMSupervisor,
    Orchestrator,
    RoleSpec,
    ScriptedSupervisor,
    SharedBoard,
    build_role_agent,
)
from atlas.tools.registry import ToolRegistry
from atlas.types import (
    Budget,
    LLMResponse,
    RunContext,
    Step,
    ToolOutput,
    ToolSpec,
    Trajectory,
    Usage,
)


class FixedRunner:
    def __init__(
        self,
        answer: str | None,
        *,
        stop_reason: str = "final_answer",
        usage: Usage | None = None,
    ) -> None:
        self.answer = answer
        self.stop_reason = stop_reason
        self.usage = usage or Usage()
        self.tasks: list[str] = []
        self.contexts: list[RunContext | None] = []

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        self.tasks.append(task)
        self.contexts.append(ctx)
        return Trajectory(
            task=task,
            run_id=ctx.run_id if ctx else "child",
            steps=[Step(index=1, thought=self.answer, usage=self.usage)],
            final_answer=self.answer,
            stop_reason=self.stop_reason,  # type: ignore[arg-type]
            usage=self.usage,
        )


class NamedTool:
    def __init__(self, name: str) -> None:
        self.spec = ToolSpec(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
        )

    def run(self, arguments):
        return ToolOutput(content=self.spec.name)


def test_board_versions_and_isolates_runs():
    board = SharedBoard()
    first = board.write("artifact/a", "v1", author="a", run_id="r1")
    second = board.write("artifact/a", "v2", author="a", run_id="r1")
    other = board.write("artifact/a", "other", author="a", run_id="r2")

    assert (first.version, second.version, other.version) == (1, 2, 1)
    assert board.read("artifact/a", run_id="r1").value == "v2"
    assert len(board.history("artifact/a", run_id="r1")) == 2
    assert "v2" in board.render(run_id="r1")
    assert "other" not in board.render(run_id="r1")


def test_tool_registry_subset_preserves_order_and_rejects_unknown():
    tools = ToolRegistry([NamedTool("search"), NamedTool("write")])

    subset = tools.subset(["write"])

    assert [spec.name for spec in subset.specs()] == ["write"]
    with pytest.raises(KeyError):
        tools.subset(["missing"])


def test_build_role_agent_scopes_tools_and_prompt():
    llm = MockLLM([LLMResponse(content="ok")])
    tools = ToolRegistry([NamedTool("search"), NamedTool("write")])
    role = RoleSpec("writer", "你是撰稿人", tools=("write",))

    agent = build_role_agent(llm, tools, role)
    result = agent.run("task", RunContext(run_id="r"))

    assert result.final_answer == "ok"
    assert [spec.name for spec in agent.tools.specs()] == ["write"]
    assert agent.config.system_prompt == "你是撰稿人"
    assert llm.calls[0][0].content == "你是撰稿人"


def test_role_with_empty_tools_has_no_tool_access():
    agent = build_role_agent(
        MockLLM(), ToolRegistry([NamedTool("search")]), RoleSpec("reader", "只读", tools=())
    )

    assert agent.tools.specs() == []


def test_pipeline_runs_in_order_and_hands_off_artifacts():
    researcher = FixedRunner(
        "证据 A", usage=Usage(prompt_tokens=10, completion_tokens=5)
    )
    writer = FixedRunner(
        "报告 B", usage=Usage(prompt_tokens=20, completion_tokens=5)
    )
    orchestrator = Orchestrator({"researcher": researcher, "writer": writer})
    ctx = RunContext(
        run_id="r",
        budget=Budget(max_steps=20, max_tokens=1000, max_cost_usd=10.0),
    )

    result = orchestrator.run("任务", ctx)

    assert result.stop_reason == "final_answer"
    assert result.final_answer == "报告 B"
    assert "证据 A" in writer.tasks[0]
    assert "researcher" in writer.tasks[0]
    assert result.usage.total_tokens == 40
    assert [step.thought.split("]")[0] + "]" for step in result.steps] == [
        "[researcher]",
        "[writer]",
    ]
    entry = orchestrator.board.read("artifact/writer", run_id="r")
    assert entry is not None and entry.author == "writer"
    assert entry.value == "报告 B"


def test_pipeline_continues_after_failure_and_records_error():
    bad = FixedRunner(None, stop_reason="error")
    good = FixedRunner("OK")
    orchestrator = Orchestrator({"bad": bad, "good": good})

    result = orchestrator.run("任务", RunContext(run_id="r"))

    assert result.stop_reason == "final_answer"
    assert result.final_answer == "OK"
    error = orchestrator.board.read("error/bad", run_id="r")
    assert error is not None and "stop_reason=error" in error.value


def test_pipeline_stops_on_failure_when_not_continuing():
    bad = FixedRunner(None, stop_reason="timeout")
    good = FixedRunner("OK")
    orchestrator = Orchestrator(
        {"bad": bad, "good": good}, continue_on_error=False
    )

    result = orchestrator.run("任务", RunContext(run_id="r"))

    assert result.stop_reason == "timeout"
    assert result.final_answer is None
    assert good.tasks == []


def test_global_budget_stops_before_next_role():
    first = FixedRunner("A", usage=Usage(prompt_tokens=100))
    second = FixedRunner("B")
    orchestrator = Orchestrator({"first": first, "second": second})
    ctx = RunContext(
        run_id="r",
        budget=Budget(
            max_steps=10,
            max_tokens=50,
            max_cost_usd=10.0,
            max_seconds=60.0,
            max_tool_calls=10,
        ),
    )

    result = orchestrator.run("任务", ctx)

    assert result.stop_reason == "max_tokens"
    assert result.final_answer == "A"
    assert second.tasks == []


def test_supervisor_follows_decisions_and_hands_off_board():
    first = FixedRunner("A")
    second = FixedRunner("B")
    supervisor = ScriptedSupervisor(["first", "second"])
    orchestrator = Orchestrator(
        {"first": first, "second": second},
        strategy="supervisor",
        supervisor=supervisor,
    )

    result = orchestrator.run("任务", RunContext(run_id="r"))

    assert result.stop_reason == "final_answer"
    assert result.final_answer == "B"
    assert supervisor.decisions == ["first", "second"]
    assert "A" in second.tasks[0]
    assert orchestrator.board.read("artifact/first", run_id="r").value == "A"


def test_llm_supervisor_parses_decision_and_falls_back():
    llm = MockLLM(
        [
            LLMResponse(content='{"next": "b"}'),
            LLMResponse(content='{"next": "done"}'),
            LLMResponse(content="不是 JSON"),
        ]
    )
    supervisor = LLMSupervisor(llm, ["a", "b"])

    assert supervisor.choose("task", SharedBoard(), set()) == "b"
    assert supervisor.choose("task", SharedBoard(), {"b"}) is None
    assert supervisor.choose("task", SharedBoard(), {"b"}) == "a"


def test_debate_runs_rounds_and_judge_synthesizes():
    first = FixedRunner("A1")
    second = FixedRunner("B1")
    judge = FixedRunner("VERDICT")
    orchestrator = Orchestrator(
        {"a": first, "b": second},
        strategy="debate",
        judge=judge,
        max_rounds=1,
    )

    result = orchestrator.run("任务", RunContext(run_id="r"))

    assert result.stop_reason == "final_answer"
    assert result.final_answer == "VERDICT"
    assert "A1" in judge.tasks[0]
    assert "B1" in judge.tasks[0]
    assert orchestrator.board.read("verdict", run_id="r").value == "VERDICT"


def test_chat_stops_on_final_marker_and_strips_it():
    first = FixedRunner("继续讨论")
    second = FixedRunner("FINAL: 统一结论")
    orchestrator = Orchestrator(
        {"a": first, "b": second}, strategy="chat", max_rounds=3
    )

    result = orchestrator.run("任务", RunContext(run_id="r"))

    assert result.stop_reason == "final_answer"
    assert result.final_answer == "统一结论"
    assert len(first.tasks) == 1
    assert len(second.tasks) == 1


def test_child_contexts_are_namespaced_and_share_remaining_budget():
    first = FixedRunner("A", usage=Usage(prompt_tokens=30))
    second = FixedRunner("B")
    orchestrator = Orchestrator({"first": first, "second": second})
    ctx = RunContext(
        run_id="root",
        budget=Budget(
            max_steps=10,
            max_tokens=100,
            max_cost_usd=1.0,
            max_seconds=60.0,
            max_tool_calls=10,
        ),
        metadata={"tenant": "t"},
    )

    orchestrator.run("任务", ctx)

    assert first.contexts[0].run_id == "root:first"
    assert first.contexts[0].metadata["parent_run_id"] == "root"
    assert first.contexts[0].metadata["role"] == "first"
    assert second.contexts[0].budget.max_tokens == 70
    assert second.contexts[0].metadata["tenant"] == "t"


def test_orchestrator_can_nest_as_a_role():
    inner = Orchestrator({"x": FixedRunner("X")})
    outer = Orchestrator({"team": inner, "writer": FixedRunner("W")})

    result = outer.run("任务", RunContext(run_id="r"))

    assert result.final_answer == "W"
    assert result.steps[0].thought.startswith("[team] [x]")
    assert "X" in result.steps[0].thought


def test_synthesizer_can_combine_artifacts():
    orchestrator = Orchestrator(
        {"a": FixedRunner("A"), "b": FixedRunner("B")},
        synthesizer=lambda task, artifacts: " | ".join(
            value for _, value in artifacts
        ),
    )

    result = orchestrator.run("任务")

    assert result.final_answer == "A | B"
