from __future__ import annotations

import json
import re
from typing import Any

from atlas.eval.base import EvalResult, EvalTask
from atlas.llm.base import LLM
from atlas.types import Message, Trajectory

JUDGE_SYSTEM_PROMPT = (
    "你是一名严格的评测员。你只根据给定材料评分，不补充外部知识；"
    "先逐条核对评分标准，再给出 0 到 1 之间的总分。"
)


class JudgeParseError(ValueError):
    pass


def parse_judge_response(text: str) -> tuple[float, str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise JudgeParseError("judge response contains no JSON object")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"invalid judge JSON: {exc}") from exc
    if "score" not in payload:
        raise JudgeParseError("judge JSON has no score")
    try:
        score = float(payload["score"])
    except (TypeError, ValueError) as exc:
        raise JudgeParseError("judge score is not a number") from exc
    if not 0.0 <= score <= 1.0:
        raise JudgeParseError("judge score must be between 0 and 1")
    return score, str(payload.get("reason", "")), payload.get("criteria", [])


def _trajectory_summary(trajectory: Trajectory, max_chars: int) -> str:
    lines = [
        f"stop_reason={trajectory.stop_reason}",
        f"steps={len(trajectory.steps)}",
    ]
    for step in trajectory.steps:
        tools = ", ".join(
            f"{call.name}({json.dumps(call.arguments, ensure_ascii=False)})"
            for call in step.tool_calls
        ) or "none"
        errors = " | ".join(
            result.content for result in step.tool_results if result.is_error
        ) or "none"
        lines.append(f"step {step.index}: tools={tools}; errors={errors}")
    return "\n".join(lines)[:max_chars]


class LLMJudgeEvaluator:
    """用模型按评分标准打分；适合无法用规则判定的开放任务。"""

    def __init__(
        self,
        llm: LLM,
        *,
        threshold: float = 0.7,
        temperature: float = 0.0,
        max_trajectory_chars: int = 4000,
    ) -> None:
        self.llm = llm
        self.threshold = threshold
        self.temperature = temperature
        self.max_trajectory_chars = max_trajectory_chars

    def build_prompt(self, task: EvalTask, trajectory: Trajectory) -> str:
        rubric = task.rubric or "正确性、完整性与有据性各占三分之一。"
        reference = task.reference or "（无参考答案）"
        return "\n".join(
            [
                f"任务：{task.question}",
                f"参考答案：{reference}",
                f"评分标准：{rubric}",
                "",
                "候选答案：",
                trajectory.final_answer or "（空）",
                "",
                "执行轨迹摘要：",
                _trajectory_summary(trajectory, self.max_trajectory_chars),
                "",
                "请只输出一个 JSON 对象，字段为：",
                '{"score": 0.0-1.0, "reason": "简要理由", '
                '"criteria": [{"name": "标准名", "met": true/false, "evidence": "依据"}]}',
                "没有证据支持的结论要扣分；不要因为文字更长而给更高分。",
            ]
        )

    def score(self, task: EvalTask, trajectory: Trajectory) -> EvalResult:
        prompt = self.build_prompt(task, trajectory)
        try:
            response = self.llm.complete(
                [
                    Message(role="system", content=JUDGE_SYSTEM_PROMPT),
                    Message(role="user", content=prompt),
                ],
                temperature=self.temperature,
            )
            score, reason, criteria = parse_judge_response(response.content or "")
        except Exception as exc:  # 评委失败按不通过处理，并保留原因
            return EvalResult(
                task_id=task.id,
                trajectory=trajectory,
                score=0.0,
                passed=False,
                detail={
                    "judge_error": f"{type(exc).__name__}: {exc}",
                    "judge_model": getattr(self.llm, "model", "unknown"),
                },
            )

        return EvalResult(
            task_id=task.id,
            trajectory=trajectory,
            score=score,
            passed=score >= self.threshold,
            detail={
                "reason": reason,
                "criteria": criteria,
                "threshold": self.threshold,
                "judge_model": getattr(self.llm, "model", "unknown"),
            },
        )
