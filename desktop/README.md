# CoderKing Desktop

Electron 壳，加载 `web/` 的 React UI。API 由本机 `coderking serve` 提供。

## 重要：端口

CoderKing Vite **固定 `5188`**（`strictPort`），避免和别的项目抢默认 `5173`。

若 Desktop 打开后出现「Personal Scholar Agent」等其它应用，说明连错了端口。

## 开发启动（3 个终端）

```bash
# 1 — Runtime API
python -m coderking serve --port 8000

# 2 — Vite（必须看到 Local: http://localhost:5188/）
cd web && npm run dev

# 3 — Electron（加载 5188）
cd desktop && npm run dev
```

浏览器调试：`http://localhost:5188`

## Electron 安装（国内网络）

```powershell
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
node node_modules/electron/install.js
```
