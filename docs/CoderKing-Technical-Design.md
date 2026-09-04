# CoderKing 技术方案设计

## 1. 项目定位

CoderKing 是一个自主 **Coding Agent** 平台，目标是实现类似 Codex /
Devin / OpenHands / Pi 的软件工程 Agent 能力。

用户通过自然语言描述开发任务，单一 Agent 循环自动完成：

-   需求理解与仓库探索
-   文件读写与精确编辑
-   沙箱中执行命令与测试
-   根据工具观察继续迭代
-   结果交付（diff / 摘要）

项目重点不是固定多角色 workflow，也不是简单调用 LLM 生成一段代码，而是构建具备
**纯 Agent Loop、四原子 Tool Calling、Sandbox 执行和 Evaluation** 能力的工程化 Coding Agent。

------------------------------------------------------------------------

# 2. 参考项目

项目设计参考以下开源方向：

## OpenHands

https://github.com/OpenHands/OpenHands

参考：

-   Coding Agent Loop
-   Runtime 抽象
-   Workspace 管理
-   Tool 调用机制

## SWE-agent

https://github.com/SWE-agent/SWE-agent

参考：

-   Repo 理解
-   Issue 修复流程
-   自动 Patch 生成
-   SWE Benchmark 思路

## Aider

https://github.com/Aider-AI/aider

参考：

-   Repository Context 管理
-   Code Editing
-   Git 集成

## GameForge-Copilot

https://github.com/ByteTitan-star/GameForge-Copilot

复用设计思想：

-   Sandbox 生命周期管理
-   安全执行机制
-   Agent Evaluation 体系

------------------------------------------------------------------------

# 3. 总体架构

                     User
    
                      |
    
              CLI / Web UI
    
                      |
    
              Agent Controller
    
                      |
    
              Agent Orchestrator
    
                      |
    
          -------------------------
    
          Planner Agent
    
          Coding Agent
    
          Execution Agent
    
          Reviewer Agent
    
          Repair Agent
    
                      |
    
                 Tool Layer
    
          -------------------------
    
          File Tool
    
          Shell Tool
    
          Git Tool
    
          Test Tool
    
                      |
    
                 Sandbox
    
                      |
    
              Repository Workspace
    
                      |
    
               Test / Build Result
    
                      |
    
              Reflection Loop

------------------------------------------------------------------------

# 4. 用户交互层

## CLI

支持开发者直接运行：

``` bash
CoderKing run "implement authentication system"
```

适用于：

-   开发任务执行
-   自动修复
-   Benchmark 测试

## Web UI

采用 React + FastAPI。

核心页面：

### Chat Workspace

展示：

-   用户需求
-   Agent执行过程
-   Task Plan
-   Tool调用记录

### Code Workspace

展示：

-   文件修改
-   Git Diff
-   Patch结果

### Execution Panel

展示：

-   Terminal输出
-   测试结果
-   错误日志

------------------------------------------------------------------------

# 5. LLM Provider设计

不绑定单一模型，支持用户配置。

架构：

    Agent Core
    
         |
    
    LLM Provider Interface
    
         |
    
    ----------------------
    
    DeepSeek
    
    GLM
    
    OpenAI Compatible
    
    Ollama Local Model

支持：

-   DeepSeek
-   GLM
-   Qwen
-   OpenAI Compatible API
-   本地部署模型

------------------------------------------------------------------------

# 6. 自研 Agent Loop

不依赖 LangChain / LangGraph。

采用 ReAct + Reflection 混合架构。

流程：

    User Task
    
       |
    
    Planner
    
       |
    
    Task Plan
    
       |
    
    Act
    
       |
    
    Tool Call
    
       |
    
    Observation
    
       |
    
    Reflection
    
       |
    
    Success ?
    
       |
    
    Repair Loop

Agent State：

``` python
{
 task,
 repository,
 plan,
 messages,
 tool_history,
 changed_files,
 test_results,
 errors,
 iteration
}
```

------------------------------------------------------------------------

# 7. Agent角色设计

## Planner Agent

