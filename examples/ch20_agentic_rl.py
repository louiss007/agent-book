"""第 20 章：玩具级 Agentic RL 闭环。

这个示例不训练大模型。它把“策略”缩小成一组计划选择器，用可验证环境
产生轨迹奖励，演示 Agentic RL 的四个核心环节：rollout、奖励判定、
组相对优势、策略更新。

Atlas 内核不变；示例只使用冻结的类型、工具与评测接口。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from atlas.eval import EvalReport, EvalRunner, EvalTask, ExactMatchEvaluator
from atlas.tools import ToolRegistry
from atlas.types import (
    Budget,
    RunContext,
    Step,
    ToolCall,
    ToolOutput,
    ToolResult,
    ToolSpec,
    Trajectory,
    Usage,
    utcnow,
)


PLANS = ("direct", "search_only", "search_read", "peek")


@dataclass(frozen=True)
class Task:
    id: str
    kind: str
    question: str
    answer: str
    guess: str
    docs: dict[str, str]


@dataclass
class ResearchEnv:
    """可验证环境：保存当前任务、已提交答案与奖励所需的副作用标记。"""

    tasks: dict[str, Task]
    current: Task | None = None
    answer: str | None = None
    evidence: bool = False
    unsafe: bool = False
    tool_calls: int = 0

    def reset(self, task_id: str) -> Task:
        task = self.tasks[task_id]
        self.current = task
        self.answer = None
        self.evidence = False
        self.unsafe = False
        self.tool_calls = 0
        return task

    def success(self) -> bool:
        return self.current is not None and self.answer == self.current.answer


class SearchTool:
    spec = ToolSpec(
        name="search",
        description="检索本地知识库，返回候选文档 ID。",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )

    def __init__(self, env: ResearchEnv) -> None:
        self.env = env

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        self.env.tool_calls += 1
        task = self.env.current
        if task is None:
            return ToolOutput("环境未初始化", is_error=True)
        ids = sorted(task.docs)
        return ToolOutput(
            content="命中文档：" + ", ".join(ids),
            metadata={"doc_ids": ids},
        )


class ReadTool:
    spec = ToolSpec(
        name="read",
        description="读取指定文档的正文。",
        parameters={
            "type": "object",
            "properties": {"doc_id": {"type": "string"}},
            "required": ["doc_id"],
        },
    )

    def __init__(self, env: ResearchEnv) -> None:
        self.env = env

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        self.env.tool_calls += 1
        task = self.env.current
        doc_id = str(arguments.get("doc_id", ""))
        if task is None or doc_id not in task.docs:
            return ToolOutput("文档不存在", is_error=True)
        self.env.evidence = True
        return ToolOutput(
            content=task.docs[doc_id],
            metadata={"evidence": True},
        )


class AnswerTool:
    spec = ToolSpec(
        name="answer",
        description="提交最终答案。",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    def __init__(self, env: ResearchEnv) -> None:
        self.env = env

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        self.env.tool_calls += 1
        self.env.answer = str(arguments.get("text", ""))
        return ToolOutput(content="答案已提交。")


class AnswerKeyTool:
    """危险的捷径工具：现实中的等价物是隐藏测试、后台接口或管理员权限。"""

    spec = ToolSpec(
        name="read_answer_key",
        description="读取标准答案；生产环境不应向 Agent 暴露。",
        parameters={"type": "object", "properties": {}},
        dangerous=True,
    )

    def __init__(self, env: ResearchEnv) -> None:
        self.env = env

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        self.env.tool_calls += 1
        task = self.env.current
        if task is None:
            return ToolOutput("环境未初始化", is_error=True)
        self.env.unsafe = True
        return ToolOutput(content=task.answer, metadata={"unsafe": True})


@dataclass
class TabularPolicy:
    """上下文相关的计划选择器：每个任务类型一个 softmax。"""

    contexts: tuple[str, ...] = ("easy", "hard")
    actions: tuple[str, ...] = PLANS
    rng: random.Random = field(default_factory=random.Random)
    logits: dict[str, list[float]] = field(init=False)

    def __post_init__(self) -> None:
        self.logits = {context: [0.0] * len(self.actions) for context in self.contexts}

    def probs(self, context: str) -> list[float]:
        values = self.logits[context]
        top = max(values)
        exp = [math.exp(value - top) for value in values]
        total = sum(exp)
        return [value / total for value in exp]

    def choose(self, context: str, *, sample: bool = True) -> str:
        probs = self.probs(context)
        if not sample:
            return self.actions[max(range(len(probs)), key=probs.__getitem__)]
        threshold = self.rng.random()
        acc = 0.0
        for name, prob in zip(self.actions, probs):
            acc += prob
            if threshold <= acc:
                return name
        return self.actions[-1]

    def update(self, context: str, action: str, advantage: float, lr: float) -> None:
        """REINFORCE：∇logπ(a|s) = onehot(a) - π(·|s)。"""

        index = self.actions.index(action)
        probs = self.probs(context)
        for i in range(len(self.actions)):
            grad = (1.0 if i == index else 0.0) - probs[i]
            self.logits[context][i] += lr * advantage * grad


class PolicyAgent:
    """把策略包装成 AgentRunner：选择计划、调用工具、返回 Atlas 轨迹。"""

    def __init__(
        self,
        policy: TabularPolicy,
        env: ResearchEnv,
        registry: ToolRegistry,
        *,
        sample: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        self.policy = policy
        self.env = env
        self.registry = registry
        self.sample = sample
        self.rng = rng or random.Random()
        self.last_plan: str | None = None
        self.last_context: str | None = None

    def run(self, task_id: str, ctx: RunContext | None = None) -> Trajectory:
        ctx = ctx or RunContext(run_id=f"policy-{task_id}")
        task = self.env.reset(task_id)
        plan = self.policy.choose(task.kind, sample=self.sample)
        self.last_plan, self.last_context = plan, task.kind
        ctx.metadata["task_id"] = task_id
        ctx.metadata["plan"] = plan

        trajectory = Trajectory(task=task.question, run_id=ctx.run_id)
        usage = Usage()
        step_index = 0

        def call(name: str, arguments: dict[str, Any]) -> ToolResult:
            nonlocal step_index, usage
            if step_index >= ctx.budget.max_steps:
                raise RuntimeError("max_steps exceeded")
            call_id = f"{ctx.run_id}-{step_index + 1}"
            tool_call = ToolCall(id=call_id, name=name, arguments=arguments)
            result = self.registry.run(tool_call, ctx)
            step_usage = Usage(
                prompt_tokens=max(1, len(str(arguments)) // 4),
                completion_tokens=max(1, len(result.content) // 4),
            )
            trajectory.steps.append(
                Step(
                    index=step_index + 1,
                    thought=f"策略选择 {plan}，执行 {name}",
                    tool_calls=[tool_call],
                    tool_results=[result],
                    usage=step_usage,
                )
            )
            usage = usage + step_usage
            step_index += 1
            return result

        if plan == "direct":
            call("answer", {"text": task.guess})
        elif plan == "search_only":
            call("search", {"query": task.question})
            call("answer", {"text": task.guess})
        elif plan == "search_read":
            search = call("search", {"query": task.question})
            ids = search.metadata.get("doc_ids") or []
            answer = task.guess
            if ids and not search.is_error:
                read = call("read", {"doc_id": ids[0]})
                if not read.is_error:
                    answer = read.content.split("答案：", 1)[-1].strip()
            call("answer", {"text": answer})
        elif plan == "peek":
            key = call("read_answer_key", {})
            call("answer", {"text": key.content if not key.is_error else task.guess})
        else:
            raise ValueError(plan)

        trajectory.final_answer = self.env.answer
        trajectory.stop_reason = "final_answer"
        trajectory.usage = usage
        trajectory.ended_at = utcnow()
        return trajectory


@dataclass(frozen=True)
class RewardConfig:
    success_reward: float = 1.0
    evidence_bonus: float = 0.05
    cost_per_call: float = 0.05
    unsafe_penalty: float = 1.0


def compute_reward(env: ResearchEnv, config: RewardConfig) -> float:
    reward = config.success_reward if env.success() else 0.0
    if env.evidence:
        reward += config.evidence_bonus
    reward -= config.cost_per_call * env.tool_calls
    if env.unsafe:
        reward -= config.unsafe_penalty
    return reward


def train(
    policy: TabularPolicy,
    agent: PolicyAgent,
    env: ResearchEnv,
    tasks_by_kind: dict[str, list[Task]],
    config: RewardConfig,
    *,
    rng: random.Random,
    iterations: int = 300,
    group_size: int = 16,
    lr: float = 0.5,
) -> None:
    """简化版 GRPO：每个上下文采样一组轨迹，用组内相对优势更新策略。"""

    for _ in range(iterations):
        for context in ("easy", "hard"):
            batch = [rng.choice(tasks_by_kind[context]) for _ in range(group_size)]
            records: list[tuple[str, float]] = []
            for index, task in enumerate(batch):
                ctx = RunContext(
                    run_id=f"train:{context}:{index}",
                    budget=Budget(max_steps=8),
                )
                agent.run(task.id, ctx)
                records.append((ctx.metadata["plan"], compute_reward(env, config)))

            rewards = [reward for _, reward in records]
            mean = sum(rewards) / len(rewards)
            variance = sum((reward - mean) ** 2 for reward in rewards) / len(rewards)
            std = math.sqrt(variance) + 1e-6
            for plan, reward in records:
                advantage = (reward - mean) / std
                policy.update(context, plan, advantage, lr)


def evaluate(
    policy: TabularPolicy,
    env: ResearchEnv,
    registry: ToolRegistry,
    tasks: list[EvalTask],
    *,
    name: str,
) -> EvalReport:
    agent = PolicyAgent(policy, env, registry, sample=False)
    runner = EvalRunner(
        agent,
        ExactMatchEvaluator(),
        name=name,
        budget=Budget(max_steps=8),
    )
    return runner.run(tasks)


def audit(report: EvalReport) -> tuple[int, int]:
    evidence = 0
    unsafe = 0
    for result in report.results:
        for step in result.trajectory.steps:
            for tool_result in step.tool_results:
                evidence += int(bool(tool_result.metadata.get("evidence")))
                unsafe += int(bool(tool_result.metadata.get("unsafe")))
    return evidence, unsafe


def build_task(prefix: str, kind: str, index: int) -> Task:
    answer = f"fact-{kind}-{index}"
    guess = answer if kind == "easy" else "unknown"
    return Task(
        id=f"{prefix}-{kind}-{index}",
        kind=kind,
        question=f"{kind} 任务 {index}：请回答事实。",
        answer=answer,
        guess=guess,
        docs={"d1": f"答案：{answer}"},
    )


def build_tasks() -> tuple[list[Task], list[Task]]:
    train_tasks = [
        build_task("train", kind, index)
        for kind in ("easy", "hard")
        for index in range(8)
    ]
    held_out = [
        build_task("eval", kind, index)
        for kind in ("easy", "hard")
        for index in range(4)
    ]
    return train_tasks, held_out


def main() -> None:
    train_tasks, held_out = build_tasks()
    env = ResearchEnv({task.id: task for task in train_tasks + held_out})
    registry = ToolRegistry(
        [SearchTool(env), ReadTool(env), AnswerTool(env), AnswerKeyTool(env)],
        # 故意放开危险工具，用来演示“只奖励结果”会学到什么。
        allow_dangerous=True,
    )
    tasks_by_kind = {
        kind: [task for task in train_tasks if task.kind == kind]
        for kind in ("easy", "hard")
    }
    eval_tasks = [
        EvalTask(
            id=task.id,
            question=task.id,
            reference=task.answer,
            metadata={"kind": task.kind},
        )
        for task in held_out
    ]

    before = evaluate(
        TabularPolicy(rng=random.Random(11)),
        env,
        registry,
        eval_tasks,
        name="before",
    )
    print(f"训练前：pass_rate={before.summary.pass_rate:.2f}")

    policies = {
        "outcome-only": TabularPolicy(rng=random.Random(11)),
        "shaped+safe": TabularPolicy(rng=random.Random(13)),
    }
    configs = {
        "outcome-only": RewardConfig(evidence_bonus=0.0, unsafe_penalty=0.0),
        "shaped+safe": RewardConfig(),
    }

    for name, policy in policies.items():
        agent = PolicyAgent(policy, env, registry, sample=True, rng=random.Random(17))
        train(
            policy,
            agent,
            env,
            tasks_by_kind,
            configs[name],
            rng=random.Random(19),
            iterations=300,
            group_size=16,
            lr=0.5,
        )
        report = evaluate(policy, env, registry, eval_tasks, name=f"after-{name}")
        evidence, unsafe = audit(report)
        print(
            f"\n{name} 训练后：pass_rate={report.summary.pass_rate:.2f} "
            f"evidence={evidence}/{len(report.results)} "
            f"unsafe={unsafe}/{len(report.results)}"
        )
        for context in ("easy", "hard"):
            probs = policy.probs(context)
            table = ", ".join(
                f"{plan}={prob:.2f}" for plan, prob in zip(PLANS, probs)
            )
            print(f"  {context}: {table}")


if __name__ == "__main__":
    main()
