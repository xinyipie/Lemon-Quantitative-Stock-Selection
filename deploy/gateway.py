"""对外入口：分离选股助手与产品原型。"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from gateway_home import render_public_home
from web_app.app import BASE_DIR, PRODUCT_WORK_DIR, app as stock_app


PROTOTYPE_DIR = PRODUCT_WORK_DIR / "prototypes"

app = FastAPI(title="Personal web gateway", docs_url=None, redoc_url=None)
app.mount("/prototypes", StaticFiles(directory=PROTOTYPE_DIR, html=True), name="prototypes")
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
