"""最小 MCP stdio 服务器：用于第 5 章离线示例。"""

from __future__ import annotations

import json
import sys
from typing import Any

NOTES: list[dict[str, str]] = []

TOOLS = [
    {
        "name": "word_count",
        "description": "统计一段文本中的单词数量。只读，不修改任何状态。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要统计的文本"}
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "save_note",
        "description": "把一条笔记写入当前会话的内存笔记库，返回保存后的编号。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "笔记标题"},
                "body": {"type": "string", "description": "笔记正文"},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
        "annotations": {"destructiveHint": True, "idempotentHint": False},
    },
]


class RPCError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _text_result(
    text: str, *, is_error: bool = False, structured: Any = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }
    if structured is not None:
        result["structuredContent"] = structured
    return result


def _handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name == "word_count":
        text = arguments.get("text")
        if not isinstance(text, str):
            return _text_result("text 必须是字符串", is_error=True)
        count = len(text.split())
        return _text_result(str(count), structured={"count": count})
    if name == "save_note":
        title = arguments.get("title")
        body = arguments.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            return _text_result("title 和 body 都必须是字符串", is_error=True)
        NOTES.append({"title": title, "body": body})
        return _text_result(
            f"saved note #{len(NOTES)}", structured={"saved": len(NOTES)}
        )
    raise RPCError(-32602, f"unknown tool: {name}")


def handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "atlas-notes", "version": "0.1.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return _handle_tools_call(params)
    if method == "resources/list":
        return {
            "resources": [
                {
                    "uri": "atlas://handbook",
                    "name": "Atlas Handbook",
                    "mimeType": "text/plain",
                }
            ]
        }
    if method == "resources/read":
        uri = params.get("uri")
        if uri != "atlas://handbook":
            raise RPCError(-32602, f"unknown resource: {uri}")
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/plain",
                    "text": "Atlas 是一个研究助手示例。",
                }
            ]
        }
    raise RPCError(-32601, f"method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        method = message.get("method")
        if not isinstance(method, str):
            continue
        if "id" not in message:
            continue  # 通知不需要响应
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}
        try:
            result = handle(method, params)
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except RPCError as exc:
            reply = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": exc.code, "message": exc.message},
            }
        except Exception as exc:
            reply = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32603, "message": str(exc)},
            }
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
