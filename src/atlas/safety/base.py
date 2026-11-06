from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from atlas.types import RunContext, ToolCall, ToolResult

GuardAction = Literal["allow", "deny", "approve"]


@dataclass
class GuardDecision:
    """护栏对一次工具调用的裁决。

    ``replacement`` 用于“不执行原工具，但给模型一个可控结果”的场景，
    例如命中注入后返回脱敏内容，或审批被拒绝后返回可恢复的错误。
    """

    action: GuardAction = "allow"
    reason: str = ""
    replacement: ToolResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Guard(Protocol):
    def before_tool(self, call: ToolCall, ctx: RunContext) -> GuardDecision:
        ...

    def after_tool(self, result: ToolResult, ctx: RunContext) -> GuardDecision:
        ...


class ApprovalHandler(Protocol):
    def request(self, call: ToolCall, ctx: RunContext, reason: str) -> bool:
        ...


def denied_result(
    call: ToolCall,
    reason: str,
    *,
    guard: str | None = None,
    approval: str | None = None,
    decisions: list[dict[str, Any]] | None = None,
    skipped: bool = False,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    """把拒绝转换成模型可读、审计可查的错误结果。"""

    metadata: dict[str, Any] = {
        "error_type": "denied",
        "denied": True,
        "tool": call.name,
        "reason": reason,
    }
    if guard is not None:
        metadata["guard"] = guard
    if approval is not None:
        metadata["approval"] = approval
    if skipped:
        metadata["skipped"] = True
    if decisions:
        metadata["guard_decisions"] = decisions
    if extra:
        metadata.update(extra)
    return ToolResult(
        tool_call_id=call.id,
        content=(
            f"工具 {call.name} 的调用被安全护栏拒绝：{reason}。"
            "请换一种不需要该权限的方式；如果确实必要，请向用户说明并请求授权。"
        ),
        is_error=True,
        metadata=metadata,
    )
