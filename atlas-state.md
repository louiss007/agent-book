# Atlas 状态

## 当前状态

- **当前版本**：v1.4.0（第 18 章）。第 19 章为产品设计章，无代码变更；第 20 章为训练章，同样无内核变更，只新增 `examples/ch20_agentic_rl.py`；第 21 章为未来与全书回顾章，无代码变更；代码版本保持 v1.4.0，178 条测试通过。
- **接口基线**：`atlas/interfaces.md` 的冻结签名未变更；v1.4.0 新增 `atlas.runtime` 运行时层，以实现既有 `LLM.complete(...)` 与 `Tool.run(...)` 协议的包装器提供缓存、路由、重试、幂等、限流、计量与任务队列，`Agent`、`ToolRegistry`、`build_app` 均不需要改动。
- **下一实现版本**：无（全书正文已完成）。第 19–21 章均不新增内核代码；第 20 章只在示例层演示训练闭环，第 21 章不新增可运行代码。
- **兼容性检查**：无破坏性修改；新增 `CachedLLM`、`RoutingLLM`、`RetryingLLM`、`IdempotentTool`、`TokenBucket`、`JobRunner`、`RuntimeMetrics` 等运行时符号；`LLM` 与 `Tool` 协议签名不变；缓存、限流与幂等存储均明确为进程内实现，生产替换不影响上层接口；`Agent.run` 的正常、错误与拒绝路径不变。

## 第 1 章变更

### 新增 / 修改的类与接口

无。本章只引入概念约束，不新增代码。

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| Agent 必须同时具备目标性、运行时决策、行动与观察、停止条件 | v0.4.0 的 `Agent.run` 必须有显式 `StopPolicy`；不接受"无限循环直到模型自己说停" |
| 默认自主性目标是 L2–L3，不默认设计 L4 | Atlas 默认保留人工审批与预算上限；长时程执行只在第 18 章作为可选运行时 |
| 可验证性与产物可审计是一等目标 | `Trajectory` 从 v0.4.0 起记录每一步；研究报告必须保留来源引用 |
| 预算与停止条件从第一天就是必选组件 | `Budget`、`RunContext`、`StopReason` 进入 v0.4.0 的类型基线 |
| 工具是行动空间的边界 | 工具注册表必须声明参数 schema 与 `dangerous` 标记；第 5 章实现 |

## 第 2 章变更

### 新增 / 修改的类与接口

无。本章为历史与概念章，不新增代码，也不修改 `atlas/interfaces.md`。

### 本章对 Atlas 的设计约束

| 历史教训 | 对 Atlas 实现的影响 |
|---|---|
| 符号主义的规划需要显式终止条件 | `StopPolicy` 与 `StopReason` 从 v0.4.0 起就是必选组件，而不是可选项 |
| RL 的回合约束与预算控制 | `Budget` 覆盖步数、令牌、成本、时间与工具调用次数，避免循环失控 |
| 奖励黑客与不可验证目标 | `Evaluator` 与序列化轨迹从早期就为可验证性预留接口；评测不能只看最终答案 |
| LLM 的上下文限制 | `ContextBuilder` 每步重建输入，为第 9 章的压缩与渐进式披露留出位置 |
| 长时程任务需要可审计 | `Tracer`、`Trajectory`、`Step` 记录完整过程，支持回放与根因分析 |
| 开放世界的对抗输入 | `Guard` 与 `ApprovalHandler` 在工具调用前后设卡，第 17 章实现 |
| 四代思想是叠加而非替代 | Atlas 同时保留确定性工作流、模型决策、轨迹评测与运行时约束，不追求"纯 Agent" |

### 兼容性

无接口变更，无破坏性修改。v0.4.0 的基线仍以 `atlas/interfaces.md` 为准。

## 第 3 章变更

### 新增 / 修改的类与接口

无。本章不落代码，不修改 `atlas/interfaces.md`。第 4 章才实现 v0.4.0 基线。

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 模型能力差异必须被适配层吸收 | `OpenAICompatLLM` 负责把不同供应商的响应归一化为 `LLMResponse`；上层只认 `content`、`tool_calls`、`finish_reason`、`usage` |
| 工具调用只产生"提议"，执行权在运行时 | `Agent` 不得把模型返回的参数直接当作已授权动作；`ToolRegistry.run` 负责校验与执行，`Guard` 在前后设卡 |
| 结构化输出失败要可恢复 | 适配层解析失败时返回明确错误或重试一次；不能让半截 JSON 进入 `Step` |
| 上下文增长必须可计量 | `Usage` 与 `Budget.max_tokens` 从 v0.4.0 起生效；`AgentConfig.max_context_tokens` 先作为配置预留，第 9 章启用上下文预算与压缩 |
| 推理模型的隐藏推理不是日志 | `Step.thought` 只记录模型显式输出的推理摘要；不把供应商隐藏的推理链当作可审计内容 |
| 模型选型是配置问题，不是内核问题 | `AtlasConfig.model` 固定模型名；替换模型不改 `Agent` 与 `Tool` 接口 |
| 能力探针是外部诊断工具 | 探针不进入内核；第 15 章可将其改造成 `EvalTask` 与回归测试 |
| 供应商特有参数不得泄漏到核心类型 | 温度、JSON 模式、推理预算等通过适配层参数表达；核心 `Message`/`LLMResponse` 保持中立 |

### 兼容性

无接口变更，无破坏性修改。`LLM.complete`、`Message`、`ToolSpec`、`LLMResponse` 等仍按 `atlas/interfaces.md` 冻结；v0.4.0 实现时不得改变签名。

## 第 4 章变更

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 所有公开类型先冻结再实现 | `types.py` 按 `interfaces.md` 原样落地；后续章节只允许尾部追加默认字段 |
| 模型差异由适配层吸收 | `OpenAICompatLLM` 归一化为 `content`、`tool_calls`、`finish_reason`、`usage` |
| 工具调用只产生"提议"，执行权在运行时 | `ToolRegistry.run` 负责查找、分发与异常转换；参数 schema 校验在第 5 章加入 |
| 工具异常不得冒泡 | 工具失败转为 `ToolResult(is_error=True)`，模型可以改道继续 |
| 循环必须有外部停止 | `BudgetStopPolicy` + `RunContext.budget`；默认预算只是安全护栏 |
| 过程必须可审计 | `Step` / `Trajectory` 记录决策、调用、结果、用量与终止原因 |
| 停止原因必须可复现 | `BudgetStopPolicy` 固定检查顺序：时间 → 步数 → token → 费用 → 工具调用 |
| 后续能力不得改签名 | `context_builder`、`tracer`、`guards`、`approval` 先占位，对应章节替换注解 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| `max_tool_calls` 越界返回 `max_steps` | `StopReason` 枚举没有独立取值 | 第 16 章用追踪事件区分具体原因 |
| `run_many` 暂顺序执行 | `max_workers` 保留但未生效 | 第 5 章并行化，签名不变 |
| 后续协议参数暂用 `Any` | 类型检查暂宽松 | 第 7、16、17 章替换为真实协议 |
| `max_context_tokens`、`parallel_tools` 暂未生效 | 配置项预留 | `parallel_tools` 第 5 章启用；`max_context_tokens` 第 9 章由 `BudgetedContextBuilder` 显式配置，第 12 章统一装配 |
| `OpenAICompatLLM` 新增 `max_retries` | 仅关键字、带默认值 | 向后兼容，保留 |

### 验证

- `PYTHONPATH=src python3 examples/ch04_single_tool.py` 输出与正文一致
- `python3 -m pytest -q`：10 passed
- 契约测试覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`StopPolicy.check` 与 `Budget` 默认值

## v0.4.0 实现清单（第 4 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/types.py` | `Usage`、`ToolSpec`、`ToolCall`、`ToolOutput`、`ToolResult`、`Message`、`LLMResponse`、`Step`、`Trajectory`、`Budget`、`RunContext` |
| `src/atlas/llm/base.py` | `LLM`、`LLMError` |
| `src/atlas/llm/mock.py` | `MockLLM` |
| `src/atlas/llm/openai_compat.py` | `OpenAICompatLLM` |
| `src/atlas/tools/base.py` | `Tool` |
| `src/atlas/tools/registry.py` | `ToolRegistry`（`run`、`run_many`） |
| `src/atlas/agent/policy.py` | `RunState`、`StopPolicy`、`BudgetStopPolicy` |
| `src/atlas/agent/loop.py` | `AgentConfig`、`Agent` |
| `src/atlas/agent/runner.py` | `AgentRunner` |
| `examples/ch04_single_tool.py` | 离线单工具示例 |
| `tests/test_agent_loop.py` | 预算终止、工具错误回填 |
| `tests/test_contracts.py` | 冻结接口与默认值检查 |

{% hint style="success" %}
v0.4.0 已全部落地，`python3 -m pytest -q` 通过；离线示例不需要 API Key。第 5 章在不改变上述签名与字段的前提下，扩展工具校验、并行执行与 MCP。
{% endhint %}

## 第 5 章变更（v0.5.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `ToolRegistry.__init__(..., *, allow_dangerous=False)` | 新增关键字参数 | 向后兼容 |
| `ToolRegistry.run` | 增加 schema 校验、危险工具授权、`error_type` 元数据 | 签名不变 |
| `ToolRegistry.run_many` | 只读调用并行；出现未知/危险工具时整批串行；返回顺序不变 | 签名不变 |
| `AgentConfig.parallel_tools` | 从占位变为生效；`False` 时 `max_workers=1` | 字段不变 |
| `MCPTool` | 新增，实现 `Tool` 协议 | 新增 |
| `StdioMCPClient` | 新增，MCP stdio 传输客户端 | 新增 |
| `MCPError` / `MCPTimeout` | 新增异常 | 新增 |
| `validate_arguments` | 新增 JSON Schema 子集校验函数 | 新增 |
| `load_mcp_tools` / `tool_spec_from_mcp` | 新增 MCP 工具发现与 `ToolSpec` 映射 | 新增 |
| `ToolSpec.dangerous` | 从声明字段变为有运行时语义 | 字段不变，行为增强 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 工具描述与 schema 是模型选择工具的唯一依据 | `ToolSpec.description` 必须写清何时用/不用；`parameters` 使用 JSON Schema 子集 |
| 参数校验在运行时执行，模型输出不可信 | `ToolRegistry.run` 先校验后执行；失败返回 `ToolResult(is_error=True)`，`metadata["error_type"]="validation"` |
| 危险工具默认拒绝 | `ToolSpec.dangerous=True` 且未显式 `allow_dangerous` 时返回 permission 错误；审批留给第 17 章 |
| 并行只用于无副作用调用 | 一批调用中出现未知/危险工具时整批串行；只读调用用线程池；结果保持输入顺序 |
| MCP 只是工具来源之一 | `MCPTool` 实现 `Tool` 协议，Agent Loop 不引入第二套执行路径 |
| MCP 服务器不可信 | 工具注解只作提示；默认把未声明只读的工具视为危险；结果按数据处理，不当作指令 |
| 传输与协议细节隔离在客户端 | `StdioMCPClient` 负责 JSON-RPC、生命周期、分页与请求匹配；上层只看到 `ToolSpec`/`ToolOutput` |
| 错误必须可被模型理解 | 校验、权限、MCP、异常都转换为可读 `ToolResult`；`metadata` 携带 `error_type` 与 `retryable` |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| JSON Schema 只实现常用子集 | 复杂 schema 的约束不会被校验 | 需要时引入完整 `jsonschema` 或供应商严格模式 |
| 危险工具整批串行 | 混合读写调用时并行度下降 | 第 17 章按工具粒度审批与调度 |
| MCP stdio 单连接串行 | 同一服务器的并发调用被锁住 | 第 18 章连接池/多客户端 |
| `allow_dangerous` 是粗粒度开关 | 无法区分审批范围 | 第 17 章 `ApprovalHandler` 与 `Guard` |
| MCP 注解是提示，不是保证 | 恶意服务器可谎报只读 | 第 17 章沙箱与权限最小化 |
| 示例服务器无认证、无沙箱 | 仅用于教学 | 第 17–18 章生产化 |

### 验证

- `PYTHONPATH=src python3 examples/ch05_mcp.py` 输出与正文 5.5.7 一致
- `python3 -m pytest -q`：17 passed（原有 10 条 + 新增 7 条）
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`StopPolicy.check` 与 `Budget` 默认值

### v0.5.0 实现清单（第 5 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/tools/schema.py` | JSON Schema 子集校验 |
| `src/atlas/tools/registry.py` | 参数校验、危险工具授权、并行 `run_many` |
| `src/atlas/tools/mcp.py` | `StdioMCPClient`、`MCPTool`、工具发现与内容渲染 |
| `src/atlas/agent/loop.py` | 接入 `AgentConfig.parallel_tools` |
| `src/atlas/tools/__init__.py` | 导出 MCP 与校验符号 |
| `examples/ch05_mcp_server.py` | 最小 stdio MCP 服务器 |
| `examples/ch05_mcp.py` | 离线端到端示例 |
| `tests/test_tools.py` | 校验、权限、并行与顺序测试 |
| `tests/test_mcp.py` | 初始化、工具列表、调用、错误与注解映射测试 |

{% hint style="success" %}
v0.5.0 代码已按本章清单写入仓库并验证（17 passed），未改动任何 v0.4.0 冻结签名。
{% endhint %}

