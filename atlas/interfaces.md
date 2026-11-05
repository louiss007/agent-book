# Atlas 接口清单

{% hint style="warning" %}
本页是 Atlas 的"合同"。第 4 章起，这里列出的公开接口不得改名、删除或改变语义；后续章节只能做向后兼容的增量扩展。写代码前先读本页，遇到冲突以本页为准。
{% endhint %}

## 为什么先定接口

Agent 系统最常见的返工不是"模型不够强"，而是**抽象没定好**：第 5 章把工具写成了固定函数，第 7 章发现记忆也要走同一套调用路径；第 9 章想压缩上下文，却发现消息结构里没有足够信息。每改一次底层类型，前面所有示例都要重写。

Atlas 的做法是先把数据类型和协议固定下来，每章只增加实现。这样做有两个好处：

- 读者看到的代码是**累积**的，不是每章重写一遍
- 你能观察到"接口稳定"本身如何降低系统演进成本

## 兼容规则

以下规则在全书范围内生效：

1. **公开符号不重命名、不删除**：模块路径、类名、函数名、字段名一旦出现，后续章节保持不变。
2. **核心方法签名冻结**：
   - `LLM.complete(messages, tools=None, *, temperature=0.0, max_tokens=None)`
   - `Tool.run(arguments)`
   - `ToolRegistry.run(call, ctx=None)` / `run_many(calls, ctx=None, *, max_workers=4)`
   - `AgentRunner.run(task, ctx=None)`
   - `ContextBuilder.build(task, history, step, ctx)`
   - `MemoryStore.add/search/forget/clear`
   - `Retriever.retrieve(query, k=5, filters=None)`
   - `Planner.plan(task, history)`
   - `Guard.before_tool/after_tool`
3. **允许的扩展**：
   - 新增仅关键字、带默认值的参数
   - 在 dataclass 末尾新增带默认值的字段
   - 新增协议实现、子类或独立函数
4. **禁止的修改**：
   - 把可选参数改成必选
   - 改变已有字段的类型或语义
   - 把同步接口改成 `async`
   - 在 `Agent.run` 中改变返回类型
5. **同步内核，异步外壳**：内核保持同步；第 18 章的长任务、并发与重试在 `runtime/` 层包装，不侵入 `Agent` 与 `LLM`。

{% hint style="info" %}
"允许新增关键字参数"看起来像在改接口，但它保持了所有已有调用不变，是语义化版本里的 minor 变更。书中会明确标注每个参数从哪一章开始可用。
{% endhint %}

## 核心数据类型

所有模块共享 `atlas/types.py`。它是整个项目的词汇表。

```python
# atlas/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
MemoryKind = Literal["episodic", "semantic", "procedural", "preference"]
StopReason = Literal[
    "final_answer",
    "max_steps",
    "max_tokens",
    "max_cost",
    "timeout",
    "denied",
    "error",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    dangerous: bool = False


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolOutput:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: Role
    content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length", "error"] = "stop"
    usage: Usage = field(default_factory=Usage)


@dataclass
class Step:
    index: int
    thought: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class Trajectory:
    task: str
    run_id: str
    steps: list[Step] = field(default_factory=list)
    final_answer: str | None = None
    stop_reason: StopReason = "final_answer"
    usage: Usage = field(default_factory=Usage)
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None


@dataclass
class Budget:
    max_steps: int = 20
    max_tokens: int = 100_000
    max_cost_usd: float = 1.0
    max_seconds: float = 300.0
    max_tool_calls: int = 40


@dataclass
class RunContext:
    run_id: str
    budget: Budget = field(default_factory=Budget)
    user_id: str | None = None
    deadline_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

设计说明：

- `ToolOutput` 是工具自身的返回值，`ToolResult` 是注册表补上 `tool_call_id` 后写入轨迹的结果。分开是为了让工具实现不必关心调用 ID。
- `Step.thought` 只有在显式要求模型输出推理摘要时才有值。不要把模型隐藏的推理过程当成日志。
- `Trajectory` 同时记录 `stop_reason` 与 `usage`。评测时这两个字段与最终答案同等重要。
- 所有时间使用 UTC，避免跨时区部署时的比较错误。

## 模型层

```python
# atlas/llm/base.py
from typing import Protocol

