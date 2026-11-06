from __future__ import annotations

import ast
import operator
from typing import Any

from atlas import (
    Agent,
    AgentConfig,
    Budget,
    ContainsEvaluator,
    EvalRunner,
    EvalTask,
    LLMResponse,
    MockLLM,
    ToolCall,
    ToolOutput,
    ToolRegistry,
    ToolSpec,
    Trajectory,
    TrajectoryEvaluator,
    Usage,
    WeightedEvaluator,
    collect_metrics,
    compare_reports,
)

TASKS = [
    EvalTask(id="add-mul", question="计算 (12+8)*3。", reference="60"),
    EvalTask(id="multiply", question="计算 7*8。", reference="56"),
    EvalTask(id="div-zero", question="计算 9/0。", reference="无法计算"),
    EvalTask(id="add", question="计算 2+2。", reference="4"),
]

EXPRESSIONS = {
    "计算 (12+8)*3。": "(12 + 8) * 3",
    "计算 7*8。": "7 * 8",
    "计算 9/0。": "9 / 0",
    "计算 2+2。": "2 + 2",
}

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ValueError("unsupported expression")


class CalculatorTool:
    spec = ToolSpec(
        "calculator",
        "计算只含数字、括号与四则运算符的表达式。",
        {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    )

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        try:
            tree = ast.parse(str(arguments["expression"]), mode="eval")
            return ToolOutput(str(_evaluate(tree)))
        except Exception as exc:
            return ToolOutput(
                f"计算失败：{exc}",
                is_error=True,
                metadata={"error_type": "exception"},
            )


def script_for(expression: str, answer: str) -> list[LLMResponse]:
    return [
        LLMResponse(
            tool_calls=[ToolCall("c1", "calculator", {"expression": expression})],
            usage=Usage(prompt_tokens=520, completion_tokens=24, cost_usd=0.00052),
        ),
        LLMResponse(
            content=answer,
            usage=Usage(prompt_tokens=180, completion_tokens=12, cost_usd=0.00018),
        ),
    ]


class ScriptedCalculatorRunner:
    """每个任务构造一个脚本模型，模拟同一 Agent 的不同输出。"""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    def run(self, task: str, ctx=None) -> Trajectory:
        agent = Agent(
            MockLLM(script_for(EXPRESSIONS[task], self.answers[task])),
            ToolRegistry([CalculatorTool()]),
            config=AgentConfig(system_prompt="先计算，再给出简洁答案。"),
        )
        return agent.run(task, ctx)


def build_evaluator() -> WeightedEvaluator:
    return WeightedEvaluator(
        [
            (ContainsEvaluator(), 0.7),
            (TrajectoryEvaluator(max_steps=4, max_tool_calls=2), 0.3),
        ],
        pass_threshold=0.8,
    )


def main() -> None:
    baseline_answers = {
        "计算 (12+8)*3。": "60",
        "计算 7*8。": "56",
        "计算 9/0。": "无法计算：除数不能为 0。",
        "计算 2+2。": "4",
    }
    candidate_answers = dict(baseline_answers)
    candidate_answers["计算 7*8。"] = "57"  # 模拟一次模型升级引入的回归

    budget = Budget(max_steps=4, max_tool_calls=2)
    baseline = EvalRunner(
        ScriptedCalculatorRunner(baseline_answers),
        build_evaluator(),
        name="calculator-baseline",
        budget=budget,
    ).run(TASKS)
    candidate = EvalRunner(
        ScriptedCalculatorRunner(candidate_answers),
        build_evaluator(),
        name="calculator-candidate",
        budget=budget,
    ).run(TASKS)

    for report in (baseline, candidate):
        summary = report.summary
        print(
            f"{report.name}: pass_rate={summary.pass_rate:.2f} "
            f"mean_score={summary.mean_score:.3f} "
            f"tokens={summary.total_tokens} cost=${summary.total_cost_usd:.5f}"
        )

    diff = compare_reports(baseline, candidate)
    print(f"regressions={len(diff.regressions)} pass_rate_delta={diff.pass_rate_delta:+.2f}")
    for item in diff.regressions:
        print(f"- {item.task_id}: {item.baseline_score:.2f} -> {item.candidate_score:.2f}")
    print("gate:", "pass" if diff.ok() else "block")

    failed = [result for result in candidate.results if not result.passed]
    if failed:
        metrics = collect_metrics(failed[0].trajectory)
        print(
            f"failed={failed[0].task_id} steps={metrics.steps} "
            f"tool_calls={metrics.tool_calls} errors={metrics.tool_errors}"
        )


if __name__ == "__main__":
    main()
