# CoderKing 能力审计与实现路线图

更新时间：2026-09-12

## 1. 结论

CoderKing 已经具备一个可运行的 Pi 风格最小内核：分层 LLM 适配、单 Agent 工具循环、
四个原子编码工具、沙箱、安全策略、CLI/Web/Desktop 入口、事件流和评测框架。
当前主要问题不是“什么都没有”，而是若干能力停留在模块或测试层，没有贯通到真实运行链路。

本路线图采用两个原则：

1. 核心循环继续保持小而稳定；Skill、MCP、动态工具、上下文引擎等作为可选资源接入，
   不重新引入固定多角色 workflow。
2. 自进化只在离线评测管线中产生候选变更，必须经过回归基准、holdout 数据和人工审查，
   在线 Agent 不直接修改自己的生产提示词或代码。

## 2. 现状审计

| 能力 | 审计前状态 | 判断 |
| --- | --- | --- |
| L0-L3 分层与单 Agent Loop | 已实现并有边界测试 | 可作为稳定内核继续演进 |
| Read/Write/Edit/Bash 与沙箱 | 已实现，本地/Docker/MicroVM 有测试 | 主路径可用 |
| 会话 JSONL 与分支节点 | 存储结构已实现 | 恢复时历史没有真正送回模型，分支能力也没有完整 CLI 交互 |
| Skill | 有扫描、关键词匹配、懒注入单测 | 仅首轮、仅项目目录、无 CLI/显式选择/诊断，不能算完整接入 |
| 上下文压缩 | 有预算、摘要和 transform 模块 | `transform_context` 未接入生产循环，实际不会自动压缩 |
| 任务状态 | 有 `current_task.json` 和单任务查询 | 运行中状态、迭代、跨进程取消、任务列表和崩溃恢复不完整 |
| MCP | Client/Host/配置与独立测试已存在 | Runtime 的 `connect_mcp` binding 未消费，真实 Agent 看不到 MCP 工具 |
| 动态工具 | Loader/Executor 与示例已存在 | `build_tools()` 始终只返回四个原子工具，README 所称自动注册未闭环 |
| Memory | SQLite `MemoryStore` 已存在 | 只被构造后传入 Runtime，没有读取、写入或提示词注入 |
| 仓库检索 | Scanner/BM25 有独立实现和测试 | 没有接入 Agent 上下文或检索工具 |
| 扩展机制 | 有轻量 hooks/transport 边界 | 缺少 Pi 式资源加载、生命周期事件、reload、扩展状态持久化 |
| Eval/Trace | 有 scripted/live eval 和工具轨迹 | 缺少统一 trajectory、成本/时延、失败分类和回归门禁，暂不足以支撑自进化 |
| 自进化 | 未实现 | 必须建立在稳定 trace、数据集和评测门禁之上 |

## 3. 分阶段实施计划

### M0：运行时正确性与 CLI 基线（当前阶段）

状态：已完成（2026-09-12）。

目标：让仓库里已经存在的会话、Skill、压缩、任务状态能力在真实 CLI 链路中可用。

- 恢复会话时，把历史消息、工具调用 ID、Skill/压缩元数据完整还原给模型。
- 把 `ContextCompressor` 接入 L1 的 `transform_context`，压缩后更新活动上下文。
- 增加可配置上下文窗口、阈值、输出预留和最近消息保护参数。
- 增加 `/context`、`/compact`、`/skills`、`/skill:<name>` 和 `--skill`。
- Skill 同时扫描项目级、全局和 Cursor 兼容目录，支持嵌套目录、重复项和坏清单诊断。
- 增加 `codeking tasks` 与按 ID 查询状态；实时持久化迭代和终态。
- 让 `codeking stop` 的取消标记被正在运行的进程消费，并在完成后清理。
- 修复达到最大轮数却被标记为 succeeded 的错误语义。

验收：相关回归测试、全部非 live/non-Docker 测试、Ruff 和分层依赖检查通过。

### M1：资源与扩展系统

