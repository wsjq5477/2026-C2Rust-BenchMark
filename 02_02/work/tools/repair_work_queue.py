#!/usr/bin/env python3
"""Persistent per-task repair queue used by implementation, C-Cross and tests.

The queue deliberately has no project-wide numeric repair budget.  Each task
gets a small scheduling quantum in two sweeps so a hard failure cannot starve
the remaining dynamically discovered work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
ATTEMPTS_PER_SWEEP = 2
VALID_STATES = {
    "queued",
    "active",
    "provisional_pass",
    "confirmed_pass",
    "deferred_no_progress",
    "regressed",
    "exhausted",
}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_queue(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "phases": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("repair work queue has an unsupported schema")
    if not isinstance(value.get("phases"), dict):
        raise ValueError("repair work queue phases must be an object")
    return value


def _phase(queue: dict[str, Any], phase: str) -> dict[str, Any]:
    phases = queue.setdefault("phases", {})
    value = phases.setdefault(
        phase,
        {
            "phase": phase,
            "sweep": 1,
            "attempts_per_sweep": ATTEMPTS_PER_SWEEP,
            "tasks": {},
            "last_full_confirmation_id": None,
        },
    )
    if not isinstance(value.get("tasks"), dict):
        raise ValueError(f"repair queue phase {phase!r} tasks must be an object")
    return value


def _task(task_id: str, *, scenario_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "scenario_ids": scenario_ids or [task_id],
        "state": "queued",
        "sweep": 1,
        "attempts_in_sweep": 0,
        "total_attempts": 0,
        "no_progress_attempts": 0,
        "last_attempt_id": None,
        "last_fingerprint": None,
        "changed_files": [],
    }


def _validate(queue: dict[str, Any]) -> None:
    for phase_name, phase in queue.get("phases", {}).items():
        if not isinstance(phase, dict) or not isinstance(phase.get("tasks"), dict):
            raise ValueError(f"invalid repair queue phase: {phase_name}")
        for task_id, task in phase["tasks"].items():
            if not isinstance(task, dict) or task.get("state") not in VALID_STATES:
                raise ValueError(f"invalid repair task state: {task_id}")


def sync_tasks(
    path: Path,
    phase_name: str,
    task_ids: Iterable[str],
    *,
    passed_ids: Iterable[str] = (),
    full_confirmation_id: str | None = None,
    fingerprints: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Synchronize dynamically discovered tasks with current validation results."""

    queue = load_queue(path)
    phase = _phase(queue, phase_name)
    tasks: dict[str, Any] = phase["tasks"]
    dynamic = {str(item) for item in task_ids}
    passed = {str(item) for item in passed_ids}
    fingerprints = fingerprints or {}
    full = full_confirmation_id is not None

    for task_id in sorted(dynamic):
        task = tasks.setdefault(task_id, _task(task_id))
        if task_id in passed:
            task["state"] = "confirmed_pass" if full else "provisional_pass"
            task["last_fingerprint"] = None
        elif task.get("state") in {"confirmed_pass", "provisional_pass"}:
            task["state"] = "regressed"
            task["attempts_in_sweep"] = 0
            task["no_progress_attempts"] = 0
        elif task.get("state") == "active":
            task["state"] = "queued"
        if task_id in fingerprints:
            task["last_fingerprint"] = fingerprints[task_id]

    # Inputs are dynamic.  Removed tasks are retained for audit but do not
    # participate in convergence for the current phase scope.
    phase["dynamic_task_ids"] = sorted(dynamic)
    phase["dynamic_scope_fingerprint"] = hashlib.sha256(
        json.dumps(sorted(dynamic)).encode("utf-8")
    ).hexdigest()
    if full:
        phase["last_full_confirmation_id"] = full_confirmation_id
    _promote_second_sweep(phase)
    phase["summary"] = phase_summary(phase)
    _validate(queue)
    _atomic_json(path, queue)
    return phase


