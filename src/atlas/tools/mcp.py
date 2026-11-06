from __future__ import annotations

import json
import queue
import subprocess
import threading
from collections.abc import Sequence
from typing import Any

from atlas.types import ToolOutput, ToolSpec


class MCPError(RuntimeError):
    """MCP 协议或传输层错误。"""


class MCPTimeout(MCPError):
    """等待 MCP 响应超时。"""


class StdioMCPClient:
    """最小的 MCP stdio 客户端：JSON-RPC 2.0，一行一条消息。"""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        protocol_version: str = "2025-06-18",
        timeout: float = 30.0,
    ) -> None:
        self.command = list(command)
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self._closed = False

        self._proc = subprocess.Popen(
            self.command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._next_id = 0
        self._stderr_tail: list[str] = []

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def initialize(self) -> dict[str, Any]:
        result = self._request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "atlas", "version": "0.5.0"},
            },
        )
        self.server_info = result.get("serverInfo", {}) or {}
        self.capabilities = result.get("capabilities", {}) or {}
        self._notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self._request("tools/list", params)
            tools.extend(result.get("tools", []) or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def list_resources(self) -> list[dict[str, Any]]:
        result = self._request("resources/list", {})
        return result.get("resources", []) or []

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self._request("resources/read", {"uri": uri})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        stdin = self._proc.stdin
        if stdin is not None:
            try:
                stdin.close()
            except OSError:
                pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except Exception:
            self._proc.kill()
        for stream in (self._proc.stdout, self._proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def __enter__(self) -> "StdioMCPClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self._closed:
            raise MCPError("MCP client is closed")

        with self._pending_lock:
            self._next_id += 1
            request_id = self._next_id
            waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter

        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params

        try:
            self._send(message)
            try:
                response = waiter.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise MCPTimeout(
                    f"MCP request timed out after {self.timeout}s: {method}"
                ) from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        if "error" in response:
            error = response["error"] or {}
            raise MCPError(f"MCP error {error.get('code')}: {error.get('message')}")
        result = response.get("result", {})
        return result if isinstance(result, dict) else {"value": result}

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def _send(self, message: dict[str, Any]) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            raise MCPError("MCP server stdin is not available")
        line = json.dumps(message, ensure_ascii=False)
        with self._write_lock:
            try:
                stdin.write(line + "\n")
                stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise MCPError(f"MCP server is not writable: {exc}") from exc

    def _read_stdout(self) -> None:
        stdout = self._proc.stdout
        if stdout is None:
            return
        for line in stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue

            if "id" in message and ("result" in message or "error" in message):
                with self._pending_lock:
                    waiter = self._pending.pop(message["id"], None)
                if waiter is not None:
                    waiter.put(message)
            elif "id" in message and "method" in message:
                self._answer_server_request(message)

    def _answer_server_request(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method == "ping":
            response = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
        else:
            response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32601, "message": f"method not supported: {method}"},
            }
        try:
            self._send(response)
        except MCPError:
            pass

    def _read_stderr(self) -> None:
        stderr = self._proc.stderr
        if stderr is None:
            return
        for line in stderr:
            self._stderr_tail.append(line.rstrip())
            if len(self._stderr_tail) > 200:
                del self._stderr_tail[:100]


class MCPTool:
    def __init__(
        self,
        server: StdioMCPClient,
        remote_name: str,
        *,
        spec: ToolSpec | None = None,
    ) -> None:
        self.server = server
        self.remote_name = remote_name
        self.spec = spec or ToolSpec(
            name=remote_name,
            description=f"MCP tool {remote_name}",
            parameters={"type": "object"},
        )

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        try:
            result = self.server.call_tool(self.remote_name, arguments)
        except MCPError as exc:
            return ToolOutput(
                content=f"MCP error: {exc}",
                is_error=True,
                metadata={"error_type": "mcp", "retryable": isinstance(exc, MCPTimeout)},
            )

        content, content_types = _render_content(result.get("content", []))
        metadata: dict[str, Any] = {
            "mcp_server": self.server.server_info.get("name", "unknown"),
            "content_types": content_types,
        }
        structured = result.get("structuredContent")
        if structured is not None:
            metadata["structured_content"] = structured
            if not content:
                content = json.dumps(structured, ensure_ascii=False)

        return ToolOutput(
            content=content,
            is_error=bool(result.get("isError", False)),
            metadata=metadata,
        )


def tool_spec_from_mcp(definition: dict[str, Any]) -> ToolSpec:
    annotations = definition.get("annotations") or {}
    read_only = annotations.get("readOnlyHint")
    destructive = annotations.get("destructiveHint")
    dangerous = not (read_only is True or destructive is False)
    return ToolSpec(
        name=str(definition.get("name", "")),
        description=str(definition.get("description", "")),
        parameters=definition.get("inputSchema") or {"type": "object"},
        dangerous=dangerous,
    )


def load_mcp_tools(server: StdioMCPClient) -> list[MCPTool]:
    tools: list[MCPTool] = []
    for definition in server.list_tools():
        name = definition.get("name")
        if not isinstance(name, str) or not name:
            continue
        tools.append(MCPTool(server, name, spec=tool_spec_from_mcp(definition)))
    return tools


def _render_content(items: Any) -> tuple[str, list[str]]:
    if not isinstance(items, list):
        return "", []
    parts: list[str] = []
    kinds: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type", "unknown"))
        kinds.append(kind)
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource":
            resource = item.get("resource", {}) or {}
            if "text" in resource:
                parts.append(str(resource["text"]))
            else:
                parts.append(
                    f"[resource {resource.get('uri', '')} "
                    f"{resource.get('mimeType', '')}]"
                )
        elif kind in {"image", "audio"}:
            parts.append(f"[{kind} {item.get('mimeType', '')}]")
        else:
            parts.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(part for part in parts if part), kinds
