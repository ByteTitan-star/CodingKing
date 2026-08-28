#!/usr/bin/env python3
"""Create GitHub issues for whitepaper gap analysis."""

from __future__ import annotations

import json
import subprocess
import sys

REPO = "ByteTitan-star/CodingKing"

LABELS = [
    "status:done",
    "status:partial",
    "status:open",
    "phase:1",
    "phase:2",
    "phase:3",
    "phase:4",
    "area:loop",
    "area:context",
    "area:sandbox",
    "area:tools",
    "area:transport",
    "area:architecture",
    "area:llm",
    "epic",
]


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def create_label(name: str) -> None:
    subprocess.run(
        ["gh", "label", "create", name, "--repo", REPO, "--force"],
        capture_output=True,
    )


def create_issue(title: str, body: str, labels: list[str], close: bool = False) -> str:
    url = run(
        "gh",
        "issue",
        "create",
        "--repo",
        REPO,
        "--title",
        title,
        "--body",
        body,
        "--label",
        ",".join(labels),
    )
    if close:
        num = url.rstrip("/").split("/")[-1]
        subprocess.run(
            [
                "gh",
                "issue",
                "close",
                num,
                "--repo",
                REPO,
                "--comment",
                "已在 Phase 1 MVP 中实现并验收，关闭为进度记录。",
            ],
            check=True,
        )
    print(url)
    return url


EPIC_BODY = """## 背景

对照《自主 Coding Agent 系统架构与从 0 到 1 全局实现技术白皮书》（Pi 式四层架构），对 CoderKing 当前实现做全量差距跟踪。

**总体完成度：约 25%-30%**（Phase 1 大部分 + Phase 2/3/4 少量片段）

当前架构为 **5 角色 SWE Harness 单体 Runtime**，与白皮书 **极简 4 工具 + 纯 Loop 四层分包** 存在系统性偏差，需 v2 重构。

## 进度总览

### 自主循环
- [x] 基础迭代循环 — `src/coderking/runtime/loop.py`
- [x] 事件驱动流 — WebSocket
- [x] max_iterations / 任务完成终止
- [ ] 显式五阶段 FSM
- [ ] Steering / Follow-up
- [ ] 统一 Safety Policy Engine

### 多通道
- [x] CLI / Web / Electron 壳
- [ ] TUI 差分渲染 / RPC stdio / SSE / SDK

### 四层架构
- [x] L0 基础（同步 OpenAI Compatible）
- [ ] L0 streaming+retry / L1 纯 Loop / L2 JSONL+压缩 / L3 传输解耦

### 上下文
- [x] Scanner + BM25
- [ ] 极简 prompt / AGENTS.md / Skills / JSONL 树 / 压缩

### 沙盒
- [x] Docker + Local + 快照 Rollback
- [ ] Micro-VM / CoW / 网络白名单 / 凭据隔离

### 工具
- [x] Read/Write/Bash 基础版
- [ ] Edit / MCP / 四原子迁移 / 自扩展

## 参考
- `docs/CoderKing-Technical-Design.md`
- `docs/phase1-acceptance.md`
"""

