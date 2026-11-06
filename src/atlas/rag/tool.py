from __future__ import annotations

from typing import Any

from atlas.rag.base import Document, Retriever
from atlas.rag.evidence import EvidenceLedger
from atlas.types import ToolOutput, ToolSpec

_DESCRIPTION = (
    "在知识库中检索资料。回答需要外部事实、数据或来源时必须先调用；"
    "query 用具体名词与限定词，不要重复相同查询；"
    "拿到结果后用 [doc_id] 标注引用。"
)


class KnowledgeSearchTool:
    """把检索器包装成模型可调用的工具，并限制重复查询与检索次数。"""

    def __init__(
        self,
        retriever: Retriever,
        *,
        ledger: EvidenceLedger | None = None,
        name: str = "search_knowledge",
        max_queries: int = 6,
        max_passage_chars: int = 700,
        max_total_chars: int = 3200,
    ) -> None:
        self.retriever = retriever
        self.ledger = ledger
        self.max_queries = max_queries
        self.max_passage_chars = max_passage_chars
        self.max_total_chars = max_total_chars
        self._calls = 0
        self._seen: set[str] = set()
        self.spec = ToolSpec(
            name=name,
            description=_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 2,
                        "description": "检索词或问题，尽量具体",
                    },
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "返回的片段数量，默认 5",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def reset(self) -> None:
        self._calls = 0
        self._seen.clear()

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        query = str(arguments.get("query", "")).strip()
        k = int(arguments.get("k", 5) or 5)
        if len(query) < 2:
            return ToolOutput(
                content="检索词至少需要两个字符。",
                is_error=True,
                metadata={"error_type": "validation"},
            )

        normalized = " ".join(query.lower().split())
        if normalized in self._seen_queries():
            return ToolOutput(
                content=(
                    "这个查询已经执行过。请换一个更具体的关键词，"
                    "或基于已有结果继续推理。"
                ),
                is_error=True,
                metadata={"error_type": "duplicate_query", "query": query},
            )
        if self._call_count() >= self.max_queries:
            return ToolOutput(
                content=(
                    f"本次运行的检索次数已达上限（{self.max_queries}）。"
                    "请基于已有证据作答，并说明信息缺口。"
                ),
                is_error=True,
                metadata={"error_type": "retrieval_budget", "query": query},
            )

        if self.ledger is None:
            self._calls += 1
            self._seen.add(normalized)
        documents = self.retriever.retrieve(query, k=max(1, min(k, 10)))
        if self.ledger is not None:
            self.ledger.record(query, documents)

        if not documents:
            return ToolOutput(
                content=(
                    "没有检索到相关片段。可以换用更宽泛的关键词，"
                    "或指出知识库中没有这项信息。"
                ),
                metadata={"query": query, "results": 0, "citations": []},
            )

        return ToolOutput(
            content=self._render(query, documents),
            metadata={
                "query": query,
                "results": len(documents),
                "citations": [document.doc_id for document in documents],
                "retrieval_calls": self._call_count(),
            },
        )

    def _seen_queries(self) -> set[str]:
        if self.ledger is not None:
            return {
                " ".join(entry.lower().split()) for entry in self.ledger.queries
            }
        return self._seen

    def _call_count(self) -> int:
        if self.ledger is not None:
            return self.ledger.retrieval_count
        return self._calls

    def _render(self, query: str, documents: list[Document]) -> str:
        lines = [f"检索：{query}"]
        used = len(lines[0])
        for document in documents:
            title = str(document.metadata.get("title") or document.source)
            header = f"[{document.doc_id}] {title}｜来源：{document.source}"
            body = document.content.strip()
            if len(body) > self.max_passage_chars:
                body = body[: self.max_passage_chars] + "…"
            block = header + "\n" + body
            if used + len(block) > self.max_total_chars:
                break
            lines.append(block)
            used += len(block)
        return "\n\n".join(lines)
