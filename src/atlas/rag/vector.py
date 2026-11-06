from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Protocol

from atlas.rag.base import Document
from atlas.rag.filters import matches
from atlas.rag.text import tokenize


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class HashingEmbedder:
    """离线哈希词袋嵌入，只模拟向量索引的形状，不具备真正的语义能力。"""

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token, frequency in Counter(tokenize(text)).items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "big")
            index = raw % self.dimensions
            sign = 1.0 if (raw >> 8) & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(frequency))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class VectorRetriever:
    """余弦相似度检索；嵌入器可替换为真实模型。"""

    def __init__(
        self,
        documents: Sequence[Document],
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self.embedder = embedder or HashingEmbedder()
        self._documents = list(documents)
        self._vectors = [
            self.embedder.embed(document.content) for document in self._documents
        ]

    def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[Document]:
        if not self._documents or k <= 0:
            return []
        query_vector = self.embedder.embed(query)
        scored: list[tuple[float, Document]] = []
        for document, vector in zip(self._documents, self._vectors):
            if not matches(document, filters):
                continue
            score = sum(left * right for left, right in zip(query_vector, vector))
            if score > 0:
                scored.append((score, document))
        scored.sort(key=lambda pair: (-pair[0], pair[1].doc_id))
        return [replace(document, score=score) for score, document in scored[:k]]