DONE_ISSUES = [
    (
        "[Done] 自主循环基础迭代与终止条件",
        ["status:done", "phase:1", "area:loop"],
        """## 状态：已完成

- `AgentRuntime.run()` LLM -> Tool -> Observation 循环
- 终止：SUCCEEDED / FAILED / INTERRUPTED / max_iterations
- Harness：测试通过自动 succeed、失败自动 Repair

**代码**: `src/coderking/runtime/loop.py`, `config.py`
""",
    ),
    (
        "[Done] 事件驱动流与 Web 实时推送",
        ["status:done", "phase:1", "area:loop"],
        """## 状态：已完成

- AgentEvent 全类型 + asyncio.Queue + WebSocket

**代码**: `runtime/events.py`, `controller.py`, `api/app.py`
""",
    ),
    (
        "[Done] Docker 沙盒运行时",
        ["status:done", "phase:3", "area:sandbox"],
        """## 状态：已完成

- CPU/Memory/Timeout、network none、容器清理

**代码**: `sandbox/docker.py`, `tests/test_docker.py`
""",
    ),
    (
        "[Done] Write 工具（mkdir + UTF-8）",
        ["status:done", "phase:2", "area:tools"],
        """## 状态：已完成

**代码**: `tools/file.py`, `tests/test_file_tools.py`
""",
    ),
    (
        "[Done] Shell/Bash 工具（同步 + timeout + HITL）",
        ["status:done", "phase:2", "area:tools"],
        """## 状态：已完成

**代码**: `tools/shell.py`, `sandbox/local.py`, `sandbox/docker.py`
""",
    ),
    (
        "[Done] L0 基础 LLM 适配（OpenAI Compatible）",
        ["status:done", "phase:1", "area:llm"],
        """## 状态：已完成

- 同步调用、Token 统计、Cancel、thinking 兼容重试

**代码**: `llm/provider.py`, `llm/openai_compat.py`

**差距**: 无 streaming、无通用 retry
""",
    ),
    (
        "[Done] CLI 基础命令与交互",
        ["status:done", "phase:1", "area:transport"],
        """## 状态：已完成

init/run/chat/serve/stop/status/eval/config + Rich Live

**代码**: `cli.py`, `tests/test_cli.py`
""",
    ),
    (
        "[Done] Web UI 工程工作台",
        ["status:done", "phase:1", "area:transport"],
        """## 状态：已完成

Plan/Trace/Terminal/Diff/Sandbox + Stop/HITL/Rollback

**代码**: `web/`, `api/app.py`
""",
    ),
    (
        "[Done] Eval 评测体系",
        ["status:done", "phase:1", "area:architecture"],
        """## 状态：已完成

bug_fix/feature_add/refactor + evalkit 报告

**代码**: `eval/`, `evalkit/`

**差距**: 真实模型 E2E 未验收
""",
    ),
    (
        "[Done] Human-in-the-loop 危险操作审批",
        ["status:done", "phase:1", "area:loop"],
        """## 状态：已完成

delete_file + 危险 shell 需审批，CLI --yes

**代码**: `runtime/loop.py`, `tools/shell.py`
""",
    ),
    (
        "[Done] 任务取消与中断",
        ["status:done", "phase:3", "area:loop"],
        """## 状态：已完成

CancellationToken + stop/interrupt API

**代码**: `runtime/cancel.py`, `registry.py`, `tests/test_cancel.py`
""",
    ),
    (
        "[Done] 工作区快照、Diff 与 Rollback",
        ["status:done", "phase:1", "area:sandbox"],
        """## 状态：已完成

**代码**: `diffing.py`, `tests/test_diffing.py`
""",
    ),
    (
        "[Done] 5 角色 Agent 编排",
        ["status:done", "phase:1", "area:loop"],
        """## 状态：已完成（偏离 Pi 极简路线）

Planner/Coding/Execution/Reviewer/Repair + Harness 硬路由

**代码**: `runtime/roles.py`, `loop.py`, `tests/test_harness_guards.py`

应迁移为 L2 Extension
""",
    ),
    (
        "[Done] 基础上下文：Repository Scanner + BM25",
        ["status:done", "phase:2", "area:context"],
        """## 状态：已完成

**代码**: `context/scanner.py`, `context/bm25.py`
""",
    ),
    (
        "[Done] Read 与 Search 工具（基础版）",
        ["status:done", "phase:2", "area:tools"],
        """## 状态：已完成（部分符合 Read 规范）

read_file + search_code

**差距**: 无行号/glob read/图片
""",
    ),
    (
        "[Done] Local Sandbox fallback",
        ["status:done", "phase:1", "area:sandbox"],
        """## 状态：已完成

sandbox_mode: auto/docker/local

**代码**: `sandbox/local.py`, `sandbox/manager.py`
""",
    ),
    (
        "[Done] Electron Desktop 壳（基础）",
        ["status:done", "phase:4", "area:transport"],
        """## 状态：已完成（仅壳）

IPC: dialog:openDirectory

**代码**: `desktop/`

**差距**: 未接 Agent RPC
""",
    ),
]

