"""第 8 章示例：混合检索、带引用的多跳问答与引用审计。"""

from atlas import (
    Agent,
    AgentConfig,
    AgenticRAG,
    EvidenceLedger,
    KnowledgeBase,
    KnowledgeSearchTool,
    MockLLM,
    RunContext,
    ToolCall,
    ToolRegistry,
    LLMResponse,
)

SYSTEM = "你是研究助手。先检索证据，再回答，并用 [doc_id] 标注引用。"


def build_knowledge_base() -> KnowledgeBase:
    kb = KnowledgeBase(max_chars=240, overlap_chars=40)
    kb.add_document(
        "react",
        "ReAct 让模型交替进行推理与行动，并根据工具观察调整下一步。"
        "它适合 3–5 步、路径不确定的任务；步骤过多时容易打转。",
        "https://example.test/react",
        title="ReAct",
        metadata={"topic": "planning"},
    )
    kb.add_document(
        "plan",
        "Plan-and-Execute 先制定完整计划，再逐步执行。"
        "单步失败时可以重试或重规划，适合步骤较多、依赖关系清晰的长任务。",
        "https://example.test/plan",
        title="Plan-and-Execute",
        metadata={"topic": "planning"},
    )
    kb.add_document(
        "rag",
        "传统 RAG 在每轮回答前固定检索一次。"
        "当问题需要多跳、检索结果不足或查询本身含糊时，一次性检索容易失效。",
        "https://example.test/rag",
        title="传统 RAG 的局限",
        metadata={"topic": "retrieval"},
    )
    kb.add_document(
        "hybrid",
        "混合检索用 BM25 抓精确词，用向量召回处理改写，"
        "再通过倒数排名融合（RRF）合并两路结果，降低单一检索器的偏差。",
        "https://example.test/hybrid",
        title="混合检索",
        metadata={"topic": "retrieval"},
    )
    return kb


def main() -> None:
    kb = build_knowledge_base()

    print("混合检索：ReAct 推理 行动")
    for document in kb.retrieve("ReAct 推理 行动", k=3):
        print(
            f"  {document.doc_id:<10} score={document.score:.4f} "
            f"retrievers={document.metadata.get('retrievers')}"
        )

    ledger = EvidenceLedger()
    search = KnowledgeSearchTool(kb, ledger=ledger)
    llm = MockLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="search_knowledge",
                        arguments={"query": "ReAct 适合什么任务", "k": 2},
                    )
                ]
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="search_knowledge",
                        arguments={"query": "Plan-and-Execute 长任务 重规划", "k": 2},
                    )
                ]
            ),
            LLMResponse(
                content=(
                    "短任务、路径不确定时优先 ReAct [react#0]；"
                    "步骤较多、依赖清晰时优先 Plan-and-Execute [plan#0]。"
                )
            ),
        ]
    )
    agent = Agent(
        llm,
        ToolRegistry([search]),
        config=AgentConfig(system_prompt=SYSTEM),
    )
    app = AgenticRAG(agent, ledger=ledger)

    trajectory = app.run(
        "比较 ReAct 与 Plan-and-Execute 的适用场景",
        RunContext(run_id="ch08"),
    )

    print("\n轨迹：")
    for step in trajectory.steps:
        if step.tool_calls:
            query = step.tool_calls[0].arguments.get("query")
            print(f"  step {step.index}: search_knowledge({query!r})")
        else:
            print(f"  step {step.index}: final_answer")

    print("\n最终答案：")
    print(" ", trajectory.final_answer)

    report = app.last_report
    print("\n引用审计：")
    print(f"  cited={report.cited}")
    print(f"  unknown={report.unknown}")
    print(f"  retrieved={report.retrieved} queries={report.queries}")
    print(f"  ok={report.ok}")

    duplicate = search.run({"query": "react 适合什么任务"})
    print("\n重复查询保护：")
    print(f"  is_error={duplicate.is_error} type={duplicate.metadata.get('error_type')}")

    fake_report = ledger.verify("结论 [react#0]，补充 [made-up#0]。")
    print("\n伪造引用的检查：")
    print(f"  cited={fake_report.cited} unknown={fake_report.unknown} ok={fake_report.ok}")


if __name__ == "__main__":
    main()
