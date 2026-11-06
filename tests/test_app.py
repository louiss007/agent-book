import importlib.util
import json
import sys
from pathlib import Path

import pytest

from atlas.app import AtlasApp, build_app
from atlas.cli import load_knowledge_dir, main
from atlas.config import AtlasConfig
from atlas.context.budgeted import BudgetedContextBuilder
from atlas.demo import DEMO_TASK, demo_knowledge, seed_memory
from atlas.memory.long_term import InMemoryStore
from atlas.memory.recorder import MemoryRecorder
from atlas.types import Budget, Trajectory

_ENV_KEYS = (
    "ATLAS_MODEL",
    "ATLAS_API_KEY",
    "ATLAS_BASE_URL",
    "ATLAS_TEMPERATURE",
    "ATLAS_OFFLINE",
    "ATLAS_MAX_CONTEXT_TOKENS",
    "ATLAS_MAX_STEPS",
    "ATLAS_MAX_TOKENS",
    "ATLAS_MAX_COST_USD",
    "ATLAS_MAX_SECONDS",
    "ATLAS_MAX_TOOL_CALLS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def offline_config() -> AtlasConfig:
    return AtlasConfig(model="mock", offline=True)


def test_config_defaults():
    config = AtlasConfig.from_env()
    assert config.model == "gpt-4o-mini"
    assert config.api_key is None
    assert config.offline is False
    assert config.max_context_tokens == 32_000
    assert config.budget == Budget()


def test_config_reads_env(monkeypatch):
    monkeypatch.setenv("ATLAS_MODEL", "local-model")
    monkeypatch.setenv("ATLAS_API_KEY", "test-key")
    monkeypatch.setenv("ATLAS_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("ATLAS_TEMPERATURE", "0.3")
    monkeypatch.setenv("ATLAS_OFFLINE", "yes")
    monkeypatch.setenv("ATLAS_MAX_CONTEXT_TOKENS", "8000")
    monkeypatch.setenv("ATLAS_MAX_STEPS", "7")
    monkeypatch.setenv("ATLAS_MAX_TOKENS", "9000")
    monkeypatch.setenv("ATLAS_MAX_COST_USD", "0.25")
    monkeypatch.setenv("ATLAS_MAX_SECONDS", "30")
    monkeypatch.setenv("ATLAS_MAX_TOOL_CALLS", "11")

    config = AtlasConfig.from_env()

    assert config.model == "local-model"
    assert config.api_key == "test-key"
    assert config.base_url == "http://localhost:8000/v1"
    assert config.temperature == 0.3
    assert config.offline is True
    assert config.max_context_tokens == 8000
    assert config.budget == Budget(
        max_steps=7,
        max_tokens=9000,
        max_cost_usd=0.25,
        max_seconds=30.0,
        max_tool_calls=11,
    )


def test_config_rejects_bad_boolean(monkeypatch):
    monkeypatch.setenv("ATLAS_OFFLINE", "maybe")
    with pytest.raises(ValueError):
        AtlasConfig.from_env()


def test_offline_app_end_to_end():
    memory = InMemoryStore()
    seed_memory(memory)
    app = build_app(
        offline_config(),
        knowledge=demo_knowledge(),
        memory=memory,
    )

    trajectory = app.run(DEMO_TASK)

    assert isinstance(app, AtlasApp)
    assert isinstance(app.runner, MemoryRecorder)
    assert isinstance(app.context_builder, BudgetedContextBuilder)
    assert isinstance(trajectory, Trajectory)
    assert trajectory.stop_reason == "final_answer"
    assert "[atlas-memory#0]" in trajectory.final_answer
    assert [step.index for step in trajectory.steps] == [1, 2]
    assert trajectory.usage.total_tokens == 968

    assert app.last_report is not None
    assert app.last_report.ok
    assert app.last_report.queries == 1
    assert set(app.last_report.cited) == {
        "atlas-memory#0",
        "atlas-rag#0",
        "atlas-context#0",
    }
    assert len(memory.all()) == 2


def test_app_without_knowledge_adds_no_search_tool():
    app = build_app(offline_config())
    assert app.tools.specs() == []
    assert app.ledger is None


def test_load_knowledge_dir(tmp_path: Path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "a.md").write_text("第一份资料，讲记忆。", encoding="utf-8")
    (tmp_path / "notes" / "b.txt").write_text("第二份资料，讲检索。", encoding="utf-8")
    (tmp_path / "empty.md").write_text("   ", encoding="utf-8")

    knowledge = load_knowledge_dir(tmp_path)

    assert sorted(doc.doc_id for doc in knowledge.chunks) == ["a#0", "notes/b#0"]


def test_load_knowledge_dir_rejects_missing(tmp_path: Path):
    with pytest.raises(ValueError):
        load_knowledge_dir(tmp_path / "missing")


def test_cli_offline_text(capsys):
    assert main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "Atlas · 离线演示" in out
    assert "停止原因：final_answer" in out
    assert "令牌：968" in out
    assert "长期记忆：2 条" in out


def test_cli_offline_json(capsys):
    assert main(["--offline", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stop_reason"] == "final_answer"
    assert payload["steps"] == 2
    assert payload["tool_calls"] == 1
    assert payload["total_tokens"] == 968
    assert payload["unknown_citations"] == []
    assert payload["memory_items"] == 2


def test_cli_requires_task_when_online():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_minimal_example_builds_trajectory():
    path = Path(__file__).resolve().parents[1] / "examples" / "ch12_minimal_agent.py"
    spec = importlib.util.spec_from_file_location("ch12_minimal_agent", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    agent = module.Agent(
        module.ScriptedLLM(module.build_script()),
        module.ToolRegistry([module.Calculator()]),
        system_prompt="需要计算时先调用 calculator。",
    )
    trajectory = agent.run("计算 (128 + 64) * 3。")

    assert trajectory.final_answer == "(128 + 64) * 3 = 576。"
    assert trajectory.stop_reason == "final_answer"
    assert [step.index for step in trajectory.steps] == [1, 2]
    assert trajectory.steps[0].tool_results[0].content == "576"
    assert trajectory.usage.total_tokens == 364