## 第 6 章变更（v0.6.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `Plan` / `PlanStep` / `PlanStatus` | 新增，计划的数据结构与状态 | 新增 |
| `Planner` | 新增协议，`plan(task, history)` 与接口清单一致 | 新增 |
| `LLMPlanner` | 新增，调用 LLM 生成并解析计划 | 新增 |
| `PlanParseError` | 新增，计划解析失败异常 | 新增 |
| `StaticPlanner` | 新增，测试与离线演示用的预设计划 | 新增 |
| `Reflection` / `Reflector` | 新增，反思结果与反思器协议 | 新增 |
| `LLMReflector` | 新增，调用 LLM 生成结构化反思 | 新增 |
| `PlanExecuteAgent` | 新增，实现 `AgentRunner`，组合规划与执行 | 新增 |
| `atlas.planning` 导出 | 新增模块导出 | 新增 |
| `atlas` 顶层导出 | 新增 `Plan`、`PlanStep`、`Planner`、`PlanExecuteAgent` 等 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 计划必须是数据，不是散文 | `Plan`/`PlanStep` 进入类型基线；步骤有 `pending/running/done/failed` 状态 |
| 规划器与执行器分离 | `Planner` 只生成计划；`PlanExecuteAgent` 负责调度、反思与重规划 |
| 不改 `Agent` 与冻结接口 | `PlanExecuteAgent` 实现 `AgentRunner`，组合现有 `Agent`，不新增 `Agent` 参数 |
| 计划输出不可信 | `parse_plan` 剥离代码块、校验字段、限制步数；失败退化为单步计划 |
| 反思不能阻断主流程 | 反思解析失败默认放行，但把原因写入 `critique` 与轨迹 |
| 重试与重规划有上限 | `max_step_retries`、`max_replans` 是构造参数；超限以 `error` 结束 |
| 预算跨步骤共享 | 子运行获得剩余预算；父级累计所有尝试的用量 |
| 结果必须可追溯 | 每个计划步骤写入父轨迹，聚合工具调用、结果与用量 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 只统计执行器用量 | 规划与反思调用未进入 `Trajectory.usage` | 在 `LLM` 适配层统一计量，或扩展 `Planner`/`Reflector` 的用量字段 |
| 顺序执行计划步骤 | 无法利用可并行子任务 | 第 10 章多 Agent，或后续 DAG 执行器 |
| 重规划可能重复已完成工作 | 依赖规划器理解历史摘要 | 在计划中显式传递已完成步骤的产出 ID |
| 反思解析失败默认放行 | 可能漏过质量问题 | 高可靠场景改为 fail-closed 或引入外部验证器 |
| 综合只是拼接 | 缺少跨步骤压缩与统一文风 | 第 9 章上下文工程、第 12 章完整实现 |
| `Plan` 状态可变 | 不能跨运行复用同一实例 | 运行前复制，或把状态放入独立存储 |

### 验证

- `PYTHONPATH=src python3 examples/ch06_plan.py` 输出与正文 6.8.6 一致
- `python3 -m pytest -q`：25 passed（原有 17 条 + 新增 8 条）
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`StopPolicy.check` 与 `Budget` 默认值

### v0.6.0 实现清单（第 6 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/planning/base.py` | `PlanStatus`、`PlanStep`、`Plan`、`Planner` |
| `src/atlas/planning/planner.py` | `LLMPlanner`、`StaticPlanner`、`parse_plan`、`PlanParseError` |
| `src/atlas/planning/reflect.py` | `Reflection`、`Reflector`、`LLMReflector`、`parse_reflection` |
| `src/atlas/planning/plan_execute.py` | `PlanExecuteAgent`、预算共享、重试、重规划、综合 |
| `src/atlas/planning/__init__.py` | 模块导出 |
| `examples/ch06_plan.py` | 三步研究任务，含反思重试 |
| `tests/test_planning.py` | 计划解析、反思、重试、重规划、预算测试 |

{% hint style="success" %}
v0.6.0 代码已按本章清单写入仓库并验证（25 passed），未改动任何 v0.5.0 冻结签名。
{% endhint %}

## 第 7 章变更（v0.7.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `MemoryKind` | 在 `types.py` 中新增，取值与接口清单一致 | 新增 |
| `MemoryItem` | 新增，记忆条目数据结构 | 新增 |
| `MemoryStore` | 新增，`add/search/forget/clear` 协议 | 新增 |
| `WorkingMemory` | 新增，有容量上限的工作记忆便签 | 新增 |
| `InMemoryStore` | 新增，标准库实现的记忆存储与遗忘 | 新增 |
| `MemoryWriter` | 新增，写入闸门、脱敏、去重、冲突替换 | 新增 |
| `redact_secrets` | 新增，密钥脱敏函数 | 新增 |
| `MemoryRecorder` | 新增，实现 `AgentRunner`，任务结束后写回 | 新增 |
| `ContextBuilder` | 新增协议，`build(task, history, step, ctx)` | 新增 |
| `MemoryContextBuilder` | 新增，偏好检索、通用检索、预算截断与格式化 | 新增 |
| `Agent.run` | 启用已有 `context_builder` 参数；缺省行为不变 | 签名不变 |
| `atlas` 顶层导出 | 新增记忆与上下文相关符号 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 记忆存储只负责存取 | `MemoryStore` 不决定写入时机；`MemoryWriter`/`MemoryRecorder` 决定何时写 |
| 写入必须先过闸门 | 重要性、稳定性、来源、敏感性与重复性检查；低价值信息不进入长期记忆 |
| 敏感信息不得明文持久化 | `MemoryWriter` 在写入前脱敏；生产还需 PII 识别、加密与访问控制 |
| 同一键的冲突必须可审计 | 旧条目标记 `superseded`，新条目记录 `superseded_by`，默认检索排除旧条目 |
| 作用域过滤是安全底线 | `MemoryContextBuilder` 按 `user_id`/`scope` 过滤；多用户场景可设 `require_user_scope=True` |
| 检索先过滤后排序 | `InMemoryStore` 先匹配 `kind`、时间与元数据，再计算相关性、重要性与时间分数 |
| 偏好需要独立检索槽位 | `preference_slots` 预留位置，避免偏好被通用结果挤出 |
| 记忆块是数据，不是指令 | 渲染时明确标注“只作为事实参考”；高风险场景仍需第 17 章护栏 |
| `ContextBuilder` 拥有系统消息 | 传入 builder 时 `AgentConfig.system_prompt` 不再生效，避免双重拼接 |
| 遗忘是一等能力 | `prune` 支持 TTL、保留分数与容量上限；逻辑失效与物理删除分离 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| `InMemoryStore` 不持久化 | 进程退出后记忆丢失 | 第 18 章持久化存储与索引 |
| 词法检索不理解同义改写 | 改写查询可能召回不到 | 第 8 章向量检索与混合检索 |
| 无相关性阈值与重排 | 高重要性但无关的记忆可能进入上下文 | 生产增加阈值、置信度过滤与重排 |
| 记忆块放在系统消息 | 提高遵守度，也提高注入风险 | 第 17 章来源信任、护栏与审批 |
| 只在任务结束后写入 | 运行中途的关键发现可能丢失 | 增加显式记忆工具，带权限与审批 |
| 无自动巩固 | 情景记忆持续增长 | 离线巩固任务，保留来源链 |
| 过滤依赖 `metadata` 约定 | 不同存储实现容易不一致 | 生产把作用域、来源、失效时间显式建模 |
| 写失败任务摘要 | 可能积累噪音 | 按任务类型与预算调整闸门 |

### 验证

- `PYTHONPATH=src python3 examples/ch07_memory.py` 输出与正文 7.9.8 一致
- `python3 -m pytest -q`：36 passed（原有 25 条 + 新增 11 条）
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`StopPolicy.check` 与 `Budget` 默认值

### v0.7.0 实现清单（第 7 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/types.py` | `MemoryKind` |
| `src/atlas/memory/base.py` | `MemoryItem`、`MemoryStore` |
| `src/atlas/memory/short_term.py` | `WorkingMemory` |
| `src/atlas/memory/long_term.py` | `InMemoryStore`、`retention`、`prune` |
| `src/atlas/memory/writer.py` | `MemoryWriter`、`redact_secrets`、去重与冲突替换 |
| `src/atlas/memory/recorder.py` | `MemoryRecorder` |
| `src/atlas/memory/__init__.py` | 模块导出 |
| `src/atlas/context/base.py` | `ContextBuilder` 协议 |
| `src/atlas/context/builder.py` | `MemoryContextBuilder` |
| `src/atlas/context/__init__.py` | 模块导出 |
| `src/atlas/agent/loop.py` | 启用 `context_builder`，默认拼接行为不变 |
| `src/atlas/__init__.py` | 导出记忆与上下文符号，版本改为 0.7.0 |
| `examples/ch07_memory.py` | 写入、检索、遗忘与工作记忆示例 |
| `tests/test_memory.py` | 存储、过滤、排序、TTL、容量、写入、脱敏、上下文、Agent 接入测试 |

{% hint style="success" %}
v0.7.0 代码已按本章清单写入仓库并验证（36 passed），未改动任何 v0.6.0 冻结签名。
{% endhint %}

## 第 8 章变更（v0.8.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `Document` | 新增，检索结果与分块的数据结构 | 按 `interfaces.md` 落地 |
| `Retriever` | 新增，`retrieve(query, k=5, filters=None)` 协议 | 按 `interfaces.md` 落地 |
| `chunk_text` | 新增，按边界优先与重叠窗口切分文本 | 新增 |
| `make_chunks` | 新增，生成 `doc_id#index` 稳定引用 ID | 新增 |
| `tokenize` | 新增，英文按词、中文按二元组切分 | 新增 |
| `BM25Retriever` | 新增，词法检索基线 | 新增 |
| `Embedder` / `HashingEmbedder` | 新增，嵌入协议与离线哈希词袋实现 | 新增 |
| `VectorRetriever` | 新增，余弦相似度检索 | 新增 |
| `HybridRetriever` | 新增，RRF 合并多路检索 | 新增 |
| `KnowledgeBase` | 新增，文档累积、自动分块与混合检索 | 新增 |
| `KnowledgeSearchTool` | 新增，检索工具，含引用渲染、重复查询与预算限制 | 新增 |
| `EvidenceLedger` | 新增，记录本轮证据并校验引用存在性 | 新增 |
| `CitationReport` | 新增，引用审计结果 | 新增 |
| `extract_citations` / `verify_citations` | 新增，引用提取与校验函数 | 新增 |
| `AgenticRAG` | 新增，实现 `AgentRunner`，在循环外做引用审计 | 新增 |
| `Agent` | 未修改 | 签名与默认行为不变 |
| `atlas` 顶层导出 | 新增检索与 Agentic RAG 相关符号 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 检索器只返回 `Document` | 上层不依赖 BM25、向量或混合实现的具体类型 |
| 分数不可跨实现比较 | 混合检索使用 RRF 名次融合，不把不同量纲的分数相加 |
| 引用 ID 必须稳定 | 分块 ID 使用 `doc_id#index`，重排不改变 ID |
| 过滤先于排序 | 权限、租户、时效过滤由服务端注入，不能依赖提示词 |
| 预算由运行时强制 | `KnowledgeSearchTool` 限制重复查询、最大检索次数与返回字符 |
| 证据与检索分离 | `EvidenceLedger` 只记录结果与引用校验，不负责召回 |
| AgenticRAG 不改循环 | 通过组合 `AgentRunner` 实现，`Agent.run` 保持冻结 |
| 不强制检索 | 简单问题可直答；证据要求由调用方通过 `require_citations` 配置 |
| 引用校验只做存在性 | 支持性、来源性与一致性留给后续评测与安全章节 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 哈希嵌入不是语义嵌入 | 无法演示同义改写召回 | 生产替换为真实嵌入模型 |
| 内存索引全量重建 | 文档多时构建慢 | 第 18 章增量索引与持久化 |
| 无重排器 | 候选噪声大时精度有限 | 增加交叉编码器或模型重排 |
| 引用只做存在性检查 | 发现伪造引用，发现不了过度结论 | 第 15 章有据性评测、第 17 章来源信任 |
| 无台账时预算按工具实例计数 | 多工具共享预算需额外封装 | 第 18 章统一运行时预算 |
| 分块不解析表格与代码 | 结构化文档可能切坏 | 引入结构感知解析与父子块 |

### 验证

- `PYTHONPATH=src python3 examples/ch08_rag.py` 输出与正文 8.8.6 一致
- `python3 -m pytest -q`：51 passed（原有 36 条 + 新增 15 条）
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`StopPolicy.check` 与 `Budget` 默认值；`Document`/`Retriever` 按 `interfaces.md` 原签名实现

### v0.8.0 实现清单（第 8 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/rag/base.py` | `Document`、`Retriever` |
| `src/atlas/rag/text.py` | `tokenize` |
| `src/atlas/rag/filters.py` | 元数据、来源与文档 ID 过滤 |
| `src/atlas/rag/chunking.py` | `chunk_text`、`make_chunks` |
| `src/atlas/rag/bm25.py` | `BM25Retriever` |
| `src/atlas/rag/vector.py` | `Embedder`、`HashingEmbedder`、`VectorRetriever` |
| `src/atlas/rag/hybrid.py` | `HybridRetriever`、`KnowledgeBase` |
| `src/atlas/rag/evidence.py` | `EvidenceLedger`、`CitationReport`、引用提取与校验 |
| `src/atlas/rag/tool.py` | `KnowledgeSearchTool`、重复查询与预算限制 |
| `src/atlas/rag/agentic.py` | `AgenticRAG` |
| `src/atlas/rag/__init__.py` | 模块导出 |
| `src/atlas/__init__.py` | 导出检索符号，版本改为 0.8.0 |
| `pyproject.toml` | 版本改为 0.8.0 |
| `examples/ch08_rag.py` | 混合检索、多跳问答、引用审计示例 |
| `tests/test_rag.py` | 分块、BM25、过滤、向量、RRF、知识库、工具预算与台账重置、证据台账、AgenticRAG、多跳接入测试 |

{% hint style="success" %}
v0.8.0 代码已按本章清单写入仓库并验证（51 passed），未改动任何 v0.7.0 冻结签名。
{% endhint %}

