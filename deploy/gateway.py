"""对外入口：分离选股助手与产品原型。"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from gateway_home import render_public_home
from web_app.app import BASE_DIR, app as stock_app


_product_work_dir = os.environ.get("STOCK_PRODUCT_WORK_DIR", "").strip()
PROTOTYPE_DIR = Path(_product_work_dir).expanduser() / "prototypes" if _product_work_dir else None

app = FastAPI(title="Personal web gateway", docs_url=None, redoc_url=None)
if PROTOTYPE_DIR and PROTOTYPE_DIR.is_dir():
    app.mount("/prototypes", StaticFiles(directory=PROTOTYPE_DIR, html=True), name="prototypes")
    # 保留现有生产环境的旧入口，原型内容仍来自独立目录。
    app.mount("/stock/prototypes", StaticFiles(directory=PROTOTYPE_DIR, html=True), name="stock-prototypes")
app.mount("/stock/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/stock", stock_app, name="stock")


@app.get("/", response_class=HTMLResponse)
def public_home() -> str:
    """根地址不展示任何项目入口。"""
    return ""


@app.get("/menu/", response_class=HTMLResponse)
def public_menu() -> str:
    """统一展示可访问的项目目录。"""
    return render_public_home()


@app.api_route(
    "/{legacy_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
def redirect_stock_internal_link(request: Request, legacy_path: str):
    """仅为从 /stock/ 页面发起的旧绝对路径请求补上前缀。"""
    referer_path = urlsplit(request.headers.get("referer", "")).path
    if referer_path != "/stock" and not referer_path.startswith("/stock/"):
        raise HTTPException(status_code=404, detail="Not Found")

    target = f"/stock/{legacy_path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target, status_code=307)
