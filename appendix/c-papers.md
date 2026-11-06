# 附录 C 必读论文清单

{% hint style="info" %}
本清单是主干路线，不是论文综述。选文标准只有三条：与本书的问题链直接相关；提供了可复用的设计或评测方法；有公开的方法与实验细节。清单按主题分组，每篇给出一句话结论、对应章节与读法。论文的作者、年份、标题与实验结论请以原文为准；本附录不提供链接与编号，按标题检索即可。
{% endhint %}

## 本章导读

面对几百篇 Agent 论文，最有效的读法不是从最新开始，而是沿着问题链读：Agent 如何定义，如何推理，如何用工具，如何记忆，如何协作，如何评测，如何安全，如何训练，如何走向长时程。本附录给出约 80 篇的主干路线，并标出每一篇该读到什么程度。

⭐⭐ 进阶 ｜ 适合：工程师、研究者、技术负责人

## 学习目标

读完本附录你将能够：

- 按主题建立 Agent 论文地图，而不是按年份堆叠阅读
- 区分奠基论文、方法论文、基准论文与工程报告，知道各自该信什么
- 用一张“论文卡”提取可复用设计，而不是只记住分数
- 把论文假设映射到 Atlas 的模块、评测与安全边界
- 识别论文结论的适用条件，避免把实验设置当成通用规律

## C.1 怎么用这份清单

论文大致分四类，读法不同：

| 类型 | 回答的问题 | 读法 | 常见误用 |
|---|---|---|---|
| 奠基论文 | 这个概念从哪来，边界是什么 | 选读摘要、定义与讨论 | 把几十年前的假设直接套到 LLM |
| 方法论文 | 它用什么机制解决什么问题 | 精读方法、实验、消融与局限 | 只看主结果，不看基线与失败案例 |
| 基准论文 | 它衡量什么，判定是否可靠 | 工具书式查阅，必要时跑子集 | 把榜单分数当产品能力 |
| 工程报告 | 真实系统如何取舍与踩坑 | 选读架构、失败模式与成本 | 把一家公司的内部数据当普遍结论 |

本清单用三种标记：

- **精读**：读方法、实验、消融与局限，最好复现一个小实验。
- **选读**：读摘要、方法图与结论，知道它解决什么问题、代价是什么。
- **工具书**：需要时查指标定义、任务构造与判定细节。

同一篇论文，投入时间不同，读法也不同：

{% tabs %}
{% tab title="15 分钟" %}
读标题、摘要、方法图与结论，只回答三个问题：它解决什么问题、核心机制是什么、作者自己承认的局限是什么。这一步的目标是建立索引，不是下结论。
{% endtab %}

{% tab title="1 小时" %}
加读引言、方法、主实验表与消融，重点看基线与实验设置：模型、提示、预算、数据规模是否和你的场景可比。写一张半成品论文卡，把还不确定的地方标出来。
{% endtab %}

{% tab title="半天" %}
精读方法、实验、消融、局限与失败案例，最好复现一个小实验或跑一个子集。目标不是记住结论，而是判断“这个机制迁移到我的任务时，哪条假设会先坏”。
{% endtab %}
{% endtabs %}

如果时间有限，先读这 12 篇，它们覆盖本书的主干：

| 主题 | 论文 | 编号 |
|---|---|---|
| 推理 | Chain-of-Thought Prompting | P10 |
| 循环 | ReAct | P13 |
| 工具 | Toolformer | P14 |
| 检索 | Retrieval-Augmented Generation | P22 |
| 上下文 | Lost in the Middle | P26 |
| 记忆 | Generative Agents | P30 |
| 记忆管理 | MemGPT | P31 |
| 编码评测 | SWE-bench | P47 |
| 可靠性评测 | τ-bench | P49 |
| 安全 | CaMeL | P61 |
| 训练 | DeepSeek-R1 | P70 |
| 长时程 | METR 时间跨度 | P77 |

