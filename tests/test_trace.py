import json

import pytest

import atlas
from atlas.agent.loop import Agent
from atlas.llm.mock import MockLLM
from atlas.multi_agent.orchestrator import Orchestrator
from atlas.tools.registry import ToolRegistry
from atlas.trace import (
    CompositeTracer,
    InMemoryTracer,
    JSONLTracer,
    TraceEvent,
    TraceFormatError,
    compare_traces,
    diagnose_trace,
    load_events,
    redact_text,
    redact_value,
    replay_trajectory,
    summarize_trace,
)
from atlas.types import (
    Budget,
    LLMResponse,
    RunContext,
    ToolCall,
    Trajectory,
    Usage,
    utcnow,
)

from examples.ch04_single_tool import CalculatorTool


def make_agent(script, tracer=None):
    return Agent(
        MockLLM(script),
        ToolRegistry([CalculatorTool()]),
        tracer=tracer,
    )


def calculator_script(expression="1+1", answer="2"):
    return [
        LLMResponse(
            tool_calls=[
                ToolCall(id="c1", name="calculator", arguments={"expression": expression})
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content=answer),
    ]


def test_jsonl_trace_round_trip(tmp_path):
    path = tmp_path / "trace.jsonl"
    tracer = JSONLTracer(path)
    agent = make_agent(calculator_script(), tracer=tracer)

    trajectory = agent.run("算一下", RunContext(run_id="run-1"))
    events = load_events(path)

    assert trajectory.final_answer == "2"
    assert [event.type for event in events] == [
        "run_start",
        "step",
        "tool_call",
        "tool_result",
        "step",
        "run_end",
    ]
    assert events[0].run_id == "run-1"
    assert events[2].parent_id == events[1].event_id

    replayed = replay_trajectory(events)
    assert replayed.run_id == "run-1"
    assert replayed.final_answer == "2"
    assert len(replayed.steps) == 2
    assert replayed.steps[0].tool_calls[0].name == "calculator"


def test_trace_summary_counts_tool_errors_and_signals(tmp_path):
    tracer = JSONLTracer(tmp_path / "trace.jsonl")
    agent = make_agent(calculator_script("1/0", "除零"), tracer=tracer)
    agent.run("算一下", RunContext(run_id="run-err"))

    summary = summarize_trace(load_events(tmp_path / "trace.jsonl"))

    assert summary.steps == 2
    assert summary.tool_calls == 1
    assert summary.tool_errors == 1
    assert summary.error_types == {"exception": 1}
    assert "tool_error" in summary.signals
    assert summary.first_error_event_id is not None


def test_diagnose_recovered_tool_error():
    tracer = InMemoryTracer()
    make_agent(calculator_script("1/0", "除零"), tracer=tracer).run(
        "算一下", RunContext(run_id="r1")
    )

    diagnosis = diagnose_trace(tracer.events)

    assert diagnosis.category == "recovered_tool_error"
    assert diagnosis.recovered is True


def test_diagnose_budget_stop():
    tracer = InMemoryTracer()
    agent = make_agent(calculator_script(), tracer=tracer)
    agent.run(
        "算一下",
        RunContext(run_id="r2", budget=Budget(max_steps=1)),
    )

    summary = summarize_trace(tracer.events)
    diagnosis = diagnose_trace(tracer.events)

    assert summary.stop_reason == "max_steps"
    assert "stop:max_steps" in summary.signals
    assert diagnosis.category == "budget_stop"


def test_duplicate_calls_are_detected():
    tracer = InMemoryTracer()
    script = [
        LLMResponse(
            tool_calls=[ToolCall("c1", "calculator", {"expression": "1+1"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            tool_calls=[ToolCall("c2", "calculator", {"expression": "1+1"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="2"),
    ]
    make_agent(script, tracer=tracer).run("算一下", RunContext(run_id="r3"))

    summary = summarize_trace(tracer.events)

    assert summary.duplicate_tool_calls == 1
    assert "duplicate_tool_call" in summary.signals
    assert diagnose_trace(tracer.events).category == "loop_suspected"


def test_compare_traces_finds_first_tool_call_divergence():
    baseline_tracer = InMemoryTracer()
    candidate_tracer = InMemoryTracer()
    make_agent(calculator_script("1+1", "2"), tracer=baseline_tracer).run(
        "算一下", RunContext(run_id="base")
    )
    make_agent(calculator_script("1+2", "3"), tracer=candidate_tracer).run(
        "算一下", RunContext(run_id="cand")
    )

    diff = compare_traces(baseline_tracer.events, candidate_tracer.events)

    assert diff.diverged is True
    assert diff.index == 0
    assert diff.reason == "tool_call"


def test_compare_identical_traces_has_no_divergence():
    left = InMemoryTracer()
    right = InMemoryTracer()
    make_agent(calculator_script(), tracer=left).run("q", RunContext(run_id="a"))
    make_agent(calculator_script(), tracer=right).run("q", RunContext(run_id="b"))

    diff = compare_traces(left.events, right.events)

    assert diff.diverged is False
    assert diff.reason == "none"


def test_redaction_and_truncation():
    redacted = redact_text("api_key=sk-abcdefgh12345678")
    assert "sk-abcdefgh" not in redacted
    assert "<redacted>" in redacted

    value = redact_value({"authorization": "Bearer abc", "note": "ok"})
    assert value == {"authorization": "<redacted>", "note": "ok"}

    truncated = redact_text("x" * 100, max_chars=10)
    assert "truncated 90 chars" in truncated


def test_content_can_be_hashed_instead_of_recorded(tmp_path):
    path = tmp_path / "hashed.jsonl"
    tracer = JSONLTracer(path, include_content=False)
    make_agent(calculator_script(), tracer=tracer).run(
        "算一下", RunContext(run_id="hash")
    )

    run_end = [event for event in load_events(path) if event.type == "run_end"][0]
    replayed = replay_trajectory(load_events(path))

    assert "content" not in run_end.payload
    assert len(run_end.payload["content_sha256"]) == 64
    assert replayed.final_answer is None


def test_sampling_can_disable_writes(tmp_path):
    path = tmp_path / "sampled.jsonl"
    tracer = JSONLTracer(path, sample_rate=0.0)
    make_agent(calculator_script(), tracer=tracer).run(
        "算一下", RunContext(run_id="sample")
    )

    assert not path.exists()

    with pytest.raises(ValueError):
        JSONLTracer(path, sample_rate=1.5)


def test_load_events_rejects_bad_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(TraceFormatError, match="line 1"):
        load_events(path)


def test_replay_requires_run_start():
    with pytest.raises(TraceFormatError):
        replay_trajectory([])


def test_tracer_failure_does_not_break_agent():
    class BoomTracer:
        def on_run_start(self, task, ctx):
            raise RuntimeError("start")

        def on_step(self, step, ctx):
            raise RuntimeError("step")

        def on_run_end(self, trajectory, ctx):
            raise RuntimeError("end")

    trajectory = make_agent(calculator_script(), tracer=BoomTracer()).run(
        "算一下", RunContext(run_id="boom")
    )

    assert trajectory.stop_reason == "final_answer"
    assert trajectory.final_answer == "2"


def test_composite_tracer_isolates_failures():
    class BoomTracer:
        def on_run_start(self, task, ctx):
            raise RuntimeError("boom")

        def on_step(self, step, ctx):
            pass

        def on_run_end(self, trajectory, ctx):
            pass

    memory = InMemoryTracer()
    tracer = CompositeTracer([memory, BoomTracer()])
    make_agent(calculator_script(), tracer=tracer).run(
        "算一下", RunContext(run_id="comp")
    )

    assert len(memory.events) == 6
    assert len(tracer.errors) == 1


def test_orchestrator_emits_run_boundaries():
    class FixedRunner:
        def run(self, task, ctx=None):
            return Trajectory(
                task=task,
                run_id=ctx.run_id,
                final_answer="ok",
                stop_reason="final_answer",
                usage=Usage(prompt_tokens=3, completion_tokens=1),
                ended_at=utcnow(),
            )

    tracer = InMemoryTracer()
    orchestrator = Orchestrator({"solo": FixedRunner()}, tracer=tracer)
    orchestrator.run("任务", RunContext(run_id="orch"))

    assert [event.type for event in tracer.events] == ["run_start", "run_end"]
    assert tracer.events[-1].payload["stop_reason"] == "final_answer"


def test_trace_event_serialization():
    event = TraceEvent(run_id="r", type="note", payload={"message": "hi"})
    restored = TraceEvent.from_dict(json.loads(json.dumps(event.to_dict())))

    assert restored.run_id == event.run_id
    assert restored.type == "note"
    assert restored.payload == {"message": "hi"}


def test_public_exports_and_version():
    assert atlas.__version__ == "1.4.0"
    for name in (
        "Tracer",
        "TraceEvent",
        "JSONLTracer",
        "InMemoryTracer",
        "load_events",
        "replay_trajectory",
        "summarize_trace",
        "compare_traces",
        "diagnose_trace",
    ):
        assert hasattr(atlas, name)
