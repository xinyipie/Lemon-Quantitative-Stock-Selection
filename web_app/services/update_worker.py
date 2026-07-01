#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Subprocess entrypoint for dashboard update jobs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from web_app.services.update_service import run_update_job


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        return 2
    command = json.loads(args[0])
    status_path = Path(args[1])
    run_update_job(command, status_path=status_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