```mermaid
flowchart LR
    A[基础<br/>Agent / RL / Transformer] --> B[推理与工具<br/>CoT / ReAct / Toolformer]
    B --> C[记忆与检索<br/>RAG / MemGPT / 上下文]
    C --> D[多智能体<br/>角色 / 辩论 / 编排]
    D --> E[应用<br/>编码 / 网页 / 计算机]
    E --> F[评测与可观测<br/>基准 / 轨迹 / 成本]
    F --> G[安全<br/>注入 / 权限 / 隔离]
    G --> H[训练<br/>RLHF / RLVR / Agentic RL]
    H --> I[长时程与自我改进<br/>时间跨度 / 门禁]
```

## C.2 基础与智能体概念

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P01 | Computing Machinery and Intelligence（Turing，1950） | 用“模仿游戏”提出机器智能的判据问题，提醒我们“像人说话”不等于“能完成任务”。 | 第 1、2 章 | 选读 |
| P02 | STRIPS: A New Approach to the Application of Theorem Proving to Problem Solving（Fikes & Nilsson，1971） | 用前提、动作与效果描述规划，奠定符号规划的基本形式。 | 第 2 章 | 选读 |
| P03 | Computer-Based Medical Consultations: MYCIN（Shortliffe，1976） | 用规则与不确定性推理做医学诊断，展示专家系统的能力与知识获取瓶颈。 | 第 2 章 | 选读 |
| P04 | BDI Agents: From Theory to Practice（Rao & Georgeff，1995） | 把信念、愿望、意图形式化，BDI 成为经典 Agent 架构。 | 第 1、2 章 | 精读 |
| P05 | Intelligent Agents: Theory and Practice（Wooldridge & Jennings，1995） | 系统讨论 Agent 的定义、属性与理论，是“什么是 Agent”的经典入口。 | 第 1 章 | 精读 |
| P06 | Human-level Control through Deep Reinforcement Learning（Mnih 等，2015） | DQN 用深度网络从像素学习控制策略，开启深度强化学习。 | 第 2 章 | 选读 |
| P07 | Mastering the Game of Go with Deep Neural Networks and Tree Search（Silver 等，2016） | AlphaGo 结合策略网络、价值网络与树搜索，展示搜索与学习结合的力量。 | 第 2 章 | 选读 |
| P08 | Attention Is All You Need（Vaswani 等，2017） | Transformer 用自注意力替代循环结构，成为现代大语言模型的基础。 | 第 3 章 | 精读 |
| P09 | Language Models are Few-Shot Learners（Brown 等，2020） | GPT-3 展示规模化预训练与上下文学习，让“语言作为统一接口”成为可能。 | 第 3 章 | 精读 |

## C.3 推理、规划与工具使用

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P10 | Chain-of-Thought Prompting Elicits Reasoning in Large Language Models（Wei 等，2022） | 让模型先写推理步骤再给答案，显著改善多步推理；但推理链不等于可执行计划。 | 第 3、6 章 | 精读 |
| P11 | Self-Consistency Improves Chain of Thought Reasoning in Language Models（Wang 等，2022） | 对多条推理路径采样并投票，用一致性换正确率，代价是多次调用。 | 第 6 章 | 精读 |
| P12 | Least-to-Most Prompting Enables Complex Reasoning in Large Language Models（Zhou 等，2022） | 先把问题拆成子问题再逐个求解，是显式分解的早期代表。 | 第 6 章 | 选读 |
| P13 | ReAct: Synergizing Reasoning and Acting in Language Models（Yao 等，2022） | 把思考与行动交替，观察驱动下一步推理，是 Agent 循环的直接来源。 | 第 4、6 章 | 精读 |
| P14 | Toolformer: Language Models Can Teach Themselves to Use Tools（Schick 等，2023） | 让模型自监督学习何时调用 API 以及如何填参，展示工具调用的可学习性。 | 第 3、5 章 | 精读 |
| P15 | Gorilla: Large Language Model Connected with Massive APIs（Patil 等，2023） | 让模型通过检索文档调用大量 API，强调 API 描述与参数生成的准确性。 | 第 5 章 | 选读 |
| P16 | Plan-and-Solve Prompting: Improving Zero-Shot Chain-of-Thought Reasoning by Large Language Models（Wang 等，2023） | 先制定计划再执行，把“规划”从推理链中显式分离出来。 | 第 6 章 | 精读 |
| P17 | Tree of Thoughts: Deliberate Problem Solving with Large Language Models（Yao 等，2023） | 把推理组织成树搜索，用评估与回溯探索多条路径，成本随分支与深度增长。 | 第 6 章 | 精读 |
| P18 | Reflexion: Language Agents with Verbal Reinforcement Learning（Shinn 等，2023） | 用语言化反馈总结失败并写入记忆，在下一轮尝试中改进；依赖可靠的成功信号。 | 第 6 章 | 精读 |
| P19 | Self-Refine: Iterative Refinement with Self-Feedback（Madaan 等，2023） | 让模型生成、批评并修订自己的输出，无需额外训练，但容易陷入自我确认。 | 第 6 章 | 选读 |
| P20 | Executable Code Actions Elicit Better LLM Agents（CodeAct，Wang 等，2024） | 用可执行代码表达动作，把多步工具组合压缩成一次代码生成，扩大行动空间也扩大风险。 | 第 12、13 章 | 精读 |
| P21 | SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering（Yang 等，2024） | 设计面向 Agent 的计算机接口，用查看、搜索与编辑命令提升仓库任务成功率。 | 第 13 章 | 精读 |

