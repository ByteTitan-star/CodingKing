# CodeKing CLI 使用指南

> 面向新用户的完整教学文档：装好 → 配好 → 会用所有命令。
> 对应版本：v1.0.9+

CodeKing 是一个自主编码代理：你用自然语言描述工程任务，它会自己浏览代码、修改文件、在沙箱里跑测试，直到验证通过。CLI 是它最主要的使用形态（另有 Web / Desktop / TUI）。

---

## 1. 安装

三种方式任选其一，装完都有全局 `codeking` 命令：

```bash
# 方式一：一行脚本（无需任何账号）
curl -fsSL https://raw.githubusercontent.com/ByteTitan-star/CodingKing/main/install.sh | sh

# 方式二：npm（需要 Node 18+）
npm install -g codeking

# 方式三：pipx（需要 Python 3.12+）
pipx install git+https://github.com/ByteTitan-star/CodingKing.git
```

脚本/npm 方式会把运行环境装在 `~/.codeking/venv`，不污染系统 Python。

## 2. 首次配置（必做）

CodeKing 通过任意 OpenAI 兼容接口调模型。把配置写进 `~/.coderking/.env`（全局，所有项目生效）：

```env
CODERKING_OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 智谱 GLM
CODERKING_OPENAI_API_KEY=你的key
CODERKING_MODEL=glm-5.2
```

也可以用 DeepSeek / Qwen / Ollama 等任何兼容网关，换前两个值即可。

**配置优先级**（高 → 低）：shell 环境变量 > 项目目录的 `.env` > 全局 `~/.coderking/.env`。
在某个项目里需要不同模型时，在该项目根目录放一个 `.env` 覆盖即可。

## 3. 五分钟上手

```bash
cd 你的项目          # 进入你要处理的代码仓库
codeking             # 启动（会看到小男孩 + CNU 入场动画）
```

然后直接用中文/英文描述任务：

```
❯ 修复这个仓库里失败的单元测试，跑通后停止
```

代理会自己读代码 → 改文件 → 跑测试 → 失败则继续修 → 通过后给你结果摘要。
改了哪些文件、测试结果、token 用量都会在结束时列出。

- 退出：`/exit`（或 Ctrl+C）
- 中途改方向：运行时直接输入新的指示（steering，会打断当前方向）
- 开新对话：输入 `/new`

## 4. 命令总表

| 命令 | 作用 | 常用度 |
| --- | --- | --- |
| `codeking` | 继续当前会话（等于 `claude -c`） | ★★★ |
| `codeking new` | 开一条全新会话（旧的保留） | ★★★ |
| `codeking -r` | 交互式选择历史会话恢复（等于 `claude -r`） | ★★★ |
| `codeking -r 2` | 直接恢复列表中第 2 个会话 | ★★ |
| `codeking sessions` | 列出所有会话（时间/任务/消息数/token） | ★★ |
| `codeking skills list` | 列出项目级/全局/Cursor 兼容 Skills | ★★ |
| `codeking skills show <name>` | 查看 Skill 内容与来源 | ★★ |
| `codeking skills check` | 校验 Skill 清单、重复名与 token 限制 | ★ |
| `codeking tasks` | 列出当前工作区已持久化的任务 | ★★ |
| `codeking run "任务"` | 一次性执行任务，不进交互 | ★★★ |
| `codeking status` | 查看当前任务状态 | ★ |
| `codeking stop <task_id>` | 取消运行中的任务 | ★ |
| `codeking diff` | 查看工作区的 git diff | ★★ |
| `codeking test` | 在沙箱里跑测试（默认 `python -m pytest -q`） | ★ |
| `codeking init` | 在项目里生成 `.coderking/` 配置模板和 AGENTS.md | ★★ |
| `codeking serve` | 启动 Web/API 服务（默认 127.0.0.1:8000） | ★ |
| `codeking tui` | 终端全屏界面（三面板） | ★ |
| `codeking config model` | 保存模型配置到项目 `.coderking/config.yaml` | ★ |
| `codeking eval` | 跑评测集（`eval/tasks/`） | 开发者 |
| `codeking rpc` | JSON-RPC over stdio（Desktop/自动化集成用） | 开发者 |
| `codeking --version` | 查看版本 | — |

