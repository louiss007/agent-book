from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import Literal

from atlas.memory.writer import redact_secrets
from atlas.safety.base import GuardDecision
from atlas.types import RunContext, ToolCall, ToolResult

InjectionMode = Literal["redact", "drop", "flag"]

# 只收录“高信号”表达：宁可漏报一部分变体，也不要把安全教育文章整段误杀。
_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_instructions",
        re.compile(
            r"(?i)\b(ignore|disregard|forget)\s+(all\s+)?"
            r"(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)"
        ),
    ),
    (
        "override_role",
        re.compile(
            r"(?i)\b(you\s+are\s+now|from\s+now\s+on\s+you|"
            r"new\s+system\s+prompt|system\s+override)\b"
        ),
    ),
    (
        "reveal_prompt",
        re.compile(
            r"(?i)\b(reveal|print|show|repeat)\b.{0,30}"
            r"\b(system\s+prompt|hidden\s+instructions?|developer\s+message)\b"
        ),
    ),
    (
        "exfiltration",
        re.compile(
            r"(?i)\b(send|post|upload|email|exfiltrate)\b.{0,60}"
            r"\b(api[_ -]?key|access[_ -]?token|password|secret|credential)s?\b"
        ),
    ),
    (
        "secrecy",
        re.compile(
            r"(?i)\b(do\s+not|don't|never)\s+(tell|inform|mention|reveal)\b"
            r".{0,40}\b(user|human|operator)\b"
        ),
    ),
    (
        "zh_ignore",
        re.compile(r"(忽略|无视|忘记|跳过).{0,12}(之前|以上|前面|先前|所有).{0,8}(指令|提示|规则|要求)"),
    ),
    (
        "zh_override",
        re.compile(r"(你现在是|从现在开始你|新的系统提示|系统指令覆盖|忽略你的设定)"),
    ),
    (
        "zh_secrecy",
        re.compile(r"(不要|别|禁止).{0,8}(告诉|告知|提醒|透露).{0,8}(用户|人类|操作员)"),
    ),
    (
        "html_comment",
        re.compile(
            r"<!--[\s\S]{0,500}?(ignore|忽略|system|指令|prompt|assistant)"
            r"[\s\S]{0,500}?-->",
            re.IGNORECASE,
        ),
    ),
)


def detect_injection(text: str, *, extra_rules: Sequence[tuple[str, str]] = ()) -> list[str]:
    """返回命中的规则名；规则名用于审计，不用于判断严重程度。"""

    hits = [name for name, pattern in _INJECTION_RULES if pattern.search(text)]
    for name, raw in extra_rules:
        if re.search(raw, text, re.IGNORECASE):
            hits.append(name)
    return hits


def _redact_spans(text: str) -> str:
    for _, pattern in _INJECTION_RULES:
        text = pattern.sub("[已移除可疑指令]", text)
    return text


class ToolAllowlistGuard:
    """按工具名做能力白名单；白名单是运行时事实，不依赖提示词。"""

    name = "tool_allowlist"

    def __init__(self, allowed: Iterable[str], *, name: str | None = None) -> None:
        self.allowed = frozenset(allowed)
        if name is not None:
            self.name = name

    def before_tool(self, call: ToolCall, ctx: RunContext) -> GuardDecision:
        if call.name not in self.allowed:
            return GuardDecision(
                "deny",
                f"工具 {call.name} 不在本次运行的能力白名单中",
                metadata={"allowed_tools": sorted(self.allowed)},
            )
        return GuardDecision()

    def after_tool(self, result: ToolResult, ctx: RunContext) -> GuardDecision:
        return GuardDecision()


class ApprovalGuard:
    """把指定工具升级为“需要人工审批”，而不是直接放行或直接拒绝。"""

    name = "approval"

    def __init__(
        self,
        tool_names: Iterable[str],
        *,
        reason: str = "该工具可能产生不可逆副作用",
        name: str | None = None,
    ) -> None:
        self.tool_names = frozenset(tool_names)
        self.reason = reason
        if name is not None:
            self.name = name

    @classmethod
    def from_registry(cls, registry, **kwargs) -> "ApprovalGuard":
        names = [spec.name for spec in registry.specs() if spec.dangerous]
        return cls(names, **kwargs)

    def before_tool(self, call: ToolCall, ctx: RunContext) -> GuardDecision:
        if call.name in self.tool_names:
            return GuardDecision("approve", self.reason)
        return GuardDecision()

    def after_tool(self, result: ToolResult, ctx: RunContext) -> GuardDecision:
        return GuardDecision()