from atlas.types import LLMResponse, Message, ToolSpec


class LLM(Protocol):
    model: str

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        ...
```

`OpenAICompatLLM` 负责把内部 `Message` 转成 OpenAI 风格的请求，并把返回的工具调用归一化为 `ToolCall`。`MockLLM` 实现同一协议，用于离线测试。

```python
# 最小可用实现的行为约定
class OpenAICompatLLM:
    model: str
    def __init__(self, model: str, *, api_key: str | None = None,
                 base_url: str | None = None, timeout: float = 60.0) -> None: ...
    def complete(self, messages, tools=None, *, temperature=0.0,
                 max_tokens=None) -> LLMResponse: ...
```

约定：

- 模型不支持原生工具调用时，适配层负责提示词降级与解析，但对上层仍返回 `LLMResponse`
- 网络错误在客户端内部做有限重试；最终失败抛 `LLMError`，由 Agent 转为 `stop_reason="error"`
- `usage` 必须尽量回填；无法获取成本时 `cost_usd=0.0`，由价格表另行计算

## 工具层

```python
# atlas/tools/base.py
from typing import Any, Protocol

from atlas.types import ToolOutput, ToolSpec


class Tool(Protocol):
    spec: ToolSpec

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        ...
```

```python
# atlas/tools/registry.py
from collections.abc import Iterable

from atlas.tools.base import Tool
from atlas.types import RunContext, ToolCall, ToolResult, ToolSpec


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None: ...
    def register(self, tool: Tool) -> None: ...
    def specs(self) -> list[ToolSpec]: ...
    def run(self, call: ToolCall, ctx: RunContext | None = None) -> ToolResult: ...
    def run_many(
        self,
        calls: list[ToolCall],
        ctx: RunContext | None = None,
        *,
        max_workers: int = 4,
    ) -> list[ToolResult]: ...
```

行为约定：

- 工具内部抛出的异常由 `run` 捕获，转换成 `ToolResult(is_error=True)`，不向 Agent 冒泡
- 参数校验失败同样返回错误结果，并在 `metadata["error_type"]` 中标注 `validation`
- `run_many` 只对互不依赖的调用并行；返回顺序与输入顺序一致
- 单个工具的默认超时由工具自己实现；注册表不提供全局超时，避免不同工具语义混淆
- 工具的描述与参数 schema 是模型选工具的唯一依据，必须写清楚"什么时候用、什么时候不用"

第 5 章的 MCP 工具也实现 `Tool` 协议：

```python
class MCPTool:
    spec: ToolSpec
    def __init__(self, server: "MCPClient", remote_name: str) -> None: ...
    def run(self, arguments: dict[str, Any]) -> ToolOutput: ...
```

这样 MCP 只是"工具的来源之一"，不会在 Agent 循环里引入第二套执行路径。

## Agent 与循环

```python
# atlas/agent/runner.py
from typing import Protocol

from atlas.types import RunContext, Trajectory


class AgentRunner(Protocol):
    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory:
        ...
```

任何"能接一个任务并返回轨迹"的对象都满足这个协议：基础循环、Plan-and-Execute、多 Agent 编排器，以及第 11 章的框架适配器。

```python
# atlas/agent/loop.py
from collections.abc import Sequence
from dataclasses import dataclass

from atlas.agent.policy import StopPolicy
from atlas.context.base import ContextBuilder
from atlas.llm.base import LLM
from atlas.safety.base import ApprovalHandler, Guard
from atlas.tools.registry import ToolRegistry
from atlas.trace.base import Tracer
from atlas.types import RunContext, Trajectory


