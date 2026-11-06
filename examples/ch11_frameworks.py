"""第 11 章示例：用框架画像做选型，并把外部框架包装成 AgentRunner。

画像字段是教学用的简化模型，不代表官方评测或完整能力清单。
"""

from atlas import (
    ConformanceCase,
    FrameworkProfile,
    Requirements,
    RunContext,
    Trajectory,
    as_agent_runner,
    check_runner,
    select_frameworks,
)

_MATURITY = {"experimental": 0, "stable": 1, "mature": 2}


def profiles() -> list[FrameworkProfile]:
    return [
        FrameworkProfile(
            name="LangGraph",
            kind="code",
            supports=frozenset(
                {
                    "tools",
                    "mcp",
                    "memory",
                    "multi_agent",
                    "durability",
                    "human_in_loop",
                    "streaming",
                    "tracing",
                    "evaluation",
                }
            ),
            strengths=("显式状态图", "检查点与中断恢复", "细粒度控制"),
            constraints=("状态与图结构需要自行设计",),
        ),
        FrameworkProfile(
            name="OpenAI Agents SDK",
            kind="code",
            supports=frozenset(
                {
                    "tools",
                    "mcp",
                    "multi_agent",
                    "guardrails",
                    "streaming",
                    "tracing",
                }
            ),
            strengths=("Agent/Handoff 原语轻量", "内置追踪", "上手快"),
            constraints=("复杂状态与长任务需自行补齐",),
        ),
        FrameworkProfile(
            name="Claude Agent SDK",
            kind="code",
            supports=frozenset(
                {
                    "tools",
                    "mcp",
                    "multi_agent",
                    "human_in_loop",
                    "guardrails",
                    "streaming",
                    "tracing",
                }
            ),
            strengths=("内置 Agent 循环", "子 Agent 与钩子", "工具权限控制"),
            constraints=("与 Claude 生态绑定较深",),
            model_binding="vendor",
        ),
        FrameworkProfile(
            name="Google ADK",
            kind="code",
            supports=frozenset(
                {
                    "tools",
                    "mcp",
                    "multi_agent",
                    "human_in_loop",
                    "streaming",
                    "tracing",
                    "evaluation",
                }
            ),
            strengths=("工作流 Agent 原语", "多语言支持", "部署与评测配套"),
            constraints=("Google Cloud 之外的部署需要额外工作",),
        ),
        FrameworkProfile(
            name="CrewAI",
            kind="code",
            supports=frozenset(
                {
                    "tools",
                    "memory",
                    "multi_agent",
                    "streaming",
                    "tracing",
                }
            ),
            strengths=("角色/任务抽象直观", "Crew 与 Flow 两种编排", "适合快速搭团队"),
            constraints=("复杂控制流仍需 Flows 或自定义代码",),
        ),
        FrameworkProfile(
            name="Microsoft Agent Framework",
            kind="code",
            supports=frozenset(
                {
                    "tools",
                    "mcp",
                    "multi_agent",
                    "durability",
                    "human_in_loop",
                    "guardrails",
                    "streaming",
                    "tracing",
                    "evaluation",
                }
            ),
            strengths=("多语言", "内置多种编排模式", "企业集成"),
            constraints=("生态较新，版本演进快",),
            maturity="experimental",
        ),
        FrameworkProfile(
            name="Dify",
            kind="platform",
            supports=frozenset(
                {"tools", "memory", "low_code", "streaming", "tracing"}
            ),
            strengths=("可视化工作流", "内置 RAG 与模型管理", "可自托管"),
            constraints=("深度定制受平台边界限制",),
        ),
        FrameworkProfile(
            name="Coze",
            kind="platform",
            supports=frozenset(
                {"tools", "memory", "low_code", "streaming"}
            ),
            self_hosted=False,
            strengths=("零代码搭建", "插件与渠道发布", "上手成本低"),
            constraints=("托管服务，深度控制与可移植性有限",),
        ),
    ]


def fake_langgraph(task: str, ctx: RunContext) -> Trajectory:
    return Trajectory(
        task=task,
        run_id=ctx.run_id,
        final_answer=f"[fake-langgraph] {task}",
        stop_reason="final_answer",
    )


def exclusion_reason(
    profile: FrameworkProfile, requirements: Requirements
) -> str | None:
    missing = sorted(profile.missing(requirements.required))
    reasons: list[str] = []
    if missing:
        reasons.append(f"缺少 {', '.join(missing)}")
    if requirements.must_self_host and not profile.self_hosted:
        reasons.append("不可自托管")
    if (
        requirements.must_support_open_models
        and profile.model_binding != "open"
    ):
        reasons.append("绑定供应商模型")
    if _MATURITY[profile.maturity] < _MATURITY[requirements.min_maturity]:
        reasons.append(f"成熟度低于 {requirements.min_maturity}")
    return "；".join(reasons) or None


def show(requirements: Requirements, *, title: str) -> None:
    print(f"\n{title}")
    print(f"  硬约束={sorted(requirements.required)}")
    print(f"  偏好={sorted(requirements.preferred)}")
    print(
        f"  自托管={requirements.must_self_host} "
        f"开放模型={requirements.must_support_open_models} "
        f"最低成熟度={requirements.min_maturity}"
    )

    choices = select_frameworks(profiles(), requirements, limit=3)
    print("  候选顺序：")
    if not choices:
        print("    （无满足硬约束的候选）")
    for rank, choice in enumerate(choices, start=1):
        print(
            f"    {rank}. {choice.profile.name} "
            f"(kind={choice.profile.kind}, score={choice.score})"
        )
        print(f"       理由：{'；'.join(choice.reasons)}")

    print("  被排除：")
    for profile in profiles():
        reason = exclusion_reason(profile, requirements)
        if reason:
            print(f"    {profile.name}: {reason}")


def main() -> None:
    show(
        Requirements(
            required=frozenset({"multi_agent", "human_in_loop"}),
            preferred=frozenset({"tracing", "mcp", "evaluation"}),
            must_self_host=True,
            must_support_open_models=True,
            min_maturity="stable",
        ),
        title="场景一：生产级研究助手（自托管、开放模型、多 Agent）",
    )
    show(
        Requirements(
            required=frozenset({"low_code"}),
            preferred=frozenset({"tools", "streaming"}),
            must_self_host=False,
            must_support_open_models=False,
        ),
        title="场景二：业务人员快速搭原型（低代码优先）",
    )

    runner = as_agent_runner(fake_langgraph, name="langgraph")
    report = check_runner(
        runner,
        [
            ConformanceCase("比较两个 Agent 框架"),
            ConformanceCase("给出选型建议"),
        ],
        name="LangGraph",
    )

    print("\n适配层契约检查：")
    print(f"  runner={report.runner} passed={report.passed}")
    print(f"  checks={report.checks}")
    print(f"  failures={report.failures}")

    first = runner.run("比较两个 Agent 框架", RunContext(run_id="ch11"))
    print("\n包装后的轨迹：")
    print(f"  run_id={first.run_id}")
    print(f"  final_answer={first.final_answer}")
    print(f"  stop_reason={first.stop_reason}")


if __name__ == "__main__":
    main()
