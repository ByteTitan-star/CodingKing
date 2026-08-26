# Desktop Electron + Chat UI 实现计划

> **面向 AI 代理：** 按任务顺序实现；完成后跑 `web` build 与 Desktop 启动检查。

**目标：** 用 Electron 壳 + ChatGPT 式 React 布局替换三栏仪表盘，复用现有 FastAPI/WS。

**架构：** `desktop/` 仅负责窗口与目录选择；`web/` 重做布局（左会话 / 中聊天 / 右可折叠工作区）；开发连 `coderking serve:8000`。

**技术栈：** Electron、React 19、Vite、Tailwind 4

---

### 任务 1：Electron shell

- 创建：`desktop/package.json`、`desktop/main.mjs`、`desktop/preload.cjs`、`desktop/README.md`
- [ ] 开发模式加载 `http://localhost:5188`
- [ ] preload 暴露 `openDirectory`

### 任务 2：ChatGPT 式 UI

- 修改：`web/src/App.tsx`、`web/src/index.css`、`web/index.html`
- [ ] 左栏会话、中栏消息流+composer、右栏按任务自动展开
- [ ] 保留 testid 便于后续 E2E

### 任务 3：验证

- [ ] `cd web && npm run build`
- [ ] 文档路径已指向 Desktop