## 第 9 章变更（v0.9.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `estimate_tokens` | 新增，与分词器无关的轻量令牌估算 | 新增 |
| `message_tokens` / `messages_tokens` | 新增，消息与消息列表的令牌估算 | 新增 |
| `ContextBudget` | 新增，系统、记忆、历史、证据与预留的比例预算 | 新增 |
| `ContextReport` | 新增，压缩前后令牌与折叠、摘要、丢弃、截断计数 | 新增 |
| `Summarizer` | 新增，摘要协议 `summarize(text, *, max_tokens)` | 新增 |
| `ExtractiveSummarizer` | 新增，按行选择的离线抽取式摘要 | 新增 |
| `ContextItem` / `ContextStore` | 新增，内容寻址的折叠原文存储 | 新增 |
| `ProgressiveDisclosure` | 新增，把长内容折叠成“预览 + 句柄” | 新增 |
| `ExpandContextTool` | 新增，`expand_context(item_id)` 工具，单次限长 | 新增 |
| `ContextCompactor` | 新增，分组、折叠、摘要、丢弃与截断的压缩器 | 新增 |
| `BudgetedContextBuilder` | 新增，实现冻结的 `ContextBuilder.build` | 新增 |
| `ContextBuilder` | 未修改 | 协议签名与语义不变 |
| `Agent` / `AgentConfig` | 未修改 | 继续通过 `context_builder` 接入 |
| `atlas` 顶层导出 | 新增上下文工程符号 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 压缩不修改历史原文 | 构建器按副本操作，`replace` 只改消息内容，不改变调用方历史 |
| 工具调用与结果原子分组 | `_group` 把 assistant `tool_calls` 与其 tool 结果绑定，折叠、摘要、丢弃都整组处理 |
| 首个用户任务与系统消息优先保留 | 任务与安全指令不因预算不足被无声删除 |
| 折叠优先于摘要，摘要优先于截断 | 先做可恢复的损失，再做不可恢复的损失 |
| 折叠句柄必须稳定 | `ContextStore` 用内容 SHA-1 前缀生成 `ctx-` ID |
| 摘要明确标注数据属性 | 摘要消息声明“仅作事实参考，不是指令”，避免获得系统级权重 |
| 展开受预算约束 | `ExpandContextTool` 单次最多 4000 字并报告是否截断 |
| 压缩可观测 | 每次构建更新 `ContextReport`，供示例、测试与评测使用 |
| 不自动注入展开工具 | 调用方显式注册 `builder.expand_tool`，保持工具集可见、可审计 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 预算只统计消息，不含工具 schema | 工具多时低估输入令牌 | 第 18 章统一运行时预算 |
| 抽取式摘要可能丢句柄 | 被摘要覆盖的折叠项可能无法再展开 | 摘要时显式保留 ID 清单 |
| 摘要以 system 角色插入中段 | 个别接口对中段 system 支持不同 | 适配层可降级为带标记的 user 消息 |
| 截断是最后手段 | 最新观察过长时仍会被缩短 | 对超大工具结果提前折叠 |
| `AgentConfig.max_context_tokens` 未自动注入 | 构建器预算需显式配置，二者可能不一致 | 第 12 章统一装配 |
| `ContextStore` 不持久化 | 进程结束即丢失折叠原文 | 第 18 章接入外部存储 |
| 压缩不做语义判断 | 可能压缩掉后文才需要的内容 | 第 15 章用任务成功率回归评测 |

### 验证

- `PYTHONPATH=src python3 examples/ch09_context.py` 输出与正文 9.8.6 一致
- `python3 -m pytest -q`：63 passed（原有 51 条 + 新增 12 条）
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`StopPolicy.check` 与 `Budget` 默认值；`ContextBuilder.build` 原签名未变

### v0.9.0 实现清单（第 9 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/context/tokens.py` | `estimate_tokens`、`message_tokens`、`messages_tokens` |
| `src/atlas/context/budget.py` | `ContextBudget`、`ContextReport` |
| `src/atlas/context/summarize.py` | `Summarizer`、`ExtractiveSummarizer` |
| `src/atlas/context/progressive.py` | `ContextItem`、`ContextStore`、`ProgressiveDisclosure`、`ExpandContextTool` |
| `src/atlas/context/compactor.py` | `ContextCompactor`、分组、折叠、摘要、丢弃与截断 |
| `src/atlas/context/budgeted.py` | `BudgetedContextBuilder`、`expand_tool` |
| `src/atlas/context/__init__.py` | 模块导出 |
| `src/atlas/__init__.py` | 导出上下文工程符号，版本改为 0.9.0 |
| `pyproject.toml` | 版本改为 0.9.0 |
| `examples/ch09_context.py` | 预算、折叠、摘要、配对检查与按需展开示例 |
| `tests/test_context_engineering.py` | 令牌估算、预算、摘要、存储、折叠展开、压缩路径、构建器包装与 Agent 集成测试 |

{% hint style="success" %}
v0.9.0 代码已按本章清单写入仓库并验证（63 passed），未改动任何 v0.8.0 冻结签名。
{% endhint %}

## 第 10 章变更（v0.10.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `BoardEntry` | 新增，黑板条目：`key`、`value`、`author`、`run_id`、`version`、`created_at`、`metadata` | 新增 |
| `SharedBoard` | 新增，按 `(run_id, key)` 分区、追加版本、线程安全的共享黑板 | 新增 |
| `RoleSpec` | 新增，角色契约：名称、系统提示词、工具白名单、温度 | 新增；与 `types.Role`（消息角色 `Literal`）区分命名 |
| `build_role_agent` | 新增，用 `RoleSpec` 裁剪工具并构造 `Agent` | 新增 |
| `ToolRegistry.subset` | 新增，按名称复制出工具子集；未知名称抛 `KeyError` | 向后兼容 |
| `Strategy` | 新增，`Literal["pipeline", "supervisor", "debate", "chat"]` | 新增 |
| `Supervisor` / `ScriptedSupervisor` / `LLMSupervisor` | 新增，编排决策协议与离线、模型两种实现 | 新增 |
| `Orchestrator` | 新增，实现 `AgentRunner`，用 `strategy` 覆盖四种协作模式，支持嵌套 | 按 `interfaces.md` 的冻结签名实现，新增参数均为仅关键字带默认值 |
| `Synthesizer` | 新增，合并多角色产物的回调类型 | 新增 |
| `atlas` 顶层导出 | 新增多智能体符号 | 向后兼容；`atlas.Role` 仍为消息角色 `Literal` |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 编排器本身必须是 `AgentRunner` | `Orchestrator` 可嵌套为其他编排器的角色，测试覆盖 `[team] [x]` 轨迹前缀 |
| 角色顺序即执行/发言顺序 | `roles` 使用有序 `dict`，不额外引入排序字段 |
| 角色上下文必须命名空间化 | 子上下文 `run_id = f"{parent}:{role}"`，`metadata` 注入 `parent_run_id`、`role`、`strategy` |
| 子角色共享父预算 | `_child_context` 用父预算减已用步数、令牌、费用、时间与工具调用数 |
| 预算检查先于角色执行 | 每个角色开始前用 `BudgetStopPolicy` 检查，超限时携带当前最佳答案返回 |
| 失败必须隔离且可见 | 默认 `continue_on_error=True`；失败写入 `error/{role}` 黑板条目；关闭时立即返回子轨迹的停止原因 |
| 轨迹必须可归因 | 子步骤加 `[role]` 前缀合并，`usage` 逐角色累加 |
| 共享状态必须按运行隔离 | 黑板以 `(run_id, key)` 为分区，读取与渲染默认带 `run_id`，避免旧运行污染提示 |
| 黑板写入只追加 | 同 key 重复写入生成新版本，保留作者与时间，支持冲突回溯 |
| 工具权限是运行时事实 | 角色通过 `ToolRegistry.subset` 获得裁剪后的注册表；`tools=()` 表示无工具，`None` 表示继承全部 |
| 辩论与群聊必须有轮次上限 | `max_rounds` 默认 2；群聊额外以 `FINAL:` 标记收敛 |
| 编排决策不得绕过角色白名单 | `Supervisor.choose` 返回未知角色时记为失败并终止，不能动态执行任意角色 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 角色串行执行 | 未利用可并行的子任务，延迟高于理论值 | 第 18 章加入并行调度；`Orchestrator` 签名不变 |
| 上游产物按 1200 字截断注入 | 超长产物需要下游再次检索 | 引入黑板句柄与按需展开，与第 9 章折叠机制对接 |
| 共享黑板仅在内存 | 进程结束即丢失，跨进程不可见 | 第 18 章持久化；跨进程协作由 A2A 承担 |
| `LLMSupervisor` 解析失败退回第一个可用角色 | 决策质量不稳定但保证可继续 | 第 15 章用评测集校准编排策略 |
| 子上下文预算为执行前快照 | 并行角色会重复分配同一份剩余预算 | 并行调度时改为原子扣减 |
| 群聊以字符串标记收敛 | 模型可能永不输出 `FINAL:`，只能靠轮次上限终止 | 引入结构化收敛信号 |
| 裁判不复核证据 | 辩论结论仍可能建立在错误前提上 | 第 15、17 章加入证据校验与来源信任 |
| 无远程调用与身份认证 | v0.10.0 只在进程内编排 | A2A 客户端/服务端与认证留作后续扩展 |

### 验证

- `PYTHONPATH=src python3 examples/ch10_multi_agent.py` 输出与正文 10.6.5 一致；流水线总令牌 1210，`writer` 输入含上游证据但不含原始检索记录
- `python3 -m pytest -q`：78 passed（原有 63 条 + 新增 15 条）
- 新增测试覆盖：黑板版本与运行隔离、工具子集与未知工具、角色提示词与工具裁剪、空工具角色、流水线顺序与交接、失败继续/终止、全局预算、supervisor 决策、`LLMSupervisor` 解析与回退、辩论与裁判、群聊 `FINAL` 收敛、子上下文命名与剩余预算、编排器嵌套、合成器
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`ContextBuilder.build`、`StopPolicy.check` 与 `Budget` 默认值

### v0.10.0 实现清单（第 10 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/multi_agent/board.py` | `BoardEntry`、`SharedBoard`、版本化写入、渲染与按运行清理 |
| `src/atlas/multi_agent/roles.py` | `RoleSpec`、`build_role_agent`、工具白名单裁剪 |
| `src/atlas/multi_agent/orchestrator.py` | `Orchestrator`、`Supervisor`、`ScriptedSupervisor`、`LLMSupervisor`、四种策略、预算共享、失败隔离与轨迹合并 |
| `src/atlas/multi_agent/__init__.py` | 模块导出 |
| `src/atlas/tools/registry.py` | 追加 `subset` |
| `src/atlas/__init__.py` | 导出多智能体符号，版本改为 0.10.0 |
| `pyproject.toml` | 版本改为 0.10.0 |
| `examples/ch10_multi_agent.py` | 三角色流水线、共享黑板、上下文隔离与编排者—执行者示例 |
| `tests/test_multi_agent.py` | 15 条协作、预算、失败、嵌套与上下文隔离测试 |

{% hint style="success" %}
v0.10.0 代码已按本章清单写入仓库并验证（78 passed），`Orchestrator` 按冻结签名实现，未改动任何 v0.9.0 冻结接口。
{% endhint %}

## 第 11 章变更（v0.11.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `FrameworkProfile` | 新增，框架画像：类型、能力集合、模型绑定、自托管、成熟度、优势与约束 | 新增，仅用于选型 |
| `Requirements` | 新增，选型需求：硬约束、偏好、自托管/开放模型要求、最低成熟度 | 新增 |
| `FrameworkChoice` | 新增，候选结果：画像、分数、命中偏好与理由 | 新增 |
| `select_frameworks` | 新增，按硬约束过滤、按偏好确定性排序 | 新增 |
| `CallableAgentRunner` | 新增，把 `(task, ctx) -> Trajectory | str` 的外部入口包装为 `AgentRunner` | 新增，不改变 `AgentRunner` 协议 |
| `as_agent_runner` | 新增，`CallableAgentRunner` 的快捷构造函数 | 新增 |
| `ConformanceCase` / `ConformanceReport` | 新增，契约用例与检查报告 | 新增 |
| `check_runner` | 新增，验证轨迹、运行 ID、步骤编号、停止原因与失败行为 | 新增 |
| `atlas` 顶层导出 | 新增适配层符号 | 向后兼容，版本改为 0.11.0 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 不新增内核接口 | 选型与适配全部放在 `integrations/`，核心 `AgentRunner`/`Trajectory` 不变 |
| 框架类型不得越过边界 | 适配器只暴露 `AgentRunner` 与 `Trajectory`，业务核心不 import 框架 |
| 选型结果必须可解释 | 每个候选携带命中偏好、分数与理由，而不是只返回排名 |
| 选型必须确定 | 同分按名称排序，避免输入顺序影响结果 |
| 硬约束与偏好分离 | `Requirements.required` 过滤，`preferred` 只影响排序 |
| 成熟度是显式门槛 | `min_maturity` 参与过滤，避免把实验性框架混入稳定候选 |
| 包装必须归一化 | 字符串结果补最小步骤；`Trajectory` 补齐空白任务、运行 ID 与结束时间 |
| 失败必须显式 | 非法返回类型抛 `TypeError`；契约检查逐用例捕获异常并记录 |
| 契约检查保持黑盒 | 只验证可观察输出，不假设框架内部预算或恢复语义 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 框架画像靠人工维护 | 容易过时且带主观性 | 第 15 章用评测数据校准 |
| 评分规则简单 | 只适合粗筛，不适合精细排序 | 引入加权需求与团队约束 |
| 适配器只支持 `(task, ctx)` 入口 | 复杂框架需要闭包或专用适配器 | 按框架补充适配实现 |
| 契约检查不验证内部预算 | 无法发现框架绕过预算的问题 | 第 16、18 章加入追踪与运行时检查 |
| 未引入真实框架依赖 | 示例离线可复现，但不证明真实集成可用 | 第 12 章用真实框架重写并对比 |
| 画像不包含价格与性能数据 | 选型无法自动做成本比较 | 使用时叠加自有 spike 数据 |

### 验证

- `PYTHONPATH=src python3 examples/ch11_frameworks.py` 输出与正文 11.6.4 一致
- 两组需求分别筛出 `Google ADK / LangGraph` 与 `Dify / Coze`，排除原因可逐条打印
- `python3 -m pytest -q`：91 passed（原有 78 条 + 新增 13 条）
- 新增测试覆盖：硬约束过滤、自托管与模型绑定过滤、成熟度过滤、偏好排序、确定性与数量限制、非法 limit、字符串/轨迹包装、默认运行 ID、非法返回类型、契约通过、契约违规与异常上报
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`ContextBuilder.build`、`StopPolicy.check` 与 `Budget` 默认值

### v0.11.0 实现清单（第 11 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/integrations/profiles.py` | `FrameworkProfile`、`Requirements`、`FrameworkChoice`、`select_frameworks` |
| `src/atlas/integrations/runner.py` | `CallableAgentRunner`、`as_agent_runner`、结果归一化 |
| `src/atlas/integrations/conformance.py` | `ConformanceCase`、`ConformanceReport`、`check_runner` |
| `src/atlas/integrations/__init__.py` | 模块导出 |
| `src/atlas/__init__.py` | 导出适配层符号，版本改为 0.11.0 |
| `pyproject.toml` | 版本改为 0.11.0 |
| `examples/ch11_frameworks.py` | 八个框架画像、两组需求选型、适配与契约检查示例 |
| `tests/test_integrations.py` | 13 条选型、包装与契约测试 |

{% hint style="success" %}
v0.11.0 代码已按本章清单写入仓库并验证（91 passed），未新增内核接口，未改动任何 v0.10.0 冻结签名。
{% endhint %}

