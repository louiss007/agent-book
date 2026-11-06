from typing import Any, Protocol

from atlas.types import ToolOutput, ToolSpec


class Tool(Protocol):
    spec: ToolSpec

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        ...
