from __future__ import annotations

from datetime import timedelta

from atlas.agent.loop import Agent, AgentConfig
from atlas.context import MemoryContextBuilder
from atlas.llm.mock import MockLLM
from atlas.memory import (
    InMemoryStore,
    MemoryItem,
    MemoryRecorder,
    MemoryWriter,
    WorkingMemory,
    redact_secrets,
)
from atlas.tools import ToolRegistry
from atlas.types import (
    LLMResponse,
    Message,
    RunContext,
    Step,
    Trajectory,
    Usage,
    utcnow,
)


def make_item(content: str, **kwargs) -> MemoryItem:
    kwargs.setdefault("id", "")
    return MemoryItem(content=content, **kwargs)


def test_store_add_search_and_filters():
    store = InMemoryStore()
    pref = store.add(
        make_item(
            "用户偏好中文报告",
            kind="preference",
            importance=0.9,
            metadata={"user_id": "u1"},
        )
    )
    other = store.add(
        make_item(
            "另一用户要求英文报告",
            kind="preference",
            importance=0.9,
            metadata={"user_id": "u2"},
        )
    )
    fact = store.add(
        make_item(
            "ReAct 适合路径开放的中短任务",
            kind="semantic",
            importance=0.5,
            metadata={"user_id": "u1"},
        )
    )

    assert store.get(pref).content == "用户偏好中文报告"
    assert [item.id for item in store.search("报告", filters={"user_id": "u1"})] == [
        pref,
        fact,
    ]
    assert {item.id for item in store.search("报告", filters={"kind": "preference"})} == {
        pref,
        other,
    }
    assert store.search("报告", filters={"user_id": "u1", "kind": "preference"})[0].id == pref


def test_relevance_beats_importance_but_importance_breaks_ties():
    store = InMemoryStore()
    relevant = store.add(
        make_item("ReAct 的失败模式是重复调用", importance=0.2)
    )
    store.add(make_item("用户喜欢蓝色", importance=0.5))

    assert store.search("ReAct 失败模式", k=1)[0].id == relevant
    ranked = store.search("", k=2)
    assert ranked[0].importance >= ranked[1].importance


def test_forget_clear_and_prune():
    store = InMemoryStore(half_life_days=30.0)
    alive = store.add(make_item("新记忆", metadata={"scope": "a"}))
    old = store.add(
        make_item(
            "旧记忆",
            importance=0.9,
            created_at=utcnow() - timedelta(days=100),
            metadata={"scope": "a"},
        )
    )
    other = store.add(make_item("另一个作用域", metadata={"scope": "b"}))

    store.forget(alive)
    assert store.get(alive) is None
    store.clear("b")
    assert store.get(other) is None
    assert store.get(old) is not None

    removed = store.prune(ttl_days=30)
    assert [item.id for item in removed] == [old]
    assert store.all() == []


def test_prune_by_retention_and_capacity():
    store = InMemoryStore(half_life_days=30.0)
    old_low = store.add(
        make_item(
            "低价值旧记忆",
            importance=0.1,
            created_at=utcnow() - timedelta(days=90),
        )
    )
    keep = store.add(make_item("高价值新记忆", importance=0.9))
    extra = store.add(make_item("普通记忆", importance=0.4))

    removed = store.prune(min_retention=0.05)
    assert [item.id for item in removed] == [old_low]

    removed = store.prune(max_items=1, now=utcnow())
    assert {item.id for item in removed} == {extra}
    assert [item.id for item in store.all()] == [keep]


def test_writer_dedupes_and_supersedes_conflicting_preference():
    store = InMemoryStore()
    writer = MemoryWriter(store, min_importance=0.3)

    old = writer.remember_preference(
        "用户要求引用 2023 年以后的一手来源。",
        key="pref:sources",
        user_id="u1",
    )
    new = writer.remember_preference(
        "用户要求引用 2024 年以后的一手来源。",
        key="pref:sources",
        user_id="u1",
    )
    again = writer.remember_preference(
        "用户要求引用 2024 年以后的一手来源。",
        key="pref:sources",
        user_id="u1",
    )

    assert old and new and new != old
    assert again == new
    assert store.get(old).metadata["superseded"] is True
    assert store.get(old).metadata["superseded_by"] == new

    results = store.search(
        "引用来源", filters={"user_id": "u1", "kind": "preference"}
    )
    assert [item.id for item in results] == [new]
    assert len(store.all()) == 2


def test_writer_redacts_secrets_and_applies_gate():
    store = InMemoryStore()
    writer = MemoryWriter(store, min_importance=0.5)

    assert writer.remember("短", importance=0.9) is None
    assert writer.remember("内容够长但重要性低", importance=0.1) is None

    item_id = writer.remember(
        "请记住 api_key=sk-abcdefgh12345，之后自动登录。",
        importance=0.9,
    )
    saved = store.get(item_id)
    assert "sk-abcdefgh12345" not in saved.content
    assert "[REDACTED]" in saved.content
    assert saved.metadata["redacted"] is True
    assert redact_secrets("Bearer abc.def-123") == "[REDACTED]"