## 5. 会话管理详解

会话 = 一段连续的对话上下文。每个项目（工作区）独立保存，互不干扰。

**存储位置**：`<项目>/.coderking/sessions/*.jsonl`（append-only，树状结构）。
注意不是 `~/.codeking`——那只是运行环境。

```bash
# 看看这个项目有哪些会话
codeking sessions
#  #  session             updated              task               msgs  tokens
#  1  *s-20260911-224836  2026-09-11 22:48:36  修复登录超时bug       14   12k/8k
#  2   default             2026-09-11 20:12:01  重构配置模块          31   45k/22k

# 恢复第 1 个（* 表示当前会话）
codeking -r 1

# 不记得序号就交互式选
codeking -r

# 想干净地开个新话题
codeking new

# 聊天过程中想换话题
❯ /new
```

小贴士：任务结束后再进 `codeking`，上下文自动接上（这就是默认行为，不需要 `-c`）。

## 6. 一次性任务：run

不想进交互界面、适合脚本/CI：

```bash
codeking run "给 utils/date.py 补充单元测试，覆盖边界情况"
codeking run "修复失败测试" --test "python -m pytest -q"    # 附带推荐的验证命令
```

## 7. 任务控制

```bash
codeking status          # 最近一次任务的 ID、状态、变更文件数、token
codeking stop <task_id>  # 取消运行中的任务（status 里能拿到 ID）
codeking diff            # 看代理到底改了什么（git diff）
codeking test            # 自己再跑一遍测试确认
```

## 8. 聊天内命令

| 输入 | 作用 |
| --- | --- |
| `/exit` 或 `/quit` | 退出 |
| `/new` | 立刻切换到新会话 |
| `/skills` | 列出当前可用 Skills |
| `/skill:<name>` | 为下一条消息启用指定 Skill |
| `/skill:<name> 任务` | 用指定 Skill 立即执行任务 |
| `/context` | 查看估算上下文、阈值和压缩次数 |
| `/compact` | 立即压缩当前会话上下文 |
| `Ctrl+C` | 中断当前运行（回到提示符）/ 退出 |
| 任意文字（运行中） | 转向（steering）：停止当前方向，改做你新说的事 |

## 9. 通用选项

| 选项 | 适用命令 | 说明 |
| --- | --- | --- |
| `-w, --workspace <path>` | 几乎全部 | 指定工作区，默认当前目录 |
| `--yes` | chat/new/run/tui | 自动批准危险操作（默认危险命令要人工确认） |
| `--commit` | chat/new/run/tui | 允许代理执行 `git commit` |
| `--test "<cmd>"` | chat/new/run | 给代理的推荐验证命令（软提示） |
| `--skill <name>` | chat/new/run | 显式加载 Skill；可以重复指定 |

危险命令（如 `rm -rf /`、`mkfs`）默认会被拦截并弹出确认，`--yes` 跳过。

## 10. 模型与配置