## 第 12 章变更（v1.0.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `AtlasConfig` | 新增，模型、API 地址、温度、离线开关、上下文窗口与预算配置 | 新增 |
| `AtlasConfig.from_env` | 新增，从 `ATLAS_` 前缀环境变量读取配置 | 新增 |
| `AtlasApp` | 新增，装配结果：runner、agent、工具、上下文构建器、记忆、检索与引用报告 | 新增 |
| `build_app` | 新增，按固定顺序装配 Atlas 并返回 `AtlasApp` | 新增 |
| `load_knowledge_dir` | 新增，把本地 Markdown/文本目录装入知识库 | 新增 |
| `main` / `python -m atlas` | 新增，CLI 入口，支持离线演示、本地知识目录与 JSON 输出 | 新增 |
| `demo` 模块 | 新增，内置知识库、预置偏好与脚本模型，仅用于示例与测试 | 新增 |
| `atlas` 顶层导出 | 新增装配与配置符号；版本改为 1.0.0 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 内核接口冻结 | v1.0.0 只新增装配与入口，`Agent`、`AgentRunner`、`ContextBuilder`、`StopPolicy` 等签名不变 |
| 装配顺序固定 | 工具 → 模型 → 记忆/检索 → 上下文预算 → 循环 → 引用审计 → 记忆写回 |
| 记忆检索先于预算压缩 | `BudgetedContextBuilder` 包装 `MemoryContextBuilder`，预算统一权衡记忆、历史与证据 |
| 引用审计先于记忆写回 | `AgenticRAG` 位于 `MemoryRecorder` 内层，记忆记录审计后的答案 |
| 配置只描述运行参数 | `AtlasConfig` 不承担状态、失败策略或安全策略 |
| 密钥不落代码 | 环境变量仅作教学示例；生产使用密钥管理与最小权限 |
| CLI 必须可离线复现 | `--offline` 使用脚本模型与内置知识库，不发起网络请求 |
| 本地知识目录使用稳定 ID | `doc_id` 由相对路径生成，保证引用与分块 ID 可复现 |
| 未配置模型时显式失败 | 无可用模型时以 `stop_reason="error"` 结束，不静默返回空答案 |
| 冻结契约可执行 | 契约测试逐条检查参数名、顺序、默认值与关键字约束 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 装配顺序写死在 `build_app` | 灵活组合需要自定义装配函数 | 第 18 章引入运行时配置与调度 |
| CLI 只加载本地文本 | 不具备网页检索能力 | 第 13 章补充抓取与搜索工具 |
| 离线模型是脚本 | 只验证链路，不证明模型质量 | 第 15 章用评测集替换 |
| 记忆与知识库均在内存 | 进程退出即丢失 | 第 18 章持久化存储与索引 |
| 未接入护栏与审批 | 工具调用直接执行 | 第 17 章接入 `Guard` 与 `ApprovalHandler` |
| 检查点尚未实现 | 无法从中断处恢复 | 第 18 章运行时层补齐 |
| LangGraph 示例不进入默认测试 | 避免强制可选依赖 | 安装 `langgraph` 后单独运行验证 |

### 验证

- `PYTHONPATH=src python3 -m atlas --offline` 输出与正文 12.4.3 一致：`final_answer`、2 步、968 tokens、3 条引用、2 条记忆
- `python3 examples/ch12_minimal_agent.py` 输出与正文 12.2.4 一致：最终答案 576，总用量 364
- 安装 `langgraph` 后 `python3 examples/ch12_langgraph.py` 输出四条消息：Human → AI（工具调用）→ 工具结果 → 最终答案
- `python3 -m pytest -q`：102 passed（原有 91 条 + 新增 11 条）
- 新增测试覆盖：配置默认值与覆盖、非法布尔值、离线端到端、装配类型与顺序、引用审计、记忆写回、无知识库时不注册检索工具、目录加载与缺失目录、CLI 文本/JSON 输出、在线模式缺任务、最小内核轨迹契约
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`ContextBuilder.build`、`StopPolicy.check` 与 `Budget` 默认值

### v1.0.0 实现清单（第 12 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/config.py` | `AtlasConfig`、`from_env`、环境变量解析 |
| `src/atlas/app.py` | `AtlasApp`、`build_app`、固定装配顺序、引用报告 |
| `src/atlas/cli.py` | `main`、`load_knowledge_dir`、文本与 JSON 输出 |
| `src/atlas/__main__.py` | `python -m atlas` 入口 |
| `src/atlas/demo.py` | 内置知识库、预置偏好、脚本模型 |
| `src/atlas/__init__.py` | 导出装配符号，版本改为 1.0.0 |
| `pyproject.toml` | 版本改为 1.0.0 |
| `examples/ch12_minimal_agent.py` | 约 300 行有效代码的离线最小 Agent |
| `examples/ch12_langgraph.py` | 可选依赖的 LangGraph 对照实现 |
| `tests/test_app.py` | 11 条配置、装配、CLI 与最小内核测试 |

{% hint style="success" %}
v1.0.0 代码已按本章清单写入仓库并验证（102 passed），公开接口冻结；未改动任何 v0.11.0 冻结签名。
{% endhint %}

## 后续章节的接口引入顺序

| 章节 | 新增接口 | 版本 |
|---|---|---|
| 第 4 章 | `types`、`LLM`、`Tool`、`ToolRegistry`、`Agent`、`StopPolicy` | v0.4.0 |
| 第 5 章 | 参数校验、`MCPTool`、`StdioMCPClient`、`run_many` 并行、`dangerous` 授权 | v0.5.0 |
| 第 6 章 | `Plan`、`PlanStep`、`Planner`、`LLMPlanner`、`PlanExecuteAgent`、反思与重规划 | v0.6.0 |
| 第 7 章 | `MemoryStore`、`MemoryItem`、`ContextBuilder`、`MemoryWriter`、`MemoryRecorder`、`InMemoryStore` | v0.7.0 |
| 第 8 章 | `Retriever`、`Document`、`AgenticRAG` | v0.8.0 |
| 第 9 章 | `ContextBudget`、`ContextReport`、`ContextCompactor`、`ProgressiveDisclosure`、`ExpandContextTool`、`BudgetedContextBuilder` | v0.9.0 |
| 第 10 章 | `Orchestrator`、`SharedBoard`、`RoleSpec`、`build_role_agent`、`ToolRegistry.subset` | v0.10.0 |
| 第 11 章 | `FrameworkProfile`、`Requirements`、`select_frameworks`、`CallableAgentRunner`、`check_runner`（不新增内核接口） | v0.11.0 |
| 第 12 章 | `AtlasConfig`、`AtlasApp`、`build_app`、CLI（内核接口冻结） | v1.0.0 |
| 第 15 章 | `EvalTask`、`EvalResult`、`Evaluator` | v1.1.0 |
| 第 16 章 | `Tracer`、JSONL 记录与回放 | v1.2.0 |
| 第 17 章 | `Guard`、`GuardDecision`、`ApprovalHandler`、`ToolAllowlistGuard`、`ApprovalGuard`、`SandboxGuard`、`SandboxPolicy`、`PromptInjectionGuard`、`OutputRedactionGuard`、`AuditLog`、`AuditTracer` | v1.3.0 |
| 第 18 章 | `runtime` 层：`CachedLLM`、`RoutingLLM`、`RetryingLLM`、`IdempotentTool`、`TokenBucket`、`JobRunner`、`RuntimeMetrics`、`MeteredLLM` | v1.4.0 |
| 第 19–21 章 | 无新增内核接口；第 20 章仅在 `examples/ch20_agentic_rl.py` 中使用冻结类型与评测接口；第 21 章无代码 | 无变更 |

## 第 13 章变更（无代码变更）

### 新增 / 修改的类与接口

无。本章不修改 `src/atlas`，不改变 `atlas/interfaces.md`，版本仍为 v1.0.0。正文中的编码 Agent 与研究 Agent 示例是独立示例，只实现既有 `Tool` 协议并组合冻结接口。

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 编码 Agent 的工具必须有路径边界 | 文件类工具在运行时解析并校验路径，禁止逃逸工作区；不依赖提示词约束 |
| 写操作与命令执行默认高危 | `apply_patch`、`run_tests` 等标记 `dangerous=True`，由 `ToolRegistry` 显式授权；生产应接第 17 章审批 |
| 测试输出是观察，不是日志 | 工具返回退出码、失败用例与截断后的输出；错误转为 `ToolResult(is_error=True)`，模型可继续修复 |
| 验证分层且先廉后贵 | 语法/类型/目标测试/相关测试/全量测试按成本排序；停止条件由 `StopPolicy` 与验收标准共同决定 |
| 仓库上下文按需加载 | 用仓库地图、搜索与区间读取构造工作集；不把整仓库注入 `ContextBuilder` |
| 研究以主张为单位 | `EvidenceLedger` 继续记录文档级证据；主张级台账、引用支持性与来源多样性在示例/评测层扩展，不新增内核接口 |
| 引用审计不等于引用存在 | `AgenticRAG` 只做存在性校验；支持性与来源可信留给第 15、17 章与人工复核 |
| 研究停止依赖覆盖标准 | 子问题覆盖、证据充分性与预算共同决定停止；不能只靠 `max_steps` |
| 示例不进入运行时 | 第 13 章示例用于说明组装方式，不改变 `AtlasApp`、`build_app` 与 CLI 的默认行为 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 示例编码工具只支持单文件精确替换 | 复杂重构需要多次补丁或 AST 工具 | 生产接入 LSP/语法树与更细粒度编辑 |
| 示例测试执行无容器隔离 | 仅适合可信本地工作区 | 第 17 章沙箱、第 18 章运行时隔离 |
| 示例研究覆盖检查按标题分节 | 依赖模型输出格式 | 生产用结构化输出或独立评估器 |
| `EvidenceLedger` 仍是文档级 | 无法表达片段对主张的支持/反驳 | 第 15 章评测、第 17 章来源信任 |
| 示例不实现检索缓存与限流 | 真实研究任务的成本不可控 | 第 18 章缓存、限流与预算 |
| 示例模型是脚本 | 只验证链路 | 第 15 章用固定评测集替换 |

### 验证

- 本章不新增 `src/atlas` 代码，现有测试基线仍为 102 passed
- 正文示例仅使用 v1.0.0 公开导出；不修改 `Agent`、`Tool`、`ToolRegistry`、`AgenticRAG`、`EvidenceLedger` 等冻结签名
- 编码示例离线运行，预期输出最终答案与四步轨迹；研究示例预期 `CitationReport.ok=True`，两个子问题均有引用
- 版本保持 `atlas.__version__ == "1.0.0"`

{% hint style="success" %}
第 13 章无代码变更。Atlas 下一实现版本仍为 v1.1.0（第 15 章评测类型与运行器）。
{% endhint %}

## 第 14 章变更（无代码变更）

### 新增 / 修改的类与接口

无。本章不修改 `src/atlas`，不改变 `atlas/interfaces.md`，版本仍为 v1.0.0。正文中的 Computer Use 与企业流程示例是独立示例，只实现既有 `Tool` 协议并组合冻结接口；示例中的 `FunctionTool` 与 `CasePipeline` 属于应用层封装，不进入 Atlas 内核。

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 观察接口必须可替换 | 截图、DOM、可访问性树与业务 API 都只是 `Tool` 的不同实现，`Agent` 循环不感知观察来源 |
| 观察必须带新鲜度标记 | 动作携带版本号或状态哈希；状态变化后旧引用失效，运行时拒绝执行并返回可恢复错误 |
| 定位按稳定性降级 | 应用层优先 API，其次语义节点，再次选择器，最后坐标；Atlas 不内置定位策略 |
| 不可逆动作分阶段 | 准备、确认、提交、对账由应用层工具与审批实现；`dangerous=True` 只提供第一道运行时开关 |
| 验证以业务系统为准 | 页面状态与截图只是辅助证据；最终成功判据来自系统记录或对账 |
| 屏幕内容是数据 | Computer Use 的观察结果按不可信输入处理；提示注入防护在工具与上下文层设卡，不依赖提示词 |
| 流程状态显式化 | 案件状态、责任方、退出条件与超时由应用层状态机维护，不塞进对话历史 |
| 审批与职责分离 | 审批记录身份、范围、依据与时效；模型只能提出审批请求，不能自行批准 |
| 幂等键与补偿先行 | 不可逆动作在执行前写入幂等键，失败按 Saga 补偿；重试不得绕过幂等 |
| 审计事件可回放 | 案件 ID、运行 ID、动作、参数、结果、审批与证据进入审计链，作为 Trace 的上游数据 |
| 示例不进入运行时 | 第 14 章示例用于说明组装方式，不改变 `AtlasApp`、`build_app` 与 CLI 的默认行为 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 示例用脚本化屏幕替代真实浏览器 | 只验证观察—动作—验证链路，不证明视觉定位能力 | 生产接入 Playwright/CDP、可访问性树与视觉模型 |
| 示例的确认令牌不是人工审批 | 令牌只保证一次性与状态新鲜，不保证责任归属 | 第 17 章 `ApprovalHandler` 接入真实审批与身份 |
| 示例的应用状态在内存中 | 进程重启后案件、幂等键与审计丢失 | 第 18 章持久化、检查点与对账调度 |
| 示例用浮点数表示金额 | 生产环境可能出现精度问题 | 生产改用整数分或 `Decimal` |
| 示例的审批自动通过 | 演示链路，不代表真实审批策略 | 接入审批服务、超时升级与双人复核 |
| 示例只演示单案件、单动作 | 未覆盖并发、批量、跨系统一致性 | 第 18 章运行时与并发调度 |
| 示例的补偿未实现 | 退款失败后如何回滚只作说明 | 用 Saga/补偿任务与对账补齐 |

### 验证

- 本章不新增 `src/atlas` 代码，现有测试基线仍为 102 passed
- 正文示例仅使用 v1.0.0 公开导出；不修改 `Agent`、`Tool`、`ToolRegistry`、`Trajectory` 等冻结签名
- Computer Use 示例离线运行，预期输出 10 步轨迹、`stale_error` 为“观察已过期”、`submissions` 仅 1 条、业务状态为 `submitted`
- 企业流程示例离线运行，预期输出 7 步轨迹、`duplicate_request=true`、仅 1 笔退款、4 条审计事件
- 版本保持 `atlas.__version__ == "1.0.0"`

