"""离线演示数据：内置知识库、预置记忆与脚本化模型。

这些数据只用于示例与测试，不代表真实模型能力。
"""

from __future__ import annotations

from atlas.llm.mock import MockLLM
from atlas.memory.base import MemoryItem, MemoryStore
from atlas.rag.hybrid import KnowledgeBase
from atlas.types import LLMResponse, Message, ToolCall, ToolSpec, Usage

DEMO_TASK = "Atlas 如何把记忆、检索与上下文预算组合起来？"

_MEMORY_DOC = (
    "Atlas 的短期记忆是当前运行的消息历史；长期记忆由 MemoryStore 保存，"
    "MemoryWriter 在任务结束后经过闸门写入。MemoryContextBuilder 在每一轮开始时"
    "按相关性检索记忆，并把结果放进系统消息，明确标注为事实参考而不是指令。"
)

_RAG_DOC = (
    "Atlas 的检索层由 KnowledgeBase 组合 BM25 与向量检索，并用 RRF 合并两路名次。"
    "KnowledgeSearchTool 把检索封装成模型可调用的工具；EvidenceLedger 记录本轮证据，"
    "并校验最终答案中的引用是否来自本轮检索结果。"
)

_CONTEXT_DOC = (
    "BudgetedContextBuilder 在记忆、历史与证据进入模型之前按令牌预算压缩："
    "先折叠可恢复的长内容，再做抽取式摘要，最后才截断。"
    "它包装 MemoryContextBuilder，不改变 ContextBuilder.build 的签名。"
)

PREFERENCE = "用户偏好：回答使用简体中文，并尽量给出来源。"


def demo_knowledge() -> KnowledgeBase:
    knowledge = KnowledgeBase()
    knowledge.add_document(
        "atlas-memory",
        _MEMORY_DOC,
        "atlas-notes/memory.md",
        title="记忆与上下文",
    )
    knowledge.add_document(
        "atlas-rag",
        _RAG_DOC,
        "atlas-notes/rag.md",
        title="检索与证据",
    )
    knowledge.add_document(
        "atlas-context",
        _CONTEXT_DOC,
        "atlas-notes/context.md",
        title="上下文预算",
    )
    return knowledge


def seed_memory(store: MemoryStore) -> str:
    return store.add(
        MemoryItem(
            id="mem-demo-preference",
            content=PREFERENCE,
            kind="preference",
            importance=0.9,
            metadata={"key": "preference:language"},
        )
    )


def scripted_llm() -> MockLLM:
    def responder(
        messages: list[Message], tools: list[ToolSpec] | None
    ) -> LLMResponse:
        if not any(message.role == "tool" for message in messages):
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call-demo-1",
                        name="search_knowledge",
                        arguments={"query": "记忆 检索 上下文预算"},
                    )
                ],
                finish_reason="tool_calls",
                usage=Usage(prompt_tokens=320, completion_tokens=24),
            )
        return LLMResponse(
            content=(
                "Atlas 把三者放在不同层：记忆由 MemoryBuilder 检索后注入系统消息"
                "[atlas-memory#0]；知识检索被封装成工具，结果进入证据台账"
                "[atlas-rag#0]；上下文预算在两者之后统一压缩"
                "[atlas-context#0]。"
            ),
            finish_reason="stop",
            usage=Usage(prompt_tokens=560, completion_tokens=64),
        )

    return MockLLM(responder=responder)