class PromptInjectionGuard:
    """扫描工具结果中的指令性内容，并在进入上下文前降权或隔离。

    这是启发式防线，不是安全边界：它能拦住常见模板，拦不住改写与编码变体。
    真正的边界仍然是最小权限、审批与沙箱。
    """

    name = "prompt_injection"

    def __init__(
        self,
        *,
        mode: InjectionMode = "redact",
        extra_rules: Sequence[tuple[str, str]] = (),
        block_arguments: bool = False,
        name: str | None = None,
    ) -> None:
        if mode not in {"redact", "drop", "flag"}:
            raise ValueError(f"unsupported injection mode: {mode}")
        self.mode = mode
        self.extra_rules = tuple(extra_rules)
        self.block_arguments = block_arguments
        if name is not None:
            self.name = name

    def before_tool(self, call: ToolCall, ctx: RunContext) -> GuardDecision:
        if not self.block_arguments:
            return GuardDecision()
        text = json.dumps(call.arguments, ensure_ascii=False, default=str)
        hits = detect_injection(text, extra_rules=self.extra_rules)
        if hits:
            return GuardDecision(
                "deny",
                f"工具参数包含疑似指令注入：{', '.join(hits)}",
                metadata={"injection_rules": hits, "stage": "arguments"},
            )
        return GuardDecision()

    def after_tool(self, result: ToolResult, ctx: RunContext) -> GuardDecision:
        if result.is_error or not result.content:
            return GuardDecision()
        hits = detect_injection(result.content, extra_rules=self.extra_rules)
        if not hits:
            return GuardDecision()

        metadata = {
            "injection_suspected": True,
            "injection_rules": hits,
            "injection_mode": self.mode,
        }
        if self.mode == "flag":
            return GuardDecision(
                "allow",
                f"工具结果命中注入规则：{', '.join(hits)}",
                metadata=metadata,
            )

        if self.mode == "drop":
            content = (
                "[安全护栏] 工具结果包含疑似提示注入，已整段隔离；"
                "原始内容未进入上下文。"
            )
        else:
            content = _redact_spans(result.content)

        return GuardDecision(
            "allow",
            f"工具结果命中注入规则：{', '.join(hits)}",
            replacement=ToolResult(
                tool_call_id=result.tool_call_id,
                content=content,
                is_error=False,
                metadata={**result.metadata, **metadata, "sanitized": True},
            ),
            metadata=metadata,
        )


class OutputRedactionGuard:
    """在工具结果进入上下文前移除密钥；可选移除常见 PII。"""

    name = "output_redaction"

    _EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    _PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)")

    def __init__(
        self,
        *,
        redact_pii: bool = False,
        name: str | None = None,
    ) -> None:
        self.redact_pii = redact_pii
        if name is not None:
            self.name = name

    def before_tool(self, call: ToolCall, ctx: RunContext) -> GuardDecision:
        return GuardDecision()

    def after_tool(self, result: ToolResult, ctx: RunContext) -> GuardDecision:
        if result.is_error or not result.content:
            return GuardDecision()
        text = redact_secrets(result.content)
        rules = ["secret"]
        if self.redact_pii:
            text = self._EMAIL.sub("[EMAIL]", text)
            text = self._PHONE.sub("[PHONE]", text)
            rules.append("pii")
        if text == result.content:
            return GuardDecision()

        metadata = {
            "redacted": True,
            "redaction_rules": rules,
        }
        return GuardDecision(
            "allow",
            "工具结果包含敏感信息，已脱敏",
            replacement=ToolResult(
                tool_call_id=result.tool_call_id,
                content=text,
                is_error=False,
                metadata={**result.metadata, **metadata},
            ),
            metadata=metadata,
        )