{% hint style="success" %}
第 14 章无代码变更。Atlas 下一实现版本仍为 v1.1.0（第 15 章评测类型与运行器）。
{% endhint %}

## 第 15 章变更（v1.1.0）

### 新增 / 修改的类与接口

| 符号 | 变更 | 兼容性 |
|---|---|---|
| `EvalTask` | 新增，评测任务：`id`、`question`、`reference`、`rubric`、`metadata` | 按 `interfaces.md` 落地 |
| `EvalResult` | 新增，单次评测结果：`task_id`、`trajectory`、`score`、`passed`、`detail` | 按 `interfaces.md` 落地 |
| `Evaluator` | 新增，`score(task, trajectory) -> EvalResult` 协议 | 按 `interfaces.md` 落地 |
| `EvaluationError` | 新增，评测器或运行器包装异常 | 新增 |
| `ExactMatchEvaluator` | 新增，规范化大小写与空白后的精确匹配 | 新增 |
| `ContainsEvaluator` | 新增，按 `required_snippets` 计算片段覆盖率，支持部分分 | 新增 |
| `TrajectoryEvaluator` | 新增，检查步数、工具调用数、必需/禁止工具与工具错误 | 新增 |
| `WeightedEvaluator` | 新增，多评分器加权平均与通过阈值 | 新增 |
| `LLMJudgeEvaluator` | 新增，模型评委；解析失败或调用异常时 fail-closed | 新增 |
| `parse_judge_response` / `JudgeParseError` | 新增，剥代码块、解析 JSON、校验 0–1 分数 | 新增 |
| `TrajectoryMetrics` / `collect_metrics` | 新增，从轨迹计算步数、工具调用、重复、并行、令牌、费用、时延与错误分布 | 新增 |
| `EvalSummary` / `summarize` | 新增，任务数、尝试数、pass@k、pass^k、均值分、成本、p95 时延与失败任务 | 新增 |
| `EvalRunner` | 新增，实现批量运行；每任务构造独立 `RunContext`，捕获异常为 `stop_reason="error"` | 新增 |
| `EvalReport` | 新增，评测报告：名称、结果、汇总、元数据；`by_task()` 与 `to_dict()` | 新增 |
| `TaskDelta` / `RegressionReport` / `compare_reports` | 新增，按任务比较基线与候选，识别回归、改进、缺失任务与汇总差值；`ok()` 作为门禁 | 新增 |
| `atlas` 顶层导出 | 新增评测符号；版本改为 1.1.0 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 评测层只组合冻结接口 | `EvalRunner` 接受任意 `AgentRunner`，不修改 `Agent`、`Trajectory` 或 `StopPolicy` |
| 每次尝试有独立运行标识 | `run_id = f"{name}:{task.id}:{attempt}"`，便于把结果回溯到具体运行 |
| 结果与过程分开评分 | 结果评分器看 `final_answer`；轨迹评分器看 `Step`、工具调用与错误，不把两者混成一个数 |
| 汇总必须区分尝试与任务 | `pass_rate` 按尝试、`pass@k` 按任务任一次成功、`pass^k` 按任务全部成功 |
| 失败尝试也要计入成本 | 成本与令牌汇总覆盖失败任务，`cost_per_success` 只在有成功时给出 |
| 时延使用最近秩分位 | `p95_latency_seconds` 不依赖第三方库，小样本下行为稳定可测 |
| 评分器不得抛出未处理异常 | 单个评分器失败转成 `score=0` 与 `detail["error"]`；运行器异常转成 `stop_reason="error"` |
| 模型评委必须 fail-closed | 解析失败、越界分数或模型异常一律判不通过，并写入 `judge_error` |
| 评测量纲不可混用 | 权重归一到总和为 1；未给权重时等权；阈值与权重在构造时校验 |
| 回归门禁可配置且有默认 | `RegressionReport.ok(max_regressions=0, min_pass_rate_delta=0.0)`；默认任何回归或成功率下降都阻断 |
| 评测集只是数据 | `EvalTask` 不绑定具体 Agent、模型或工具；切片通过 `metadata` 表达 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 令牌与费用来自轨迹上报 | 适配层未计量时汇总会低估 | 第 16 章用追踪事件统一采集 |
| 判定以字符串包含为主 | 语义等价答案可能被判错 | 需要时组合 `LLMJudgeEvaluator` 并做校准 |
| `contains` 不检查否定与顺序 | 片段齐全但语义相反的答案可能得分 | 第 17 章加入证据与安全校验；生产增加结构化判定 |
| 模型评委与主模型可能同源 | 自我偏好偏差 | 引入独立评委模型、成对比较与人工抽检 |
| 重复工具调用按参数完全一致统计 | 语义重复但参数微变的调用不计入 | 需要更细的动作归一化或嵌入聚类 |
| `p95` 为最近秩 | 小样本下与插值分位差异较大 | 生产改用统计库并报告样本量 |
| 尚未接入追踪与回放 | 失败原因只能看汇总指标 | 第 16 章 JSONL 记录与回放 |
| 尚未接入护栏与审批 | 评测可直接执行危险工具 | 第 17 章评测集接入沙箱与授权 |

### 验证

- `PYTHONPATH=src python3 examples/ch15_eval.py` 输出与正文 15.7 一致：基线 `pass_rate=1.00 mean_score=1.000`，候选 `pass_rate=0.75 mean_score=0.825`，`regressions=1 pass_rate_delta=-0.25`，门禁为 `block`
- `python3 -m pytest -q`：117 passed（原有 102 条 + 新增 15 条）
- 新增测试覆盖：任务默认值、轨迹指标、精确匹配规范化、片段部分分、轨迹过程检查、加权评分、pass@k/pass^k 与成本、运行器聚合与运行 ID、运行器异常捕获、回归检测、缺失任务、评委解析、评委成功与 fail-closed、公开导出与版本
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`ContextBuilder.build`、`StopPolicy.check` 与 `Budget` 默认值

### v1.1.0 实现清单（第 15 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/eval/base.py` | `EvalTask`、`EvalResult`、`Evaluator`、`EvaluationError` |
| `src/atlas/eval/metrics.py` | `TrajectoryMetrics`、`collect_metrics`、`EvalSummary`、`summarize` |
| `src/atlas/eval/scorers.py` | `ExactMatchEvaluator`、`ContainsEvaluator`、`TrajectoryEvaluator`、`WeightedEvaluator` |
| `src/atlas/eval/runner.py` | `EvalRunner`、`EvalReport`、`TaskDelta`、`RegressionReport`、`compare_reports` |
| `src/atlas/eval/judge.py` | `LLMJudgeEvaluator`、`parse_judge_response`、`JudgeParseError` |
| `src/atlas/eval/__init__.py` | 模块导出 |
| `src/atlas/__init__.py` | 导出评测符号，版本改为 1.1.0 |
| `pyproject.toml` | 版本改为 1.1.0 |
| `examples/ch15_eval.py` | 脚本化计算器任务、基线/候选对比、回归门禁与失败指标输出 |
| `tests/test_eval.py` | 15 条评测类型、指标、评分器、运行器、回归与评委测试 |

{% hint style="success" %}
v1.1.0 代码已按本章清单写入仓库并验证（117 passed），`EvalTask`/`EvalResult`/`Evaluator` 按冻结签名实现，未改动任何 v1.0.0 冻结接口。Atlas 下一实现版本为 v1.2.0（第 16 章追踪与回放）。
{% endhint %}

## 第 16 章变更（v1.2.0）

### 新增 / 修改的类与接口

| 接口 | 说明 | 变更 |
|---|---|---|
| `Tracer` | 追踪协议：`on_run_start`、`on_step`、`on_run_end`；只规定回调时点，不规定存储格式 | 新增，签名与 `atlas/interfaces.md` 预留一致 |
| `TraceEvent` | 统一事件信封：`event_id`、`run_id`、`parent_id`、`type`、`timestamp`、`schema_version`、`payload` | 新增 |
| `TraceEvent.to_dict()` / `from_dict()` | JSON 可序列化与恢复；保留原始 `event_id` 与时间 | 新增 |
| `EventType` | `run_start`、`step`、`tool_call`、`tool_result`、`run_end`、`note` 六类 | 新增 |
| `redact_text` / `redact_value` | 先脱敏后截断；递归处理敏感字段名 | 新增 |
| `InMemoryTracer` | 内存事件列表，用于测试与一次性分析 | 新增 |
| `JSONLTracer` | 追加写 JSONL；线程锁；可配置采样率、内容哈希、脱敏与截断 | 新增 |
| `CompositeTracer` | 扇出到多个追踪器；单个后端异常不中断其他后端 | 新增 |
| `load_events` / `events_for_run` | 读取 JSONL 并按运行过滤；坏 JSON 报 `TraceFormatError` 并带行号 | 新增 |
| `replay_trajectory` | 从事件重建 `Trajectory`；缺少 `run_start` 时拒绝回放 | 新增 |
| `TraceSummary` / `summarize_trace` | 步数、调用数、错误类型、重复调用、令牌、费用、耗时、信号与首个错误事件 | 新增 |
| `TraceDivergence` / `compare_traces` | 按步骤比较动作与观察，返回首个分歧的索引与原因 | 新增 |
| `FailureDiagnosis` / `diagnose_trace` | 规则式分诊：`recovered_tool_error`、`tool_error`、`budget_stop`、`timeout`、`policy_denied`、`runtime_error`、`incomplete_trace`、`empty_answer`、`loop_suspected`、`healthy`、`unknown` | 新增 |
| `Agent._emit` | 在三个时点调用追踪器，并吞掉追踪异常 | 修改（内部方法） |
| `Orchestrator` 运行边界 | 编排器只发 `run_start` / `run_end`；子 Agent 记录自己的步骤 | 修改（行为扩展） |
| `AtlasApp.tracer` / `build_app(tracer=...)` | 可选追踪器注入，默认 `None` | 新增（向后兼容） |
| `atlas` 顶层导出 | 新增追踪符号与脱敏函数；版本改为 1.2.0 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 追踪必须是旁路 | `Agent._emit` 捕获并忽略追踪异常；无论追踪是否失败，`Agent.run` 的结果与停止原因不变 |
| 协议保持最小 | `Tracer` 只有三个回调，不感知存储、采样或导出格式；JSONL、内存与组合追踪器都实现同一协议 |
| 事件只追加 | `JSONLTracer` 逐行追加；修正记录应写新事件，`replay_trajectory` 不修改已有事件 |
| 事件信封稳定 | `schema_version` 随格式演进；字段名与类型不因后端变化而改变 |
| 运行标识贯穿全链路 | `run_id` 直接复用 `RunContext.run_id`，与评测、日志、告警共用同一标识 |
| 父子关系只做一层 | `parent_id` 指向产生该工具调用的步骤；更深因果由时间与载荷还原，避免复杂图结构 |
| 先脱敏后截断 | `redact_text` 先替换密钥再截断，避免半截密钥逃过正则 |
| 采样必须确定性 | 对 `run_id` 做 SHA-256 后落桶；同一运行在多次判断中得到相同结果，避免半截 Trace |
| 内容可只留哈希 | `include_content=False` 时记录 SHA-256 与字符数，回放保留结构但不暴露原文 |
| 失败可诊断 | `summarize_trace` 至少暴露停止原因、错误类型、重复调用与缺失结束事件 |
| 比较看动作而非措辞 | `compare_traces` 比较工具名、规范化参数、结果状态与内容哈希，不比较思考文本 |
| 分诊与评测分离 | `diagnose_trace` 只做结构性规则判断；语义正确性仍交给第 15 章判分器或人工 |
| 回放默认无副作用 | 重建轨迹只读事件，不重新执行工具；确定性回放需显式命中录制，未命中应失败 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| `Agent._emit` 完全吞掉追踪异常 | 追踪故障可能静默 | 生产实现应把失败计数与最后错误暴露为指标 |
| `step` 与 `tool_call`/`tool_result` 存在冗余 | 存储略增 | 换取按步骤回放与按工具查询两种能力 |
| 头部采样可能漏掉失败运行 | 高流量下失败样本偏少 | 第 18 章或生产实现增加尾部采样与错误必留 |
| 内容哈希不可逆 | 回放可还原结构但拿不到原文 | 原文留在受控存储，用哈希换取访问 |
| `compare_traces` 只按步骤对齐 | 步骤错位时可能把后续全部标为分歧 | 需要更细的对齐算法或按工具调用 ID 匹配 |
| `diagnose_trace` 是规则分类 | 无法判断语义正确性与根因 | 与判分器、人工复核组合使用 |
| 编排器只记录边界 | 跨 Agent 的因果关系依赖子运行 ID 关联 | 第 17–18 章补充跨进程传播与统一采集 |
| JSONL 无索引 | 大量文件查询需借助外部工具 | 生产改用 OTel Collector 与后端索引 |

### 验证

- `PYTHONPATH=src python3 examples/ch16_trace.py` 输出与正文 16.7.4 一致：基线 `steps=2 tool_calls=1 errors=0`，候选 `errors=1 signals=['tool_error']`，首个分歧 `index=0 reason=tool_call`，诊断 `recovered_tool_error`，回放答案与工具错误状态均可还原
- `python3 -m pytest -q`：134 passed（原 117 条 + 新增 17 条）
- 新增测试覆盖：JSONL 往返与父子关系、汇总与错误类型、恢复型工具错误诊断、预算停止、重复调用与循环诊断、首个分歧、相同轨迹、脱敏与截断、内容哈希、采样关闭与非法采样率、坏 JSON 行号、缺少 `run_start`、追踪器异常隔离、组合追踪器隔离、编排器边界、事件序列化、公开导出与版本
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`ContextBuilder.build`、`StopPolicy.check` 与 `Budget` 默认值

