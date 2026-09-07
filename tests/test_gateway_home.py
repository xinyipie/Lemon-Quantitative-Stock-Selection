from html.parser import HTMLParser
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

    import web_app.app as stock_app_module

    monkeypatch.setattr(stock_app_module, "PRODUCT_WORK_DIR", tmp_path, raising=False)
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