## C.4 记忆、检索与上下文

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P22 | Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks（Lewis 等，2020） | 把检索器与生成器结合，用外部文档缓解知识密集任务的事实错误。 | 第 8 章 | 精读 |
| P23 | Dense Passage Retrieval for Open-Domain Question Answering（Karpukhin 等，2020） | 用双塔稠密向量做段落检索，证明语义检索可以超过稀疏检索。 | 第 8 章 | 精读 |
| P24 | The Probabilistic Relevance Framework: BM25 and Beyond（Robertson & Zaragoza，2009） | 系统总结 BM25 概率相关性框架，是词法检索的工程基线。 | 第 8 章 | 工具书 |
| P25 | Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods（Cormack 等，2009） | 用倒数排名融合多路检索结果，不依赖分数可比性，适合混合检索。 | 第 8 章 | 精读 |
| P26 | Lost in the Middle: How Language Models Use Long Contexts（Liu 等，2023） | 发现长上下文模型对中段信息利用最差，说明“窗口大”不等于“有效上下文大”。 | 第 9 章 | 精读 |
| P27 | Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection（Asai 等，2023） | 让模型学习何时检索、评估证据并自我批判，把检索变成可学习的决策。 | 第 8 章 | 精读 |
| P28 | Corrective Retrieval Augmented Generation（CRAG，Yan 等，2024） | 在检索后评估证据质量，必要时触发纠正检索，强调检索结果不是终点。 | 第 8 章 | 选读 |
| P29 | From Local to Global: A Graph RAG Approach to Query-Focused Summarization（Edge 等，2024） | 用实体关系图与社区摘要回答全局性问题，补片段检索的聚合盲区。 | 第 8 章 | 选读 |
| P30 | Generative Agents: Interactive Simulacra of Human Behavior（Park 等，2023） | 用记忆流、重要性与反思组织长期行为，是记忆分层与巩固的经典来源。 | 第 7 章 | 精读 |
| P31 | MemGPT: Towards LLMs as Operating Systems（Packer 等，2023） | 把上下文管理类比为操作系统分页，让模型主动在内存与外部存储间调度。 | 第 7、9 章 | 精读 |
| P32 | Voyager: An Open-Ended Embodied Agent with Large Language Models（Wang 等，2023） | 在开放环境中把验证过的技能写成代码存入技能库，展示程序性记忆与持续学习。 | 第 2、7 章 | 选读 |
| P33 | LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Models（Jiang 等，2023） | 用小型模型压缩提示词，在尽量保留任务效果的同时降低 token 成本。 | 第 9 章 | 选读 |

