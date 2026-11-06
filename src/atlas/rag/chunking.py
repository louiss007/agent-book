from __future__ import annotations

from typing import Any

from atlas.rag.base import Document

_BOUNDARIES = ("\n\n", "。", "！", "？", "\n", "；")


def chunk_text(
    text: str,
    *,
    max_chars: int = 400,
    overlap_chars: int = 80,
) -> list[str]:
    """按字符窗口切块，优先在段落或句子边界收尾，并保留尾部重叠。"""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be in [0, max_chars)")

    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]

    chunks: list[str] = []
    start = 0
    length = len(clean)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            window = clean[start:end]
            floor = int(max_chars * 0.6)
            cut = -1
            for marker in _BOUNDARIES:
                position = window.rfind(marker)
                if position >= floor:
                    cut = max(cut, position + len(marker))
            if cut > 0:
                end = start + cut

        piece = clean[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def make_chunks(
    doc_id: str,
    content: str,
    source: str,
    *,
    metadata: dict[str, Any] | None = None,
    max_chars: int = 400,
    overlap_chars: int = 80,
    title: str | None = None,
) -> list[Document]:
    """把一篇文档切成可检索的块；块 ID 为 `doc_id#index`，便于引用。"""
    parts = chunk_text(content, max_chars=max_chars, overlap_chars=overlap_chars)
    chunks: list[Document] = []
    for index, part in enumerate(parts):
        chunk_metadata = dict(metadata or {})
        chunk_metadata.update(
            {
                "parent_doc_id": doc_id,
                "chunk_index": index,
                "chunk_count": len(parts),
            }
        )
        if title:
            chunk_metadata.setdefault("title", title)
        chunks.append(
            Document(
                doc_id=f"{doc_id}#{index}",
                content=part,
                source=source,
                metadata=chunk_metadata,
            )
        )
    return chunks