### v1.2.0 实现清单（第 16 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/trace/base.py` | `Tracer` 协议 |
| `src/atlas/trace/events.py` | `SCHEMA_VERSION`、`EventType`、`TraceEvent`、`redact_text`、`redact_value`、事件构造函数与 JSON 序列化 |
| `src/atlas/trace/recorder.py` | `InMemoryTracer`、`JSONLTracer`（线程锁、确定性采样、内容哈希）、`CompositeTracer` |
| `src/atlas/trace/replay.py` | `TraceFormatError`、`load_events`、`events_for_run`、`replay_trajectory`、`TraceSummary`、`summarize_trace`、`TraceDivergence`、`compare_traces`、`FailureDiagnosis`、`diagnose_trace` |
| `src/atlas/trace/__init__.py` | 模块导出 |
| `src/atlas/agent/loop.py` | 在运行开始、每次追加步骤、`finally` 结束三个时点调用追踪器；`_emit` 隔离异常 |
| `src/atlas/multi_agent/orchestrator.py` | 在编排开始与结束时发出运行边界事件 |
| `src/atlas/app.py` | `AtlasApp.tracer` 与 `build_app(tracer=...)`，向下传递给 `Agent` |
| `src/atlas/__init__.py` | 导出追踪符号与脱敏函数，版本改为 1.2.0 |
| `pyproject.toml` | 版本改为 1.2.0 |
| `examples/ch16_trace.py` | 基线/候选两次运行、JSONL 与内存追踪、汇总、分歧、诊断、回放与脱敏输出 |
| `tests/test_trace.py` | 17 条追踪协议、记录器、回放、比较、诊断与隔离测试 |

{% hint style="success" %}
v1.2.0 代码已按本章清单写入仓库并验证（134 passed），`Tracer` 按冻结协议实现，未改动任何 v1.0.0 冻结接口。Atlas 下一实现版本为 v1.3.0（第 17 章护栏、审批与沙箱）。
{% endhint %}

## 第 17 章变更（v1.3.0）

### 新增 / 修改的类与接口

| 接口 | 说明 | 变更 |
|---|---|---|
| `Guard` | 护栏协议：`before_tool`、`after_tool`；只规定裁决时点，不规定具体策略 | 新增实现，签名与 `atlas/interfaces.md` 预留一致 |
| `GuardAction` | `allow`、`deny`、`approve` 三值 | 新增类型别名 |
| `GuardDecision` | 裁决对象：`action`、`reason`、`replacement`、`metadata` | 新增；`metadata` 是带默认值的新增字段 |
| `ApprovalHandler` | 审批协议：`request(call, ctx, reason) -> bool` | 新增实现，签名与预留一致 |
| `denied_result` | 把拒绝转换成模型可读、审计可查的 `ToolResult` | 新增 |
| `ToolAllowlistGuard` | 工具名白名单，运行时事实而非提示词约定 | 新增 |
| `ApprovalGuard` | 把指定工具升级为需审批；`from_registry` 按 `dangerous` 标记生成 | 新增 |
| `PromptInjectionGuard` | 扫描工具结果或参数，支持 `redact`、`drop`、`flag` 三种模式 | 新增 |
| `detect_injection` | 返回命中的高信号规则名，供护栏与审计复用 | 新增 |
| `OutputRedactionGuard` | 在结果进入上下文前脱敏密钥，可选脱敏邮箱与电话 | 新增 |
| `SandboxPolicy` | 工作区根目录、只读开关、命令白名单、写入与命令工具集合 | 新增 |
| `SandboxGuard` | 检查只读写入、路径逃逸、命令白名单与 shell 元字符 | 新增 |
| `ApprovalRecord` | 记录一次审批的调用、工具、原因、结果与审批人 | 新增 |
| `AutoApprove` / `AutoDeny` | 演示与测试用的固定审批器，明确标注不可用于生产默认 | 新增 |
| `ScriptedApproval` | 按脚本顺序批准或拒绝，便于离线复现审批路径 | 新增 |
| `CallbackApproval` | 把审批委托给外部工单、聊天机器人或审批 API | 新增 |
| `ConsoleApproval` | 终端审批的最小实现；超时、身份与范围校验留给生产审批服务 | 新增 |
| `AuditRecord` | 审计记录：序号、运行、时间、主体、动作、工具、调用、决策、原因、详情、前后哈希 | 新增 |
| `AuditLog` | 只追加哈希链：`append`、`for_run`、`verify`、`export_jsonl` | 新增 |
| `AuditTracer` | 实现 `Tracer` 协议，把工具决策写成 `allow`/`deny`/`approve`/`modify`/`error` | 新增 |
| `Agent._execute_tools` | 前置裁决、审批、并行执行、后置复核；保持输入顺序 | 修改（内部方法） |
| `Agent._before_tool` / `_after_tool` | 顺序调用护栏；护栏异常转换为拒绝；审批缺失或异常失败关闭 | 新增（内部方法） |
| `MAX_CONSECUTIVE_DENIALS` | 连续拒绝阈值 3；达到后 `stop_reason="denied"`，其余调用标记 `skipped` | 新增 |
| `ToolRegistry.run` | 接受 `ctx.metadata["approved_tool_calls"]` 中的调用 ID，放行已批准的 `dangerous` 工具 | 修改（向后兼容） |
| `AtlasApp.guards` / `.approval` | 保存装配时的护栏与审批器 | 新增（向后兼容） |
| `build_app(guards=..., approval=...)` | 可选关键字注入，默认空护栏与无审批器 | 新增（向后兼容） |
| `atlas` 顶层导出 | 新增安全符号；版本改为 1.3.0 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 模型提议、运行时裁决 | 护栏在工具执行前运行；模型返回的参数不被视为已授权动作 |
| 失败关闭 | 护栏抛异常、需要审批但无处理器、审批器抛异常，均转换为拒绝 |
| 拒绝可恢复 | 拒绝返回 `ToolResult(is_error=True)` 而不是抛异常，模型可以改道 |
| 连续拒绝有上限 | 连续 3 次拒绝停止运行，避免模型反复冲撞护栏 |
| 审批绑定具体调用 | 批准结果写入 `ctx.metadata["approved_tool_calls"]`，按 `tool_call.id` 放行 |
| 前置裁决串行、执行并行 | 护栏按注册顺序逐个运行；允许的调用仍走 `run_many`，结果按输入顺序回填 |
| 后置护栏可修改结果 | `replacement` 在写回历史前生效，注入隔离与脱敏因此能影响模型看到的内容 |
| 护栏元数据必须可追踪 | `GuardDecision.metadata` 合并进结果元数据，并由 `guard_decisions` 保留完整链 |
| 协议最小且可组合 | `Guard` 只有两个方法；白名单、审批、沙箱、注入、脱敏可以独立叠加 |
| 沙箱护栏不是操作系统沙箱 | `SandboxGuard` 只做应用层检查，正文与代码注释都明确需容器或 microVM 兜底 |
| 注入检测是降权不是准入 | `PromptInjectionGuard` 使用高信号启发式，允许误报与漏报，不承担最终边界 |
| 审计只追加 | `AuditLog` 不提供修改与删除方法；修正以新记录表达 |
| 哈希链可验证 | 每条记录包含 `prev_hash` 与 `hash`；`verify()` 从头重算并检测断链 |
| 审计不存原文 | 详情只保留内容长度与 SHA-256；原文留在受控存储 |
| 审计与追踪共享运行标识 | `AuditTracer` 直接使用 `RunContext.run_id`，可与 Trace 按同一主键关联 |
| 公开签名不变 | `Agent.__init__`、`Agent.run`、`build_app` 的既有参数名称、顺序与默认值不变 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 注入规则是高信号启发式 | 会漏掉改写、编码与多语言变体，也可能误伤安全文章 | 生产可叠加分类器、双 LLM 或能力隔离，但不能把检测当唯一防线 |
| 路径检查依赖参数命名约定 | 非标准键名或嵌套结构可能漏检 | 工具 schema 应约束路径参数名；高风险执行仍用容器隔离 |
| 命令白名单只做字符串级检查 | 无法理解解释器内部行为，合法解释器仍可能执行恶意脚本 | 沙箱内限制文件系统与网络，不把命令白名单当完整隔离 |
| 审批器只有一个布尔返回值 | 超时、身份、审批范围由实现方自行处理 | 生产审批服务需补充身份校验、超时失败关闭与审批去重 |
| 审批绑定调用 ID 而非参数哈希 | 同一运行内参数不被重新读取时足够；但调用 ID 由模型生成，跨步骤复用或参数可变场景不足 | 生产实现应绑定工具名、规范化参数哈希与有效期，不把模型生成的 ID 当安全凭据 |
| `AuditLog` 默认在内存中且无上限 | 进程退出即丢失，长期运行会增长 | 本章示例用内存实现；生产应落盘、分段、外部锚定链头 |
| 哈希链不能阻止整段重建 | 能检测内容篡改，不能证明“没有删除后重写” | 定期把链头写入独立受信存储或时间戳服务 |
| 审计详情只存内容哈希 | 取证时需回到受控存储比对原文 | 这是隐私与可验证性的显式取舍 |
| 前置护栏串行执行 | 每次调用增加少量延迟 | 护栏通常很轻；重检查应异步化或下沉到工具服务 |
| 连续拒绝阈值固定为 3 | 对合法重试也可能过早停止 | 可按任务风险与模型行为配置；当前保持常量以稳定测试与叙事 |

### 验证

- `PYTHONPATH=src python3 examples/ch17_safety.py` 输出与正文 17.7.5 一致：`stop_reason=final_answer`，5 次调用中 2 次 `denied`，注入与脱敏各命中一次，审批一批准一拒绝，越界路径被沙箱拒绝，`audit: records=12 verify=True`
- `python3 -m pytest -q`：155 passed（原 134 条 + 新增 21 条安全测试）
- `python3 -m compileall -q src examples`：通过
- 新增测试覆盖：`GuardDecision` 默认值、白名单拒绝与模型恢复、连续三次拒绝停止、拒绝计数复位、危险工具审批后执行、审批拒绝、审批器缺失失败关闭、输出脱敏、注入 `redact`/`drop`、沙箱路径逃逸与工作区内路径、只读与命令白名单、护栏异常失败关闭、并行执行顺序与拒绝隔离、护栏决策进入 Trace、审计哈希链与篡改检测、`AuditTracer` 记录、`build_app` 装配、`Agent` 关键字参数契约、公开导出与版本
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`ContextBuilder.build`、`StopPolicy.check` 与 `Budget` 默认值

### v1.3.0 实现清单（第 17 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/safety/base.py` | `GuardAction`、`GuardDecision`、`Guard`、`ApprovalHandler`、`denied_result` |
| `src/atlas/safety/guards.py` | 注入规则与 `detect_injection`、`ToolAllowlistGuard`、`ApprovalGuard`、`PromptInjectionGuard`、`OutputRedactionGuard` |
| `src/atlas/safety/sandbox.py` | `SandboxPolicy`、`SandboxGuard`、路径与命令检查辅助函数 |
| `src/atlas/safety/approval.py` | `ApprovalRecord`、`AutoApprove`、`AutoDeny`、`ScriptedApproval`、`CallbackApproval`、`ConsoleApproval` |
| `src/atlas/safety/audit.py` | `AuditRecord`、`AuditLog` 哈希链、`AuditTracer`、决策归类 |
| `src/atlas/safety/__init__.py` | 模块导出 |
| `src/atlas/agent/loop.py` | `MAX_CONSECUTIVE_DENIALS`、`_execute_tools`、`_before_tool`、`_after_tool`、`_denied`、`_guard_record`；`guards`/`approval` 注解改为真实协议 |
| `src/atlas/tools/registry.py` | 按 `ctx.metadata["approved_tool_calls"]` 放行已批准的 `dangerous` 工具 |
| `src/atlas/app.py` | `AtlasApp.guards`/`.approval` 与 `build_app(guards=..., approval=...)` |
| `src/atlas/__init__.py` | 导出安全符号，版本改为 1.3.0 |
| `pyproject.toml` | 版本改为 1.3.0 |
| `examples/ch17_safety.py` | 搜索注入、配置脱敏、审批批准/拒绝、沙箱越界、Trace 与审计链的端到端示例 |
| `tests/test_safety.py` | 21 条护栏、审批、沙箱、审计、装配与契约测试 |

{% hint style="success" %}
v1.3.0 代码已按本章清单写入仓库并验证（155 passed），`Guard`、`ApprovalHandler` 按冻结协议实现，未改动任何 v1.0.0 冻结接口。Atlas 下一实现版本为 v1.4.0（第 18 章生产化运行时）。
{% endhint %}

## 第 18 章变更（v1.4.0）

### 新增 / 修改的类与接口