## C.5 多智能体协作

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P34 | CAMEL: Communicative Agents for “Mind” Exploration of Large Language Model Society（Li 等，2023） | 用角色扮演与对话让两个 Agent 协作完成任务，展示角色契约的早期形态。 | 第 10 章 | 选读 |
| P35 | AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation（Wu 等，2023） | 把多 Agent 对话抽象成可编程的会话与执行器，支持工具与人类参与。 | 第 10 章 | 精读 |
| P36 | MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework（Hong 等，2023） | 把软件公司的标准流程编码进多 Agent 流程，用结构化产物减少协作漂移。 | 第 10 章 | 精读 |
| P37 | Improving Factuality and Reasoning in Language Models through Multiagent Debate（Du 等，2023） | 让多个模型实例相互辩论并由裁判综合，提升事实性与推理表现。 | 第 10 章 | 精读 |
| P38 | Communicative Agents for Software Development（ChatDev，Qian 等，2023） | 用角色化多 Agent 流水线模拟软件开发，展示阶段化交接与产物链。 | 第 10 章 | 选读 |

## C.6 编码、网页与计算机操作

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P39 | WebGPT: Browser-assisted Question-Answering with Human Feedback（Nakano 等，2021） | 让模型通过浏览器检索、引用来源并用人类反馈优化长答案，是深度研究的早期形态。 | 第 13 章 | 精读 |
| P40 | Mind2Web: Towards a Generalist Agent for the Web（Deng 等，2023） | 构建真实网页上的通用 Agent 数据集，强调跨网站泛化。 | 第 14、15 章 | 工具书 |
| P41 | WebVoyager: Building an End-to-End Web Agent with Large Multimodal Models（He 等，2024） | 用多模态模型端到端操作真实网站，并以任务成功率评估。 | 第 14、15 章 | 选读 |
| P42 | GPT-4V(ision) is a Generalist Web Agent, if Grounded（SeeAct，Zheng 等，2024） | 研究视觉定位对网页 Agent 的影响，指出“看得见”不等于“点得准”。 | 第 14 章 | 精读 |
| P43 | Set-of-Mark Prompting Unleashes Extraordinary Visual Grounding in GPT-4V（Yang 等，2023） | 在截图上叠加可点击标记，显著改善多模态模型的视觉定位。 | 第 14 章 | 选读 |
| P44 | Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models（STORM，Shao 等，2024） | 用多视角提问与检索合成主题大纲，展示研究型写作的结构化流程。 | 第 13 章 | 精读 |
| P45 | UI-TARS: Pioneering Automated GUI Interaction with Native Agents（Qin 等，2025） | 用原生 GUI Agent 模型统一感知、定位与动作，代表端到端界面操作路线。 | 第 14 章 | 选读 |

## C.7 评测、基准与可观测

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P46 | Evaluating Large Language Models Trained on Code（Chen 等，2021） | 提出代码生成基准与 pass@k 估计，区分能力上限与可靠性。 | 第 15 章 | 精读 |
| P47 | SWE-bench: Can Language Models Resolve Real-World GitHub Issues?（Jimenez 等，2023） | 用真实仓库 issue 与测试评估补丁，把编码 Agent 推向可执行验证。 | 第 13、15 章 | 精读 |
| P48 | GAIA: A Benchmark for General AI Assistants（Mialon 等，2023） | 用需要浏览与工具的多步问题评估通用助手，强调现实性与难度分级。 | 第 15 章 | 精读 |
| P49 | τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains（Yao 等，2024） | 在带模拟用户与领域工具的环境中评估多轮任务，提出 pass^k 可靠性指标。 | 第 15、20 章 | 精读 |
| P50 | WebArena: A Realistic Web Environment for Building Autonomous Agents（Zhou 等，2023） | 提供可复现的自托管网站环境，评估网页 Agent 的端到端完成能力。 | 第 14、15 章 | 工具书 |
| P51 | OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments（Xie 等，2024） | 在真实桌面环境中评估 Computer Use，覆盖开放任务与多应用协作。 | 第 14、15 章 | 工具书 |
| P52 | AgentBench: Evaluating LLMs as Agents（Liu 等，2023） | 用多环境任务评估 LLM 作为 Agent 的综合能力，暴露工具使用与长程规划短板。 | 第 15 章 | 选读 |
| P53 | Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena（Zheng 等，2023） | 系统分析模型评委的位置、冗长与自我偏好偏差，是评委校准的必读。 | 第 15 章 | 精读 |
| P54 | AI Agents That Matter（Kapoor 等，2024） | 批评只看准确率的评测，主张同时报告成本、可靠性与复现性。 | 第 15 章 | 精读 |
| P55 | Agent-as-a-Judge: Evaluate Agents with Agents（Zhuge 等，2024） | 用 Agent 评估 Agent 的过程与产物，探索轨迹级自动评测。 | 第 15 章 | 选读 |
| P56 | Dapper, a Large-Scale Distributed Systems Tracing Infrastructure（Sigelman 等，2010） | 大规模分布式追踪的经典设计，为 Agent Trace 的父子 Span 提供参照。 | 第 16 章 | 选读 |
| P57 | The Tail at Scale（Dean & Barroso，2013） | 解释尾延迟放大与并行扇出的代价，是生产化延迟设计的必读。 | 第 18 章 | 精读 |