def record_attempt(
    path: Path,
    phase_name: str,
    task_ids: Iterable[str],
    *,
    attempt_id: str,
    progress_ids: Iterable[str] = (),
    passed_ids: Iterable[str] = (),
    fingerprints: dict[str, str] | None = None,
    changed_files: Iterable[str] = (),
    repair_kind: str = "local",
) -> dict[str, Any]:
    queue = load_queue(path)
    phase = _phase(queue, phase_name)
    tasks: dict[str, Any] = phase["tasks"]
    progress = {str(item) for item in progress_ids}
    passed = {str(item) for item in passed_ids}
    fingerprints = fingerprints or {}
    changes = sorted({str(item) for item in changed_files})
    selected = sorted({str(item) for item in task_ids})
    blocked = [
        task_id
        for task_id in selected
        if task_id in tasks and tasks[task_id].get("state") in {"confirmed_pass", "exhausted"}
    ]
    if blocked:
        raise ValueError("repair task is already terminal: " + ", ".join(blocked))

    for task_id in selected:
        task = tasks.setdefault(task_id, _task(task_id))
        task["state"] = "active"
        task["sweep"] = int(phase.get("sweep", 1))
        task["attempts_in_sweep"] = int(task.get("attempts_in_sweep", 0)) + 1
        task["total_attempts"] = int(task.get("total_attempts", 0)) + 1
        task["last_attempt_id"] = attempt_id
        task["repair_kind"] = repair_kind
        task["changed_files"] = changes
        if task_id in fingerprints:
            task["last_fingerprint"] = fingerprints[task_id]
        if task_id in passed:
            task["state"] = "provisional_pass"
            task["no_progress_attempts"] = 0
        else:
            made_progress = task_id in progress
            task["no_progress_attempts"] = 0 if made_progress else int(task.get("no_progress_attempts", 0)) + 1
            if int(task["attempts_in_sweep"]) >= ATTEMPTS_PER_SWEEP:
                task["state"] = "deferred_no_progress" if int(task["sweep"]) == 1 else "exhausted"
            else:
                task["state"] = "queued"

    phase["last_attempt_id"] = attempt_id
    _promote_second_sweep(phase)
    phase["summary"] = phase_summary(phase)
    _validate(queue)
    _atomic_json(path, queue)
    return phase


def _promote_second_sweep(phase: dict[str, Any]) -> None:
    dynamic = set(phase.get("dynamic_task_ids") or phase.get("tasks", {}).keys())
    tasks = [phase["tasks"][task_id] for task_id in dynamic if task_id in phase["tasks"]]
    if int(phase.get("sweep", 1)) != 1 or not tasks:
        return
    blocking = {"queued", "active", "regressed"}
    if any(task.get("state") in blocking for task in tasks):
        return
    deferred = [task for task in tasks if task.get("state") == "deferred_no_progress"]
    if not deferred:
        return
    phase["sweep"] = 2
    for task in deferred:
        task["state"] = "queued"
        task["sweep"] = 2
        task["attempts_in_sweep"] = 0
        task["no_progress_attempts"] = 0


def phase_summary(phase: dict[str, Any]) -> dict[str, Any]:
    dynamic = set(phase.get("dynamic_task_ids") or phase.get("tasks", {}).keys())
    tasks = [phase["tasks"][task_id] for task_id in dynamic if task_id in phase["tasks"]]
    counts = {state: 0 for state in sorted(VALID_STATES)}
    for task in tasks:
        counts[str(task.get("state"))] += 1
    all_pass = bool(tasks) and all(task.get("state") == "confirmed_pass" for task in tasks)
    exhausted = bool(tasks) and all(task.get("state") in {"confirmed_pass", "exhausted"} for task in tasks)
    repair_actions_exhausted = bool(tasks) and all(
        task.get("state") in {"provisional_pass", "confirmed_pass", "exhausted"}
        for task in tasks
    )
    pending = [
        str(task.get("task_id"))
        for task in tasks
        if task.get("state") not in {"confirmed_pass", "exhausted"}
    ]
    return {
        "total": len(tasks),
        "counts": counts,
        "all_pass": all_pass,
        "queue_exhausted": exhausted,
        "repair_actions_exhausted": repair_actions_exhausted,
        "pending_task_ids": sorted(pending),
        "sweep": int(phase.get("sweep", 1)),
        "last_full_confirmation_id": phase.get("last_full_confirmation_id"),
        "dynamic_scope_fingerprint": phase.get("dynamic_scope_fingerprint"),
    }


def convergence(phase: dict[str, Any], *, current_full_confirmation_id: str | None = None) -> dict[str, Any]:
    summary = phase_summary(phase)
    if summary["all_pass"] and current_full_confirmation_id:
        return {"status": "ready_for_final", "terminal": False, "next_action": "run_fresh_final", **summary}
    if summary["queue_exhausted"] and current_full_confirmation_id:
        return {"status": "failed_final", "terminal": True, "next_action": "continue_to_test_and_report", **summary}
    if summary["repair_actions_exhausted"]:
        return {"status": "repair_required", "terminal": False, "next_action": "run_full_confirmation", **summary}
    return {"status": "repair_required", "terminal": False, "next_action": "repair_next_queued_task", **summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the per-task repair work queue.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--phase")
    args = parser.parse_args(argv)
    path = Path(args.root).resolve() / "logs" / "trace" / "repair-work-queue.json"
    queue = load_queue(path)
    if args.phase:
        phase = queue.get("phases", {}).get(args.phase)
        if not isinstance(phase, dict):
            print(f"no repair queue phase: {args.phase}")
            return 1
        print(json.dumps({**phase, "summary": phase_summary(phase)}, indent=2, sort_keys=True))
    else:
        print(json.dumps(queue, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
