"""第 9 章示例：上下文预算、折叠、摘要与按需展开。"""

from atlas import (
    Agent,
    BudgetedContextBuilder,
    ExtractiveSummarizer,
    LLMResponse,
    MockLLM,
    RunContext,
    ToolCall,
    ToolOutput,
    ToolRegistry,
    ToolSpec,
)


class LogTool:
    spec = ToolSpec(
        name="read_log",
        description="按服务名读取最近的错误日志。",
        parameters={
            "type": "object",
            "properties": {
                "service": {"type": "string", "minLength": 2},
            },
            "required": ["service"],
            "additionalProperties": False,
        },
    )

    def run(self, arguments):
        service = str(arguments["service"])
        lines = [
            f"{service} 第 {index} 分钟：上游超时，等待 5 秒后重试。"
            f"重试成功，但连接池占用率升到 {60 + index * 4}%。"
            for index in range(1, 4)
        ]
        return ToolOutput(content="\n".join(lines))


def pairing_ok(messages) -> bool:
    pending: set[str] = set()
    for message in messages:
        if message.role == "assistant":
            pending.update(call.id for call in message.tool_calls)
        elif message.role == "tool":
            if message.tool_call_id not in pending:
                return False
            pending.remove(message.tool_call_id)
    return not pending


def main() -> None:
    builder = BudgetedContextBuilder(
        system_prompt="你是日志分析助手。基于观察给出结论，不确定时说明信息缺口。",
        max_tokens=320,
        reserve_tokens=20,
        keep_recent=1,
        max_tool_chars=120,
        preview_chars=40,
        summarizer=ExtractiveSummarizer(max_lines=3),
    )
    llm = MockLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(id="c1", name="read_log", arguments={"service": "gateway"})
                ]
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(id="c2", name="read_log", arguments={"service": "orders"})
                ]
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(id="c3", name="read_log", arguments={"service": "search"})
                ]
            ),
            LLMResponse(
                content="三份日志都显示重试有效，但 gateway 的延迟最高；建议先检查下游连接池。"
            ),
        ]
    )
    agent = Agent(
        llm,
        ToolRegistry([LogTool(), builder.expand_tool]),
        context_builder=builder,
    )

    trajectory = agent.run("比较三份错误日志，给出排查建议", RunContext(run_id="ch09"))

    print(
        f"预算：max_tokens={builder.budget.max_tokens} "
        f"reserve={builder.budget.reserve_tokens} "
        f"usable={builder.budget.usable_tokens}"
    )
    print("\n轨迹：")
    for step in trajectory.steps:
        if step.tool_calls:
            service = step.tool_calls[0].arguments.get("service")
            print(f"  step {step.index}: read_log({service!r})")
        else:
            print(f"  step {step.index}: final_answer")

    report = builder.last_report
    print("\n压缩报告：")
    for key, value in report.to_dict().items():
        print(f"  {key}={value}")

    last_context = llm.calls[-1]
    folded = sum("已折叠" in (message.content or "") for message in last_context)
    summarized = any(
        "较早对话摘要" in (message.content or "") for message in last_context
    )
    print("\n最终上下文：")
    print(f"  消息数={len(last_context)} 折叠标记={folded} 摘要={summarized}")
    print(f"  工具调用配对={pairing_ok(last_context)}")

    item = builder.disclosure.store.items()[0]
    expanded = builder.expand_tool.run({"item_id": item.item_id})
    print("\n按需展开：")
    print(f"  item={item.item_id} 原文={item.chars} 字")
    print(f"  {expanded.content.splitlines()[0]}")

    print("\n最终答案：")
    print(f"  {trajectory.final_answer}")


if __name__ == "__main__":
    main()
