from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from atlas.rag.base import Document
from atlas.rag.filters import matches
from atlas.rag.text import tokenize


class BM25Retriever:
    """词法检索基线：精确词命中强，但对同义改写不敏感。"""

    def __init__(
        self,
        documents: Sequence[Document],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self._documents = list(documents)
        self._tokens = [tokenize(document.content) for document in self._documents]
        self._frequencies = [Counter(tokens) for tokens in self._tokens]
        self._document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            self._document_frequency.update(set(tokens))
        self._average_length = (
            sum(len(tokens) for tokens in self._tokens) / len(self._tokens)
            if self._tokens
            else 0.0
        )

    def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[Document]:
        query_terms = Counter(tokenize(query))
        if not query_terms or not self._documents or k <= 0:
            return []

        total = len(self._documents)
        scored: list[tuple[float, Document]] = []
        for document, frequencies, tokens in zip(
            self._documents, self._frequencies, self._tokens
        ):
            if not matches(document, filters):
                continue
            length = len(tokens)
            score = 0.0
            for term, query_frequency in query_terms.items():
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                document_frequency = self._document_frequency[term]
                idf = math.log(
                    1.0 + (total - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = term_frequency + self.k1 * (
                    1.0 - self.b + self.b * length / self._average_length
                )
                score += (
                    idf
                    * term_frequency
                    * (self.k1 + 1.0)
                    / denominator
                    * query_frequency
                )
            if score > 0:
                scored.append((score, document))

        scored.sort(key=lambda pair: (-pair[0], pair[1].doc_id))
        return [replace(document, score=score) for score, document in scored[:k]]