职责：

-   分析需求
-   拆分任务
-   制定执行计划

## Coding Agent

职责：

-   修改代码
-   创建文件
-   重构逻辑

## Execution Agent

职责：

-   编译项目
-   执行命令
-   运行测试

## Reviewer Agent

职责：

-   检查代码质量
-   判断任务完成情况

## Repair Agent

职责：

-   分析失败原因
-   自动修复问题

------------------------------------------------------------------------

# 8. Tool Protocol设计

实现自研 Tool Protocol。

统一接口：

``` python
class Tool:

    name: str

    description: str

    parameters: dict

    execute()
```

------------------------------------------------------------------------

# 9. Tool设计

## File Tool

负责代码文件操作：

能力：

-   read_file
-   write_file
-   create_file
-   search_code
-   delete_file

------------------------------------------------------------------------

## Shell Tool

负责执行：

-   编译
-   安装依赖
-   运行脚本

所有 Shell 操作必须经过 Sandbox。

------------------------------------------------------------------------

## Git Tool

支持：

-   git_status
-   git_diff
-   git_apply_patch
-   git_commit

用于：

-   代码变更追踪
-   Patch生成

------------------------------------------------------------------------

## Test Tool

负责：

-   自动运行测试
-   收集日志
-   分析失败原因

------------------------------------------------------------------------

# 10. Sandbox执行系统

参考 GameForge-Copilot Sandbox设计。

架构：

    Agent
    
     |
    
    Sandbox Manager
    
     |
    
    Container Runtime
    
     |
    
    Workspace
    
     |
    
    Repository

生命周期：

    create
    
    ↓
    
    mount repository
    
    ↓
    
    execute command
    
    ↓
    
    collect result
    
    ↓
    
    cleanup

能力：

-   CPU限制
-   Memory限制
-   Timeout控制
-   网络隔离
-   进程清理

------------------------------------------------------------------------

# 11. Repository Context Engineering

Coding Agent 最大问题是上下文管理。

设计：

## Repository Scanner

扫描：

-   文件结构
-   入口文件
-   README
-   依赖
-   测试目录

生成：

repository_summary。

## Context Retrieval

根据任务动态检索：

-   BM25
-   Vector Search

支持：

-   ChromaDB
-   Milvus

------------------------------------------------------------------------

# 12. Memory设计

## Short-term Memory

保存：

-   当前任务状态
-   Tool调用历史
-   错误信息
-   修复尝试

## Long-term Project Memory

保存：

-   项目架构
-   编码规范
-   历史修改经验

存储：

-   PostgreSQL
-   Vector Database

------------------------------------------------------------------------

# 13. Evaluation体系

构建 Coding Agent Benchmark。

目录：

    eval/
    
     tasks/
    
       bug_fix/
    
       feature_add/
    
       refactor/

任务格式：

``` json
{
 task_id:"",
 repository:"",
 instruction:"",
 expected_result:"",
 test_command:""
}
```

------------------------------------------------------------------------

# 14. 评测指标

## Task Success Rate

任务完成比例。

## Test Pass Rate

自动测试通过率。

## Repair Success Rate

失败后的自动修复成功率。

## Iteration Efficiency

完成任务平均循环次数。

## Token Cost

模型调用成本。

------------------------------------------------------------------------

# 15. 技术栈

## Backend

-   Python 3.12
-   FastAPI
-   PostgreSQL
-   Redis

## Agent Runtime

-   自研 Agent Loop
-   自研 Tool Protocol
-   OpenAI Compatible SDK

## Frontend

-   React
-   Tailwind CSS
-   WebSocket

## Sandbox

-   Docker
-   Daytona（可选）

## Retrieval

-   ChromaDB / Milvus

------------------------------------------------------------------------

# 16. 简历项目描述

CoderKing：

自主 Coding Agent 平台，自研 Agent Loop 与 Tool
Protocol，实现需求理解、代码生成、Sandbox执行、测试验证和自动修复闭环；支持多模型配置、CLI/Web交互及自动化代码任务评测。