**环境变量**（写在 `.env` 里）：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `CODERKING_OPENAI_BASE_URL` | OpenAI 兼容接口地址 | — |
| `CODERKING_OPENAI_API_KEY` | API Key（不要提交进 git） | — |
| `CODERKING_MODEL` | 模型名 | gpt-4o-mini |
| `CODERKING_DISABLE_THINKING` | 关闭 thinking 字段（DeepSeek 类需要 true；GLM 始终思考模型用 false） | false |
| `CODERKING_SANDBOX_MODE` | `auto` / `docker` / `local` / `microvm` | auto |
| `CODERKING_SANDBOX_TIMEOUT_SEC` | 单条命令超时（秒） | 120 |
| `CODERKING_MAX_ITERATIONS` | 最大迭代轮数 | 24 |
| `CODERKING_ALLOW_COMMIT` | 是否允许 git commit | false |
| `CODERKING_CONTEXT_WINDOW` | 当前模型上下文窗口 | 128000 |
| `CODERKING_COMPRESSION_ENABLED` | 是否自动压缩长会话 | true |
| `CODERKING_COMPRESSION_THRESHOLD` | 窗口使用到该比例时压缩 | 0.75 |
| `CODERKING_COMPRESSION_RESERVE_TOKENS` | 为回复预留 token | 4096 |
| `CODERKING_COMPRESSION_KEEP_RECENT_MESSAGES` | 压缩时保护的最近消息数 | 20 |

也可以用命令把模型配置写进项目（只存 base_url/model，不存 key）：

```bash
codeking config model --base-url https://api.deepseek.com/v1 --model deepseek-chat
# 模型名也可以用 --name 指定
```

## 11. 沙箱说明

代理跑的每条 bash 命令都经过沙箱：

- `auto`（默认）：有 Docker 就用容器（CPU/内存限额、网络可关、环境变量清洁），没有就退回本地进程
- `docker`：强制容器，Docker 不可用则报错
- `local`：本地进程（开发用途，非强隔离）
- `microvm`：E2B / Firecracker 微虚拟机（最强隔离）

## 12. 项目级定制

```bash
codeking init
```

会在项目里生成：

- `.coderking/config.yaml` — 模型/运行时配置
- `.coderking/policy.yaml` — 工具审批策略（哪些操作要确认/直接拒绝）
- `AGENTS.md` — 项目指令（代理每次启动自动读取，写编码规范、注意事项）
- `.coderking/tools/browser_smoke/` — 自定义工具示例；当前 loader 可校验/执行，Agent 自动注册列入 M1
- `.coderking/skills/<name>/SKILL.md` — 项目级 Skill；也支持 `~/.coderking/skills/` 和 `~/.cursor/skills/`

## 13. 其他使用形态

```bash
codeking serve --port 8000   # 启动 API + Web
cd web && npm run dev        # 另开终端，浏览器打开 http://localhost:5173

codeking tui                 # 终端全屏界面（Chat/Tools/Terminal 三面板）
```

Desktop 版（Electron）与 Web 共用同一套界面：`cd desktop && npm start`。

## 14. 常见问题

**报 `401 Unauthorized`**：key 没配对。检查 `~/.coderking/.env`（全局）或项目 `.env` 里的 `CODERKING_OPENAI_API_KEY`。

**报 `429 ... 余额不足 (code 1113)`**：账户没额度了，去模型服务商控制台充值/领资源包。

**报 `400 该模型始终思考，不支持关闭思考`**：把 `CODERKING_DISABLE_THINKING` 改为 `false`（新版本已自动兜底重试）。

**退出后上下文丢了吗？** 没有。同目录再进 `codeking` 自动接上；`codeking sessions` 随时翻历史。

**它到底改了我什么文件？** `codeking diff` 一目了然；Web/Desktop 里还有逐行 Diff 视图和采纳/回滚按钮。

## 15. 速查表

```bash
codeking                    # 继续上次对话
codeking new                # 新对话
codeking -r                 # 选历史会话恢复
codeking -r 3               # 恢复第 3 个
codeking sessions           # 会话列表
codeking run "任务描述"      # 一次性任务
codeking diff               # 看改动
codeking status             # 任务状态
# 聊天内：/exit 退出 · /new 新会话 · Ctrl+C 中断
```

---

更多文档：

- [技术设计](../CoderKing-Technical-Design.md)
- [Web UI & CLI 设计](../CoderKing-WebUI-CLI-Design.md)
- [SDK 嵌入](../sdk.md) · [MCP 集成](../mcp-setup.md) · [安全策略](../security.md)
