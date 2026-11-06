from __future__ import annotations

import json
import re
from collections.abc import Iterable

from atlas.llm.base import LLM
from atlas.planning.base import Plan, PlanStep
from atlas.types import Message

_FENCED = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

PLANNER_PROMPT = """你是任务规划器。把用户任务拆成 2–6 个可独立执行的步骤。
只输出 JSON，不要解释：
{"goal": "一句话目标", "steps": [{"id": "1", "description": "..."}]}
每个步骤要说明产出物与完成标准；不要写"思考一下"这类无法验证的步骤。"""


class PlanParseError(ValueError):
    """计划输出无法解析成 Plan 时抛出。"""


def _strip_fences(text: str) -> str:
    match = _FENCED.search(text)
    if match:
        return match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


def parse_plan(text: str, *, max_steps: int = 6) -> Plan:
    payload = _strip_fences(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PlanParseError(f"计划不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise PlanParseError("计划顶层必须是对象")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanParseError("计划缺少非空 steps 数组")

    steps: list[PlanStep] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_steps, start=1):
        if len(steps) >= max_steps:
            break
        if isinstance(raw, str):
            description = raw.strip()
            step_id = str(index)
        elif isinstance(raw, dict):
            description = str(raw.get("description", "")).strip()
            step_id = str(raw.get("id") or index).strip()
        else:
            raise PlanParseError(f"第 {index} 个步骤格式不正确")
        if not description:
            raise PlanParseError(f"第 {index} 个步骤缺少 description")
        if not step_id or step_id in seen:
            step_id = f"s{index}"
        seen.add(step_id)
        steps.append(PlanStep(id=step_id, description=description))

    if not steps:
        raise PlanParseError("计划没有有效步骤")
    goal = str(data.get("goal") or "").strip()
    return Plan(goal=goal, steps=steps)


class LLMPlanner:
    def __init__(
        self,
        llm: LLM,
        *,
        max_steps: int = 6,
        temperature: float = 0.0,
        system_prompt: str = PLANNER_PROMPT,
        max_history: int = 8,
        max_history_chars: int = 800,
    ) -> None:
        self.llm = llm
        self.max_steps = max_steps
        self.temperature = temperature
        self.system_prompt = system_prompt
        self.max_history = max_history
        self.max_history_chars = max_history_chars
        self.last_plan: Plan | None = None

    def plan(self, task: str, history: list[Message]) -> Plan:
        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=self._render(task, history)),
        ]
        response = self.llm.complete(messages, temperature=self.temperature)
        plan = parse_plan(response.content or "", max_steps=self.max_steps)
        if not plan.goal:
            plan.goal = task
        self.last_plan = plan
        return plan

    def _render(self, task: str, history: list[Message]) -> str:
        lines = [f"任务：{task}", "", "已有进展："]
        recent = [message for message in history if (message.content or "").strip()]
        if not recent:
            lines.append("（无）")
        else:
            for message in recent[-self.max_history :]:
                content = (message.content or "").strip()
                lines.append(
                    f"- {message.role}: {content[: self.max_history_chars]}"
                )
        lines.extend(["", "请输出 JSON 计划。"])
        return "\n".join(lines)


class StaticPlanner:
    """按顺序返回预设计划，主要用于测试与离线演示。"""

    def __init__(self, plans: Iterable[Plan]) -> None:
        self._plans = list(plans)
        self.calls = 0
        self.last_plan: Plan | None = None

    def plan(self, task: str, history: list[Message]) -> Plan:
        if self.calls >= len(self._plans):
            raise PlanParseError("StaticPlanner 没有更多计划")
        template = self._plans[self.calls]
        self.calls += 1
        plan = Plan(
            goal=template.goal or task,
            steps=[
                PlanStep(id=step.id, description=step.description)
                for step in template.steps
            ],
        )
        self.last_plan = plan
        return plan
