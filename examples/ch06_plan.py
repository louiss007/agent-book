from __future__ import annotations

import json

from atlas.agent.loop import Agent, AgentConfig
from atlas.llm.mock import MockLLM
from atlas.planning import LLMPlanner, LLMReflector, PlanExecuteAgent
from atlas.tools import ToolRegistry
from atlas.types import LLMResponse, ToolCall, ToolOutput, ToolSpec, Usage

TOKEN_USAGE = Usage(prompt_tokens=120, completion_tokens=40)


def reply(content: str, **kwargs) -> LLMResponse:
    return LLMResponse(content=content, usage=TOKEN_USAGE, **kwargs)


class CorpusSearchTool:
    spec = ToolSpec(
        name="search",
        description=(
            "检索 Atlas 本地语料。输入查询词，返回与 Agent 规划相关的段落。"
            "适合查概念定义与失败模式；不用于实时新闻。"
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    )

    def run(self, arguments):
        query = arguments["query"]
        return ToolOutput(
            content=(
                f"检索“{query}”：ReAct 交替进行推理与行动；"
                "Plan-and-Execute 先生成计划再逐步执行。"
                "前者容易重复调用与目标漂移，后者容易计划过时。"
            )
        )


def main() -> None:
    planner_llm = MockLLM(
        [
            LLMResponse(
                content=json.dumps(
                    {
                        "goal": "对比 ReAct 与 Plan-and-Execute",
                        "steps": [
                            {
                                "id": "1",
                                "description": "检索 ReAct 的机制与常见失败模式",
                            },
                            {
                                "id": "2",
                                "description": "检索 Plan-and-Execute 的机制与常见失败模式",
                            },
                            {
                                "id": "3",
                                "description": "给出两种范式的适用建议",
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        ]
    )
    executor_llm = MockLLM(
        [
            reply(
                "先检索 ReAct 的资料。",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="search",
                        arguments={"query": "ReAct 失败模式"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            reply("ReAct 的常见失败模式是重复调用、目标漂移和过早收敛。"),
            reply("Plan-and-Execute 先规划再执行。"),
            reply(
                "Plan-and-Execute 的失败模式包括计划过时、"
                "步骤过细和重规划成本高。"
            ),
            reply(
                "短任务适合 ReAct，长任务适合 Plan-and-Execute，"
                "并保留重规划与预算上限。"
            ),
        ]
    )
    reflector_llm = MockLLM(
        [
            LLMResponse(content='{"ok": true, "critique": "", "suggestion": ""}'),
            LLMResponse(
                content=(
                    '{"ok": false, "critique": "只说了定义，没有失败模式", '
                    '"suggestion": "补充失败模式与适用边界"}'
                )
            ),
            LLMResponse(content='{"ok": true, "critique": "", "suggestion": ""}'),
            LLMResponse(content='{"ok": true, "critique": "", "suggestion": ""}'),
        ]
    )

    executor = Agent(
        executor_llm,
        ToolRegistry([CorpusSearchTool()]),
        config=AgentConfig(system_prompt="你是一名严谨的研究助手。"),
    )
    agent = PlanExecuteAgent(
        LLMPlanner(planner_llm),
        executor,
        reflector=LLMReflector(reflector_llm),
        max_step_retries=1,
    )
    trajectory = agent.run("对比 ReAct 与 Plan-and-Execute，并给出适用建议。")

    print("plan:")
    for step in agent.last_plan.steps:
        print(f"  {step.id}. {step.description} [{step.status}]")
    for step in trajectory.steps:
        print(f"[step {step.index}] {step.thought}")
    print(f"stop_reason={trajectory.stop_reason}")
    print(f"answer={trajectory.final_answer}")
    print(
        "usage="
        f"{trajectory.usage.total_tokens} tokens, "
        f"tool_calls={sum(len(item.tool_calls) for item in trajectory.steps)}"
    )


if __name__ == "__main__":
    main()
