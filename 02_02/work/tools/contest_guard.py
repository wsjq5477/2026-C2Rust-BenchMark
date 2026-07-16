#!/usr/bin/env python3
"""Shared contest freeze guard for mutating tools and dispatch points."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FINALIZE_EXIT_CODE = 75
CONTROL_DIR = Path("logs/trace/contest-control")


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def contest_state(root: Path) -> dict[str, Any]:
    root = root.resolve()
    control = root / CONTROL_DIR
    run = _read(control / "run.json")
    frozen = _read(control / "submission-frozen.json")
    requested = _read(control / "freeze-requested.json")
    if frozen:
        status = "submission_frozen"
    elif requested:
        status = "freeze_requested"
    elif run.get("status") in {"running", "ready"}:
        status = "running"
    else:
        status = "not_started"
    return {"status": status, "run": run, "freeze_requested": requested, "submission_frozen": frozen}


def mutation_allowed(root: Path) -> tuple[bool, str | None]:
    state = contest_state(root)
    if state["status"] in {"freeze_requested", "submission_frozen"}:
        return False, "CONTEST_FINALIZE_REQUIRED"
    return True, None


def guard_mutation_allowed(root: Path) -> None:
    allowed, reason = mutation_allowed(root)
    if not allowed:
        raise RuntimeError(reason or "CONTEST_FINALIZE_REQUIRED")


def guard_dispatch_allowed(root: Path) -> None:
    guard_mutation_allowed(root)
