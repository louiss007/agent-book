from __future__ import annotations

from atlas.agent.loop import Agent
from atlas.context import (
    BudgetedContextBuilder,
    ContextBudget,
    ContextCompactor,
    ContextStore,
    ExpandContextTool,
    ExtractiveSummarizer,
    ProgressiveDisclosure,
    estimate_tokens,
    message_tokens,
    messages_tokens,
)
from atlas.llm.mock import MockLLM
from atlas.memory import InMemoryStore, MemoryWriter
from atlas.tools import ToolRegistry
from atlas.types import (
    LLMResponse,
    Message,
    RunContext,
    ToolCall,
    ToolOutput,
    ToolSpec,
)


def long_text(size: int = 200, marker: str = "日志") -> str:
    line = "服务超时后重试成功，但延迟仍然偏高；"
    return marker + line * (size // len(line) + 1)


def tool_round(call_id: str, content: str, name: str = "read_log") -> list[Message]:
    return [
        Message(
            role="assistant",
            tool_calls=[ToolCall(id=call_id, name=name, arguments={"path": call_id})],
        ),
        Message(role="tool", content=content, name=name, tool_call_id=call_id),
    ]


def assert_tool_pairs(messages: list[Message]) -> None:
    pending: set[str] = set()
    for message in messages:
        if message.role == "assistant" and message.tool_calls:
            pending.update(call.id for call in message.tool_calls)
        elif message.role == "tool":
            assert message.tool_call_id in pending
            pending.remove(message.tool_call_id)
    assert not pending


def test_token_estimate_handles_cjk_ascii_and_tool_calls():
    assert estimate_tokens(None) == 0
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好世界") == 4
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcdefgh") == 2

    plain = Message(role="user", content="查询")
    with_call = Message(
        role="assistant",
        tool_calls=[ToolCall(id="c1", name="search", arguments={"q": "日志"})],
    )
    assert message_tokens(with_call) > message_tokens(plain)
    assert messages_tokens([plain, with_call]) == (
        message_tokens(plain) + message_tokens(with_call)
    )


def test_context_budget_allocates_and_validates():
    budget = ContextBudget(max_tokens=1000, reserve_tokens=200)

    assert budget.usable_tokens == 800
    assert budget.system_tokens == 160
    assert budget.memory_tokens == 80
    assert budget.history_tokens == 480
    assert budget.evidence_tokens == 80
    assert budget.summary_tokens == 128

    for kwargs in (
        {"max_tokens": 0},
        {"reserve_tokens": -1},
        {"system_ratio": -0.1},
    ):
        try:
            ContextBudget(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")


def test_extractive_summarizer_respects_line_and_token_budgets():
    summarizer = ExtractiveSummarizer(max_lines=2)

    assert summarizer.summarize("", max_tokens=100) == ""
    assert summarizer.summarize("第一行\n第二行\n第三行", max_tokens=100) == (
        "第一行\n第二行\n…"
    )

    oversized = "长" * 200
    summary = summarizer.summarize(oversized, max_tokens=5)
    assert summary.endswith("…")
    assert len(summary) == 81


def test_context_store_is_content_addressed():
    store = ContextStore()

    first = store.put("完整日志内容", label="app.log")
    second = store.put("完整日志内容")
    other = store.put("另一段内容")

    assert first.startswith("ctx-")
    assert first == second
    assert first != other
    assert store.get(first) == "完整日志内容"
    assert store.label(first) == "app.log"
    assert len(store) == 2
    assert first in store


def test_progressive_disclosure_and_expand_tool_round_trip():
    disclosure = ProgressiveDisclosure()
    content = long_text(400)

    preview = disclosure.fold(content, label="app.log", preview_chars=40)

    assert "已折叠 ctx-" in preview
    assert "expand_context" in preview
    assert len(preview) < len(content)
    item_id = disclosure.store.items()[0].item_id

    tool = ExpandContextTool(disclosure.store)
    expanded = tool.run({"item_id": item_id})
    assert not expanded.is_error
    assert expanded.content == content
    assert expanded.metadata["chars"] == len(content)

    missing = tool.run({"item_id": "ctx-missing"})
    assert missing.is_error
    assert missing.metadata["error_type"] == "not_found"


def test_compactor_folds_long_tool_results_but_keeps_pairs():
    history = [Message(role="user", content="分析日志")]
    for index in range(3):
        history.extend(tool_round(f"c{index}", long_text(240, marker=f"第{index}段")))
    budget = ContextBudget(max_tokens=20_000, reserve_tokens=0)
    compactor = ContextCompactor(
        keep_recent=1, max_tool_chars=120, preview_chars=40
    )

    output = compactor.compact(history, budget)

    report = compactor.last_report
    assert report.folded_items == 2
    assert report.summarized_messages == 0
    assert report.after_tokens < report.before_tokens
    assert len(output) == len(history)
    assert sum("已折叠" in (message.content or "") for message in output) == 2
    assert len(compactor.disclosure.store) == 2
    assert_tool_pairs(output)


def test_compactor_summarizes_middle_groups_when_still_over_budget():
    history = [Message(role="user", content="分析日志")]
    for index in range(4):
        history.extend(tool_round(f"c{index}", long_text(180, marker=f"第{index}段")))
    history.extend(tool_round("c9", long_text(80, marker="最新")))
    budget = ContextBudget(max_tokens=300, reserve_tokens=0)
    compactor = ContextCompactor(
        keep_recent=1,
        max_tool_chars=120,
        preview_chars=40,
        summarizer=ExtractiveSummarizer(max_lines=3),
    )

    output = compactor.compact(history, budget)

    report = compactor.last_report
    assert report.summary_used
    assert report.summarized_messages >= 2
    assert any("较早对话摘要" in (message.content or "") for message in output)
    assert_tool_pairs(output)
    assert messages_tokens(output) <= budget.usable_tokens


def test_compactor_drops_middle_groups_without_summarizer():
    history = [Message(role="user", content="分析日志")]
    for index in range(4):
        history.extend(tool_round(f"c{index}", long_text(180, marker=f"第{index}段")))
    history.extend(tool_round("c9", long_text(80, marker="最新")))
    budget = ContextBudget(max_tokens=300, reserve_tokens=0)
    compactor = ContextCompactor(keep_recent=1, max_tool_chars=120)

    output = compactor.compact(history, budget)

    assert compactor.last_report.dropped_messages > 0
    assert not any("较早对话摘要" in (message.content or "") for message in output)
    assert_tool_pairs(output)
    assert messages_tokens(output) <= budget.usable_tokens


def test_compactor_truncates_and_preserves_tool_pairing():
    history = [
        Message(role="user", content="分析日志"),
        *tool_round("c1", "x" * 2000),
    ]
    budget = ContextBudget(max_tokens=100, reserve_tokens=0)
    compactor = ContextCompactor(keep_recent=1, max_tool_chars=120)

    output = compactor.compact(history, budget)

    assert compactor.last_report.truncated_messages >= 1
    assert messages_tokens(output) <= budget.usable_tokens
    assert_tool_pairs(output)
    assert output[-1].role == "tool"


def test_compactor_truncation_terminates_at_minimum_length():
    history = [
        Message(role="user", content="任务"),
        *tool_round("c1", "x" * 41),
    ]
    budget = ContextBudget(max_tokens=10, reserve_tokens=0)
    compactor = ContextCompactor(keep_recent=1, max_tool_chars=120, min_chars=40)

    output = compactor.compact(history, budget)

    assert compactor.last_report.truncated_messages == 0
    assert_tool_pairs(output)
    assert messages_tokens(output) > budget.usable_tokens


def test_budgeted_builder_wraps_inner_builder_and_reports():
    store = InMemoryStore()
    MemoryWriter(store).remember_preference(
        "用户要求结论先行。",
        key="pref:style",
        user_id="u1",
    )
    inner = BudgetedContextBuilder(
        system_prompt="你是研究助手。",
        max_tokens=20_000,
        reserve_tokens=0,
    )
    from atlas.context import MemoryContextBuilder

    builder = BudgetedContextBuilder(
        MemoryContextBuilder(store, system_prompt="你是研究助手。"),
        max_tokens=20_000,
        reserve_tokens=0,
    )
    history = [Message(role="user", content="调研 ReAct")]
    ctx = RunContext(run_id="r1", user_id="u1")

    messages = builder.build("调研 ReAct", history, 0, ctx)

    assert messages[0].role == "system"
    assert "长期记忆" in messages[0].content
    assert builder.last_report.before_tokens > 0
    assert builder.last_report.after_tokens <= builder.last_report.before_tokens

    fallback = inner.build("调研 ReAct", history, 0, RunContext(run_id="r2"))
    assert fallback[0].content == "你是研究助手。"


class LongLogTool:
    spec = ToolSpec(
        name="read_log",
        description="读取服务日志",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )

    def run(self, arguments):
        return ToolOutput(content=long_text(240, marker=arguments["path"]))


def test_agent_runs_with_budgeted_builder_and_expand_tool():
    builder = BudgetedContextBuilder(
        system_prompt="你是日志分析助手。",
        max_tokens=400,
        reserve_tokens=20,
        keep_recent=1,
        max_tool_chars=120,
        preview_chars=40,
        summarizer=ExtractiveSummarizer(max_lines=3),
    )
    script = [
        LLMResponse(
            tool_calls=[ToolCall(id=f"c{i}", name="read_log", arguments={"path": f"p{i}"})]
        )
        for i in range(3)
    ]
    script.append(LLMResponse(content="三个服务都在重试后恢复，延迟仍然偏高。"))
    llm = MockLLM(script)
    agent = Agent(
        llm,
        ToolRegistry([LongLogTool(), builder.expand_tool]),
        context_builder=builder,
    )

    trajectory = agent.run("分析三份日志", RunContext(run_id="r1"))

    assert trajectory.stop_reason == "final_answer"
    assert trajectory.final_answer.startswith("三个服务")
    assert builder.last_report.folded_items >= 1
    assert builder.last_report.saved_tokens > 0
    for call in llm.calls:
        assert_tool_pairs(call)

    item = builder.disclosure.store.items()[0]
    expanded = builder.expand_tool.run({"item_id": item.item_id})
    assert not expanded.is_error
    assert item.content[:20] in expanded.content
