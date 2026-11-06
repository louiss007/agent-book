from __future__ import annotations

from typing import Literal

from atlas.agent.runner import AgentRunner
from atlas.rag.evidence import CitationReport, EvidenceLedger
from atlas.types import RunContext, Step, Trajectory


class AgenticRAG:
    """在 Agent 循环外做引用审计；不改变循环本身，也不强制检索。"""

    def __init__(
        self,
        runner: AgentRunner,
        *,
        ledger: EvidenceLedger | None = None,
        require_citations: bool = True,
        min_citations: int = 1,
        on_missing: Literal["warn", "refuse"] = "warn",
    ) -> None:
        self.runner = runner
        self.ledger = ledger or EvidenceLedger()
        self.require_citations = require_citations
        self.min_citations = max(1, min_citations)
        self.on_missing = on_missing
        self.last_report: CitationReport | None = None

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        self.ledger.reset()
        trajectory = self.runner.run(task, ctx)
        report = self.ledger.verify(trajectory.final_answer or "")
        self.last_report = report

        problems: list[str] = []
        if self.require_citations:
            if len(report.cited) < self.min_citations:
                problems.append(
                    f"最终答案只有 {len(report.cited)} 条引用，"
                    f"少于要求的 {self.min_citations} 条"
                )
            if report.unknown:
                problems.append(
                    "以下引用不在本轮证据中：" + "、".join(report.unknown)
                )

        if problems:
            note = "引用检查未通过：" + "；".join(problems)
            trajectory.steps.append(
                Step(index=len(trajectory.steps) + 1, thought=note)
            )
            if self.on_missing == "refuse":
                trajectory.final_answer = (
                    "无法给出有据可查的答案：本轮检索没有提供足够的可引用证据。"
                )
        return trajectory
