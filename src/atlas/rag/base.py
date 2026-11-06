from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Document:
    doc_id: str
    content: str
    source: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class Retriever(Protocol):
    def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[Document]:
        ...