@dataclass
class AgentConfig:
    system_prompt: str
    temperature: float = 0.0
    max_context_tokens: int = 32_000
    parallel_tools: bool = True


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        *,
        config: AgentConfig | None = None,
        policy: StopPolicy | None = None,
        context_builder: ContextBuilder | None = None,
        tracer: Tracer | None = None,
        guards: Sequence[Guard] = (),
        approval: ApprovalHandler | None = None,
    ) -> None: ...

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory: ...
```

各参数的引入章节：

| 参数 | 引入章节 | 缺省行为 |
|---|---|---|
| `config` | 第 4 章 | 使用默认系统提示词与温度 0 |
| `policy` | 第 4 章 | `BudgetStopPolicy(默认预算)` |
| `context_builder` | 第 7 章 | 原样拼接 system + history |
| `tracer` | 第 16 章 | 不记录 |
| `guards` | 第 17 章 | 不拦截 |
| `approval` | 第 17 章 | 拒绝所有 `approve` 请求 |

```python
# atlas/agent/policy.py
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from atlas.types import Budget, LLMResponse, StopReason, Usage


@dataclass
class RunState:
    step: int
    tool_calls: int
    usage: Usage
    started_at: datetime
    now: datetime
    last_response: LLMResponse | None = None


class StopPolicy(Protocol):
    def check(self, state: RunState) -> StopReason | None:
        ...


class BudgetStopPolicy:
    def __init__(self, budget: Budget) -> None: ...
    def check(self, state: RunState) -> StopReason | None: ...
```

`StopPolicy.check` 返回 `None` 表示继续。检查顺序固定为：时间 → 步数 → token → 费用 → 工具调用数。顺序固定是为了让轨迹中的停止原因可复现。

## 上下文与记忆

```python
# atlas/context/base.py
from typing import Protocol

from atlas.types import Message, RunContext


class ContextBuilder(Protocol):
    def build(
        self,
        task: str,
        history: list[Message],
        step: int,
        ctx: RunContext,
    ) -> list[Message]:
        ...
```

`build` 每轮调用一次，返回**本轮要发给模型的完整消息列表**，包含系统提示词。这样上下文策略可以在循环中改变输入，而不只是开头拼一次。

```python
# atlas/memory/base.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from atlas.types import MemoryKind, utcnow


@dataclass
class MemoryItem:
    id: str
    content: str
    kind: MemoryKind = "episodic"
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    last_accessed_at: datetime | None = None


class MemoryStore(Protocol):
    def add(self, item: MemoryItem) -> str: ...
    def search(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryItem]: ...
    def forget(self, item_id: str) -> None: ...
    def clear(self, scope: str | None = None) -> None: ...
```

`MemoryStore` 只负责存取，不负责决定"什么时候写入"。写入时机由 Agent 或 `ContextBuilder` 决定，这是第 7 章讨论的核心问题之一。

## 检索

```python
# atlas/rag/base.py
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Document:
    doc_id: str
    content: str
    source: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class Retriever(Protocol):
    def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[Document]:
        ...
```

`score` 的语义由实现决定（BM25 分数、余弦相似度或重排分数），上层只用它做排序，不跨实现比较绝对值。跨实现比较是 Agent 检索系统里常见的错误。

## 规划与多智能体

```python
# atlas/planning/base.py
from dataclasses import dataclass, field
from typing import Literal, Protocol

from atlas.types import Message

PlanStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class PlanStep:
    id: str
    description: str
    status: PlanStatus = "pending"


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)


class Planner(Protocol):
    def plan(self, task: str, history: list[Message]) -> Plan:
        ...
```

```python
# atlas/multi_agent/orchestrator.py
from atlas.agent.runner import AgentRunner
from atlas.trace.base import Tracer
from atlas.types import RunContext, Trajectory