OPEN_ISSUES = [
    (
        "[Todo] Phase 1：真实模型 E2E 验收",
        ["status:open", "phase:1", "area:architecture"],
        """## 状态：未完成

- [ ] 配置真实 API Key
- [ ] coderking run 真实 bug fix
- [ ] eval 真实模型报告
- [ ] 更新 phase1-acceptance.md

**参考**: `docs/phase1-acceptance.md`
""",
    ),
    (
        "[Todo] v2 四层 Monorepo 架构重构",
        ["status:open", "phase:1", "area:architecture", "epic"],
        """## 状态：未完成

目标: llm / agent-core / coding-agent / transport 四层分包

- [ ] CoderKing-v2-Architecture.md
- [ ] 包边界与接口
- [ ] 迁移映射表
- [ ] 渐进 PR 迁移
""",
    ),
    (
        "[Todo] L1：拆分纯 Agent Loop（pi-agent-core 层）",
        ["status:open", "phase:1", "area:architecture"],
        """## 状态：未完成

将 loop.py 中角色/harness 下沉 L2，L1 仅保留 agentLoop + EventStream + transformContext
""",
    ),
    (
        "[Todo] L0：LLM Streaming + 指数退避重试",
        ["status:open", "phase:1", "area:llm"],
        """## 状态：未完成

- [ ] streamAssistantResponse
- [ ] 429/5xx retry
- [ ] stop_reason 统一
""",
    ),
    (
        "[Todo] 实现 Edit 工具（str replace + 唯一性 + 模糊匹配）",
        ["status:open", "phase:2", "area:tools"],
        """## 状态：未完成

白皮书四原子工具之一，当前缺失
""",
    ),
    (
        "[Todo] 树状 Append-Only JSONL 会话持久化",
        ["status:open", "phase:2", "area:context"],
        """## 状态：未完成

nodeId/parentId/head pointer/分支/崩溃恢复
""",
    ),
    (
        "[Todo] 动态上下文压缩 + Summary 节点",
        ["status:open", "phase:2", "area:context"],
        """## 状态：未完成

token 阈值 + transformContext + compression 节点
""",
    ),
    (
        "[Todo] AGENTS.md / SYSTEM.md 项目指令加载",
        ["status:open", "phase:2", "area:context"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] Skills 延迟加载机制",
        ["status:open", "phase:2", "area:context"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] 极简 System Prompt（<1000 tokens）",
        ["status:open", "phase:2", "area:context"],
        """## 状态：部分完成

角色 prompt 短，但启动注入 README+树+BM25 易超标
""",
    ),
    (
        "[Todo] Steering 转向控制",
        ["status:open", "phase:3", "area:loop"],
        """## 状态：未完成

mid-turn 注入、中断剩余 tool 队列
""",
    ),
    (
        "[Todo] Follow-up 跟进队列",
        ["status:open", "phase:3", "area:loop"],
        """## 状态：未完成

turn 结束后排队执行
""",
    ),
    (
        "[Todo] RPC JSONL over Stdio 协议",
        ["status:open", "phase:3", "area:transport"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] SSE EventStream API",
        ["status:open", "phase:3", "area:transport"],
        """## 状态：未完成

当前仅 WebSocket
""",
    ),
    (
        "[Todo] SDK 嵌入模式",
        ["status:open", "phase:4", "area:transport"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] MCP 集成",
        ["status:open", "phase:4", "area:tools"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] 四原子工具架构迁移",
        ["status:open", "phase:2", "area:tools", "area:architecture"],
        """## 状态：未完成

Read/Write/Edit/Bash only，其余 Extension/MCP
""",
    ),
    (
        "[Todo] Read 工具增强（行号/glob/图片）",
        ["status:open", "phase:2", "area:tools"],
        """## 状态：部分完成
""",
    ),
    (
        "[Todo] Bash 异步后台 job",
        ["status:open", "phase:2", "area:tools"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] Agent 自扩展工具范式",
        ["status:open", "phase:4", "area:tools"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] 显式五阶段 FSM",
        ["status:open", "phase:1", "area:loop"],
        """## 状态：未完成

Perceive/Decide/Act/Observe/Re-perceive
""",
    ),
    (
        "[Todo] 统一 Safety Policy Engine",
        ["status:open", "phase:3", "area:loop"],
        """## 状态：部分完成

HITL 规则散落各处
""",
    ),
    (
        "[Todo] Micro-VM 沙盒",
        ["status:open", "phase:4", "area:sandbox"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] Copy-on-Write 文件系统",
        ["status:open", "phase:3", "area:sandbox"],
        """## 状态：部分完成

当前仅内存快照
""",
    ),
    (
        "[Todo] 沙盒网络域名白名单",
        ["status:open", "phase:3", "area:sandbox"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] 凭据与沙盒完全隔离",
        ["status:open", "phase:3", "area:sandbox"],
        """## 状态：部分完成

.env 可能被 mount 进容器
""",
    ),
    (
        "[Todo] Interactive TUI 差分渲染",
        ["status:open", "phase:4", "area:transport"],
        """## 状态：未完成
""",
    ),
    (
        "[Todo] Desktop IPC 全链路",
        ["status:open", "phase:4", "area:transport"],
        """## 状态：部分完成

Electron 壳已有，未 spawn Agent 子进程
""",
    ),
]


def main() -> int:
    for label in LABELS:
        create_label(label)

    urls: list[str] = []
    urls.append(
        create_issue(
            "[Epic] 白皮书对齐 — 自主 Coding Agent 全局实现进度跟踪",
            EPIC_BODY,
            ["epic", "area:architecture"],
        )
    )
    for title, labels, body in DONE_ISSUES:
        urls.append(create_issue(title, body, labels, close=True))
    for title, labels, body in OPEN_ISSUES:
        urls.append(create_issue(title, body, labels))

    print(f"\nCreated {len(urls)} issues")
    print(json.dumps(urls, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
