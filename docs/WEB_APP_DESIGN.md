# Web v0.1 设计方案

## 定位

本项目 Web 端第一版是本地只读的“A股策略研究看板”，用于查看策略信号、历史数据、单股体检和数据库状态。它不是交易软件，不包含下单、仓位管理或交易执行能力。

## 技术路线

- 后端：FastAPI
- 模板：Jinja2
- 交互：HTMX 预留，v0.1 先使用普通表单和链接
- 数据：SQLite
  - `data/stock_history.db`：历史事实库
  - `data/stock_signals.db`：信号和观察池状态库

## v0.1 页面

1. 今日看板
   - 展示数据库最新交易日、股票数量、信号库摘要
   - 提供单股查询入口

2. 数据库状态
   - 展示 `history_db_check.py` 的体检结果
   - 展示每张表的行数与日期范围

3. 单股查询
   - 输入股票代码
   - 展示基础信息、最新行情、近10/40/80日收益、估值、资金流、财务和信号状态

4. 短线信号
   - 展示最近信号记录，区分模式和策略 profile

5. 长线观察池
   - 展示当前 active 的长线观察池/Elite 状态

## 第一阶段不做

- 自动下单
- 仓位管理
- 用户系统
- 云部署
- 新闻聚合
- 复杂图表
- 在线调参

## 文件结构

```text
web_app/
  app.py
  services/
    history_service.py
    signal_service.py
  templates/
    base.html
    dashboard.html
    db_status.html
    stock_detail.html
    signals.html
    longterm_pool.html
  static/
    app.css
```

## 启动命令

```powershell
python -m uvicorn web_app.app:app --reload --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000
```
