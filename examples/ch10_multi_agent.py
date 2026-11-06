"""第 10 章示例：流水线与编排者—执行者两种协作模式。"""

from atlas import (
    LLMResponse,
    MockLLM,
    Orchestrator,
    RoleSpec,
    RunContext,
    ScriptedSupervisor,
    SharedBoard,
    ToolCall,
    ToolOutput,
    ToolRegistry,
    ToolSpec,
    Usage,
    build_role_agent,
)


class SearchNotesTool:
    spec = ToolSpec(
        name="search_notes",
        description="检索内部研究笔记，返回带来源 ID 的证据摘要。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )

    def run(self, arguments):
        query = str(arguments["query"])
        return ToolOutput(
            content=(
                f"检索词：{query}\n"
                "原始记录：研究团队内部评测，样本 40 个任务。\n"
                "note#12：多 Agent 的 token 消耗约为单 Agent 的 15 倍；"
                "在广度优先的检索任务上收益明显。\n"
                "note#13：多数编码任务步骤紧耦合，多 Agent 收益有限。"
            )
        )


def researcher_llm() -> MockLLM:
    return MockLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="search_notes",
                        arguments={"query": "multi-agent research"},
                    )
                ],
                usage=Usage(prompt_tokens=180, completion_tokens=20),
            ),
            LLMResponse(
                content=(
                    "证据清单：\n"
                    "- note#12：多 Agent 成本约为单 Agent 的 15 倍，"
                    "广度检索任务收益明显。\n"
                    "- note#13：紧耦合的编码任务收益有限。"
                ),
                usage=Usage(prompt_tokens=260, completion_tokens=90),
            ),
        ]
    )


def analyst_llm() -> MockLLM:
    return MockLLM(
        [
            LLMResponse(
                content=(
                    "分析：\n"
                    "- 多 Agent 的价值来自并行检索与上下文隔离，不是角色数量。\n"
                    "- 成本约为 15 倍，只有在任务可并行拆分时才值得。\n"
                    "- 编码类任务步骤紧耦合，应优先单 Agent 加计划。"
                ),
                usage=Usage(prompt_tokens=220, completion_tokens=80),
            )
        ]
    )


def writer_llm() -> MockLLM:
    return MockLLM(
        [
            LLMResponse(
                content=(
                    "# 多智能体使用建议\n\n"
                    "## 结论\n"
                    "只有在任务可并行拆分、角色上下文需要隔离时，"
                    "多 Agent 才值得约 15 倍的成本。\n\n"
                    "## 依据\n"
                    "- 广度优先的研究任务收益明显（note#12）。\n"
                    "- 紧耦合的编码任务收益有限（note#13）。\n\n"
                    "## 建议\n"
                    "默认先做单 Agent 基线；出现明确的并行或隔离需求后再拆分角色。"
                ),
                usage=Usage(prompt_tokens=240, completion_tokens=120),
            )
        ]
    )


def build_pipeline():
    tools = ToolRegistry([SearchNotesTool()])
    r_llm, a_llm, w_llm = researcher_llm(), analyst_llm(), writer_llm()
    roles = {
        "researcher": build_role_agent(
            r_llm,
            tools,
            RoleSpec(
                "researcher",
                "你是检索员。只负责找证据；每条结论必须带来源 ID。",
                tools=("search_notes",),
            ),
        ),
        "analyst": build_role_agent(
            a_llm,
            tools,
            RoleSpec(
                "analyst",
                "你是分析员。只负责核对证据、比较方案、指出矛盾；不要写最终报告。",
                tools=(),
            ),
        ),
        "writer": build_role_agent(
            w_llm,
            tools,
            RoleSpec(
                "writer",
                "你是撰稿人。把上游产物整理成给决策者的报告；不要新增未出现的事实。",
                tools=(),
            ),
        ),
    }
    return roles, (r_llm, a_llm, w_llm)


def main() -> None:
    roles, (r_llm, a_llm, w_llm) = build_pipeline()
    board = SharedBoard()
    orchestrator = Orchestrator(roles, strategy="pipeline", board=board)
    trajectory = orchestrator.run(
        "比较多智能体与单智能体，给出是否采用的建议",
        RunContext(run_id="ch10"),
    )

    print("角色顺序：" + " -> ".join(roles))
    print("\n角色工具：")
    for name, agent in roles.items():
        print(f"  {name}: {[spec.name for spec in agent.tools.specs()]}")

    print("\n父轨迹：")
    for step in trajectory.steps:
        tools_used = ", ".join(call.name for call in step.tool_calls) or "-"
        first_line = (step.thought or "").splitlines()[0]
        print(f"  step {step.index}: {first_line} (tools: {tools_used})")

    print("\n共享黑板：")
    for entry in board.snapshot(run_id="ch10"):
        print(
            f"  {entry.key} v{entry.version} by {entry.author}: "
            f"{entry.value.splitlines()[0][:48]}"
        )

    writer_input = "\n".join(
        message.content or "" for message in w_llm.calls[-1]
    )
    print("\n上下文隔离：")
    print(f"  researcher 模型调用={len(r_llm.calls)} 最后输入消息={len(r_llm.calls[-1])}")
    print(f"  analyst    模型调用={len(a_llm.calls)} 最后输入消息={len(a_llm.calls[-1])}")
    print(f"  writer     模型调用={len(w_llm.calls)} 最后输入消息={len(w_llm.calls[-1])}")
    print(f"  writer 输入包含上游证据={'note#12' in writer_input}")
    print(f"  writer 输入包含原始记录={'原始记录' in writer_input}")

    print("\n最终答案：")
    print(trajectory.final_answer)
    print(
        f"\n总令牌：{trajectory.usage.total_tokens} "
        f"停止原因：{trajectory.stop_reason}"
    )

    print("\n编排者—执行者：")
    sup_tools = ToolRegistry([])
    sup_roles = {
        "researcher": build_role_agent(
            MockLLM(
                [
                    LLMResponse(
                        content="证据：note#12 显示约 15 倍成本。",
                        usage=Usage(prompt_tokens=60, completion_tokens=20),
                    )
                ]
            ),
            sup_tools,
            RoleSpec("researcher", "你是检索员。只给证据。", tools=()),
        ),
        "analyst": build_role_agent(
            MockLLM(
                [
                    LLMResponse(
                        content="分析：只在广度并行任务上建议采用多 Agent。",
                        usage=Usage(prompt_tokens=80, completion_tokens=30),
                    )
                ]
            ),
            sup_tools,
            RoleSpec("analyst", "你是分析员。基于证据给结论。", tools=()),
        ),
    }
    supervisor = ScriptedSupervisor(["researcher", "analyst"])
    sup_orchestrator = Orchestrator(
        sup_roles,
        strategy="supervisor",
        supervisor=supervisor,
        board=SharedBoard(),
    )
    sup_trajectory = sup_orchestrator.run(
        "是否应该采用多智能体", RunContext(run_id="ch10-sup")
    )
    print("  决策顺序：" + " -> ".join(supervisor.decisions))
    print("  最终答案：" + (sup_trajectory.final_answer or ""))
    print(f"  停止原因：{sup_trajectory.stop_reason}")


if __name__ == "__main__":
    main()
