import os

import pytest
import requests


# 普通测试不初始化真实行情接口，避免依赖开发机凭据。
os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")


@pytest.fixture(autouse=True)
def block_external_http(monkeypatch):
    """外部HTTP必须由用例提供替身，不能消耗实际接口额度。"""
    def reject(self, method, url, *args, **kwargs):
        raise RuntimeError("测试禁止真实HTTP请求，请在接口边界注入测试数据")
    monkeypatch.setattr(requests.sessions.Session, "request", reject)
