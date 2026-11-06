from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from atlas.safety.base import GuardDecision
from atlas.types import RunContext, ToolCall, ToolResult

DEFAULT_WRITE_TOOLS = frozenset(
    {
        "apply_patch",
        "create_directory",
        "delete_file",
        "edit_file",
        "move_file",
        "write_file",
    }
)
DEFAULT_COMMAND_TOOLS = frozenset({"exec", "run_command", "run_tests", "shell"})

_PATH_KEYS = {
    "cwd",
    "dir",
    "directory",
    "file",
    "file_path",
    "filename",
    "filepath",
    "path",
    "target",
    "workdir",
    "workspace",
}
_SHELL_META = re.compile(r"[;&|<>`$\n]")


@dataclass(frozen=True)
class SandboxPolicy:
    """工作区边界策略；它是护栏，不是操作系统级沙箱。"""

    root: Path | str = "."
    read_only: bool = True
    allowed_commands: tuple[str, ...] = ()
    write_tools: frozenset[str] = field(default=DEFAULT_WRITE_TOOLS)
    command_tools: frozenset[str] = field(default=DEFAULT_COMMAND_TOOLS)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())


class SandboxGuard:
    """在工具执行前检查路径逃逸、只读约束与命令白名单。

    真正的隔离仍需要容器、microVM 或受限子进程；本类只负责把
    “明显越界的请求”在运行时挡在工具之前。
    """

    name = "sandbox"

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()

    def before_tool(self, call: ToolCall, ctx: RunContext) -> GuardDecision:
        if self.policy.read_only and call.name in self.policy.write_tools:
            return GuardDecision(
                "deny",
                f"沙箱处于只读模式，工具 {call.name} 需要写权限",
                metadata={"sandbox": "read_only", "root": str(self.policy.root)},
            )

        for key, value in _walk_arguments(call.arguments):
            if _is_path_key(key):
                for raw in _strings(value):
                    violation = self._check_path(raw)
                    if violation is not None:
                        return GuardDecision(
                            "deny",
                            violation,
                            metadata={
                                "sandbox": "path_escape",
                                "root": str(self.policy.root),
                                "argument": key,
                            },
                        )

        if call.name in self.policy.command_tools or "command" in call.arguments:
            violation = self._check_command(call)
            if violation is not None:
                return GuardDecision(
                    "deny",
                    violation,
                    metadata={
                        "sandbox": "command",
                        "allowed_commands": list(self.policy.allowed_commands),
                    },
                )
        return GuardDecision()

    def after_tool(self, result: ToolResult, ctx: RunContext) -> GuardDecision:
        return GuardDecision()

    def _check_path(self, raw: str) -> str | None:
        text = raw.strip()
        if not text:
            return None
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = self.policy.root / candidate
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            return f"无法解析路径：{text}"
        if not _is_relative_to(resolved, self.policy.root):
            return f"路径 {text} 超出工作区 {self.policy.root}"
        return None

    def _check_command(self, call: ToolCall) -> str | None:
        command = call.arguments.get("command", call.arguments.get("cmd"))
        if command is None:
            return "命令执行工具缺少 command 参数"
        if isinstance(command, (list, tuple)):
            joined = " ".join(str(part) for part in command)
        else:
            joined = str(command)
        if _SHELL_META.search(joined):
            return "命令包含 shell 元字符，沙箱只接受单条可执行命令"
        try:
            parts = shlex.split(joined)
        except ValueError as exc:
            return f"命令无法解析：{exc}"
        if not parts:
            return "命令为空"
        executable = Path(parts[0]).name
        allowed = {Path(item).name for item in self.policy.allowed_commands}
        if executable not in allowed:
            return f"命令 {executable} 不在允许列表中"
        for token in parts[1:]:
            if token.startswith("-"):
                continue
            if token.startswith("/") or token.startswith("~"):
                violation = self._check_path(token)
                if violation is not None:
                    return violation
        return None


def _walk_arguments(value: Any, key: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for name, item in value.items():
            yield from _walk_arguments(item, str(name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_arguments(item, key)
    else:
        yield key, value


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _is_path_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _PATH_KEYS or lowered.endswith("_path")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
