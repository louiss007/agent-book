from atlas.agent.loop import Agent
from atlas.llm.mock import MockLLM
from atlas.tools.registry import ToolRegistry
from atlas.types import Budget, LLMResponse, RunContext, ToolCall

from examples.ch04_single_tool import CalculatorTool


def test_budget_stops_before_second_call():
    llm = MockLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="calculator",
                        arguments={"expression": "1+1"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="不该被调用到"),
        ]
    )
    agent = Agent(llm, ToolRegistry([CalculatorTool()]))

    trajectory = agent.run(
        "算一下",
        RunContext(run_id="t-budget", budget=Budget(max_steps=1)),
    )

    assert trajectory.stop_reason == "max_steps"
    assert trajectory.final_answer is None
    assert len(llm.calls) == 1


def test_tool_error_is_returned_to_model():
    llm = MockLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="calculator",
                        arguments={"expression": "1/0"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="除数为零，无法计算。"),
        ]
    )
    trajectory = Agent(llm, ToolRegistry([CalculatorTool()])).run("算一下")

    assert trajectory.steps[0].tool_results[0].is_error is True
    assert trajectory.stop_reason == "final_answer"
