from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from atlas.types import ToolOutput, ToolSpec

_DESCRIPTION = (
    "展开此前被折叠的上下文片段。消息里出现 [已折叠 ctx-…] 时，"
    "先用本工具取回完整内容，再基于完整内容推理。"
)


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    content: str
    label: str | None = None

    @property
    def chars(self) -> int:
        return len(self.content)


class ContextStore:
    """按内容哈希保存原文，折叠后只把稳定 ID 与预览留在消息里。"""

    def __init__(self) -> None:
        self._items: dict[str, ContextItem] = {}

    def put(self, content: str, *, label: str | None = None) -> str:
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]
        item_id = f"ctx-{digest}"
        if item_id not in self._items:
            self._items[item_id] = ContextItem(
                item_id=item_id,
                content=content,
                label=label,
            )
        return item_id

    def get(self, item_id: str) -> str | None:
        item = self._items.get(item_id)
        return item.content if item is not None else None

    def label(self, item_id: str) -> str | None:
        item = self._items.get(item_id)
        return item.label if item is not None else None

    def items(self) -> list[ContextItem]:
        return list(self._items.values())

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._items

    def __len__(self) -> int:
        return len(self._items)


class ProgressiveDisclosure:
    """把长内容折叠成“预览 + 句柄”，需要时再用工具展开。"""

    def __init__(self, store: ContextStore | None = None) -> None:
        self.store = store or ContextStore()

    def fold(
        self,
        content: str,
        *,
        label: str | None = None,
        preview_chars: int = 240,
    ) -> str:
        body = content.strip()
        if not body:
            return ""
        size = max(20, preview_chars)
        item_id = self.store.put(body, label=label)
        preview = body[:size].rstrip()
        if len(body) > size:
            preview += "…"
        return (
            f"[已折叠 {item_id}｜原文 {len(body)} 字]\n"
            f"{preview}\n"
            f'需要时调用 expand_context(item_id="{item_id}") 展开。'
        )


class ExpandContextTool:
    """把被折叠的上下文重新交给模型，并限制单次展开长度。"""

    def __init__(
        self,
        store: ContextStore,
        *,
        name: str = "expand_context",
        max_chars: int = 4000,
    ) -> None:
        self.store = store
        self.max_chars = max_chars
        self.spec = ToolSpec(
            name=name,
            description=_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "minLength": 3,
                        "description": "消息中 [已折叠 ctx-…] 里的上下文 ID",
                    }
                },
                "required": ["item_id"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        item_id = str(arguments.get("item_id", "")).strip()
        content = self.store.get(item_id)
        if content is None:
            return ToolOutput(
                content=(
                    f"没有找到上下文片段 {item_id!r}。"
                    "请只使用消息里出现过的 ctx- 开头的 ID。"
                ),
                is_error=True,
                metadata={"error_type": "not_found", "item_id": item_id},
            )

        truncated = len(content) > self.max_chars
        body = content[: self.max_chars] + ("…" if truncated else "")
        return ToolOutput(
            content=body,
            metadata={
                "item_id": item_id,
                "label": self.store.label(item_id),
                "chars": len(content),
                "truncated": truncated,
            },
        )
