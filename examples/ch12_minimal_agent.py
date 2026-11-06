"""第 12 章：不用框架，用约 300 行实现一个完整的最小 Agent。

只依赖标准库。运行：

    python3 examples/ch12_minimal_agent.py

它包含五个部分：数据类型、模型协议、工具协议、停止策略与 Agent Loop。
长期记忆、检索与上下文压缩不在最小内核里，它们由 Atlas 后续层补齐。
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, Sequence
from uuid import uuid4

Role = Literal["system", "user", "assistant", "tool"]
StopReason = Literal[
    "final_answer",
    "max_steps",
    "max_tokens",
    "max_tool_calls",
    "timeout",
    "error",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- 1. 数据类型


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    dangerous: bool = False


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Role
    content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class Step:
    index: int
    thought: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class Trajectory:
    task: str
    run_id: str
    steps: list[Step] = field(default_factory=list)
    final_answer: str | None = None
    stop_reason: StopReason = "final_answer"
    usage: Usage = field(default_factory=Usage)
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None


@dataclass
class Budget:
    max_steps: int = 10
    max_tokens: int = 20_000
    max_tool_calls: int = 8
    max_seconds: float = 60.0


@dataclass
class RunContext:
    run_id: str
    budget: Budget = field(default_factory=Budget)


# ---------------------------------------------------------------- 2. 模型协议


class LLM(Protocol):
    model: str

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse: ...


class ScriptedLLM:
    """按脚本返回响应，模拟模型的两步决策：先调用工具，再给出答案。"""

    model = "scripted"

    def __init__(self, script: Sequence[LLMResponse]) -> None:
        self._script = list(script)
        self.calls: list[list[Message]] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if not self._script:
            raise RuntimeError("script exhausted")
        return self._script.pop(0)


# ---------------------------------------------------------------- 3. 工具协议


class Tool(Protocol):
    spec: ToolSpec

    def run(self, arguments: dict[str, Any]) -> str: ...


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval(node: ast.AST) -> float:
    """只接受数字与四则运算，避免把用户输入交给 eval。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _BINARY[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    raise ValueError("只支持数字与 + - * / % ** 运算")


class Calculator:
    spec = ToolSpec(
        name="calculator",
        description="计算数学表达式；参数 expression 是只含数字与运算符的字符串。",
        parameters={
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    )

    def run(self, arguments: dict[str, Any]) -> str:
        expression = str(arguments.get("expression", "")).strip()
        tree = ast.parse(expression, mode="eval")
        return str(_eval(tree.body))


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool] = ()) -> None:
        self._tools = {tool.spec.name: tool for tool in tools}

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def run(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, f"未知工具：{call.name}", is_error=True)

        required = tool.spec.parameters.get("required", [])
        missing = [name for name in required if name not in call.arguments]
        if missing:
            return ToolResult(
                call.id, f"缺少参数：{', '.join(missing)}", is_error=True
            )

        try:
            return ToolResult(call.id, tool.run(call.arguments))
        except Exception as exc:  # 工具失败必须变成观察，而不是冒泡
            return ToolResult(call.id, f"工具执行失败：{exc}", is_error=True)


# ---------------------------------------------------------------- 4. 停止策略


def check_budget(
    budget: Budget,
    *,
    step: int,
    tool_calls: int,
    usage: Usage,
    started_at: datetime,
) -> StopReason | None:
    """顺序固定，保证同一输入得到可复现的停止原因。"""
    if (utcnow() - started_at).total_seconds() > budget.max_seconds:
        return "timeout"
    if step >= budget.max_steps:
        return "max_steps"
    if usage.total_tokens >= budget.max_tokens:
        return "max_tokens"
    if tool_calls >= budget.max_tool_calls:
        return "max_tool_calls"
    return None


# ---------------------------------------------------------------- 5. Agent Loop


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        *,
        system_prompt: str,
        budget: Budget | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.budget = budget or Budget()

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        ctx = ctx or RunContext(run_id=f"min-{uuid4().hex[:12]}")
        trajectory = Trajectory(task=task, run_id=ctx.run_id)
        history: list[Message] = [Message("user", task)]
        usage = Usage()
        tool_calls = 0
        step_index = 0

        try:
            while True:
                reason = check_budget(
                    ctx.budget,
                    step=step_index,
                    tool_calls=tool_calls,
                    usage=usage,
                    started_at=trajectory.started_at,
                )
                if reason is not None:
                    trajectory.stop_reason = reason
                    break

                response = self.llm.complete(
                    [Message("system", self.system_prompt), *history],
                    self.tools.specs(),
                )
                usage = usage + response.usage
                step_index += 1

                if not response.tool_calls:
                    trajectory.steps.append(
                        Step(step_index, response.content, usage=response.usage)
                    )
                    trajectory.final_answer = response.content
                    trajectory.stop_reason = "final_answer"
                    break

                results = [self.tools.run(call) for call in response.tool_calls]
                trajectory.steps.append(
                    Step(
                        step_index,
                        response.content,
                        response.tool_calls,
                        results,
                        response.usage,
                    )
                )

                history.append(
                    Message(
                        "assistant",
                        response.content,
                        tool_calls=response.tool_calls,
                    )
                )
                for call, result in zip(response.tool_calls, results):
                    history.append(
                        Message(
                            "tool",
                            result.content,
                            name=call.name,
                            tool_call_id=call.id,
                        )
                    )
                tool_calls += len(response.tool_calls)

        except Exception as exc:
            trajectory.steps.append(Step(step_index + 1, f"错误：{exc}"))
            trajectory.stop_reason = "error"
        finally:
            trajectory.usage = usage
            trajectory.ended_at = utcnow()

        return trajectory


# ---------------------------------------------------------------- 演示


def build_script() -> list[LLMResponse]:
    return [
        LLMResponse(
            tool_calls=[
                ToolCall(
                    "call-1",
                    "calculator",
                    {"expression": "(128 + 64) * 3"},
                )
            ],
            usage=Usage(prompt_tokens=120, completion_tokens=18),
        ),
        LLMResponse(
            content="(128 + 64) * 3 = 576。",
            usage=Usage(prompt_tokens=210, completion_tokens=16),
        ),
    ]


def main() -> None:
    agent = Agent(
        ScriptedLLM(build_script()),
        ToolRegistry([Calculator()]),
        system_prompt="需要计算时先调用 calculator，再回答。",
        budget=Budget(max_steps=4, max_tokens=5_000, max_tool_calls=2),
    )
    trajectory = agent.run("计算 (128 + 64) * 3，并给出结果。")

    print(f"任务：{trajectory.task}")
    print(f"停止原因：{trajectory.stop_reason}")
    print(f"最终答案：{trajectory.final_answer}")
    for step in trajectory.steps:
        names = ", ".join(call.name for call in step.tool_calls)
        print(f"  步骤 {step.index}：工具={names or '无'}｜用量={step.usage.total_tokens}")
    print(f"总用量：{trajectory.usage.total_tokens} tokens")


if __name__ == "__main__":
    main()
