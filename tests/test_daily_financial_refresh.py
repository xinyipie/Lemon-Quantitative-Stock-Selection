from argparse import Namespace

import daily_web_update


def test_daily_defaults_include_financial_refresh(monkeypatch):
    monkeypatch.setattr("sys.argv", ["daily_web_update.py"])
    assert daily_web_update.parse_args().skip_financial is False


def test_core_update_downloads_and_imports_same_financial_cache(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(daily_web_update, "run_command", lambda args, dry_run: commands.append(args))
    args = Namespace(skip_download=False, skip_history_import=False, skip_financial=False,
                     cache_dir=tmp_path / "isolated", history_db=tmp_path / "history.db", dry_run=True)
    daily_web_update.refresh_core_history_data("python", args, "20260901", "20260907")
    download, imported = commands
    assert "--skip-financial" not in download
    assert download[download.index("--cache-dir") + 1] == str(tmp_path / "isolated")
    assert {"fina_indicator", "income"} <= set(imported[imported.index("--tables") + 1:])
