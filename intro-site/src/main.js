import './style.css'

const app = document.querySelector('#app')

app.innerHTML = `
  <a class="skip" href="#main">跳到正文</a>

  <header class="top">
    <div class="top__inner">
      <a class="brand" href="#top" aria-label="CoderKing 首页">
        <span class="brand__mark" aria-hidden="true"></span>
        <span class="brand__name">CoderKing</span>
      </a>
      <nav class="nav" aria-label="章节导航">
        <a href="#core">核心逻辑</a>
        <a href="#layers">四层架构</a>
        <a href="#orchestrate">编排模式</a>
        <a href="#tools">工具</a>
        <a href="#safety">沙箱</a>
        <a href="#channels">通道</a>
      </nav>
      <a class="top__cta" href="#core">开始阅读</a>
    </div>
  </header>

  <main id="main">
    <section class="hero" id="top">
      <div class="hero__glow" aria-hidden="true"></div>
      <div class="hero__grid" aria-hidden="true"></div>
      <div class="hero__orbit" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
      <div class="hero__content">
        <p class="hero__brand">CoderKing</p>
        <h1>自主 Coding Agent<br />入门导览</h1>
        <p class="hero__lead">
          用自然语言下任务，Agent 在受控沙箱里读代码、改文件、跑测试，直到任务完成。
        </p>
        <div class="hero__actions">
          <a class="btn btn--primary" href="#core">理解核心循环</a>
          <a class="btn btn--ghost" href="#orchestrate">编排模式说明</a>
        </div>
      </div>
    </section>

    <section class="section" id="core">
      <div class="section__head">
        <p class="eyebrow">01 · 核心逻辑</p>
        <h2>一条循环，把任务做完</h2>
        <p class="section__lead">
          CoderKing 的本质是 <strong>ReAct 式单 Agent 循环</strong>：反复「感知上下文 → 模型决策 → 调用工具 → 观察结果」，直到模型不再需要工具或达到终止条件。
        </p>
      </div>
      <ol class="loop" aria-label="Agent 五阶段循环">
        <li class="loop__step" data-step="1"><strong>Perceive</strong><span>组装上下文与系统提示</span></li>
        <li class="loop__step" data-step="2"><strong>Decide</strong><span>调用 LLM，决定说什么或调哪些工具</span></li>
        <li class="loop__step" data-step="3"><strong>Act</strong><span>在沙箱中执行工具（读/写/改/跑命令…）</span></li>
        <li class="loop__step" data-step="4"><strong>Observe</strong><span>把工具结果写回对话</span></li>
        <li class="loop__step" data-step="5"><strong>Re-perceive</strong><span>决定继续下一轮还是结束</span></li>
      </ol>
      <p class="note">
        实现上由 L1 的显式五阶段 FSM 驱动；SWE 模式还会在循环中切换「角色」并限制可用工具集。
      </p>
    </section>

    <section class="section section--alt" id="layers">
      <div class="section__head">
        <p class="eyebrow">02 · 如何设计</p>
        <h2>Pi 风格四层分包</h2>
        <p class="section__lead">
          对齐白皮书的极简分层：下层不感知上层 UI，上层只通过稳定接口驱动循环。
        </p>
      </div>
      <div class="layers">
        <article class="layer">
          <span class="layer__tag">L0</span>
          <h3>coderking_llm</h3>
          <p>OpenAI 兼容 Provider、流式 SSE、重试与 token 统计。</p>
        </article>
        <article class="layer">
          <span class="layer__tag">L1</span>
          <h3>coderking_agent_core</h3>
          <p>纯 Agent Loop + FSM，零领域逻辑：不碰沙箱、Git、文件工具。</p>
        </article>
        <article class="layer">
          <span class="layer__tag">L2</span>
          <h3>coderking_coding_agent</h3>
          <p>工具、沙箱、会话、安全策略、SWE Harness 与 Atomic 扩展。</p>
        </article>
        <article class="layer">
          <span class="layer__tag">L3</span>
          <h3>coderking_transport</h3>
          <p>TUI / SSE / RPC 等传输原语；CLI、Web、桌面走门面接入。</p>
        </article>
      </div>
      <p class="note">
        门面包 <code>src/coderking</code> 负责 CLI / FastAPI / 配置；依赖方向固定为
        <code>transport → coding_agent → agent_core → llm</code>。
      </p>
    </section>

    <section class="section" id="orchestrate">
      <div class="section__head">
        <p class="eyebrow">03 · 编排模式</p>
        <h2>不是主从多 Agent</h2>
        <p class="section__lead">
          仓库里<strong>没有</strong>「主 Agent 调度多个从 Agent」的编排器。始终是<strong>同一条循环、同一条 LLM 对话流</strong>。
        </p>
      </div>
      <div class="split">
        <div class="panel panel--warn">
          <h3>不是什么</h3>
          <ul>
            <li>不是 Planner / Coder / Tester 三个独立进程互发消息</li>
            <li>不是主从 Swarm / 多 Agent 投票</li>
            <li>角色不是 FSM 状态，而是 L2 Harness 的软约束</li>
          </ul>
        </div>
        <div class="panel panel--ok">
          <h3>实际是什么</h3>
          <ul>
            <li><strong>默认 Atomic</strong>：L1 纯 Loop + 四原子工具（Read/Write/Edit/Bash），无固定角色 workflow</li>
            <li><strong>可选 SWE</strong>：<code>extension=swe</code> 才启用角色切换（规划 → 编码 → 执行 → 审查 / 修复）</li>
            <li><strong>Steering / Follow-up</strong>：运行中可插入转向消息，成功后可排队跟进任务</li>
          </ul>
        </div>
      </div>
      <div class="roles" aria-label="可选 SWE 角色流">
        <span>Planner</span>
        <span class="roles__arrow" aria-hidden="true"></span>
        <span>Coding</span>
        <span class="roles__arrow" aria-hidden="true"></span>
        <span>Execution</span>
        <span class="roles__arrow" aria-hidden="true"></span>
        <span>Reviewer</span>
        <span class="roles__repair">仅 --extension swe：失败 → Repair → 再测</span>
      </div>
    </section>

    <section class="section section--alt" id="tools">
      <div class="section__head">
        <p class="eyebrow">04 · 基本工具</p>
        <h2>绑定了哪些能力</h2>
        <p class="section__lead">按扩展配置不同，工具面宽窄不同；动态工具与 MCP 可在运行中扩展。</p>
      </div>
      <div class="tool-grid">
        <article class="tool">
          <h3>Atomic 四件套</h3>
          <p class="tool__mode">默认 extension = atomic</p>
          <ul class="chips">
            <li>read</li><li>write</li><li>edit</li><li>bash</li>
          </ul>
          <p>Pi 风格极简：读写改文件 + 终端，由 L1 <code>run_agent_loop</code> 驱动。</p>
        </article>
        <article class="tool">
          <h3>SWE Harness 工具</h3>
          <p class="tool__mode">可选 extension = swe</p>
          <ul class="chips">
            <li>read_file</li><li>write_file</li><li>edit_file</li><li>search_code</li>
            <li>shell</li><li>run_tests</li><li>git_*</li><li>finish_task…</li>
          </ul>
          <p>按角色白名单开放；含规划/提交/请求修复等元工具。</p>
        </article>
        <article class="tool">
          <h3>扩展能力</h3>
          <p class="tool__mode">可选接入</p>
          <ul class="chips">
            <li>MCP（mcp_*）</li><li>.coderking/tools 动态工具</li>
          </ul>
          <p>MCP 默认需人工确认；动态工具每轮可刷新，在沙箱内执行。</p>
        </article>
      </div>
    </section>

    <section class="section" id="safety">
      <div class="section__head">
        <p class="eyebrow">05 · 沙箱与安全</p>
        <h2>改代码也要可控</h2>
        <p class="section__lead">工具副作用发生在沙箱中；策略引擎在调用前门禁危险操作。</p>
      </div>
      <ul class="mech">
        <li>
          <strong>运行后端</strong>
          <span>local（开发兜底）/ docker / auto / microvm（mock · E2B · Firecracker 桩）</span>
        </li>
        <li>
          <strong>CoW 工作区</strong>
          <span>会话级拷贝；成功可 promote，中断可回滚快照</span>
        </li>
        <li>
          <strong>网络与凭据</strong>
          <span>域名白名单（none / full / restricted）；环境变量与敏感路径脱敏</span>
        </li>
        <li>
          <strong>策略引擎</strong>
          <span>拒绝危险 shell / 敏感文件写入；删除、commit、MCP 等可要求审批</span>
        </li>
      </ul>
    </section>

    <section class="section section--alt" id="channels">
      <div class="section__head">
        <p class="eyebrow">06 · 入口与上下文</p>
        <h2>同一套 Runtime，多种通道</h2>
      </div>
      <div class="channels">
        <p><strong>通道：</strong>CLI · Web（WS / SSE）· TUI · RPC stdio · SDK 嵌入 · Desktop（Electron）</p>
        <p><strong>上下文：</strong>角色 System Prompt · 项目 <code>AGENTS.md</code> · Skills 延迟加载 · 会话 JSONL 树状持久化</p>
      </div>
      <blockquote class="takeaway">
        <p>
          一句话记住：CoderKing 用<strong>单 Agent 纯循环</strong>完成编码任务（对齐 Pi）；默认 Atomic 四工具；SWE 角色 harness 仅显式 opt-in；沙箱与策略负责安全边界，CLI/Web/桌面都接到同一 Runtime。
        </p>
      </blockquote>
    </section>
  </main>

  <footer class="footer">
    <div class="footer__inner">
      <p>本站与主工程隔离，仅作 CoderKing Coding Agent 入门介绍。</p>
      <p class="footer__meta">本地启动：<code>cd intro-site && npm run dev</code> → <code>http://localhost:5173</code></p>
    </div>
  </footer>
`

const top = document.querySelector('.top')
const onScroll = () => {
  top?.classList.toggle('top--solid', window.scrollY > 24)
}
window.addEventListener('scroll', onScroll, { passive: true })
onScroll()

const reveal = document.querySelectorAll(
  '.loop__step, .layer, .panel, .tool, .mech li, .takeaway, .roles',
)
const io = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-in')
        io.unobserve(entry.target)
      }
    })
  },
  { threshold: 0.15, rootMargin: '0px 0px -8% 0px' },
)
reveal.forEach((el, i) => {
  el.style.setProperty('--delay', `${Math.min(i % 5, 4) * 60}ms`)
  io.observe(el)
})