class Orchestrator:
    def __init__(
        self,
        roles: dict[str, AgentRunner],
        *,
        tracer: Tracer | None = None,
    ) -> None: ...

    def run(self, task: str, ctx: RunContext | None = None) -> Trajectory: ...
```

`roles` 使用 `dict`，顺序即执行或发言顺序。编排器本身也是 `AgentRunner`，因此可以嵌套：一个多 Agent 系统可以作为另一个编排器的子节点。

## 评测、追踪与安全

```python
# atlas/eval/base.py
from dataclasses import dataclass, field
from typing import Any, Protocol

from atlas.types import Trajectory


@dataclass
class EvalTask:
    id: str
    question: str
    reference: str | None = None
    rubric: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    task_id: str
    trajectory: Trajectory
    score: float
    passed: bool
    detail: dict[str, Any] = field(default_factory=dict)


class Evaluator(Protocol):
    def score(self, task: EvalTask, trajectory: Trajectory) -> EvalResult:
        ...
```

```python
# atlas/trace/base.py
from typing import Protocol

from atlas.types import RunContext, Step, Trajectory


class Tracer(Protocol):
    def on_run_start(self, task: str, ctx: RunContext) -> None: ...
    def on_step(self, step: Step, ctx: RunContext) -> None: ...
    def on_run_end(self, trajectory: Trajectory, ctx: RunContext) -> None: ...
```

```python
# atlas/safety/base.py
from dataclasses import dataclass
from typing import Literal, Protocol

from atlas.types import RunContext, ToolCall, ToolResult

GuardAction = Literal["allow", "deny", "approve"]


@dataclass
class GuardDecision:
    action: GuardAction = "allow"
    reason: str = ""
    replacement: ToolResult | None = None


class Guard(Protocol):
    def before_tool(self, call: ToolCall, ctx: RunContext) -> GuardDecision: ...
    def after_tool(self, result: ToolResult, ctx: RunContext) -> GuardDecision: ...


class ApprovalHandler(Protocol):
    def request(self, call: ToolCall, ctx: RunContext, reason: str) -> bool:
        ...
```

行为约定：

- `before_tool` 返回 `deny` 时，Agent 生成一个 `is_error=True` 的工具结果，并在 `metadata["denied"]=True` 中说明；模型可以换一条路径继续
- 返回 `approve` 时，调用 `ApprovalHandler.request`；被拒绝按 `deny` 处理
- `after_tool` 可以返回 `replacement`，用于脱敏、截断或替换工具结果
- 连续拒绝超过阈值（默认 3 次）时，整个运行以 `stop_reason="denied"` 结束，防止模型陷入反复尝试

## 配置与装配

```python
# atlas/config.py
from dataclasses import dataclass, field

from atlas.types import Budget


@dataclass
class AtlasConfig:
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    offline: bool = False
    max_context_tokens: int = 32_000
    budget: Budget = field(default_factory=Budget)

    @classmethod
    def from_env(cls, prefix: str = "ATLAS_") -> "AtlasConfig": ...
```

典型装配：

```python
from atlas.agent import Agent, AgentConfig
from atlas.config import AtlasConfig
from atlas.llm import OpenAICompatLLM
from atlas.tools import FetchURLTool, PythonExecTool, ToolRegistry, WebSearchTool

cfg = AtlasConfig.from_env()

llm = OpenAICompatLLM(
    model=cfg.model,
    api_key=cfg.api_key,
    base_url=cfg.base_url,
)

tools = ToolRegistry([
    WebSearchTool(),
    FetchURLTool(),
    PythonExecTool(timeout=10),
])

agent = Agent(
    llm,
    tools,
    config=AgentConfig(
        system_prompt="你是一名严谨的研究助手。每条结论都必须给出来源。",
        temperature=0.0,
    ),
)

