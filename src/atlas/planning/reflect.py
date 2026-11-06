from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from atlas.llm.base import LLM
from atlas.planning.base import PlanStep
from atlas.types import Message

_FENCED = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

REFLECT_PROMPT = """你是严格的审稿人。判断给定步骤的结果是否足以支撑任务目标。
只输出 JSON：{"ok": true, "critique": "...", "suggestion": "..."}
critique 必须指出具体缺口；suggestion 必须是下一次尝试可执行的修改。"""


@dataclass
class Reflection:
    ok: bool
    critique: str = ""
    suggestion: str = ""


class Reflector(Protocol):
    def reflect(
        self,
        task: str,
        step: PlanStep,
        answer: str,
        history: list[Message],
    ) -> Reflection:
        ...


def _strip_fences(text: str) -> str:
    match = _FENCED.search(text)
    if match:
        return match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


def _as_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def parse_reflection(text: str) -> Reflection:
    try:
        data = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        # 反思器是辅助组件；解析失败时不阻断主流程，但把原因写进 critique。
        return Reflection(ok=True, critique=f"反思输出无法解析，按通过处理：{exc}")
    if not isinstance(data, dict):
        return Reflection(ok=True, critique="反思输出不是对象，按通过处理")
    return Reflection(
        ok=_as_bool(data.get("ok"), default=True),
        critique=str(data.get("critique") or ""),
        suggestion=str(data.get("suggestion") or ""),
    )


class LLMReflector:
    def __init__(
        self,
        llm: LLM,
        *,
        temperature: float = 0.0,
        system_prompt: str = REFLECT_PROMPT,
        max_history: int = 6,
        max_history_chars: int = 600,
    ) -> None:
        self.llm = llm
        self.temperature = temperature
        self.system_prompt = system_prompt
        self.max_history = max_history
        self.max_history_chars = max_history_chars

    def reflect(
        self,
        task: str,
        step: PlanStep,
        answer: str,
        history: list[Message],
    ) -> Reflection:
        messages = [
            Message(role="system", content=self.system_prompt),
            Message(
                role="user",
                content=(
                    f"任务：{task}\n步骤：{step.description}\n"
                    f"步骤结果：\n{answer}\n\n已有进展：\n{self._history(history)}"
                ),
            ),
        ]
        response = self.llm.complete(messages, temperature=self.temperature)
        return parse_reflection(response.content or "")

    def _history(self, history: list[Message]) -> str:
        recent = [message for message in history if (message.content or "").strip()]
        if not recent:
            return "（无）"
        return "\n".join(
            f"- {message.role}: {(message.content or '')[: self.max_history_chars]}"
            for message in recent[-self.max_history :]
        )
