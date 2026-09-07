import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient


def test_legacy_systemd_entrypoint_uses_packaged_gateway():
    import gateway
    from deploy.gateway import app

    assert gateway.app is app


def test_gateway_preserves_both_existing_prototype_addresses(tmp_path, monkeypatch):
    prototype = tmp_path / "prototypes"
    prototype.mkdir()
    (prototype / "index.html").write_text("deployment prototype fixture", encoding="utf-8")
    monkeypatch.setenv("STOCK_PRODUCT_WORK_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("gateway_release_fixture", Path("deploy/gateway.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        for path in ("/prototypes/", "/stock/prototypes/"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.text == "deployment prototype fixture"