## C.8 安全、注入与可控

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P58 | Ignore Previous Prompt: Attack Techniques For Language Models（Perez & Ribeiro，2022） | 系统展示直接提示注入的攻击面，说明“指令”与“数据”共享通道的风险。 | 第 17 章 | 精读 |
| P59 | Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection（Greshake 等，2023） | 把恶意指令藏进网页、文档或工具结果，揭示 Agent 的间接注入路径。 | 第 17 章 | 精读 |
| P60 | AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents（Debenedetti 等，2024） | 提供动态环境评估 Agent 的注入攻击与防御，把安全评测做成可复现任务。 | 第 17 章 | 精读 |
| P61 | Defeating Prompt Injections by Design（CaMeL，Debenedetti 等，2025） | 用双 LLM 与能力令牌分离规划与数据访问，展示“数据流控制”而非内容检测的路线。 | 第 17 章 | 精读 |
| P62 | Llama Guard: LLM-based Input-Output Safeguard for Human-AI Conversations（Inan 等，2023） | 用 LLM 做输入输出安全分类，展示护栏模型的能力与误拒代价。 | 第 17 章 | 选读 |
| P63 | Constitutional AI: Harmlessness from AI Feedback（Bai 等，2022） | 用原则与 AI 反馈训练无害性，说明安全对齐的训练路径。 | 第 17 章 | 选读 |
| P64 | Red Teaming Language Models with Language Models（Perez 等，2022） | 用模型自动生成对抗测试，降低人工红队成本。 | 第 17 章 | 选读 |

## C.9 训练、偏好优化与 Agentic RL

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P65 | Deep Reinforcement Learning from Human Preferences（Christiano 等，2017） | 用人类偏好训练奖励模型，再用强化学习优化策略，奠定 RLHF 的基本结构。 | 第 20 章 | 精读 |
| P66 | Training Language Models to Follow Instructions with Human Feedback（InstructGPT，Ouyang 等，2022） | 把监督微调、奖励模型与 PPO 组合成指令遵循训练流程，是后训练的工程范式。 | 第 20 章 | 精读 |
| P67 | Proximal Policy Optimization Algorithms（Schulman 等，2017） | 用裁剪目标限制策略更新幅度，成为 RLHF 最常用的在线算法之一。 | 第 20 章 | 精读 |
| P68 | Direct Preference Optimization: Your Language Model is Secretly a Reward Model（Rafailov 等，2023） | 直接用偏好对优化策略，省掉显式奖励模型与在线 RL，工程上更易落地。 | 第 20 章 | 精读 |
| P69 | DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models（Shao 等，2024） | 提出 GRPO，用组内相对优势替代价值模型，降低 RL 成本，适合可验证奖励。 | 第 20 章 | 精读 |
| P70 | DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning（DeepSeek-AI，2025） | 展示纯强化学习、冷启动 SFT、拒绝采样与蒸馏的组合，激发可验证任务上的推理行为。 | 第 3、20 章 | 精读 |
| P71 | Let's Verify Step by Step（Lightman 等，2023） | 用过程奖励模型对每一步打分，比只看结果提供更密的信用信号。 | 第 20 章 | 精读 |
| P72 | STaR: Bootstrapping Reasoning With Reasoning（Zelikman 等，2022） | 用模型自己生成的理由与正确答案自举训练，展示自我训练的基本循环。 | 第 20 章 | 选读 |
| P73 | Reinforced Self-Training (ReST) for Language Modeling（Gulcehre 等，2023） | 用拒绝采样筛选成功轨迹再做监督微调，是 Agentic RL 常用的冷启动与迭代方法。 | 第 20 章 | 精读 |
| P74 | RAFT: Reward rAnked FineTuning for Generative Foundation Model Alignment（Dong 等，2023） | 用奖励排序筛选样本做微调，降低对齐对在线 RL 的依赖。 | 第 20 章 | 选读 |
| P75 | SWE-Gym: A Scalable Environment for Training Software Engineering Agents（Pan 等，2024） | 构建可执行的软件工程训练环境，把真实仓库任务变成可复现的 RL 环境。 | 第 20 章 | 精读 |
| P76 | Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters（Snell 等，2024） | 研究推理时计算的最优分配，说明“多想”与“换更大模型”的取舍。 | 第 3、20 章 | 精读 |

