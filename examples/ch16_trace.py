from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from atlas import (
    Agent,
    AgentConfig,
    InMemoryTracer,
    JSONLTracer,
    LLMResponse,
    MockLLM,
    RunContext,
    ToolCall,
    ToolOutput,
    ToolRegistry,
    ToolSpec,
    Usage,
    compare_traces,
    diagnose_trace,
    load_events,
    redact_text,
    replay_trajectory,
    summarize_trace,
)
from atlas.types import Trajectory

POLICIES = {
    "refund": "签收后 7 天内可无理由退款。",
    "shipping": "订单满 99 元包邮。",
}


class PolicyTool:
    spec = ToolSpec(
        "lookup_policy",
        "按主题查询售后政策，可用主题：refund、shipping。",
        {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
    )

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        topic = str(arguments["topic"])
        if topic not in POLICIES:
            return ToolOutput(
                f"未知主题：{topic}",
                is_error=True,
                metadata={"error_type": "unknown_topic"},
            )
        return ToolOutput(POLICIES[topic])


def script(topic: str, answer: str) -> list[LLMResponse]:
    return [
        LLMResponse(
            tool_calls=[ToolCall("c1", "lookup_policy", {"topic": topic})],
            finish_reason="tool_calls",
            usage=Usage(prompt_tokens=120, completion_tokens=18, cost_usd=0.0002),
        ),
        LLMResponse(
            content=answer,
            usage=Usage(prompt_tokens=80, completion_tokens=20, cost_usd=0.0001),
        ),
    ]


def run_agent(topic: str, answer: str, tracer, run_id: str) -> Trajectory:
    agent = Agent(
        MockLLM(script(topic, answer)),
        ToolRegistry([PolicyTool()]),
        config=AgentConfig(system_prompt="先查政策，再回答。"),
        tracer=tracer,
    )
    return agent.run("退款政策是什么？", RunContext(run_id=run_id))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "atlas-trace.jsonl"

        baseline_tracer = JSONLTracer(path)
        candidate_tracer = InMemoryTracer()

        baseline = run_agent(
            "refund", "退款政策：签收后 7 天内可无理由退款。",
            baseline_tracer, "policy-baseline",
        )
        candidate = run_agent(
            "refnd", "退款政策：签收后 7 天内可无理由退款。",
            candidate_tracer, "policy-candidate",
        )

        events = load_events(path)
        baseline_events = [event for event in events if event.run_id == "policy-baseline"]
        candidate_events = candidate_tracer.events

        for name, sample in (
            ("baseline", baseline_events),
            ("candidate", candidate_events),
        ):
            summary = summarize_trace(sample)
            print(
                f"{name}: stop={summary.stop_reason} steps={summary.steps} "
                f"tool_calls={summary.tool_calls} errors={summary.tool_errors} "
                f"signals={summary.signals}"
            )

        diff = compare_traces(baseline_events, candidate_events)
        print(
            f"first divergence: index={diff.index} reason={diff.reason} "
            f"diverged={diff.diverged}"
        )

        diagnosis = diagnose_trace(candidate_events)
        print(f"diagnosis: {diagnosis.category} evidence={diagnosis.evidence}")

        replayed = replay_trajectory(candidate_events)
        first_result = replayed.steps[0].tool_results[0]
        print(
            f"replay: answer={replayed.final_answer!r} "
            f"tool_error={first_result.is_error} "
            f"error_type={first_result.metadata.get('error_type')}"
        )
        print(
            "eval note:",
            "answer matches" if candidate.final_answer == baseline.final_answer
            else "answer differs",
            "| trace still unsafe because the tool call failed",
        )

        print("redacted:", redact_text("api_key=sk-demo123456789"))
        print(f"jsonl events: {len(baseline_events)} (file removed with temp dir)")


if __name__ == "__main__":
    main()
