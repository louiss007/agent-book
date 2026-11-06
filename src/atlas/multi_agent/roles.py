from __future__ import annotations

from dataclasses import dataclass

from atlas.agent.loop import Agent, AgentConfig
from atlas.agent.policy import StopPolicy
from atlas.context.base import ContextBuilder
from atlas.llm.base import LLM
from atlas.tools.registry import ToolRegistry


@dataclass(frozen=True)
class RoleSpec:
    """角色是一份契约：目标写在提示词里，可见工具单独声明。"""

    name: str
    system_prompt: str
    tools: tuple[str, ...] | None = None
    temperature: float = 0.0


def build_role_agent(
    llm: LLM,
    tools: ToolRegistry,
    role: RoleSpec,
    *,
    context_builder: ContextBuilder | None = None,
    policy: StopPolicy | None = None,
) -> Agent:
    """按角色裁剪工具集，构造一个独立的 Agent。

    `role.tools=None` 表示继承全部工具；空元组表示该角色不调用工具。
    每个角色拥有独立的消息历史，跨角色的信息只能通过编排器显式交接。
    """

    registry = tools if role.tools is None else tools.subset(role.tools)
    return Agent(
        llm,
        registry,
        config=AgentConfig(
            system_prompt=role.system_prompt,
            temperature=role.temperature,
        ),
        policy=policy,
        context_builder=context_builder,
    )
