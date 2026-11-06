from __future__ import annotations

import sys
from pathlib import Path

from atlas.agent.loop import Agent, AgentConfig
from atlas.llm.mock import MockLLM
from atlas.tools.mcp import StdioMCPClient, load_mcp_tools
from atlas.tools.registry import ToolRegistry
from atlas.types import LLMResponse, RunContext, ToolCall

SERVER = Path(__file__).with_name("ch05_mcp_server.py")


def main() -> None:
    client = StdioMCPClient([sys.executable, str(SERVER)], timeout=10)
    try:
        client.initialize()
        tools = load_mcp_tools(client)
        print("tools:", [(tool.spec.name, tool.spec.dangerous) for tool in tools])

        registry = ToolRegistry(tools, allow_dangerous=False)
        llm = MockLLM(
            [
                LLMResponse(
                    content="先统计单词数。",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="word_count",
                            arguments={"text": "Atlas uses tools"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                LLMResponse(content="这段文本有 3 个单词。"),
            ]
        )
        agent = Agent(
            llm,
            registry,
            config=AgentConfig(system_prompt="你是一名严谨的研究助手。"),
        )
        trajectory = agent.run(
            "统计 'Atlas uses tools' 的单词数。",
            RunContext(run_id="demo-ch05"),
        )

        for step in trajectory.steps:
            print(f"[step {step.index}] {step.thought}")
            for call, result in zip(step.tool_calls, step.tool_results):
                print(f"  {call.name}({call.arguments}) -> {result.content}")
        print(f"stop_reason={trajectory.stop_reason}")
        print(f"answer={trajectory.final_answer}")

        denied = registry.run(
            ToolCall(
                id="call_2",
                name="save_note",
                arguments={"title": "周报", "body": "本周完成 v0.5.0。"},
            )
        )
        print(f"denied={denied.is_error} metadata={denied.metadata}")

        allowed_registry = ToolRegistry(tools, allow_dangerous=True)
        saved = allowed_registry.run(
            ToolCall(
                id="call_3",
                name="save_note",
                arguments={"title": "周报", "body": "本周完成 v0.5.0。"},
            )
        )
        print(f"saved={saved.is_error} content={saved.content}")

        resources = client.list_resources()
        print(f"resources={[item['uri'] for item in resources]}")
        handbook = client.read_resource("atlas://handbook")
        print(f"handbook={handbook['contents'][0]['text']}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
