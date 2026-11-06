from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from atlas.rag.base import Document, Retriever
from atlas.rag.bm25 import BM25Retriever
from atlas.rag.chunking import make_chunks
from atlas.rag.vector import Embedder, VectorRetriever


class HybridRetriever:
    """用倒数排名融合（RRF）合并多个检索器的结果。"""

    def __init__(
        self,
        retrievers: Sequence[Retriever],
        *,
        weights: Sequence[float] | None = None,
        rrf_k: int = 60,
        candidate_multiplier: int = 3,
    ) -> None:
        if rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        self.retrievers = list(retrievers)
        self.weights = list(weights) if weights is not None else [1.0] * len(
            self.retrievers
        )
        if len(self.weights) != len(self.retrievers):
            raise ValueError("weights must match retrievers")
        self.rrf_k = rrf_k
        self.candidate_multiplier = max(1, candidate_multiplier)

    def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[Document]:
        if k <= 0 or not self.retrievers:
            return []

        scores: dict[str, float] = {}
        documents: dict[str, Document] = {}
        sources: dict[str, list[str]] = {}
        pool_size = max(k, k * self.candidate_multiplier)

        for retriever, weight in zip(self.retrievers, self.weights):
            results = retriever.retrieve(query, k=pool_size, filters=filters)
            for rank, document in enumerate(results, start=1):
                scores[document.doc_id] = scores.get(document.doc_id, 0.0) + (
                    weight / (self.rrf_k + rank)
                )
                documents.setdefault(document.doc_id, document)
                sources.setdefault(document.doc_id, [])
                if retriever.__class__.__name__ not in sources[document.doc_id]:
                    sources[document.doc_id].append(retriever.__class__.__name__)

        ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
        merged: list[Document] = []
        for doc_id, score in ranked[:k]:
            metadata = dict(documents[doc_id].metadata)
            metadata["retrievers"] = sources[doc_id]
            merged.append(replace(documents[doc_id], score=score, metadata=metadata))
        return merged


class KnowledgeBase:
    """累积文档、自动分块，并用 BM25 + 向量做混合检索。"""

    def __init__(
        self,
        *,
        max_chars: int = 400,
        overlap_chars: int = 80,
        embedder: Embedder | None = None,
    ) -> None:
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self.embedder = embedder
        self._chunks: list[Document] = []
        self._document_ids: set[str] = set()
        self._retriever: HybridRetriever | None = None

    @property
    def chunks(self) -> list[Document]:
        return list(self._chunks)

    def add_document(
        self,
        doc_id: str,
        content: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> list[str]:
        if not doc_id:
            raise ValueError("doc_id must not be empty")
        if doc_id in self._document_ids:
            raise ValueError(f"duplicate document id: {doc_id}")
        chunks = make_chunks(
            doc_id,
            content,
            source,
            metadata=metadata,
            max_chars=self.max_chars,
            overlap_chars=self.overlap_chars,
            title=title,
        )
        self._chunks.extend(chunks)
        self._document_ids.add(doc_id)
        self._retriever = None
        return [chunk.doc_id for chunk in chunks]

    def clear(self) -> None:
        self._chunks.clear()
        self._document_ids.clear()
        self._retriever = None

    def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[Document]:
        if self._retriever is None:
            self._retriever = HybridRetriever(
                [
                    BM25Retriever(self._chunks),
                    VectorRetriever(self._chunks, embedder=self.embedder),
                ]
            )
        return self._retriever.retrieve(query, k=k, filters=filters)
