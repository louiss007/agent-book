import ast
import operator
from typing import Any

from atlas.agent.loop import Agent, AgentConfig
from atlas.llm.mock import MockLLM
from atlas.tools.registry import ToolRegistry
from atlas.types import (
    Budget,
    LLMResponse,
    RunContext,
    ToolCall,
    ToolOutput,
    ToolSpec,
    Usage,
)

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_eval(expr: str) -> float:
    """只允许数字、括号和四则运算；生产环境请使用真正的沙箱。"""

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        raise ValueError(f"unsupported expression: {ast.dump(node)}")

    return _eval(ast.parse(expr, mode="eval"))


class CalculatorTool:
    spec = ToolSpec(
        name="calculator",
        description=(
            "计算只包含数字、括号和 + - * / 的算术表达式。"
            "需要精确计算时使用；不要用它做文本处理。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的表达式，例如 (17*23)+9",
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
    )

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        expression = arguments.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("expression 必须是非空字符串")

        value = safe_eval(expression)
        if isinstance(value, float) and value.is_integer():
            return ToolOutput(content=str(int(value)))
        return ToolOutput(content=str(value))


def main() -> None:
    llm = MockLLM(
        [
            LLMResponse(
                content="先用计算器算一下。",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="calculator",
                        arguments={"expression": "(17*23)+9"},
                    )
                ],
                finish_reason="tool_calls",
                usage=Usage(prompt_tokens=120, completion_tokens=16),
            ),
            LLMResponse(
                content="计算结果是 400。",
                usage=Usage(prompt_tokens=180, completion_tokens=8),
            ),
        ]
    )

    agent = Agent(
        llm,
        ToolRegistry([CalculatorTool()]),
        config=AgentConfig(system_prompt="你是一个严谨的研究助手。"),
    )

    trajectory = agent.run(
        "请计算 (17*23)+9，并告诉我结果。",
        RunContext(run_id="demo-ch04", budget=Budget(max_steps=5)),
    )

    for step in trajectory.steps:
        print(f"[step {step.index}] {step.thought}")
        for call, result in zip(step.tool_calls, step.tool_results):
            print(f"  {call.name}({call.arguments}) -> {result.content}")

    print(f"stop_reason={trajectory.stop_reason}")
    print(f"tokens={trajectory.usage.total_tokens}")
    print(f"answer={trajectory.final_answer}")


if __name__ == "__main__":
    main()
