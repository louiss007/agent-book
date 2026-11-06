from __future__ import annotations

from typing import Any

from atlas.rag.base import Document


def matches(document: Document, filters: dict[str, Any] | None) -> bool:
    """按顶层字段与 metadata 做等值过滤；None 值表示不过滤。"""
    for key, expected in (filters or {}).items():
        if expected is None:
            continue
        if key == "source":
            if document.source != expected:
                return False
        elif key == "doc_id":
            if document.doc_id != expected:
                return False
        elif document.metadata.get(key) != expected:
            return False
    return True
