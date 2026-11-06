from datetime import timedelta

import pytest

import atlas
from atlas.eval import (
    ContainsEvaluator,
    EvalResult,
    EvalRunner,
    EvalTask,
    ExactMatchEvaluator,
    LLMJudgeEvaluator,
    TrajectoryEvaluator,
    WeightedEvaluator,
    collect_metrics,
    compare_reports,
    parse_judge_response,
    summarize,
)
from atlas.types import (
    Budget,
    LLMResponse,
    Step,
    ToolCall,
    ToolResult,
    Trajectory,
    Usage,
    utcnow,
)


def make_trajectory(
    *,
    task: str = "q",
    answer: str | None = "ok",
    stop_reason: str = "final_answer",
    steps: list[Step] | None = None,
    usage: Usage | None = None,
    seconds: float = 1.0,
) -> Trajectory:
    started = utcnow()
    return Trajectory(
        task=task,
        run_id="run-1",
        steps=steps or [],
        final_answer=answer,
        stop_reason=stop_reason,
        usage=usage or Usage(),
        started_at=started,
        ended_at=started + timedelta(seconds=seconds),
    )


def test_eval_task_defaults():
    task = EvalTask(id="t1", question="问题")
    assert task.reference is None
    assert task.rubric is None
    assert task.metadata == {}


def test_collect_metrics():
    steps = [
        Step(
            index=1,
            tool_calls=[ToolCall("c1", "calculator", {"expression": "1+1"})],
            tool_results=[ToolResult("c1", "2")],
        ),
        Step(
            index=2,
            tool_calls=[
                ToolCall("c2", "calculator", {"expression": "1+1"}),
                ToolCall("c3", "search", {"query": "x"}),
            ],
            tool_results=[
                ToolResult("c2", "2"),
                ToolResult("c3", "timeout", is_error=True, metadata={"error_type": "timeout"}),
            ],
        ),
    ]
    trajectory = make_trajectory(
        steps=steps,
        usage=Usage(prompt_tokens=100, completion_tokens=20, cost_usd=0.01),
        seconds=2.5,
    )

    metrics = collect_metrics(trajectory)

    assert metrics.steps == 2
    assert metrics.tool_calls == 3
    assert metrics.failed_tool_calls == 1
    assert metrics.duplicate_tool_calls == 1
    assert metrics.max_parallel_calls == 2
    assert metrics.unique_tools == 2
    assert metrics.total_tokens == 120
    assert metrics.duration_seconds == 2.5
    assert metrics.tool_errors == {"timeout": 1}


def test_exact_match_normalizes_case_and_whitespace():
    task = EvalTask(id="t1", question="q", reference="Hello  World")
    evaluator = ExactMatchEvaluator()

    ok = evaluator.score(task, make_trajectory(answer=" hello world "))
    bad = evaluator.score(task, make_trajectory(answer="hello"))

    assert ok.passed is True and ok.score == 1.0
    assert bad.passed is False and bad.score == 0.0


def test_contains_evaluator_partial_score():
    task = EvalTask(
        id="t1",
        question="q",
        metadata={"required_snippets": ["引用", "来源"]},
    )
    evaluator = ContainsEvaluator()

    result = evaluator.score(task, make_trajectory(answer="结论有引用但缺少证据"))

    assert result.passed is False
    assert result.score == 0.5


def test_trajectory_evaluator_checks_process():
    task = EvalTask(id="t1", question="q")
    trajectory = make_trajectory(
        answer="done",
        steps=[
            Step(
                index=1,
                tool_calls=[ToolCall("c1", "search", {})],
                tool_results=[ToolResult("c1", "boom", is_error=True)],
            )
        ],
    )
    evaluator = TrajectoryEvaluator(
        max_steps=1,
        max_tool_calls=1,
        required_tools=["calculator"],
        forbidden_tools=["search"],
        allow_tool_errors=False,
    )

    result = evaluator.score(task, trajectory)

    assert result.passed is False
    assert result.detail["checks"]["max_steps"] is True
    assert result.detail["checks"]["required_tools"] is False
    assert result.detail["checks"]["forbidden_tools"] is False
    assert result.detail["checks"]["no_tool_errors"] is False


def test_weighted_evaluator():
    task = EvalTask(id="t1", question="q", reference="right")
    evaluator = WeightedEvaluator(
        [(ExactMatchEvaluator(), 0.7), (TrajectoryEvaluator(), 0.3)],
        pass_threshold=0.8,
    )

    result = evaluator.score(task, make_trajectory(answer="wrong"))

    assert abs(result.score - 0.3) < 1e-9
    assert result.passed is False
    assert len(result.detail["parts"]) == 2