def test_context_builder_injects_scoped_memory_only():
    store = InMemoryStore()
    writer = MemoryWriter(store)
    writer.remember_preference(
        "用户要求只引用 2024 年以后的一手来源。",
        key="pref:sources",
        user_id="u1",
    )
    writer.remember(
        "上次调研结论：ReAct 适合中短任务。",
        kind="episodic",
        importance=0.7,
        metadata={"user_id": "u1"},
    )
    writer.remember_preference(
        "用户要求只引用英文来源。",
        key="pref:sources",
        user_id="u2",
    )

    builder = MemoryContextBuilder(
        store,
        system_prompt="你是一名严谨的研究助手。",
        memory_k=4,
        preference_slots=1,
        require_user_scope=True,
    )
    history = [Message(role="user", content="调研 ReAct")]
    ctx = RunContext(run_id="r1", user_id="u1")

    messages = builder.build("调研 ReAct 与 Plan-and-Execute", history, 0, ctx)

    assert messages[0].role == "system"
    assert "严谨的研究助手" in messages[0].content
    assert "长期记忆" in messages[0].content
    assert "2024 年" in messages[0].content
    assert "英文来源" not in messages[0].content
    assert messages[1:] == history
    assert {item.metadata["user_id"] for item in builder.last_items} == {"u1"}

    anonymous = RunContext(run_id="r2")
    assert builder.build("调研", history, 0, anonymous)[0].content == builder.system_prompt


def test_agent_uses_context_builder_without_changing_loop():
    store = InMemoryStore()
    MemoryWriter(store).remember_preference(
        "用户要求结论先行。",
        key="pref:style",
        user_id="u1",
    )
    builder = MemoryContextBuilder(
        store,
        system_prompt="你是一名严谨的研究助手。",
        require_user_scope=True,
    )
    llm = MockLLM([LLMResponse(content="结论先行：ReAct 更适合短任务。")])
    agent = Agent(
        llm,
        ToolRegistry([]),
        config=AgentConfig(system_prompt="这个提示词不应生效"),
        context_builder=builder,
    )

    trajectory = agent.run(
        "调研 ReAct", RunContext(run_id="r1", user_id="u1")
    )

    assert trajectory.final_answer.startswith("结论先行")
    assert trajectory.stop_reason == "final_answer"
    assert "长期记忆" in llm.calls[0][0].content
    assert "结论先行" in llm.calls[0][0].content
    assert "这个提示词不应生效" not in llm.calls[0][0].content


def test_memory_recorder_writes_task_summary_and_supersedes():
    store = InMemoryStore()
    writer = MemoryWriter(store)
    llm = MockLLM(
        [
            LLMResponse(
                content="ReAct 适合短任务。",
                    usage=Usage(prompt_tokens=10, completion_tokens=5),
            ),
            LLMResponse(content="已更新：Plan-and-Execute 适合长任务。"),
        ]
    )
    agent = Agent(llm, ToolRegistry([]))
    recorder = MemoryRecorder(agent, writer, scope="research")

    first = recorder.run(
        "调研 ReAct 与 Plan-and-Execute",
        RunContext(run_id="r1", user_id="u1"),
    )
    second = recorder.run(
        "调研 ReAct 与 Plan-and-Execute",
        RunContext(run_id="r2", user_id="u1"),
    )

    assert first.final_answer and second.final_answer
    results = store.search(
        "调研 ReAct",
        filters={"kind": "episodic", "user_id": "u1"},
    )
    assert len(results) == 1
    assert "任务：调研 ReAct 与 Plan-and-Execute" in results[0].content
    assert "结果：已更新" in results[0].content
    assert results[0].metadata["scope"] == "research"
    assert len(store.all()) == 2


def test_memory_recorder_records_failed_run_with_lower_importance():
    class FailingRunner:
        def run(self, task, ctx=None):
            return Trajectory(
                task=task,
                run_id="r",
                steps=[Step(index=1, thought="LLM error")],
                final_answer=None,
                stop_reason="error",
            )

    store = InMemoryStore()
    writer = MemoryWriter(store)
    recorder = MemoryRecorder(FailingRunner(), writer)

    recorder.run("会失败的任务", RunContext(run_id="r1", user_id="u1"))

    item = store.search("会失败的任务", filters={"kind": "episodic"})[0]
    assert "状态：error" in item.content
    assert item.importance == 0.4


def test_working_memory_evicts_low_importance_first():
    memory = WorkingMemory(max_items=2)
    memory.set("a", "高价值", importance=0.9)
    memory.set("b", "低价值", importance=0.1)
    memory.set("c", "中价值", importance=0.5)

    assert memory.snapshot() == {"a": "高价值", "c": "中价值"}
    assert memory.get("b") is None
    assert "a: 高价值" in memory.render()

    memory.drop("a")
    memory.clear()
    assert memory.render() == ""
