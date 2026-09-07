from html.parser import HTMLParser
import base64
import importlib
import sys

import pytest
from fastapi.testclient import TestClient


class _HomeEntryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries = []
        self.headings = []
        self._in_heading = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "project-card" in attributes.get("class", "").split():
            self.entries.append((attributes.get("href"), attributes.get("aria-label")))
        if tag == "h1":
            self._in_heading = True

    def handle_endtag(self, tag):
        if tag == "h1":
            self._in_heading = False

    def handle_data(self, data):
        if self._in_heading and data.strip():
            self.headings.append(data.strip())


def test_public_home_exposes_two_clear_project_entries():
    """缺少任一项目入口或卡片不可整体点击时应失败。"""
    try:
        from gateway_home import render_public_home
    except ModuleNotFoundError:
        pytest.fail("gateway_home 应提供独立的首页渲染函数")

    parser = _HomeEntryParser()
    parser.feed(render_public_home())

    assert parser.headings == ["项目入口"]
    assert parser.entries == [
        ("/stock/", "进入选股助手"),
        ("/prototypes/", "进入产品原型"),
    ]


def test_gateway_keeps_root_empty_and_serves_directory_at_menu(tmp_path, monkeypatch):
    """菜单误留在根路径或 /menu/ 不可访问时应失败。"""
    prototype_dir = tmp_path / "prototypes"
    prototype_dir.mkdir()

    monkeypatch.setenv("STOCK_PRODUCT_WORK_DIR", str(tmp_path))
    sys.modules.pop("deploy.gateway", None)
    gateway = importlib.import_module("deploy.gateway")
    client = TestClient(gateway.app)

    root_response = client.get("/")
    menu_response = client.get("/menu/")

    assert root_response.status_code == 200
    assert root_response.content == b""
    assert menu_response.status_code == 200
    assert "项目入口" in menu_response.text
    assert 'href="/stock/"' in menu_response.text
    assert 'href="/prototypes/"' in menu_response.text


def test_gateway_imports_without_product_workspace_or_prototypes(monkeypatch):
    """未配置产品工作目录时，网关仍应能启动选股助手。"""
    monkeypatch.delenv("STOCK_PRODUCT_WORK_DIR", raising=False)
    sys.modules.pop("deploy.gateway", None)

    gateway = importlib.import_module("deploy.gateway")
    client = TestClient(gateway.app)

    assert client.get("/").status_code == 200
    assert client.get("/stock/static/app.css").status_code == 200
    assert client.get("/stock/openapi.json").status_code == 200
    assert client.get("/prototypes/").status_code == 404


def test_gateway_stock_redirect_keeps_the_mount_prefix(monkeypatch):
    monkeypatch.delenv("STOCK_PRODUCT_WORK_DIR", raising=False)
    sys.modules.pop("deploy.gateway", None)
    gateway = importlib.import_module("deploy.gateway")
    client = TestClient(gateway.app)

    response = client.get("/stock/stock?code=000001", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/stock/stock/000001"


def test_gateway_stock_mount_supports_browser_basic_auth(monkeypatch):
    monkeypatch.setenv("STOCK_WEB_TOKEN", "secret")
    sys.modules.pop("deploy.gateway", None)
    gateway = importlib.import_module("deploy.gateway")
    client = TestClient(gateway.app)
    basic = base64.b64encode(b"stock:secret").decode("ascii")

    denied = client.get("/stock/openapi.json")
    allowed = client.get(
        "/stock/openapi.json",
        headers={"Authorization": f"Basic {basic}"},
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_gateway_renders_stock_page_with_mounted_links(monkeypatch, tmp_path):
    from history_store import HistoryStore
    HistoryStore(tmp_path / "history.db").close()
    stock_module = importlib.import_module("web_app.app")
    monkeypatch.setattr(stock_module, "DEFAULT_HISTORY_DB_PATH", tmp_path / "history.db")
    monkeypatch.setattr(stock_module, "DEFAULT_SIGNAL_DB_PATH", tmp_path / "signals.db")
    gateway = importlib.import_module("deploy.gateway")
    client = TestClient(gateway.app)
    response = client.get("/stock/stock/abcdef")
    assert response.status_code == 200
    assert 'action="/stock/stock"' in response.text
    assert 'href="/stock/reports"' in response.text