状态：M1A 已完成——动态工具与 MCP 已通过 fail-closed `ResourceLoader` 接入运行时，
CLI/API/SDK 共用同一工具面；M1B 的通用扩展生命周期与扩展状态节点待实施。

目标：在不破坏四原子工具默认面的前提下，完成可选扩展闭环。

- 引入统一 `ResourceLoader`：project/global/package 三层加载 Skill、Prompt、Tool、Extension。
- 默认保持四原子工具；只有显式启用时才合并动态工具和 MCP 工具。
- 接通现有 `DynamicToolLoader` 与 `McpHost`，处理名称冲突、启动超时、关闭和错误隔离。
- 增加 `codeking tools list/check`、`codeking mcp list/check` 与会话内 `/reload`。
- 定义扩展生命周期：session/turn/tool/context/approval 事件，以及可持久化的扩展状态节点。
- 修正文档与实际行为不一致的部分，并为 CLI/API/SDK 使用同一资源加载器。

验收：可选资源未配置时工具面仍严格为四个；启用后 CLI、API、SDK 都能调用同一扩展工具。

### M2：会话、任务与执行状态

状态：M2A 与 M2B 核心链路已完成——`session_id`、`run_id/task_id`、`turn_id` 已分离，
JSONL 保存消息增量与 run 节点，具备 tree/fork/branch、任务列表/取消/retry、approval
状态持久化、孤儿任务恢复，以及二进制安全且拒绝不完整基线的工作区回滚。任务 JSON
仍是事实源，SQLite 提供可重建的查询索引、事件游标和进程租约；SDK 连续 `run()` 会保留
同一会话上下文并创建子 run。直接文件写工具已接入 prepared → applied/failed →
accepted/rolled_back checkpoint，回滚前会校验文件未被后续修改。M2 剩余项是 session
label/delete 与面向后台 worker 的独立心跳；`bash` 的任意副作用仍由整任务快照兜底。

目标：把“会话上下文”和“一次执行任务”拆成两个明确生命周期。

- 使用独立的 `session_id`、`run_id/task_id`、`turn_id`，不再跨多轮复用一个 task ID。
- JSONL 保存逐条消息、工具结果、压缩、分支摘要和配置变更，而不只追加完整快照。
- SQLite 保存可查询索引、任务租约和事件游标；JSONL 继续作为可移植的会话事实源。
- 增加 task list/show/cancel/retry、session tree/fork/branch/label/delete（删除优先放废纸篓）。
- 持久化 approval/waiting 状态；进程重启后把未完成任务标为 interrupted/recoverable。
- 每次工具写入前后保存可恢复 checkpoint，并明确 accept/rollback 的状态机。

验收：杀掉进程后重新启动，能解释上一次停在哪里、恢复上下文并安全重试；分支不会破坏原路径。

当前未完成边界：CLI 进程内任务已在每次持久化时续租，但长时间无事件的后台 worker
心跳属于 M5；checkpoint 只自动包裹可识别的直接文件写工具，不承诺拆解任意 shell 命令。

### M3：可插拔上下文引擎

状态：M3A 已完成——在原有批量/手动压缩前加入可配置 micro-compaction，旧的大型工具
结果会保留调用配对、最近结果、错误摘要与内容哈希，并通过事件、任务状态和 CLI/TUI
暴露压缩次数。统一 `ContextEngine`、provider token、模型注册表与辅助压缩模型属于 M3B。

目标：从启发式裁剪升级为可观测、可替换、不会破坏工具消息配对的上下文管理。

- 建立 `ContextEngine` 接口：estimate、should_compact、compact、update_usage、status。
- 优先使用 provider 返回的 prompt token；启发式估算只作为 preflight fallback。
- 建立模型能力注册表，记录 context window、thinking、tool use 和缓存能力。
- 增加独立 auxiliary compression model、超时、明确 fallback 事件和失败冷却。
- 保护 system/head、当前任务、未完成工具调用和最近 token 尾部；用 token 而非消息数控制尾部。
- 支持批量压缩、手动压缩和可选 micro-compaction，并展示 context pressure。
- 增加 prompt-cache 指标，避免频繁压缩造成的缓存失效成本高于收益。

