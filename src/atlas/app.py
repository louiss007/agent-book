from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from atlas.agent.loop import Agent, AgentConfig
from atlas.agent.runner import AgentRunner
from atlas.config import AtlasConfig
from atlas.context.budgeted import BudgetedContextBuilder
from atlas.context.builder import MemoryContextBuilder
from atlas.llm.base import LLM
from atlas.llm.openai_compat import OpenAICompatLLM
from atlas.memory.base import MemoryItem, MemoryStore
from atlas.memory.long_term import InMemoryStore
from atlas.memory.recorder import MemoryRecorder
from atlas.memory.writer import MemoryWriter
from atlas.rag.agentic import AgenticRAG
from atlas.rag.evidence import CitationReport, EvidenceLedger
from atlas.rag.hybrid import KnowledgeBase
from atlas.rag.tool import KnowledgeSearchTool
from atlas.safety.base import ApprovalHandler, Guard
from atlas.tools.base import Tool
from atlas.tools.registry import ToolRegistry
from atlas.types import RunContext, Trajectory

DEFAULT_SYSTEM_PROMPT = (
    "你是一名严谨的研究助手。需要外部事实或来源时先检索；"
    "拿到足够信息后，用简洁的中文作答，并用 [doc_id] 标注引用。"
)


@dataclass
class AtlasApp:
    config: AtlasConfig
    runner: AgentRunner
    agent: Agent
    tools: ToolRegistry
    context_builder: BudgetedContextBuilder
    memory: MemoryStore
    writer: MemoryWriter
    knowledge: KnowledgeBase | None = None
    ledger: EvidenceLedger | None = None
    last_report: CitationReport | None = None
    tracer: Any = None
    guards: tuple[Any, ...] = ()
    approval: Any = None

    def run(
        self,
        task: str,
        *,
        user_id: str | None = None,
        run_id: str | None = None,
    ) -> Trajectory:
        ctx = RunContext(
            run_id=run_id or f"app-{uuid4().hex[:12]}",
            budget=replace(self.config.budget),
            user_id=user_id,
        )
        trajectory = self.runner.run(task, ctx)
        if self.ledger is not None:
            self.last_report = self.ledger.verify(trajectory.final_answer or "")
        return trajectory


def build_app(
    config: AtlasConfig,
    *,
    llm: LLM | None = None,
    tools: Iterable[Tool] = (),
    memory: MemoryStore | None = None,
    knowledge: KnowledgeBase | None = None,
    ledger: EvidenceLedger | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    require_citations: bool | None = None,
    seed_items: Sequence[MemoryItem] = (),
    tracer: Any = None,
    guards: Sequence[Guard] = (),
    approval: ApprovalHandler | None = None,
) -> AtlasApp:
    """按固定顺序装配 Atlas：工具 → 模型 → 记忆/检索 → 上下文 → 循环 → 包装。"""

    if llm is None:
        if config.offline:
            from atlas.demo import scripted_llm

            llm = scripted_llm()
        else:
            llm = OpenAICompatLLM(
                model=config.model,
                api_key=config.api_key,
                base_url=config.base_url,
            )

    store = memory or InMemoryStore()
    for item in seed_items:
        store.add(item)

    registry = ToolRegistry(tools)
    if knowledge is not None:
        ledger = ledger or EvidenceLedger()
        registry.register(KnowledgeSearchTool(knowledge, ledger=ledger))

    writer = MemoryWriter(store)
    memory_builder = MemoryContextBuilder(store, system_prompt=system_prompt)
    context_builder = BudgetedContextBuilder(
        inner=memory_builder,
        system_prompt=system_prompt,
        max_tokens=config.max_context_tokens,
    )

    agent = Agent(
        llm,
        registry,
        config=AgentConfig(
            system_prompt=system_prompt,
            temperature=config.temperature,
            max_context_tokens=config.max_context_tokens,
        ),
        context_builder=context_builder,
        tracer=tracer,
        guards=guards,
        approval=approval,
    )

    core: AgentRunner = agent
    if knowledge is not None:
        core = AgenticRAG(
            core,
            ledger=ledger,
            require_citations=(
                knowledge is not None if require_citations is None else require_citations
            ),
        )
    runner = MemoryRecorder(core, writer)

    return AtlasApp(
        config=config,
        runner=runner,
        agent=agent,
        tools=registry,
        context_builder=context_builder,
        memory=store,
        writer=writer,
        knowledge=knowledge,
        ledger=ledger,
        tracer=tracer,
        guards=tuple(guards),
        approval=approval,
    )