## C.10 长时程、自我改进与未来

| 编号 | 论文 | 一句话结论 | 章节 | 读法 |
|---|---|---|---|---|
| P77 | Measuring AI Ability to Complete Long Tasks（Kwa 等，2025） | 用任务时长估计 Agent 的时间跨度，提供长时程能力的评测口径。 | 第 21 章 | 精读 |
| P78 | AlphaEvolve: A Coding Agent for Scientific and Algorithmic Discovery（Novikov 等，2025） | 用可验证评估、沙箱与进化搜索改进算法，展示自我改进的受控闭环。 | 第 21 章 | 精读 |
| P79 | AI Models Collapse when Trained on Recursively Generated Data（Shumailov 等，2024） | 说明递归使用自生成数据会导致分布退化，是自我改进的风险基线。 | 第 21 章 | 精读 |
| P80 | AI Control: Improving Safety Despite Intentional Subversion（Greenblatt 等，2024） | 研究在模型可能故意破坏的前提下如何保证安全，提供控制而非对齐的视角。 | 第 21 章 | 选读 |
| P81 | Quiet-STaR: Language Models Can Teach Themselves to Think Before Speaking（Zelikman 等，2024） | 让模型在无标注文本上学习内部思考，探索推理能力的自监督扩展。 | 第 21 章 | 选读 |

## C.11 规范与工程报告

下面这些不是论文，但对工程判断同样重要。它们变化快，引用时务必核对版本与日期。

| 材料 | 类型 | 为什么读 | 章节 |
|---|---|---|---|
| Model Context Protocol Specification | 开放规范 | 工具、资源、提示三种原语与主机/客户端/服务器模型；接入前确认传输与能力子集。 | 第 5 章 |
| Agent2Agent (A2A) Specification | 开放规范 | Agent Card、Task、Message/Part、Artifact 与任务状态机；跨组织协作的接口基线。 | 第 10 章 |
| OpenTelemetry GenAI Semantic Conventions | 开放约定 | 用 Span 与属性描述模型调用、令牌用量与工具执行；注意部分字段仍是实验性。 | 第 16 章 |
| OWASP Top 10 for LLM Applications | 安全清单 | 提示注入、敏感信息泄露、过度代理等风险的工程检查表。 | 第 17 章 |
| How We Built Our Multi-Agent Research System（Anthropic，2025） | 工程报告 | 编排者—执行者、并行子 Agent、token 成本与失败模式的真实案例。 | 第 10 章 |
| Contextual Retrieval（Anthropic，2024） | 工程报告 | 在片段前补充文档级上下文，再做混合检索与重排的工程做法。 | 第 8 章 |
| Deep Research System Card（OpenAI，2025） | 系统卡 | 长时程研究 Agent 的能力边界、人工复核与风险评估方式。 | 第 13 章 |
| The Lethal Trifecta（Simon Willison，2023） | 工程随笔 | 用“私有数据 + 不可信内容 + 外部通信”定位最危险的 Agent 组合。 | 第 17 章 |

## C.12 动手实践：写一张论文卡

读论文最容易的失败，是读完只记住“它比基线高几个点”。论文卡强迫你把方法、假设与适用边界写清楚。

