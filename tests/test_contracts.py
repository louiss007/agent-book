import inspect

from atlas.agent.loop import Agent
from atlas.agent.policy import BudgetStopPolicy, StopPolicy
from atlas.llm.base import LLM
from atlas.tools.base import Tool
from atlas.tools.registry import ToolRegistry
from atlas.types import Budget, ToolSpec, Usage


def _params(func):
    return inspect.signature(func).parameters


def test_llm_complete_signature():
    params = _params(LLM.complete)
    assert list(params) == ["self", "messages", "tools", "temperature", "max_tokens"]
    assert params["tools"].default is None
    assert params["temperature"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["temperature"].default == 0.0
    assert params["max_tokens"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["max_tokens"].default is None


def test_tool_signature():
    params = _params(Tool.run)
    assert list(params) == ["self", "arguments"]


def test_tool_registry_signatures():
    assert list(_params(ToolRegistry.run)) == ["self", "call", "ctx"]
    params = _params(ToolRegistry.run_many)
    assert list(params) == ["self", "calls", "ctx", "max_workers"]
    assert params["max_workers"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["max_workers"].default == 4


def test_agent_signatures():
    params = _params(Agent.__init__)
    assert list(params) == [
        "self",
        "llm",
        "tools",
        "config",
        "policy",
        "context_builder",
        "tracer",
        "guards",
        "approval",
    ]
    for name in ("config", "policy", "context_builder", "tracer", "guards", "approval"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert list(_params(Agent.run)) == ["self", "task", "ctx"]


def test_stop_policy_signature():
    assert list(_params(StopPolicy.check)) == ["self", "state"]
    assert list(_params(BudgetStopPolicy.__init__)) == ["self", "budget"]
    assert list(_params(BudgetStopPolicy.check)) == ["self", "state"]


def test_tool_spec_is_frozen():
    spec = ToolSpec(name="x", description="d", parameters={})
    try:
        spec.name = "y"
    except Exception as exc:
        assert type(exc).__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("ToolSpec should be frozen")


def test_usage_adds():
    total = Usage(prompt_tokens=10, completion_tokens=5) + Usage(
        prompt_tokens=20, completion_tokens=7, cached_tokens=3, cost_usd=0.5
    )
    assert total.prompt_tokens == 30
    assert total.completion_tokens == 12
    assert total.cached_tokens == 3
    assert total.cost_usd == 0.5
    assert total.total_tokens == 42


def test_budget_defaults():
    budget = Budget()
    assert budget.max_steps == 20
    assert budget.max_tokens == 100_000
    assert budget.max_cost_usd == 1.0
    assert budget.max_seconds == 300.0
    assert budget.max_tool_calls == 40