验收：长会话、超大工具输出、模型切换、压缩失败和取消都有端到端测试；不会产生非法 tool role 序列。

### M4：Memory 与仓库上下文

目标：让已有 MemoryStore、Scanner 和 BM25 从孤立模块变成受控能力。

- 定义 project/user/session 三类记忆及来源、置信度、更新时间和删除方式。
- 只在明确事件中抽取候选记忆；敏感信息过滤后，由策略决定自动写入或请求确认。
- 提供 memory list/show/add/delete 和 session search 工具。
- 将 BM25/文件索引作为按需检索工具，不在每轮把整个仓库树塞进系统提示词。
- 记录每条检索上下文的来源，压缩时保留重要文件和未解决任务引用。

验收：跨会话可复用项目约定，用户能审计和删除记忆；默认不会保存密钥或大段源码。

### M5：可靠性、模型路由与协作执行

目标：支持更长、更复杂的工程任务，而不让核心循环失控。

- 按 provider 错误类型做有限重试、Retry-After 上限、fallback chain 和熔断。
- 增加成本、首 token 时延、总时延、工具成功率、压缩率和取消延迟指标。
- 为长任务增加后台执行、任务租约、心跳与恢复；CLI 只作为一个 transport。
- 在有真实收益的场景再加入隔离 worktree 和 bounded sub-agent delegation。
- 子任务必须有明确输入/输出/预算；父任务负责合并证据，默认不共享可写工作区。

验收：失败可分类、可重试、可取消；并行执行不会互相覆盖文件或静默吞掉失败。

### M6：Hermes 风格离线自进化

目标：用真实轨迹和基准数据优化 Skill、工具描述和提示词，而不是让在线 Agent 自改生产代码。

1. 统一 trajectory schema：输入、模型/配置版本、工具轨迹、测试结果、人工反馈、成本和时延。
2. 从人工标注、失败会话和合成任务构建 train/validation/holdout 数据集，先做隐私清洗。
3. 第一优先级优化 `SKILL.md`；第二优先级优化工具 description；第三优先级优化版本化提示词片段。
4. 使用 DSPy + GEPA 生成候选，fitness 同时考虑任务成功率、回归、token、时延和安全约束。
5. 候选必须通过结构校验、现有测试、固定 benchmark、holdout 和语义漂移检查。
6. 只输出 proposal 分支/补丁和 before/after 报告，由人审核；不得自动覆盖活动会话资源。
7. 版本化记录 lineage、数据集 hash、模型、seed、成本和回滚点，避免不可复现的“自我提升”。

验收：至少一个 Skill 在冻结 holdout 上有可重复的显著提升，且完整回归集无下降，才进入下一类目标。

## 4. 优先级

| 优先级 | 工作 | 原因 |
| --- | --- | --- |
| P0 | M0 正确性 | 当前 UI/测试容易让人误以为能力已可用，但生产链路存在断点 |
| P1 | M1 + M2 | 没有资源闭环和可靠会话/任务数据，就无法安全扩展或收集高质量轨迹 |
| P1 | M3 | 长任务的成本、稳定性和恢复能力依赖上下文引擎 |
| P2 | M4 | 记忆应建立在可审计 session/task 数据之上 |
| P2 | M5 | 在单 Agent 正确且可观测后再扩大并发和后台执行 |
| P3 | M6 | 自进化最后接入，避免优化一个仍在变化且无法可靠评分的系统 |

## 5. 每个里程碑的共同完成标准

- 需求必须有核心路径、边界和失败语义测试。
- CLI、API、SDK 不复制业务逻辑，统一调用 L1/L2 公共接口。
- 运行状态和错误不可被伪装为成功。
- 新功能有配置说明、迁移策略和可观察事件。
- 非 live 测试、Ruff、分层依赖检查必须通过；涉及 Docker/MCP 时增加真实 smoke test。
- 评测报告只由显式 eval 命令生成，普通单元测试不得改写仓库内基准报告。
