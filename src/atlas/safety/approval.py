from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from atlas.types import RunContext, ToolCall, utcnow


@dataclass
class ApprovalRecord:
    tool_call_id: str
    tool: str
    reason: str
    approved: bool
    approver: str
    created_at: datetime = field(default_factory=utcnow)


class AutoApprove:
    """仅用于演示与测试：真实系统不应默认自动批准高风险动作。"""

    last_approver = "auto"

    def request(self, call: ToolCall, ctx: RunContext, reason: str) -> bool:
        return True


class AutoDeny:
    last_approver = "auto-deny"

    def request(self, call: ToolCall, ctx: RunContext, reason: str) -> bool:
        return False


class ScriptedApproval:
    """按脚本依次批准或拒绝，便于离线复现审批路径。"""

    def __init__(
        self,
        decisions: Iterable[bool] = (),
        *,
        default: bool = False,
        approver: str = "scripted",
    ) -> None:
        self._decisions = deque(bool(item) for item in decisions)
        self.default = default
        self.last_approver = approver
        self.history: list[ApprovalRecord] = []

    def request(self, call: ToolCall, ctx: RunContext, reason: str) -> bool:
        approved = self._decisions.popleft() if self._decisions else self.default
        self.history.append(
            ApprovalRecord(
                tool_call_id=call.id,
                tool=call.name,
                reason=reason,
                approved=approved,
                approver=self.last_approver,
            )
        )
        return approved


class CallbackApproval:
    """把审批委托给外部系统，例如工单、聊天机器人或审批 API。"""

    def __init__(
        self,
        callback: Callable[[ToolCall, RunContext, str], bool],
        *,
        approver: str = "callback",
    ) -> None:
        self.callback = callback
        self.last_approver = approver
        self.history: list[ApprovalRecord] = []

    def request(self, call: ToolCall, ctx: RunContext, reason: str) -> bool:
        approved = bool(self.callback(call, ctx, reason))
        self.history.append(
            ApprovalRecord(
                tool_call_id=call.id,
                tool=call.name,
                reason=reason,
                approved=approved,
                approver=self.last_approver,
            )
        )
        return approved


class ConsoleApproval:
    """终端审批的最小实现；超时、身份与范围校验留给生产审批服务。"""

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        approver: str = "local-user",
    ) -> None:
        self.input_fn = input_fn
        self.output_fn = output_fn
        self.last_approver = approver
        self.history: list[ApprovalRecord] = []

    def request(self, call: ToolCall, ctx: RunContext, reason: str) -> bool:
        self.output_fn(
            f"\n[审批请求] 工具：{call.name}\n"
            f"原因：{reason}\n"
            f"参数：{call.arguments}\n"
            f"运行：{ctx.run_id}\n"
        )
        answer = self.input_fn("批准本次调用？[y/N] ").strip().lower()
        approved = answer in {"y", "yes"}
        self.history.append(
            ApprovalRecord(
                tool_call_id=call.id,
                tool=call.name,
                reason=reason,
                approved=approved,
                approver=self.last_approver,
            )
        )
        return approved