| 接口 | 说明 | 变更 |
|---|---|---|
| `RuntimeMetrics` | 线程安全计数器：模型调用、错误、重试、缓存命中、回退、限流等待、工具调用、幂等回放、延迟、token 与费用 | 新增 |
| `RuntimeSnapshot` | 指标快照；提供 `cache_hit_rate`、`avg_llm_latency_ms`、`avg_tool_latency_ms`、`cache_token_ratio` | 新增 |
| `ModelPrice` | 按每千 token 计算费用，区分普通输入、缓存命中输入与输出 | 新增 |
| `MeteredLLM` | 实现 `LLM` 协议，记录延迟与费用，可按价格表覆盖 `usage.cost_usd` | 新增 |
| `ResponseCache` / `InMemoryResponseCache` | 响应缓存协议与带 TTL、LRU 的进程内实现 | 新增 |
| `response_cache_key` | 对命名空间、消息、工具、温度与 `max_tokens` 生成规范化 SHA-256 键 | 新增 |
| `CachedLLM` | 实现 `LLM` 协议；默认不缓存工具调用响应；返回深拷贝；可记录命中率 | 新增 |
| `Router` / `LengthRouter` | 路由协议与按提示长度、`[deep]` 标记选择路由的启发式实现 | 新增 |
| `RoutingLLM` | 按路由表分发，支持全局回退顺序与按路由计数；只捕获 `LLMError` | 新增 |
| `FallbackLLM` | 主模型失败时切换到备用模型的最小实现 | 新增 |
| `RetryPolicy` | 最大尝试次数、基础延迟、上限、抖动与自定义判定；`should_retry`、`delay` | 新增 |
| `is_retryable_error` | 按异常名与文本识别超时、429、502/503/504、连接重置等 | 新增 |
| `RetryingLLM` | 实现 `LLM` 协议，指数退避加抖动，可注入 `sleep`、`random_fn` 与指标 | 新增 |
| `RetryingTool` | 实现 `Tool` 协议；`max_attempts > 1` 时必须显式 `idempotent=True` | 新增 |
| `IdempotencyStore` / `InMemoryIdempotencyStore` | 幂等结果存储协议与带 TTL、LRU 的进程内实现 | 新增 |
| `idempotency_key` | 对命名空间、工具名与规范化参数生成 SHA-256 键 | 新增 |
| `IdempotentTool` | 实现 `Tool` 协议；只缓存成功结果；回放时写 `metadata["idempotent_replay"]=True` | 新增 |
| `TokenBucket` | 令牌桶限流，支持 `acquire`、`try_acquire`、`available` 与可注入时钟、sleep | 新增 |
| `ConcurrencyLimiter` | 基于 `BoundedSemaphore` 的并发上限，支持超时与上下文管理器 | 新增 |
| `RateLimitedLLM` / `RateLimitedTool` | 在调用前获取令牌；仅在真实等待大于零时记录等待指标 | 新增 |
| `JobStatus` / `Job` | 任务状态与任务快照；`to_dict` 输出停止原因与最终答案 | 新增 |
| `JobStore` / `InMemoryJobStore` | 任务保存、查询、领取与统计；`claim` 用锁保证进程内互斥 | 新增 |
| `JobRunner` | 提交、单次领取执行、重试、`drain` 与统计；把 `stop_reason="error"` 视为可重试失败 | 新增 |
| `atlas` 顶层导出 | 新增运行时符号；版本改为 1.4.0 | 向后兼容 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 不修改冻结接口 | 所有缓存、路由、重试、限流与计量能力都以 `LLM`/`Tool` 包装器实现，`Agent` 完全无感 |
| 缓存键必须完整 | 命名空间、消息、工具定义、温度与 `max_tokens` 均进入键；租户与模型版本由调用方放进命名空间 |
| 默认不缓存工具调用 | `cache_tool_calls=False`；复用提议可能放大副作用，需要显式开启并保证工具幂等 |
| 缓存返回副本 | `deepcopy` 隔离，避免调用方修改污染缓存 |
| 路由只处理服务故障 | 只捕获 `LLMError`；程序缺陷应向上冒泡，不能被静默切换掩盖 |
| 重试只处理可重试错误 | `RetryPolicy.should_retry` 基于异常名与文本；非重试错误立即抛出 |
| 非幂等工具禁止重试 | `RetryingTool` 在构造时强制 `idempotent=True`，而不是依赖文档约定 |
| 幂等只缓存成功 | 失败结果不缓存；回放标记写入元数据，便于追踪区分 |
| 全局限流不是本层职责 | `TokenBucket` 是进程内实现；多实例需 Redis 或网关配额 |
| 指标不参与控制流 | `RuntimeMetrics` 旁路累计；记录失败不应改变调用结果 |
| 延迟口径分离 | 模型延迟与工具延迟分别累计，`avg_llm_latency_ms` 不被工具耗时污染 |
| 任务可重试判定覆盖停止原因 | `Agent.run` 把模型异常转成 `stop_reason="error"`，`JobRunner` 必须显式重试该原因 |
| 进程内实现明确标注 | 缓存、幂等、限流、队列都不承诺跨进程语义；生产替换点写入正文与注释 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 响应缓存只做精确匹配 | 命中率低于语义缓存 | 高风险路径更安全；语义缓存需单独评估正确性 |
| 缓存与幂等存储都在进程内 | 多实例命中率下降，重启即丢失 | 生产替换为 Redis/数据库，接口不变 |
| 幂等存储没有原子占位 | 并发相同调用可能同时穿透 | 生产用唯一约束或 `SETNX` 占位“处理中” |
| 路由是长度启发式 | 长度不等于难度，可能误判 | 用评测集校准阈值或改用分类器 |
| 重试判定基于文本 | 不同 SDK 的错误类型可能漏判 | 生产接入服务商错误类或自定义 `retry_on` |
| 限流是单进程令牌桶 | 多实例总量等于实例数乘单桶速率 | 生产用全局限流器或网关 |
| 任务队列是内存实现 | 进程崩溃后无法恢复，无可见性超时 | 生产用 SQS/Redis/Temporal 等持久化队列 |
| 未实现熔断与检查点 | 上游持续故障时仍会尝试重试 | 后续生产实践可扩展；当前正文给出设计原则 |
| `JobRunner.drain` 顺序处理 | 单 worker 吞吐有限 | 生产由多个 worker 并发领取，存储层保证互斥 |
| 指标是近似值 | 客户端延迟、缓存命中口径依赖包装顺序 | 正文明确组合顺序与指标口径 |

### 验证

- `PYTHONPATH=src python3 examples/ch18_runtime.py` 输出与正文 18.7 一致：短请求第二次缓存命中，长请求路由到强模型，重试延迟 `[0.1, 0.2]`，成本 `$1.90`，幂等回放 `replay=True`，限流等待 1.0 秒，任务两次尝试后成功，快照 `llm_calls=3 cache_hit_rate=0.33 retries=2 cost=$2.22`
- `python3 -m pytest -q`：178 passed（原 155 条 + 新增 23 条运行时测试）
- `python3 -m compileall -q src examples`：通过
- 新增测试覆盖：缓存键稳定性与租户/温度隔离、命中返回副本、工具调用默认不缓存、TTL 与 LRU、长度路由与回退、主备切换、重试退避与非重试错误、最大尝试次数、工具重试的幂等约束、幂等去重与命名空间隔离、失败不缓存、规范化键、令牌桶、并发限制、限流等待指标、指标聚合、价格计算与延迟、任务重试与 `stop_reason="error"`、任务领取互斥、公开导出与版本
- 契约测试仍覆盖 `LLM.complete`、`Tool.run`、`ToolRegistry.run/run_many`、`Agent.run`、`ContextBuilder.build`、`StopPolicy.check` 与 `Budget` 默认值

### v1.4.0 实现清单（第 18 章）

| 文件 | 已实现内容 |
|---|---|
| `src/atlas/runtime/metrics.py` | `ModelPrice`、`RuntimeSnapshot`、`RuntimeMetrics`、`MeteredLLM` |
| `src/atlas/runtime/cache.py` | `ResponseCache`、`InMemoryResponseCache`、`response_cache_key`、`CachedLLM` |
| `src/atlas/runtime/routing.py` | `Router`、`LengthRouter`、`RoutingLLM`、`FallbackLLM` |
| `src/atlas/runtime/retry.py` | `RetryPolicy`、`is_retryable_error`、`RetryingLLM`、`RetryingTool` |
| `src/atlas/runtime/idempotency.py` | `IdempotencyStore`、`InMemoryIdempotencyStore`、`idempotency_key`、`IdempotentTool` |
| `src/atlas/runtime/limits.py` | `TokenBucket`、`ConcurrencyLimiter`、`RateLimitedLLM`、`RateLimitedTool` |
| `src/atlas/runtime/jobs.py` | `JobStatus`、`Job`、`JobStore`、`InMemoryJobStore`、`JobRunner` |
| `src/atlas/runtime/__init__.py` | 模块导出 |
| `src/atlas/__init__.py` | 导出运行时符号，版本改为 1.4.0 |
| `pyproject.toml` | 版本改为 1.4.0 |
| `examples/ch18_runtime.py` | 路由、缓存、重试、成本、幂等、限流、任务队列与指标快照 |
| `tests/test_runtime.py` | 23 条运行时包装器、存储、指标、任务与契约测试 |

{% hint style="success" %}
v1.4.0 代码已按本章清单写入仓库并验证（178 passed），所有运行时能力以实现 `LLM`/`Tool` 协议的包装器提供，未改动任何 v1.0.0 冻结接口。Atlas 第 19 章为产品设计章，不新增内核代码。
{% endhint %}

## 第 19 章变更（无代码变更）

### 新增 / 修改的类与接口

无。本章为产品设计章，不新增代码，不修改 `atlas/interfaces.md`，也不调整 `Agent`、`Tool`、`StopPolicy` 或任何运行时包装器。本章的工作是把已有产物映射为产品界面，并识别产品层需要的适配。

| 已有产物 | 产品层用途 | 本章是否新增接口 |
|---|---|---|
| `Trajectory` / `Step` | 任务时间线、步骤状态、证据与产物 | 否 |
| `TraceEvent` | 审计面板、回放、根因解释 | 否 |
| `EvalReport` | 质量说明、发布门禁、对外可靠性声明 | 否 |
| `RuntimeSnapshot` | 费用与延迟仪表、预算剩余 | 否 |
| `ApprovalHandler` | 审批收件箱、高风险动作确认 | 否 |
| `Job` / `JobRunner` | 后台任务列表、提交、轮询与重试 | 否 |
| `Guard` / `AuditLog` | 安全中心、拦截记录与追责 | 否 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 产品界面必须由结构化产物驱动 | `Trajectory`、`TraceEvent`、`RuntimeSnapshot` 保持字段化，不能只留下自由文本；否则进度、证据与费用面板无法稳定生成 |
| 解释的是动作与证据，不是隐藏推理 | 界面展示来源、假设、已执行动作与不确定性；不把供应商隐藏思维链当作可解释性产品 |
| 审批必须能表达拒绝与超时 | 产品层需要“批准 / 拒绝 / 超时暂停”三态；当前 `ApprovalHandler` 协议只约定决策结果，超时策略由调用方实现 |
| 任务生命周期要支持暂停、取消与接管 | `Job` 需要可查询状态与停止原因；工具的协作式取消是前提，不能只停前端动画 |
| 成本必须可按运行与租户归集 | `RuntimeSnapshot` 提供单次运行口径；租户、任务类型与账单维度由产品层在命名空间与外部计量中补齐 |
| 审计记录要可展示且可脱敏 | `AuditLog` 保留行为与结果；面向用户展示前必须做敏感信息裁剪 |
| 评测结论要有稳定标识 | `EvalReport` 应绑定模型、提示与评测集版本，才能支撑“这个版本更可靠”的对外声明 |
| 产品概念不进入内核 | 任务简报、定价、信任等级与界面文案属于产品层；不因此修改冻结接口或把业务字段塞进 `Agent` |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| Atlas 产物偏后端结构 | 不能直接渲染为产品界面，需要适配层做分组、分页与本地化 | 产品层增加 view model；内核仍只保证数据完整 |
| 指标是进程内聚合 | 无法直接作为账单或多租户结算依据 | 生产接入外部计量与计费系统，按 `run_id`、租户与任务类型归集 |
| `JobRunner` 没有暂停与接管 API | 后台任务的产品化中断需要额外封装，暂停不是一等状态 | 需要持久化队列与可恢复检查点；当前只保证重试与状态查询 |
| 审批协议较薄 | 没有内建超时、升级与多人审批 | 在 `ApprovalHandler` 实现中叠加策略，或由外部工作流系统承接 |
| Trace 面向调试 | 事件可能包含敏感内容，直接展示有泄露风险 | 展示前脱敏；区分“内部审计视图”与“用户解释视图” |
| 没有身份与租户模型 | 费用、审计与数据隔离的归属依赖调用方 | 生产在应用层注入租户上下文，并确保缓存与幂等命名空间包含租户 |
| 没有计费事件导出 | 无法直接生成发票或对账 | 以 `RuntimeSnapshot` 与调用日志为源，另建计费管线 |
| 评测是离线报告 | 线上信任信号仍需生产采样与人工反馈 | 把线上成功率、修改率与投诉纳入信任看板 |

### 验证

- 本章无代码变更，未修改 `src/`、`tests/`、`examples/` 或冻结接口。
- `python3 -m pytest -q`：178 passed，与第 18 章完成后一致。
- 正文中的 Atlas 符号已逐一核对：`Trajectory`、`TraceEvent`、`EvalReport`、`RuntimeSnapshot`、`ApprovalHandler`、`Job`、`JobRunner`、`Guard`、`AuditLog` 均存在于当前代码或冻结接口。
- 19.7.2 的映射表只描述“已有产物可以怎样被产品层消费”，不声称 Atlas 已自带前端、计费或租户系统。

## 第 20 章变更（无内核变更）

### 新增 / 修改的类与接口

无。本章为训练章，不修改 `src/`、`tests/` 或 `atlas/interfaces.md`，也不新增 `Policy`、`Environment`、`Reward` 等内核抽象。新增一个独立示例 `examples/ch20_agentic_rl.py`，只使用现有冻结符号：

| 已有符号 | 示例中的用途 | 是否新增接口 |
|---|---|---|
| `Trajectory` / `Step` / `Usage` | 记录每次 rollout 的步骤、工具调用、用量与终止原因 | 否 |
| `ToolSpec` / `ToolCall` / `ToolOutput` / `ToolRegistry` | 定义 search、read、answer 与危险的 `read_answer_key`，并执行授权 | 否 |
| `RunContext` / `Budget` | 为每轮 rollout 提供运行标识、元数据与步数预算 | 否 |
| `EvalTask` / `EvalRunner` / `ExactMatchEvaluator` / `EvalReport` | 在留出集上评测训练后的策略 | 否 |
| `utcnow` | 标记轨迹结束时间 | 否 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 训练示例必须在内核之外 | 策略、环境、奖励与训练循环全部放在 `examples/`；内核只提供轨迹、工具与评测原语，避免把训练框架塞进 `atlas` |
| 策略不只是模型权重 | 示例用表格型 softmax 表示“计划选择器”，说明提示、工具集、解码参数与上下文同样属于策略；不因此新增 `Policy` 接口 |
| 轨迹必须同时服务训练与评测 | 同一个 `Trajectory` 既产出 rollout 奖励，也交给 `EvalRunner`，避免训练与评测两套记录 |
| 危险工具需要显式授权 | `read_answer_key` 标记 `dangerous=True`，示例显式 `allow_dangerous=True` 以演示风险；生产环境应拒绝或走审批 |
| 奖励与护栏必须分离 | 奖励中的 `unsafe_penalty` 只是软信号；真正的安全边界由第 17 章的 `Guard`、审批与沙箱承担 |
| 训练与评测必须隔离 | 训练任务与留出任务分开生成；训练采样、评测取 argmax，评测集不参与训练与奖励调参 |
| 保持离线可运行 | 示例只依赖标准库与 Atlas，不引入分布式训练、GPU 或外部服务依赖 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 示例不训练语言模型 | 策略只是四个计划的 softmax，无法验证令牌级训练效果 | 真实 LLM 的 RL 需要训练基础设施，超出本书示例范围 |
| 奖励是人工设计的 | 没有过程奖励模型、偏好数据与 KL 惩罚 | 用于讲清机制，不用于证明算法优劣 |
| 环境是确定性的 | 没有网页漂移、外部 API 超时与并发 | 真实环境需要快照、隔离、超时与异步 rollout |
| 评测集很小 | 每类仅 4 个留出任务，不能证明泛化 | 结论只用于对比 outcome-only 与 shaped+safe 两种配置 |
| 结果对随机种子敏感 | 示例固定 11/13/17/19 便于复现 | 生产需要多种子、置信区间与回归评测 |

### 验证

