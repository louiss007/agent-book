from __future__ import annotations

from dataclasses import replace

from atlas.agent.loop import Agent, AgentConfig
from atlas.llm.mock import MockLLM
from atlas.rag import (
    AgenticRAG,
    BM25Retriever,
    Document,
    EvidenceLedger,
    HybridRetriever,
    KnowledgeBase,
    KnowledgeSearchTool,
    VectorRetriever,
    chunk_text,
    verify_citations,
)
from atlas.tools import ToolRegistry
from atlas.types import LLMResponse, RunContext, ToolCall


def doc(doc_id: str, content: str, **metadata) -> Document:
    return Document(
        doc_id=doc_id,
        content=content,
        source=f"https://example.test/{doc_id}",
        metadata=metadata,
    )


class StaticRetriever:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents

    def retrieve(self, query: str, k: int = 5, filters=None) -> list[Document]:
        return [replace(item, score=1.0) for item in self.documents[:k]]


def test_chunk_text_respects_size_and_overlap():
    chunks = chunk_text("a" * 1000, max_chars=400, overlap_chars=80)

    assert [len(chunk) for chunk in chunks] == [400, 400, 360]
    assert chunks[0][-80:] == chunks[1][:80]


def test_chunk_prefers_sentence_boundary():
    text = "第一段内容。" * 80
    chunks = chunk_text(text, max_chars=120, overlap_chars=20)

    assert all(len(chunk) <= 120 for chunk in chunks)
    assert all(chunk.endswith("。") for chunk in chunks[:-1])


def test_bm25_ranks_matching_document_first():
    documents = [
        doc("react", "ReAct 让模型交替进行推理与行动，并根据观察调整下一步。"),
        doc("memory", "记忆系统负责短期、工作与长期记忆的写入和检索。"),
        doc("plan", "Plan-and-Execute 先制定计划，再逐步执行并在失败时重规划。"),
    ]
    retriever = BM25Retriever(documents)

    results = retriever.retrieve("ReAct 推理 行动", k=2)

    assert results[0].doc_id == "react"
    assert results[0].score > 0


def test_bm25_filters_by_metadata():
    retriever = BM25Retriever(
        [
            doc("a", "向量检索使用嵌入与余弦相似度。", tenant="team-a"),
            doc("b", "向量检索使用嵌入与余弦相似度。", tenant="team-b"),
        ]
    )

    results = retriever.retrieve("向量检索", filters={"tenant": "team-b"})

    assert [item.doc_id for item in results] == ["b"]


def test_vector_retriever_returns_similar_chunks():
    retriever = VectorRetriever(
        [
            doc("vector", "向量检索把文本映射为嵌入，再计算余弦相似度。"),
            doc("memory", "长期记忆需要写入闸门与遗忘策略。"),
        ]
    )

    results = retriever.retrieve("嵌入 余弦相似度", k=1)

    assert results[0].doc_id == "vector"


def test_hybrid_uses_reciprocal_rank_fusion():
    a = doc("a", "A")
    b = doc("b", "B")
    c = doc("c", "C")
    hybrid = HybridRetriever(
        [StaticRetriever([a, b, c]), StaticRetriever([b, c, a])],
        rrf_k=60,
    )

    results = hybrid.retrieve("query", k=3)

    assert [item.doc_id for item in results] == ["b", "a", "c"]
    assert results[0].score > results[1].score


def test_knowledge_base_chunks_and_retrieves():
    kb = KnowledgeBase(max_chars=80, overlap_chars=10)
    chunk_ids = kb.add_document(
        "hybrid",
        "混合检索同时使用关键词与向量召回。" * 8,
        "https://example.test/hybrid",
        title="混合检索",
    )

    assert len(chunk_ids) > 1
    results = kb.retrieve("混合检索 向量召回", k=2)

    assert results
    assert results[0].metadata["parent_doc_id"] == "hybrid"
    assert results[0].metadata["title"] == "混合检索"


def test_search_tool_renders_citations_and_records_ledger():
    kb = KnowledgeBase()
    kb.add_document(
        "react",
        "ReAct 让模型交替进行推理与行动，并根据观察调整下一步。",
        "https://example.test/react",
        title="ReAct",
    )
    ledger = EvidenceLedger()
    tool = KnowledgeSearchTool(kb, ledger=ledger)

    output = tool.run({"query": "ReAct 推理 行动", "k": 2})

    assert not output.is_error
    assert "[react#0]" in output.content
    assert output.metadata["citations"] == ["react#0"]
    assert ledger.retrieval_count == 1
    assert ledger.lookup("react#0") is not None


