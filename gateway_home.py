"""服务器根路径的项目目录页。"""


def render_public_home() -> str:
    """返回简洁、响应式的双项目入口页。"""
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="个人项目导航入口">
  <title>项目入口</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --surface: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #e2e8f0;
      --accent: #2563eb;
      --accent-soft: #eff6ff;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC",
        "Microsoft YaHei", sans-serif;
      -webkit-font-smoothing: antialiased;
    }

    main {
      width: min(920px, calc(100% - 40px));
      min-height: 100vh;
      margin: 0 auto;
      padding: 96px 0 72px;
    }

    header { margin-bottom: 36px; }

    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 38px);
      line-height: 1.25;
      letter-spacing: -0.02em;
    }

    header p {
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 16px;
    }

    .project-list {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 20px;
    }

    .project-card {
      display: flex;
      min-height: 244px;
      padding: 28px;
      flex-direction: column;
      color: inherit;
      text-decoration: none;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 14px;
      transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
    }

    .project-card:hover,
    .project-card:focus-visible {
      border-color: #93b4f8;
      box-shadow: 0 12px 28px rgba(30, 64, 175, 0.08);
      transform: translateY(-2px);
      outline: none;
    }

    .project-type {
      align-self: flex-start;
      margin-bottom: 34px;
      padding: 4px 9px;
      color: #315792;
      background: var(--accent-soft);
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
    }

    h2 {
      margin: 0;
      font-size: 23px;
      line-height: 1.35;
    }

    .project-description {
      margin: 10px 0 28px;
      color: var(--muted);
      line-height: 1.7;
    }

    .project-action {
      display: flex;
      margin-top: auto;
      align-items: center;
      justify-content: space-between;
      color: var(--accent);
      font-size: 15px;
      font-weight: 650;
    }

    .arrow {
      font-size: 20px;
      line-height: 1;
      transition: transform 160ms ease;
    }

    .project-card:hover .arrow,
    .project-card:focus-visible .arrow { transform: translateX(3px); }

    footer {
      margin-top: 40px;
      color: #98a2b3;
      font-size: 13px;
    }

    @media (max-width: 680px) {
      main {
        width: min(100% - 28px, 520px);
        padding: 56px 0 44px;
      }

      header { margin-bottom: 26px; }
      .project-list { grid-template-columns: 1fr; }
      .project-card { min-height: 218px; padding: 24px; }
      .project-type { margin-bottom: 28px; }
    }

    @media (prefers-reduced-motion: reduce) {
      .project-card, .arrow { transition: none; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>项目入口</h1>
      <p>请选择要进入的项目</p>
    </header>

    <section class="project-list" aria-label="项目列表">
      <a class="project-card" href="/stock/" aria-label="进入选股助手">
        <span class="project-type">策略工具</span>
        <h2>选股助手</h2>
        <p class="project-description">查看每日市场判断、短线信号与长线观察。</p>
        <span class="project-action">进入选股助手 <span class="arrow" aria-hidden="true">→</span></span>
      </a>

      <a class="project-card" href="/prototypes/" aria-label="进入产品原型">
        <span class="project-type">交互演示</span>
        <h2>产品原型</h2>
        <p class="project-description">查看校本研修知识与智能填报平台的产品演示。</p>
        <span class="project-action">查看产品原型 <span class="arrow" aria-hidden="true">→</span></span>
      </a>
    </section>

    <footer>个人项目导航</footer>
  </main>
</body>
</html>"""
