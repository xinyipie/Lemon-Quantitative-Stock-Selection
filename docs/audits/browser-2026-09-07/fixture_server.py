"""浏览器审计专用：保留真实页面和路由，仅模拟更新与 AI 下游。"""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ["LEMON_SKIP_TUSHARE_INIT"] = "1"
os.environ["STOCK_WEB_TOKEN"] = ""
os.environ["STOCK_WEB_ALLOW_LOCAL_WRITE"] = "1"

import web_app.app as web
from deploy.gateway import app

state = {"state": "idle", "running": False, "message": "审计模拟环境：未启动"}
count = 0
lock = threading.Lock()


def read_status():
    with lock:
        return dict(state)


def start_update(mode="daily"):
    global count
    with lock:
        if state.get("running"):
            return dict(state)
        count += 1
        attempt = count
        state.clear()
        state.update(state="running", running=True, mode=mode,
                     message="审计模拟任务运行中", started_at="2026-09-07 12:00:00")

    def finish():
        time.sleep(15)
        with lock:
            state.update(state="finished" if attempt % 2 else "failed", running=False,
                         message="审计模拟完成" if attempt % 2 else "审计模拟失败",
                         finished_at="2026-09-07 12:00:15",
                         stderr_tail="" if attempt % 2 else "模拟下游错误：未访问外部服务")
    threading.Thread(target=finish, daemon=True).start()
    return read_status()


web.start_web_update = start_update
web.read_update_status = read_status
web._read_decorated_update_status = read_status
web.get_or_create_signal_explanation = lambda *args, **kwargs: {}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8767, log_level="warning")
