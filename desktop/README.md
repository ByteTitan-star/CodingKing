# CoderKing Desktop

Electron 壳，加载 `web/` 的 React UI。默认通过 **stdio JSON-RPC** 直连 `coderking rpc`（无需单独启动 `coderking serve`）。

## 架构

```
Renderer (React)  ←preload IPC→  Main (Electron)  ←stdio JSONL→  coderking rpc
```

- Main 进程 `spawn('python', ['-m', 'coderking', 'rpc', '--workspace', dir])`（`shell: false`）
- 事件：`agent.event` 通知转发到 Renderer（与 WebSocket/SSE 同 schema）
- Preload 暴露 `window.coderkingDesktop.useRpc = true`

## 环境变量

| 变量 | 说明 |
|------|------|
| `CODERKING_BIN` | 直接指定 `coderking` 可执行文件 |
| `CODERKING_PYTHON` | 默认 `python`，用于 `-m coderking rpc` |
| `CODERKING_DESKTOP_URL` | 开发时 Vite URL，默认 `http://localhost:5188` |

## 开发启动（2 个终端）

```bash
# 1 — Vite（必须看到 Local: http://localhost:5188/）
cd web && npm run dev

# 2 — Electron（自动 spawn RPC 子进程）
cd desktop && npm run dev
```

生产模式（加载 `web/dist`）：

```bash
cd web && npm run build
cd desktop && npm run start
```

## 测试

```bash
cd desktop && npm test
```

## Electron 安装（国内网络）

```powershell
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
node node_modules/electron/install.js
```