trajectory = agent.run("比较 ReAct 与 Plan-and-Execute 的适用场景")
print(trajectory.final_answer)
print(trajectory.stop_reason, trajectory.usage.total_tokens)
```

## 错误与终止语义

| 情况 | 运行时行为 | `stop_reason` |
|---|---|---|
| 模型给出最终答案 | 正常结束 | `final_answer` |
| 达到最大步数 | 停止，保留最后内容 | `max_steps` |
| 超过 token 预算 | 停止 | `max_tokens` |
| 超过费用预算 | 停止 | `max_cost` |
| 超过时间上限 | 停止 | `timeout` |
| 工具抛异常 | 转为错误结果，继续循环 | 不终止 |
| 护栏拒绝工具调用 | 转为错误结果，模型可改道 | 连续拒绝时 `denied` |
| 审批被拒绝 | 同护栏拒绝 | 连续拒绝时 `denied` |
| LLM 最终调用失败 | 记录错误并结束 | `error` |

这张表是后续评测与可观测章节的基础。第 15 章会按 `stop_reason` 统计失败分布；第 16 章会把每个终止点映射到具体的 Trace 事件。

## 接口与章节对照

| 接口 | 首次定义 | 稳定版本 |
|---|---|---|
| `LLM.complete` | 第 4 章 | v0.4.0 |
| `Tool` / `ToolSpec` / `ToolOutput` | 第 4 章 | v0.4.0 |
| `ToolRegistry.run` | 第 4 章 | v0.4.0 |
| `AgentRunner.run` | 第 4 章 | v0.4.0 |
| `StopPolicy.check` | 第 4 章 | v0.4.0 |
| `Planner.plan` | 第 6 章 | v0.6.0 |
| `MemoryStore` / `MemoryItem` | 第 7 章 | v0.7.0 |
| `ContextBuilder.build` | 第 7 章 | v0.7.0 |
| `Retriever.retrieve` / `Document` | 第 8 章 | v0.8.0 |
| `Orchestrator` | 第 10 章 | v0.10.0 |
| `Evaluator` / `EvalTask` / `EvalResult` | 第 15 章 | v1.1.0 |
| `Tracer` | 第 16 章 | v1.2.0 |
| `Guard` / `GuardDecision` / `ApprovalHandler` | 第 17 章 | v1.3.0 |

## 变更记录

| 版本 | 章节 | 变更 | 兼容性 |
|---|---|---|---|
| v0.4.0 | 4 | 建立 `types`、`LLM`、`Tool`、`Agent`、`StopPolicy` | 基线 |
| v0.5.0 | 5 | 新增 `ToolSpec.dangerous`、`MCPTool`、`run_many`、参数校验 | 向后兼容 |
| v0.6.0 | 6 | 新增 `Planner`、`PlanExecuteAgent` | 向后兼容 |
| v0.7.0 | 7 | 新增 `MemoryStore`、`ContextBuilder` | 向后兼容 |
| v0.8.0 | 8 | 新增 `Retriever`、`AgenticRAG` | 向后兼容 |
| v0.9.0 | 9 | `ContextBuilder` 增加预算、压缩与渐进式披露实现 | 向后兼容 |
| v0.10.0 | 10 | 新增 `Orchestrator` 与角色 Agent | 向后兼容 |
| v0.11.0 | 11 | 新增框架适配器，内核不变 | 向后兼容 |
| v1.0.0 | 12 | CLI 整合，公开接口冻结 | 稳定 |
| v1.1.0 | 15 | 新增评测类型与运行器 | 向后兼容 |
| v1.2.0 | 16 | 新增 `Tracer`、JSONL 记录与回放 | 向后兼容 |
| v1.3.0 | 17 | 新增 `Guard`、`GuardDecision`、`ApprovalHandler` | 向后兼容 |
| v1.4.0 | 18 | 新增 `runtime` 层：工作进程、缓存、重试 | 向后兼容 |

{% hint style="info" %}
第 13、14 章不新增接口；第 19–21 章不修改代码。若后续写作中发现必须改动某个冻结接口，会在本页单独记录"破坏性变更"及迁移方式，而不是悄悄改掉。
{% endhint %}
