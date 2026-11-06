from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from atlas.tools.base import Tool
from atlas.tools.schema import validate_arguments
from atlas.types import RunContext, ToolCall, ToolResult, ToolSpec


class ToolRegistry:
    def __init__(
        self,
        tools: Iterable[Tool] = (),
        *,
        allow_dangerous: bool = False,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._allow_dangerous = allow_dangerous
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"duplicate tool: {name}")
        self._tools[name] = tool

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def subset(self, names: Iterable[str]) -> "ToolRegistry":
        """按名称顺序构造工具子集；用于给不同角色裁剪行动空间。"""

        wanted = list(names)
        missing = [name for name in wanted if name not in self._tools]
        if missing:
            raise KeyError(f"unknown tools: {', '.join(missing)}")
        return ToolRegistry(
            [self._tools[name] for name in wanted],
            allow_dangerous=self._allow_dangerous,
        )

    def run(self, call: ToolCall, ctx: RunContext | None = None) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                content=f"Unknown tool: {call.name}",
                is_error=True,
                metadata={"error_type": "unknown_tool"},
            )

        approved_ids: object = ()
        if ctx is not None:
            approved_ids = ctx.metadata.get("approved_tool_calls", ())
        allowed = (
            self._allow_dangerous
            or bool(ctx and ctx.metadata.get("allow_dangerous"))
            or (isinstance(approved_ids, (list, tuple, set)) and call.id in approved_ids)
        )
        if tool.spec.dangerous and not allowed:
            return ToolResult(
                tool_call_id=call.id,
                content=(
                    f"工具 {call.name} 被标记为危险，本次运行未授权。"
                    "需要用户批准或在运行配置中显式允许后重试。"
                ),
                is_error=True,
                metadata={
                    "error_type": "permission",
                    "denied": True,
                    "dangerous": True,
                    "tool": call.name,
                },
            )

        errors = validate_arguments(tool.spec.parameters, call.arguments)
        if errors:
            return ToolResult(
                tool_call_id=call.id,
                content=f"Invalid arguments for {call.name}: " + "; ".join(errors),
                is_error=True,
                metadata={"error_type": "validation", "errors": errors},
            )

        try:
            output = tool.run(call.arguments)
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                content=f"{type(exc).__name__}: {exc}",
                is_error=True,
                metadata={"error_type": "exception", "retryable": False},
            )

        return ToolResult(
            tool_call_id=call.id,
            content=output.content,
            is_error=output.is_error,
            metadata=output.metadata,
        )

    def run_many(
        self,
        calls: list[ToolCall],
        ctx: RunContext | None = None,
        *,
        max_workers: int = 4,
    ) -> list[ToolResult]:
        if not calls:
            return []
        if len(calls) == 1 or max_workers <= 1:
            return [self.run(call, ctx) for call in calls]

        tools = [self._tools.get(call.name) for call in calls]
        if any(tool is None or tool.spec.dangerous for tool in tools):
            # 只要一批调用里出现未知或危险工具，整批退化为串行，
            # 保证副作用顺序与输入顺序一致。
            return [self.run(call, ctx) for call in calls]

        workers = min(max_workers, len(calls))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="atlas-tool"
        ) as pool:
            return list(pool.map(lambda call: self.run(call, ctx), calls))
