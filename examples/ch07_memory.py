from __future__ import annotations

from datetime import timedelta

from atlas.agent import Agent, AgentConfig
from atlas.context import MemoryContextBuilder
from atlas.llm import MockLLM
from atlas.memory import (
    InMemoryStore,
    MemoryItem,
    MemoryRecorder,
    MemoryWriter,
    WorkingMemory,
)
from atlas.tools import ToolRegistry
from atlas.types import LLMResponse, RunContext, utcnow

SYSTEM = "你是一名严谨的研究助手。结论先行，并给出来源。"


def main() -> None:
    store = InMemoryStore(half_life_days=30.0)
    writer = MemoryWriter(store, default_scope="research")

    writer.remember_preference(
        "用户要求只引用 2023 年以后的一手来源。",
        key="pref:sources",
        user_id="u-42",
    )
    writer.remember_preference(
        "用户要求只引用 2024 年以后的一手来源。",
        key="pref:sources",
        user_id="u-42",
    )
    writer.remember_preference(
        "用户偏好中文报告，结论先行。",
        key="pref:style",
        user_id="u-42",
    )
    writer.remember(
        "上次调研结论：ReAct 适合 3–5 步、路径不确定的任务。",
        kind="episodic",
        importance=0.7,
        metadata={"key": "finding:react", "user_id": "u-42"},
    )

    print("记忆写入：")
    print("  新偏好替换旧偏好（旧条目保留为 superseded）")

    builder = MemoryContextBuilder(
        store,
        system_prompt=SYSTEM,
        memory_k=4,
        preference_slots=2,
        require_user_scope=True,
    )
    llm = MockLLM(
        [
            LLMResponse(
                content=(
                    "结论先行：短任务优先 ReAct，长任务优先 Plan-and-Execute；"
                    "引用均来自 2024 年以后的一手来源。"
                )
            )
        ]
    )
    agent = Agent(
        llm,
        ToolRegistry([]),
        config=AgentConfig(system_prompt=SYSTEM),
        context_builder=builder,
    )
    recorder = MemoryRecorder(agent, writer, scope="research")

    trajectory = recorder.run(
        "调研 ReAct 与 Plan-and-Execute 的适用场景",
        RunContext(run_id="r1", user_id="u-42"),
    )

    print("\n本轮注入的系统消息：")
    print(llm.calls[0][0].content)
    print("\n召回条目：")
    for item in builder.last_items:
        print(f"  - {item.kind}: {item.content[:60]}")
    print(f"\nstop_reason={trajectory.stop_reason}")
    print(f"answer={trajectory.final_answer}")

    print("\n任务结束后写回：")
    tasks = [item for item in store.all() if item.kind == "episodic"]
    print(f"  共 {len(tasks)} 条情景记忆")
    print(f"  最新：{tasks[-1].content.splitlines()[0]}")

    stale = MemoryItem(
        id="",
        content="临时观察：某网页加载失败。",
        kind="episodic",
        importance=0.2,
        metadata={"scope": "research", "user_id": "u-42"},
        created_at=utcnow() - timedelta(days=90),
    )
    store.add(stale)
    removed = store.prune(ttl_days=60, min_retention=0.05, max_items=6)
    print("\n遗忘：")
    print(f"  删除 {len(removed)} 条：{[item.content[:16] for item in removed]}")
    print(f"  剩余 {len(store.all())} 条（含 superseded 审计记录）")

    working = WorkingMemory(max_items=3)
    working.set("current_goal", "对比 ReAct 与 Plan-and-Execute", importance=0.9)
    working.set("open_question", "2024 年后的代表性系统有哪些？", importance=0.7)
    print("\n工作记忆：")
    print(working.render())


if __name__ == "__main__":
    main()
