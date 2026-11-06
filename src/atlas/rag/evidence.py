from __future__ import annotations

import re
from dataclasses import dataclass, field

from atlas.rag.base import Document

_CITATION = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9._:#-]{0,63})\]")


def extract_citations(text: str) -> list[str]:
    """按出现顺序提取 `[doc-id]` 引用，去重但保留首次位置。"""
    seen: set[str] = set()
    citations: list[str] = []
    for match in _CITATION.finditer(text or ""):
        citation = match.group(1)
        if citation not in seen:
            seen.add(citation)
            citations.append(citation)
    return citations


@dataclass
class CitationReport:
    cited: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    retrieved: int = 0
    queries: int = 0

    @property
    def has_citation(self) -> bool:
        return bool(self.cited)

    @property
    def ok(self) -> bool:
        return self.has_citation and not self.unknown


class EvidenceLedger:
    """记录本轮检索到的证据，并检查最终答案里的引用是否都有出处。"""

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}
        self._queries: list[str] = []

    def reset(self) -> None:
        self._documents.clear()
        self._queries.clear()

    def record(self, query: str, documents: list[Document]) -> list[str]:
        self._queries.append(query)
        added: list[str] = []
        for document in documents:
            existing = self._documents.get(document.doc_id)
            if existing is None:
                self._documents[document.doc_id] = document
                added.append(document.doc_id)
            elif document.score > existing.score:
                self._documents[document.doc_id] = document
        return added

    def lookup(self, doc_id: str) -> Document | None:
        return self._documents.get(doc_id)

    @property
    def documents(self) -> list[Document]:
        return list(self._documents.values())

    @property
    def queries(self) -> list[str]:
        return list(self._queries)

    @property
    def retrieval_count(self) -> int:
        return len(self._queries)

    def verify(self, answer: str) -> CitationReport:
        cited = extract_citations(answer)
        unknown = [citation for citation in cited if citation not in self._documents]
        return CitationReport(
            cited=cited,
            unknown=unknown,
            retrieved=len(self._documents),
            queries=len(self._queries),
        )


def verify_citations(answer: str, ledger: EvidenceLedger) -> CitationReport:
    return ledger.verify(answer)