def test_summarize_pass_at_k_and_pass_pow_k():
    rows = [
        EvalResult("a", make_trajectory(), 1.0, True),
        EvalResult("a", make_trajectory(), 0.0, False),
        EvalResult("b", make_trajectory(), 0.0, False),
        EvalResult("b", make_trajectory(), 1.0, True),
    ]

    summary = summarize(rows, k=2)

    assert summary.task_count == 2
    assert summary.attempt_count == 4
    assert summary.pass_rate == 0.5
    assert summary.pass_at_k == 1.0
    assert summary.pass_pow_k == 0.0
    assert summary.mean_score == 0.5
    assert summary.cost_per_success == 0.0


class FakeRunner:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def run(self, task: str, ctx=None):
        self.calls.append((task, ctx.run_id if ctx else ""))
        return make_trajectory(task=task, answer=self.answers[task])


def test_eval_runner_aggregates_and_records_failures():
    runner = FakeRunner({"q1": "ok", "q2": "bad"})
    evaluator = ExactMatchEvaluator()
    tasks = [
        EvalTask(id="t1", question="q1", reference="ok"),
        EvalTask(id="t2", question="q2", reference="right"),
    ]

    report = EvalRunner(runner, evaluator, name="suite").run(
        tasks, budget=Budget(max_steps=3)
    )

    assert report.summary.task_count == 2
    assert report.summary.pass_rate == 0.5
    assert report.summary.failed_task_ids == ["t2"]
    assert runner.calls[0][1].startswith("suite:t1:")


def test_eval_runner_catches_runner_exception():
    class BoomRunner:
        def run(self, task, ctx=None):
            raise RuntimeError("boom")

    report = EvalRunner(BoomRunner(), ExactMatchEvaluator()).run(
        [EvalTask(id="t1", question="q", reference="ok")]
    )

    result = report.results[0]
    assert result.passed is False
    assert result.trajectory.stop_reason == "error"
    assert "RuntimeError: boom" in result.detail["error"]


def test_compare_reports_detects_regression():
    evaluator = ExactMatchEvaluator()
    tasks = [
        EvalTask(id="t1", question="q1", reference="ok"),
        EvalTask(id="t2", question="q2", reference="right"),
    ]
    baseline = EvalRunner(
        FakeRunner({"q1": "ok", "q2": "right"}), evaluator, name="base"
    ).run(tasks)
    candidate = EvalRunner(
        FakeRunner({"q1": "ok", "q2": "bad"}), evaluator, name="cand"
    ).run(tasks)

    diff = compare_reports(baseline, candidate)

    assert len(diff.regressions) == 1
    assert diff.regressions[0].task_id == "t2"
    assert diff.pass_rate_delta == -0.5
    assert diff.ok() is False


def test_compare_reports_flags_missing_tasks():
    evaluator = ExactMatchEvaluator()
    baseline = EvalRunner(
        FakeRunner({"q1": "ok"}), evaluator, name="base"
    ).run([EvalTask(id="t1", question="q1", reference="ok")])
    candidate = EvalRunner(
        FakeRunner({"q1": "ok"}), evaluator, name="cand"
    ).run([EvalTask(id="t2", question="q1", reference="ok")])

    diff = compare_reports(baseline, candidate)

    assert diff.missing_task_ids == ["t1"]
    assert diff.ok() is False


def test_parse_judge_response_accepts_fenced_json():
    score, reason, criteria = parse_judge_response(
        '```json\n{"score": 0.8, "reason": "有引用", "criteria": []}\n```'
    )
    assert score == 0.8
    assert reason == "有引用"
    assert criteria == []


def test_llm_judge_evaluator_parses_score():
    from atlas.llm import MockLLM

    llm = MockLLM([LLMResponse(content='{"score": 0.9, "reason": "完整"}')])
    evaluator = LLMJudgeEvaluator(llm, threshold=0.8)
    task = EvalTask(id="t1", question="q", rubric="完整性")

    result = evaluator.score(task, make_trajectory(answer="答案"))

    assert result.passed is True
    assert result.score == 0.9
    assert result.detail["reason"] == "完整"


def test_llm_judge_evaluator_fails_closed_on_bad_output():
    from atlas.llm import MockLLM

    evaluator = LLMJudgeEvaluator(MockLLM([LLMResponse(content="not json")]))
    result = evaluator.score(EvalTask(id="t1", question="q"), make_trajectory())

    assert result.passed is False
    assert result.score == 0.0
    assert "judge_error" in result.detail


def test_public_exports_and_version():
    assert atlas.__version__ == "1.4.0"
    for name in ("EvalTask", "EvalResult", "Evaluator", "EvalRunner", "compare_reports"):
        assert hasattr(atlas, name)
