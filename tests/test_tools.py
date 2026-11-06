from __future__ import annotations

import time
from typing import Any

from atlas.tools.registry import ToolRegistry
from atlas.types import ToolCall, ToolOutput, ToolSpec


class EchoTool:
    spec = ToolSpec(
        name="echo",
        description="回显文本",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        return ToolOutput(content=arguments["text"])


class SleepTool:
    def __init__(self, name: str, delay: float) -> None:
        self.spec = ToolSpec(name=name, description="sleep", parameters={"type": "object"})
        self.delay = delay

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        time.sleep(self.delay)
        return ToolOutput(content=self.spec.name)


class DangerousTool:
    spec = ToolSpec(
        name="dangerous",
        description="危险工具",
        parameters={"type": "object"},
        dangerous=True,
    )

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        return ToolOutput(content="executed")


def test_validation_rejects_missing_and_extra():
    registry = ToolRegistry([EchoTool()])
    missing = registry.run(ToolCall(id="1", name="echo", arguments={}))
    assert missing.is_error
    assert missing.metadata["error_type"] == "validation"
    extra = registry.run(ToolCall(id="2", name="echo", arguments={"text": "x", "y": 1}))
    assert extra.is_error
    assert "不允许字段" in extra.content


def test_dangerous_tool_requires_opt_in():
    registry = ToolRegistry([DangerousTool()])
    denied = registry.run(ToolCall(id="1", name="dangerous"))
    assert denied.is_error
    assert denied.metadata == {
        "error_type": "permission",
        "denied": True,
        "dangerous": True,
        "tool": "dangerous",
    }
    allowed = ToolRegistry([DangerousTool()], allow_dangerous=True)
    assert allowed.run(ToolCall(id="2", name="dangerous")).content == "executed"


def test_run_many_preserves_order_and_runs_in_parallel():
    tools = [SleepTool("a", 0.2), SleepTool("b", 0.2), SleepTool("c", 0.2)]
    registry = ToolRegistry(tools)
    calls = [
        ToolCall(id=str(index), name=name)
        for index, name in enumerate(["a", "b", "c"])
    ]
    started = time.monotonic()
    results = registry.run_many(calls, max_workers=3)
    elapsed = time.monotonic() - started
    assert [result.content for result in results] == ["a", "b", "c"]
    assert elapsed < 0.5