| 字段 | 要回答的问题 |
|---|---|
| 问题 | 它解决什么具体问题？这个问题在什么场景下真实存在？ |
| 假设 | 方法成立依赖哪些前提？哪些前提在你的任务里可能不成立？ |
| 方法 | 核心机制是什么？用一张图或三句话说明。 |
| 实验 | 数据集、基线、指标、模型与预算是什么？ |
| 结果 | 主结果与消融分别说明了什么？有没有反例？ |
| 局限 | 作者承认了什么？实验没有覆盖什么？ |
| 可复用 | 哪个设计可以迁移到 Atlas？迁移时需要改哪一层？ |
| 评测 | 如果要在你的任务上验证，最小评测集是什么？ |

以 ReAct 为例：

| 字段 | 示例 |
|---|---|
| 问题 | 模型能否把推理与行动交替，利用外部观察完成多跳问答与交互任务？ |
| 假设 | 推理帮助选择行动，观察帮助纠正推理；两者交替优于单独使用。 |
| 方法 | 让模型交替生成思考、行动与观察，行动由外部环境执行后回填。 |
| 实验 | 多跳问答、事实核查与交互环境；与仅推理、仅行动的基线比较。 |
| 结果 | 交替轨迹通常更有效，且过程可读；具体增益依赖任务与工具质量。 |
| 局限 | 提示设计敏感、长轨迹成本高；工具错误会被带入后续推理。 |
| 可复用 | Agent Loop、观察回填、轨迹记录；对应 Atlas 的 `Agent.run`、`Step` 与 `ToolRegistry`。 |
| 评测 | 固定 20 个多跳问题，比较有无观察回填的成功率、步骤数与工具错误率。 |

写论文卡时，至少用一句话回答“如果这篇论文的假设不成立，我的系统会怎样”。这比记住分数更有用。

论文卡可以用一个很小的结构固定下来，缺字段时会直接暴露：

```python
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class PaperCard:
    problem: str
    assumption: str
    method: str
    experiment: str
    result: str
    limitation: str
    reusable: str
    evaluation: str

    def missing(self) -> list[str]:
        return [f.name for f in fields(self) if not getattr(self, f.name).strip()]


REACT = PaperCard(
    problem="推理与行动能否交替，利用外部观察完成多跳任务？",
    assumption="推理帮助选择行动，观察帮助纠正推理。",
    method="思考、行动、观察交替，行动由外部执行后回填。",
    experiment="多跳问答与交互环境，对比仅推理、仅行动基线。",
    result="交替轨迹通常更有效，增益依赖任务与工具质量。",
    limitation="提示敏感、长轨迹成本高，工具错误会污染后续推理。",
    reusable="Agent Loop、观察回填、轨迹记录。",
    evaluation="固定 20 个多跳问题，比较成功率、步骤数与工具错误率。",
)

if __name__ == "__main__":
    print("缺字段:", REACT.missing() or "无")
```

把 `reusable` 一栏继续写到具体模块，例如“观察回填对应 `Agent.run` 的循环体，轨迹记录对应 `Step` 序列”。字段写完，论文才真正接上了代码。

<details>
<summary>判断一篇论文是否值得精读的五个信号</summary>

1. **它在定义你正在使用的概念**：如果不读，你会一直误用某个词。
2. **它给出了可迁移的机制**：方法图能直接对应到你系统里的某一层。
3. **它有诚实的基线与消融**：作者愿意展示方法在什么条件下失效。
4. **它的评测口径影响你的验收**：指标或任务构造会被你复用。
5. **它与你的失败模式重合**：你线上遇到的错误，正是它要解决的问题。

五个信号一个都没有时，读摘要即可。反过来，只要命中两个，就值得安排一次完整精读。

</details>

## C.13 业界案例：SWE-bench 从论文到评测器

SWE-bench 是“论文如何变成基础设施”的典型案例。论文的贡献不只是数据集，而是一套可运行的评测流程：每个任务由仓库快照、issue 描述与测试补丁组成；Agent 产出补丁后，在隔离环境中应用并运行测试；`FAIL_TO_PASS` 检查问题是否真的被修复，`PASS_TO_PASS` 检查是否破坏原有行为。

这套设计有三点值得借鉴。

**第一，环境是任务的一部分。** 固定仓库提交、依赖与运行脚本，避免“今天能跑、明天不能跑”。Agent 评测最怕环境漂移，SWE-bench 用容器与快照把环境变成可复现条件。

