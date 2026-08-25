# CoderKing Web UI & CLI Design Document

## 1. 文档目标

本文档定义 CoderKing 第一阶段产品交互设计，包括：

-   Web UI 工作台设计
-   CLI 交互设计
-   API 统一入口设计
-   Agent 执行过程可视化设计

目标是构建类似 Codex / Devin / OpenHands 的 Coding Agent 使用体验。

核心原则：

> Coding Agent
> 不应该只是聊天机器人，而应该是一个可观察、可控制的软件工程执行系统。

------------------------------------------------------------------------

# 2. 产品交互目标

用户输入自然语言任务：

例如：

    实现 FastAPI 用户认证系统

Agent 自动完成：

    需求理解

    ↓

    仓库分析

    ↓

    任务规划

    ↓

    代码修改

    ↓

    Sandbox执行

    ↓

    测试验证

    ↓

    错误修复

    ↓

    结果交付

用户需要看到：

-   Agent 当前执行阶段
-   修改了哪些文件
-   执行了哪些命令
-   测试结果
-   最终代码 Diff

------------------------------------------------------------------------

# 3. Web UI 总体设计

## 3.1 页面布局

采用三栏式 IDE Workspace：

    +------------------------------------------------+
    | Header                                         |
    | Project | Model | Agent Status                 |
    +------------------------------------------------+
    |                |                 |              |
    | Conversation   | Workspace       | Runtime     |
    |                |                 |              |
    | Task Plan      | File Tree       | Terminal    |
    | Agent Trace    | Code Diff       | Test Result |
    |                |                 | Sandbox     |
    +------------------------------------------------+

------------------------------------------------------------------------

# 4. Web UI 模块设计

## 4.1 Header区域

展示：

-   当前项目
-   当前模型
-   Agent运行状态
-   Sandbox状态
-   Token消耗

示例：

    Project: ecommerce-api

    Model:
    deepseek-chat

    Status:
    Running

    Sandbox:
    Active

------------------------------------------------------------------------

# 4.2 Agent Interaction Panel

位置：

左侧区域。

## Task Input

用户输入开发需求：

    Create user authentication API

支持：

-   新建任务
-   继续任务
-   中断任务

------------------------------------------------------------------------

## Agent Execution Timeline

展示 Agent Action Trace：

    Planner:

    Analyzing repository


    Coder:

    Editing auth.py


    Executor:

    Running pytest


    Repair:

    Fixing failed test

注意：

展示执行轨迹，不展示模型私有思维链。

------------------------------------------------------------------------

## Task Plan

展示：

    Plan:

    ✓ Analyze repository

    ✓ Modify authentication module

    ✓ Add test cases

    ○ Run integration test

------------------------------------------------------------------------

# 4.3 Code Workspace

类似 VS Code。

## Repository Explorer

展示项目结构：

    project

    ├── backend

    │   ├── main.py

    │   └── auth.py

    ├── tests

    └── README.md

------------------------------------------------------------------------

## File Viewer

支持：

-   文件查看
-   文件搜索
-   修改定位

------------------------------------------------------------------------

## Diff Viewer

展示 Agent 修改内容：

    + add authentication middleware

    - remove deprecated api

支持：

-   Accept
-   Reject
-   Rollback

------------------------------------------------------------------------

# 4.4 Runtime Panel

右侧区域。

## Terminal

展示 Sandbox 执行日志：

    $ pytest

    FAILED test_login

    Agent analyzing failure...

------------------------------------------------------------------------

## Test Result

展示：

    Test Result:

    20 passed

    1 failed

------------------------------------------------------------------------

## Sandbox Monitor

展示：

    Sandbox:

    Status: Running

    CPU: 30%

    Memory: 512MB

    Timeout: 300s

------------------------------------------------------------------------

# 5. Web UI P0功能列表

第一阶段必须实现：

## Workspace

-   创建项目
-   导入 Git Repository
-   创建任务

