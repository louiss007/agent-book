from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atlas.tools.mcp import MCPError, StdioMCPClient, load_mcp_tools

SERVER = Path(__file__).resolve().parent.parent / "examples" / "ch05_mcp_server.py"


@pytest.fixture()
def client():
    mcp = StdioMCPClient([sys.executable, str(SERVER)], timeout=10)
    try:
        mcp.initialize()
        yield mcp
    finally:
        mcp.close()


def test_list_and_call_tools(client):
    tools = client.list_tools()
    names = {tool["name"] for tool in tools}
    assert {"word_count", "save_note"} <= names

    result = client.call_tool("word_count", {"text": "Atlas uses tools"})
    assert result["isError"] is False
    assert result["content"][0]["text"] == "3"
    assert result["structuredContent"] == {"count": 3}


def test_tool_execution_error_is_flagged(client):
    result = client.call_tool("save_note", {"title": "只有标题"})
    assert result["isError"] is True


def test_unknown_tool_is_protocol_error(client):
    with pytest.raises(MCPError):
        client.call_tool("missing", {})


def test_mcp_tool_marks_destructive_as_dangerous(client):
    tools = {tool.spec.name: tool for tool in load_mcp_tools(client)}
    assert tools["word_count"].spec.dangerous is False
    assert tools["save_note"].spec.dangerous is True