**第二，判定要可执行。** 它不依赖模型自评，而用测试结果说话。这比“看起来对了”可靠，也把“测试是否充分”这个新问题暴露出来：测试通过不等于补丁可维护，也不等于没有改弱测试。

**第三，失败现场要保留。** 补丁、测试输出、退出码与日志都是证据。评测报告不仅给分数，还告诉你失败发生在定位、修改还是环境。

它的边界同样明显：脚手架差异会显著影响分数；测试覆盖不到的行为不会被发现；任务集与依赖需要持续维护；公开榜单存在污染风险。因此，SWE-bench 适合做能力探针与回归基线，不适合直接当产品验收。正确做法是借它的设计，在自己的仓库上构造小规模、可执行、版本固定的任务集。

把公开基准改造成内部评测集，可以按四步走：

1. **选任务**：从真实 issue、工单或故障中抽样，覆盖简单、正常、困难三档，并保留原始上下文。
2. **固定环境**：锁定提交、依赖与运行脚本，用容器或快照消除“机器不同”的差异。
3. **写判定**：优先用可执行检查（测试、类型检查、契约校验），无法自动判定的部分再引入人工或模型评委。
4. **留证据**：保存轨迹、补丁、日志、退出码与成本，让失败可以归因到定位、修改、环境还是评测本身。

这四步比“找一个更大榜单”更能反映你的真实能力，也更容易在模型或框架升级后做回归比较。

{% hint style="warning" %}
截至写作时，SWE-bench 及其变体的任务集、运行脚本与排行榜规则可能已经更新。本附录只讨论评测设计，不引用具体分数；使用前请以官方仓库与论文为准。
{% endhint %}

## C.14 常见误区

**误区一：按分数选论文。** 分数依赖模型、提示、脚手架与预算。先看实验设置与基线，再看主结果；否则你比较的是脚手架，不是方法。

**误区二：只读摘要，不读局限。** 摘要告诉你作者想让你记住什么，局限告诉你方法在哪些条件下会失效。后者往往更接近你的生产环境。

**误区三：把论文里的提示词直接搬进生产。** 论文提示通常针对特定模型与任务调过；换模型、换工具、换语言后，效果可能完全不同。要迁移的是机制，不是咒语。

**误区四：把基准当验收标准。** 基准衡量的是基准作者定义的能力，不是你的产品需求。它适合做能力探针与回归基线，不适合替代真实任务集。

**误区五：只读最新论文。** 新论文的引用网络里往往藏着更基础的解释与更诚实的失败分析。先读奠基与方法论文，再读最新进展，能显著降低理解成本。

## C.15 本章小结

- 论文要按问题链读：定义、推理、工具、记忆、协作、应用、评测、安全、训练、长时程。
- 先区分奠基论文、方法论文、基准论文与工程报告；它们回答的问题与可信边界不同。
- 12 篇核心论文可以覆盖本书主干；其余论文按主题补齐，不必从头读到尾。
- 读方法论文要抓假设、机制、实验设置与局限；读基准论文要抓任务构造、判定方式与盲区。
- 论文卡是把阅读转化为设计的工具：问题、假设、方法、实验、结果、局限、可复用点、评测。
- 论文结论要映射到自己的任务、工具、预算与安全边界；不能把实验设置当普遍规律。
- SWE-bench 说明，好的评测器把环境、判定与失败证据一起工程化；这也是自建评测集的方向。

## C.16 思考与练习

1. **主题阅读**：从 C.3 或 C.4 选一个主题，读三篇论文并各写一张论文卡。比较它们的假设、实验设置与失败模式，指出哪一篇最接近你的任务，为什么。

2. **基准复现**：选一个基准（例如 SWE-bench 或 τ-bench）的一个小子集，固定环境与版本跑一次。记录成功率、成本、延迟与失败类型，并说明哪些差异来自脚手架而不是模型。

3. **论文到 Atlas**：选一篇方法论文，列出可复用的设计、不可复用的假设、需要新增的评测与安全边界。把它映射到 Atlas 的具体模块，写出一页实现与验证计划。