## Agent Execution

-   Task Plan展示
-   Tool调用记录
-   Agent状态

## Code Management

-   文件浏览
-   Diff查看
-   修改确认

## Runtime

-   Terminal日志
-   Test结果
-   Sandbox状态

------------------------------------------------------------------------

# 6. Web UI P1功能

后续扩展：

## Memory管理

展示：

    Project Memory

    Architecture:

    FastAPI + PostgreSQL

    Coding Style:

    Async preferred

------------------------------------------------------------------------

## Model配置

支持：

    Provider:

    DeepSeek

    GLM

    OpenAI Compatible

    Ollama

------------------------------------------------------------------------

## Sandbox配置

支持：

    CPU Limit

    Memory Limit

    Timeout

    Network Policy

------------------------------------------------------------------------

# 7. CLI设计

CLI定位：

提供开发者快速调用 Coding Agent 能力。

------------------------------------------------------------------------

# 7.1 CLI命令设计

## 初始化

``` bash
CoderKing init
```

生成：

    .CoderKing/

    config.yaml

    memory/

    workspace/

------------------------------------------------------------------------

## 执行任务

``` bash
CoderKing run "implement jwt authentication"
```

执行：

    Planning...

    Analyzing repository...

    Editing files...

    Running tests...

    Completed

------------------------------------------------------------------------

## 查看状态

``` bash
CoderKing status
```

输出：

    Task:

    implement authentication


    Status:

    Running


    Iteration:

    3

------------------------------------------------------------------------

## 查看代码变化

``` bash
CoderKing diff
```

------------------------------------------------------------------------

## 执行测试

``` bash
CoderKing test
```

------------------------------------------------------------------------

## 模型配置

``` bash
CoderKing config model
```

支持：

-   DeepSeek
-   GLM
-   OpenAI Compatible
-   Ollama

------------------------------------------------------------------------

# 8. CLI架构设计

    CLI

     |

    Command Parser

     |

    API Client

     |

    Agent Runtime

     |

    Tools

CLI 不直接控制 Agent 状态。

统一通过 Runtime API。

------------------------------------------------------------------------

# 9. API统一设计

CLI和Web共享同一套Backend。

架构：

    CLI

     \
      \
       API Gateway

           |

    Agent Runtime

           |

    Tools/Sandbox

------------------------------------------------------------------------

# 10. REST API设计

## 创建任务

POST

    /api/tasks

请求：

``` json
{
 "prompt":"fix login bug",
 "repository":"./project"
}
```

------------------------------------------------------------------------

## 查询任务

GET

    /api/tasks/{task_id}

返回：

``` json
{
"status":"running",
"iteration":3
}
```

------------------------------------------------------------------------

# 11. WebSocket设计

用于实时推送 Agent 状态。

连接：

    /ws/tasks/{task_id}

事件类型：

## agent_status

    planning

    coding

    testing

    repairing

## tool_call

    {
    tool:"shell",
    status:"running"
    }

## file_change

    {
    file:"auth.py",
    action:"modified"
    }

------------------------------------------------------------------------

# 12. Human-in-the-loop设计

危险操作需要人工确认。

触发：

-   删除文件
-   执行危险命令
-   修改核心配置

流程：

    Agent

     |

    Request Approval

     |

    User Confirm

     |

    Continue Execution

------------------------------------------------------------------------

# 13. 第一阶段实现范围

Phase 1：

必须完成：

-   CLI
-   Web Workspace
-   Agent Trace
-   Task Plan
-   File Diff
-   Terminal Output
-   Test Result
-   Sandbox状态展示

暂不实现：

-   多用户系统
-   分布式任务调度
-   完整权限体系

------------------------------------------------------------------------

# 14. 技术价值

该设计体现：

-   Coding Agent产品化能力
-   Agent执行过程可观测性
-   Human-Agent协作
-   CLI/Web统一Runtime
-   工程化开发体验
