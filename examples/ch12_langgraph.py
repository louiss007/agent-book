"""第 12 章对照示例：同一个任务用 LangGraph 的状态图重写。

这是可选依赖示例，默认测试不加载它：

    pip install langgraph
    python3 examples/ch12_langgraph.py

为了离线运行，脚本用一个只实现 bind_tools/invoke 的假模型，
不发起任何网络请求。
"""

from __future__ import annotations

import ast
import operator

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_core.tools import tool
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode
except ImportError:
    print("需要可选依赖：pip install langgraph")
    raise SystemExit(0)


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    raise ValueError("只支持数字与 + - * / 运算")


@tool
def calculator(expression: str) -> str:
    """计算只含数字与 + - * / 的表达式。"""
    return str(_eval(ast.parse(expression, mode="eval").body))


class ScriptedModel:
    """模拟一次工具调用；真实项目里替换成任意绑定工具的聊天模型。"""

    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "calculator",
                        "args": {"expression": "(128 + 64) * 3"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="(128 + 64) * 3 = 576。")


model = ScriptedModel().bind_tools([calculator])


def llm_call(state: MessagesState):
    return {
        "messages": [
            model.invoke(
                [SystemMessage(content="需要计算时先调用 calculator。")]
                + state["messages"]
            )
        ]
    }


def should_continue(state: MessagesState) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


builder = StateGraph(MessagesState)
builder.add_node("llm_call", llm_call)
builder.add_node("tools", ToolNode([calculator]))
builder.add_edge(START, "llm_call")
builder.add_conditional_edges("llm_call", should_continue, ["tools", END])
builder.add_edge("tools", "llm_call")
graph = builder.compile(checkpointer=InMemorySaver())

config = {"configurable": {"thread_id": "ch12-langgraph"}}
result = graph.invoke(
    {"messages": [HumanMessage(content="计算 (128 + 64) * 3，并给出结果。")]},
    config,
)

print("消息序列：")
for message in result["messages"]:
    name = getattr(message, "name", None) or type(message).__name__
    print(f"- {name}: {message.content!r}")