def test_search_tool_rejects_duplicate_query():
    kb = KnowledgeBase()
    kb.add_document("react", "ReAct 交替进行推理与行动。", "https://example.test/react")
    tool = KnowledgeSearchTool(kb)

    first = tool.run({"query": "ReAct 推理"})
    second = tool.run({"query": "  react   推理 "})

    assert not first.is_error
    assert second.is_error
    assert second.metadata["error_type"] == "duplicate_query"


def test_search_tool_enforces_query_budget():
    kb = KnowledgeBase()
    kb.add_document("react", "ReAct 交替进行推理与行动。", "https://example.test/react")
    tool = KnowledgeSearchTool(kb, max_queries=1)

    assert not tool.run({"query": "ReAct 推理"}).is_error
    blocked = tool.run({"query": "ReAct 行动"})

    assert blocked.is_error
    assert blocked.metadata["error_type"] == "retrieval_budget"


def test_ledger_reset_restarts_tool_budget():
    kb = KnowledgeBase()
    kb.add_document("react", "ReAct 交替进行推理与行动。", "https://example.test/react")
    ledger = EvidenceLedger()
    tool = KnowledgeSearchTool(kb, ledger=ledger, max_queries=1)

    assert not tool.run({"query": "ReAct 推理"}).is_error
    ledger.reset()
    assert not tool.run({"query": "ReAct 推理"}).is_error
    assert ledger.retrieval_count == 1


def test_ledger_dedupes_and_verifies_citations():
    ledger = EvidenceLedger()
    evidence = doc("react#0", "ReAct 交替进行推理与行动。")
    ledger.record("ReAct", [evidence])
    ledger.record("ReAct 推理", [evidence])

    report = verify_citations("ReAct 适合短任务 [react#0]。", ledger)

    assert report.ok
    assert report.cited == ["react#0"]
    assert report.retrieved == 1
    assert report.queries == 2


def test_verify_flags_unknown_citation():
    ledger = EvidenceLedger()
    ledger.record("ReAct", [doc("react#0", "ReAct 交替进行推理与行动。")])

    report = ledger.verify("结论 [react#0]，补充 [invented#3]。")

    assert not report.ok
    assert report.unknown == ["invented#3"]


def test_agentic_rag_reports_missing_citations():
    llm = MockLLM([LLMResponse(content="ReAct 适合短任务。")])
    agent = Agent(llm, ToolRegistry([]), config=AgentConfig(system_prompt="测试"))
    rag = AgenticRAG(agent)

    trajectory = rag.run("ReAct 适合什么任务？", RunContext(run_id="r1"))

    assert trajectory.final_answer == "ReAct 适合短任务。"
    assert rag.last_report is not None
    assert not rag.last_report.ok
    assert "引用检查未通过" in trajectory.steps[-1].thought


def test_agent_calls_search_tool_twice_and_answers_with_citations():
    kb = KnowledgeBase()
    kb.add_document(
        "react",
        "ReAct 让模型交替进行推理与行动，适合三到五步、路径不确定的任务。",
        "https://example.test/react",
        title="ReAct",
    )
    kb.add_document(
        "plan",
        "Plan-and-Execute 先制定计划再执行，失败时可以重规划，适合长任务。",
        "https://example.test/plan",
        title="Plan-and-Execute",
    )
    ledger = EvidenceLedger()
    tool = KnowledgeSearchTool(kb, ledger=ledger)
    llm = MockLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="search_knowledge",
                        arguments={"query": "ReAct 推理 行动", "k": 2},
                    )
                ]
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="search_knowledge",
                        arguments={"query": "Plan-and-Execute 计划 重规划", "k": 2},
                    )
                ]
            ),
            LLMResponse(
                content=(
                    "短任务优先 ReAct [react#0]；长任务优先 Plan-and-Execute [plan#0]。"
                )
            ),
        ]
    )
    agent = Agent(
        llm,
        ToolRegistry([tool]),
        config=AgentConfig(system_prompt="先检索，再回答，并标注引用。"),
    )
    rag = AgenticRAG(agent, ledger=ledger)

    trajectory = rag.run("比较 ReAct 与 Plan-and-Execute", RunContext(run_id="r2"))

    assert trajectory.stop_reason == "final_answer"
    assert len(trajectory.steps) == 3
    assert sum(len(step.tool_calls) for step in trajectory.steps) == 2
    assert rag.last_report is not None
    assert rag.last_report.ok
    assert set(rag.last_report.cited) == {"react#0", "plan#0"}