- `PYTHONPATH=src python3 examples/ch20_agentic_rl.py` 输出与正文 20.8.6 一致：

```text
训练前：pass_rate=0.50

outcome-only 训练后：pass_rate=1.00 evidence=0/8 unsafe=4/8
  easy: direct=1.00, search_only=0.00, search_read=0.00, peek=0.00
  hard: direct=0.00, search_only=0.00, search_read=0.00, peek=1.00

shaped+safe 训练后：pass_rate=1.00 evidence=4/8 unsafe=0/8
  easy: direct=1.00, search_only=0.00, search_read=0.00, peek=0.00
  hard: direct=0.00, search_only=0.00, search_read=1.00, peek=0.00
```

- `python3 -m pytest -q`：178 passed，与第 19 章完成后一致。
- 未修改 `src/`、`tests/` 或 `atlas/interfaces.md`；示例仅依赖既有冻结接口。
- 正文中的 Atlas 符号已核对：`Trajectory`、`Step`、`ToolSpec`、`ToolRegistry`、`RunContext`、`Budget`、`Usage`、`EvalTask`、`EvalRunner`、`ExactMatchEvaluator`、`EvalReport`、`utcnow` 均存在。

### 示例实现清单（第 20 章）

| 文件 | 内容 |
|---|---|
| `examples/ch20_agentic_rl.py` | `ResearchEnv`、`SearchTool` / `ReadTool` / `AnswerTool` / `AnswerKeyTool`、`TabularPolicy`、`PolicyAgent`、`RewardConfig`、`compute_reward`、`train`、`evaluate`、`audit`、`main` |

## 第 21 章变更（无代码变更）

### 新增 / 修改的类与接口

无。本章为未来趋势与全书回顾章，不修改 `src/`、`tests/`、`examples/` 或 `atlas/interfaces.md`，也不新增可运行代码。正文引用的 Atlas 符号只用于回顾既有版本演进，均为已冻结或已实现的概念：

| 符号 | 在正文中的位置 | 说明 | 是否新增接口 |
|---|---|---|---|
| `Agent` / `ToolRegistry` / `build_app` | 21.7 演进路线 | 说明内核接口在 v0.4.0–v1.4.0 间保持稳定 | 否 |
| `Trajectory` / `TraceEvent` | 21.7、全书不变量 | 轨迹作为评测、调试、训练与审计的共同单位 | 否 |
| `Budget` / `RunContext` | 21.1 状态模型、21.7 | 长时程中的预算与运行上下文边界 | 否 |
| `EvalReport` / `EvalRunner` | 21.2、21.3 评测与门禁 | 持续学习与自我改进的留出集评测 | 否 |
| `Guard` / `ApprovalHandler` / `AuditLog` | 21.1、21.3 权限与审计 | 权限蠕变、提出与批准分离、可追溯 | 否 |
| `IdempotentTool` / `JobRunner` / `RuntimeSnapshot` | 21.1 检查点与幂等、21.7 | 运行时幂等、任务状态与运行快照的现有能力边界 | 否 |

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 长时程状态必须能在进程之外持久化 | 当前 `RunContext`、`Budget` 与 `Trajectory` 是进程内对象；跨天执行需要外部任务记录、对象存储与事件日志，内核不承担持久化 |
| 检查点必须落在可验证的步骤边界 | `Trajectory` 的步骤记录提供了边界数据，但“验证通过才检查点”的策略由运行时或应用层实现，不进入 `Agent.run` |
| 幂等要靠回执而不是模型自述 | `IdempotentTool` 的幂等键用于工具层去重；承诺台账需要读取外部回执，不能把模型文本当作副作用已发生的证据 |
| 恢复不是重放 | `Trajectory` 可回放用于调试；生产恢复必须先重新校验环境、权限、预算与外部状态，回放不等于恢复 |
| 经验优先进入记忆与工具，最后才进权重 | 第 7 章的记忆接口、第 5 章的工具注册表与第 20 章的示例构成回流路径；内核不新增“学习”接口 |
| 自我改进必须按发布治理 | 复用 `EvalRunner`、`Guard`、`AuditLog` 与运行时监控；提出、评估、门禁、灰度、回滚属于流程与平台能力，不塞进 `Agent` |
| 多 Agent 与 Agent 经济属于应用与制度层 | 编排、身份、支付、SLA、声誉不进入冻结接口；Atlas 只保证单次运行与轨迹的可审计 |
| 内核保持零变更完成收束 | 第 19–21 章都不新增内核代码，保证前 18 章的接口契约在全书结束时仍然成立 |

### 已知取舍

| 取舍 | 影响 | 后续 |
|---|---|---|
| 没有持久化检查点存储 | 进程重启后无法直接恢复长时程任务 | 由生产运行时接入数据库、对象存储与事件日志；内核只保留轨迹结构 |
| `JobRunner` 没有暂停与恢复 API | 后台任务只能重试与查询状态，不能跨进程挂起 | 需要持久化队列与可恢复检查点，属于运行时扩展 |
| 没有承诺台账与外部回执模型 | 重复副作用只能依赖工具层幂等键与外部系统去重 | 应用层建立承诺记录，读取支付、邮件等系统的回执 |
| 没有身份、支付与声誉抽象 | Agent 经济的四个基础设施均不在内核中 | 由企业身份系统、计费平台与合同流程承接 |
| 没有持续学习评测集与回滚编排 | 自我改进只能借用通用评测与发布流程 | 需要专门的回归集、能力回收清单与灰度平台 |
| 长时程可靠性未在代码中验证 | 本章的状态机、幂等键与恢复协议是设计方法，不是已实现能力 | 若后续新增实现版本，应优先补持久化检查点与恢复校验 |

### 验证

- 本章无代码变更，未修改 `src/`、`tests/`、`examples/` 或 `atlas/interfaces.md`。
- `python3 -m pytest -q`：178 passed，与第 20 章完成后一致。
- 正文中的 Atlas 符号已核对：`Agent`、`ToolRegistry`、`build_app`、`Trajectory`、`TraceEvent`、`Budget`、`RunContext`、`EvalReport`、`EvalRunner`、`Guard`、`ApprovalHandler`、`AuditLog`、`IdempotentTool`、`JobRunner`、`RuntimeSnapshot` 均存在于当前代码或冻结接口。
- 21.7 的演进路线表只回顾已交付版本；第 19–21 章统一标注为无内核变更或无代码变更，不虚构新版本号。

## 附录 B 变更（无代码变更）

### 新增 / 修改的类与接口

无。本附录不修改 `src/atlas`、`tests/` 或 `atlas/interfaces.md`；Atlas 版本保持 v1.4.0。

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 速查表复用既有选型接口 | 只使用 v0.11.0 的 `FrameworkProfile`、`Requirements`、`select_frameworks` 与 `examples/ch11_frameworks.py` 的画像 |
| 不引入新的框架依赖 | 附录不要求安装 LangGraph、Dify 等外部组件；示例保持离线可复现 |
| 不把工具清单写进内核 | 工具与平台属于集成选择，核心 `Agent`、`Tool`、`AgentRunner` 不变 |
| 选型结论必须可解释 | 继续沿用“硬约束过滤、偏好排序、同分按名称排序”的确定性规则 |
| 退出成本是选型的一等维度 | 适配层与契约测试仍是保留选择权的手段，不在附录中改为直接依赖框架类型 |

### 兼容性

无接口变更，无破坏性修改。B.9 的脚本直接导入 `examples.ch11_frameworks.profiles`，验证了 v0.11.0 的选型符号仍可从 `atlas` 顶层导入；`Agent`、`ToolRegistry`、`build_app`、`Trajectory` 等冻结签名未受影响。

### 验证

- 本附录无代码变更，未修改 `src/`、`tests/`、`examples/` 或 `atlas/interfaces.md`。
- `PYTHONPATH=src:. python3` 运行 B.9 脚本，输出 `Google ADK` 与 `LangGraph` 两个候选，分数均为 2.75，与第 11 章画像一致。
- `python3 -m pytest -q`：178 passed，与第 21 章完成后一致。
- 表格中的框架定位与第 11 章正文一致；未新增版本号、价格或基准分数。

## 附录 C 变更（无代码变更）

### 新增 / 修改的类与接口

无。本附录不修改 `src/atlas`、`tests/` 或 `atlas/interfaces.md`；Atlas 版本保持 v1.4.0。C.12 中的 `PaperCard` 是附录内的独立 Python 片段，不进入 Atlas 内核。

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 论文清单不引入运行时依赖 | 附录只做阅读索引，不新增 `src/` 模块，也不要求安装论文代码或基准环境 |
| 论文结论映射到既有模块 | 每篇论文标注对应章节；可复用设计回到 `Agent.run`、`Step`、`ToolRegistry`、`Trajectory` 等既有符号 |
| 不把评测基准写进内核 | SWE-bench、τ-bench 等只作为评测设计参照，Atlas 的 `EvalRunner` 与 `EvalReport` 签名不变 |
| 安全论文对应既有边界 | 注入、权限与隔离仍落在第 17 章的护栏、审批与沙箱，不新增安全接口 |
| 论文卡保持可复现 | C.12 的脚本只用标准库 `dataclasses`，可直接在 Atlas 的 Python 环境中运行 |

### 兼容性

无接口变更，无破坏性修改。附录中的论文结论与正文引用一致，未新增版本号、基准分数或未经验证的实验结论。C.12 的 `PaperCard` 与 Atlas 命名空间隔离，不影响 `Agent`、`AgentRunner`、`ToolRegistry`、`Trajectory`、`EvalRunner` 等冻结签名。

### 验证

- 本附录无代码变更，未修改 `src/`、`tests/`、`examples/` 或 `atlas/interfaces.md`。
- C.12 的论文卡脚本已验证可运行，输出为“缺字段: 无”。
- `python3 -m pytest -q`：178 passed，与第 21 章完成后一致。
- 论文标题、年份与一句话结论按公开原文整理；本附录不提供链接、编号与具体分数，使用前需核对原文。

## 附录 D 变更（无代码变更）

### 新增 / 修改的类与接口

无。本附录不修改 `src/atlas`、`tests/` 或 `atlas/interfaces.md`；Atlas 版本保持 v1.4.0。D.9 中的 `ResourceCard` 是附录内的独立 Python 片段，不进入 Atlas 内核。

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 资源清单不引入运行时依赖 | 附录只做阅读索引，不新增 `src/` 模块，也不要求安装追踪、网关或评测工具 |
| 文档与代码分开定位 | 官方文档回答接口，官方代码验证路径；Atlas 的模块边界不因外部资源变化而调整 |
| 不固化链接与版本 | 正文只给资源名称、官方入口与判断标准；版本锁定由使用方在项目中完成，不写进内核 |
| 资源卡与内核隔离 | `ResourceCard` 只用标准库 `dataclasses`，不导入 `atlas`，也不改变冻结签名 |
| 生产工具按类别而非品牌 | 可观测、安全与网关只列类别与验证点，避免把产品选择写成框架约束 |

### 兼容性

无接口变更，无破坏性修改。附录 D 与附录 B、C 的定位互补：B 回答“选什么框架与工具”，C 回答“读哪些论文”，D 回答“去哪里找、如何维护”。`Agent`、`AgentRunner`、`ToolRegistry`、`Trajectory`、`EvalRunner` 等冻结签名未受影响。

### 验证

- 本附录无代码变更，未修改 `src/`、`tests/`、`examples/` 或 `atlas/interfaces.md`。
- D.9 的资源卡脚本已验证可运行，输出为“缺字段: 无”。
- `python3 -m pytest -q`：178 passed，与第 21 章完成后一致。
- 正文未给出深链接、价格、配额或未经验证的产品功能；资源名称与官方入口以写作时的公开信息为准。

## 附录 E 变更（无代码变更）

### 新增 / 修改的类与接口

无。本附录不修改 `src/atlas`、`tests/`、`examples/` 或 `atlas/interfaces.md`；Atlas 版本保持 v1.4.0。E.3 的 `build_app` 调用、E.4 的 `AtlasConfig.from_env` 与 E.6 的 pytest 命令都只使用既有公开接口。

### 本章对 Atlas 的设计约束

| 约束 | 对实现的影响 |
|---|---|
| 运行指南不新增运行时依赖 | 离线路径只依赖标准库；`openai` 与 `pytest` 仍是可选/开发依赖，`pyproject.toml` 不变 |
| 命令与仓库版本一致 | 安装方式、CLI 参数、环境变量默认值、示例与 `178 passed` 基线均按 v1.4.0 实测 |
| 离线与真实模型边界清晰 | 离线走 `scripted_llm()`/`MockLLM`，真实模型走 `OpenAICompatLLM`；不把离线结果当作模型能力证明 |
| 预算先收紧再放开 | 指南要求先设小 `max_steps`、`max_tool_calls` 与 `max_cost_usd`，确认轨迹后再放开 |
| 密钥不进入代码与仓库 | 配置只从 `ATLAS_*` 环境变量读取，文档不给出硬编码密钥的示例 |
| 冻结接口不变 | `build_app`、`AtlasConfig`、`Budget`、`Trajectory` 等签名未改，附录只调用 |

### 兼容性

无接口变更，无破坏性修改。附录 E 与 B、C、D 定位互补：B 回答“选什么框架与工具”，C 回答“读哪些论文”，D 回答“去哪里找、如何维护”，E 回答“如何把仓库跑起来并验证改动”。E.5 的源码目录映射与第 4–18 章模块一致；E.4 的默认值与 `AtlasConfig`、`Budget` 的字段一致。

### 验证

- 本附录无代码变更，未修改 `src/`、`tests/`、`examples/` 或 `atlas/interfaces.md`。
- `python3 -m pytest -q`：`178 passed in 0.50s`，与第 21 章完成后一致。
- `PYTHONPATH=src python3 -m atlas --offline`：输出 `final_answer`、2 步、1 次工具调用、968 令牌、3 条引用与 2 条长期记忆，与 E.5 的示例一致。
- `PYTHONPATH=src python3 examples/ch04_single_tool.py`：退出码 0，`calculator` 返回 400，`stop_reason=final_answer`。
- `PYTHONPATH=src python3 examples/ch12_langgraph.py`：退出码 0，未安装依赖时打印“需要可选依赖：pip install langgraph”。
- 验证环境为 Python 3.13.12、pytest 9.0.3；文档声明的最低版本为 Python 3.11。
- 文中命令均在仓库根目录执行；MCP 服务器无输出、LangGraph 示例缺少可选依赖均按预期行为记录。
