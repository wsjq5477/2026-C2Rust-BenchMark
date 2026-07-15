#!/usr/bin/env python3
"""Finite, evidence-driven controller for C-cross convergence.

The controller emits bounded task packets and can execute generated scenario
isolation commands.  It never edits implementation sources on an agent's
behalf.  Restoring a tool-owned best snapshot requires an explicit flag.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            result.append(value)
    return result


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe snapshot path: {value}")
    return path


def restore_best_snapshot(root: Path, trace: Path, project_name: str) -> dict[str, Any]:
    """Restore only files listed in a verified tool-owned snapshot manifest."""

    c_cross = trace / "c-cross"
    best_path = c_cross / "snapshots" / "best.json"
    best = _load_json(best_path)
    attempt_id = str(best.get("attempt_id") or "")
    if not attempt_id:
        raise ValueError("best snapshot has no attempt_id")
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", attempt_id)
    snapshot_root = (c_cross / "snapshots" / safe_id).resolve()
    snapshots_root = (c_cross / "snapshots").resolve()
    if snapshots_root not in snapshot_root.parents:
        raise ValueError("best snapshot escapes logs/trace/c-cross/snapshots")
    manifest = _load_json(snapshot_root / "manifest.json")
    if manifest.get("source_scope") != "src/**":
        raise ValueError("best snapshot does not declare the required src/** scope")
    manifest_project = manifest.get("project_name")
    if isinstance(manifest_project, str) and manifest_project != Path(project_name).name:
        raise ValueError(
            f"best snapshot belongs to {manifest_project}, not requested project {Path(project_name).name}"
        )
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("best snapshot manifest has no files")

    project = (root / project_name).resolve()
    if root.resolve() not in project.parents:
        raise ValueError(f"Rust project must stay under workbench root: {project}")
    if not project.is_dir():
        raise ValueError(f"Rust project not found: {project}")
    validated: list[tuple[Path, Path, str]] = []
    for item in raw_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("malformed best snapshot file record")
        relative = _safe_relative(item["path"])
        if len(relative.parts) < 2 or relative.parts[0] != "src":
            raise ValueError(f"best snapshot may restore only project src/**: {relative}")
        expected_hash = str(item.get("sha256") or "")
        source = (snapshot_root / "files" / relative).resolve()
        if (snapshot_root / "files").resolve() not in source.parents or not source.is_file():
            raise ValueError(f"snapshot source is missing or unsafe: {relative}")
        if not expected_hash or _sha256(source) != expected_hash:
            raise ValueError(f"snapshot hash mismatch: {relative}")
        destination = (project / relative).resolve()
        if project not in destination.parents:
            raise ValueError(f"snapshot destination escapes project: {relative}")
        if destination.exists() and not destination.is_file():
            raise ValueError(f"snapshot destination is not a file: {relative}")
        validated.append((source, destination, relative.as_posix()))

    restore_id = str(time.time_ns())
    restore_root = c_cross / "snapshots" / "restores" / restore_id
    restored: list[dict[str, Any]] = []
    for source, destination, relative in validated:
        backup = restore_root / "before" / relative
        old_hash = None
        if destination.is_file():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
            old_hash = _sha256(backup)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        restored.append(
            {
                "path": relative,
                "previous_sha256": old_hash,
                "restored_sha256": _sha256(destination),
                "backup": (
                    f"logs/trace/c-cross/snapshots/restores/{restore_id}/before/{relative}"
                    if old_hash
                    else None
                ),
            }
        )
    receipt = {
        "schema_version": 1,
        "restore_id": restore_id,
        "source_attempt_id": attempt_id,
        "project": project_name,
        "restored_files": restored,
        "note": "Only manifest-listed files were restored; extra current files were not deleted.",
    }
    _write_json(restore_root / "receipt.json", receipt)
    return receipt


def _consecutive_repair_rounds(attempts: list[dict[str, Any]]) -> int:
    rounds = 0
    for attempt in reversed(attempts):
        kind = attempt.get("kind")
        trigger = str(attempt.get("trigger") or "")
        if kind == "repair":
            rounds += 1
            continue
        if kind == "confirmation":
            continue
        if kind == "checkpoint" and trigger.startswith("isolate_"):
            continue
        break
    return rounds


def build_task_packet(
    matrix: dict[str, Any],
    plan: dict[str, Any],
    attempts: list[dict[str, Any]],
    isolation_queue: dict[str, Any],
    *,
    max_rounds: int,
) -> dict[str, Any]:
    rounds_used = _consecutive_repair_rounds(attempts)
    rounds_remaining = max(0, max_rounds - rounds_used)
    latest = attempts[-1] if attempts else {}
    pending_isolation = [
        item
        for item in isolation_queue.get("queue", [])
        if isinstance(item, dict) and item.get("status") == "pending"
    ] if isinstance(isolation_queue.get("queue"), list) else []
    tasks = [item for item in plan.get("tasks", []) if isinstance(item, dict)] if isinstance(plan.get("tasks"), list) else []

    if matrix.get("verification_result") == "pass":
        next_action = "ADVANCE"
        selected_task = None
    elif latest.get("regression") and latest.get("restore_best_available"):
        next_action = "RESTORE_BEST"
        selected_task = {
            "target_agent": "controller",
            "objective": "Explicitly restore the verified best-known tool snapshot.",
            "verification_command": "python3 work/tools/c_cross_converge.py --root . --restore-best",
        }
    elif rounds_remaining == 0:
        if latest.get("best_known"):
            next_action = "RESTORE_BEST"
            selected_task = {
                "target_agent": "controller",
                "objective": "Repair budget exhausted; explicitly restore best-known before final confirmation.",
                "verification_command": "python3 work/tools/c_cross_converge.py --root . --restore-best",
            }
        else:
            next_action = "STOP_WITH_FAILURES"
            selected_task = None
    elif tasks and plan.get("next_action") in {"REPAIR_ABI_LAYOUT", "REANALYZE_C_MODEL"}:
        next_action = str(plan["next_action"])
        selected_task = tasks[0]
    elif pending_isolation:
        next_action = "ISOLATE_SCENARIOS"
        selected_task = dict(pending_isolation[0])
        selected_task.setdefault("target_agent", "controller")
        selected_task.setdefault("verification_command", selected_task.get("command"))
    elif tasks:
        next_action = str(plan.get("next_action") or "REPAIR_RUST")
        selected_task = tasks[0]
    else:
        next_action = "STOP_WITH_FAILURES"
        selected_task = None

    return {
        "schema_version": 1,
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        "execution_id": matrix.get("execution_id"),
        "next_action": next_action,
        "round_budget": {
            "maximum": max_rounds,
            "used": rounds_used,
            "remaining": rounds_remaining,
        },
        "stalled_rounds": int(latest.get("stalled_rounds", 0)) if latest else 0,
        "best_known": latest.get("best_known") if latest else None,
        "task": selected_task,
        "evidence_paths": [
            "logs/trace/validation-matrix.json",
            "logs/trace/c-cross/repair-plan.json",
            "logs/trace/c-cross/attempts.jsonl",
        ],
    }


def _preserve_primary_evidence(trace: Path) -> tuple[dict[Path, bytes], set[Path]]:
    c_cross = trace / "c-cross"
    preserved: dict[Path, bytes] = {}
    for path in [trace / "validation-matrix.json"]:
        if path.is_file():
            preserved[path] = path.read_bytes()
    excluded = {"attempts.jsonl", "isolation-results.jsonl", "task-packet.json"}
    before_direct = {path for path in c_cross.iterdir() if path.is_file()} if c_cross.is_dir() else set()
    for path in before_direct:
        if path.name not in excluded:
            preserved[path] = path.read_bytes()
    return preserved, before_direct


def _restore_primary_evidence(
    trace: Path,
    preserved: dict[Path, bytes],
    before_direct: set[Path],
) -> None:
    c_cross = trace / "c-cross"
    excluded = {"attempts.jsonl", "isolation-results.jsonl", "task-packet.json"}
    for path, content in preserved.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if c_cross.is_dir():
        for path in c_cross.iterdir():
            if path.is_file() and path not in before_direct and path.name not in excluded:
                path.unlink()


def execute_next_isolation(root: Path, trace: Path, *, timeout: float = 180) -> dict[str, Any]:
    c_cross = trace / "c-cross"
    queue_path = c_cross / "isolation-queue.json"
    queue_doc = _load_json(queue_path)
    queue = queue_doc.get("queue")
    if not isinstance(queue, list):
        raise ValueError("isolation-queue.json queue must be a list")
    pending = next((item for item in queue if isinstance(item, dict) and item.get("status") == "pending"), None)
    if pending is None:
        plan_path = c_cross / "repair-plan.json"
        if plan_path.is_file():
            plan = _load_json(plan_path)
            plan["next_action"] = "CONFIRM_C_CROSS"
            plan["status"] = "isolation_complete"
            _write_json(plan_path, plan)
        return {
            "status": "completed",
            "outcome": "queue_empty",
            "next_action": "CONFIRM_C_CROSS",
        }
    command_text = pending.get("command")
    if not isinstance(command_text, str):
        raise ValueError("pending isolation entry has no command")
    command = shlex.split(command_text)
    if (
        len(command) < 3
        or command[0] not in {"python3", "python"}
        or Path(command[1]).as_posix() != "work/tools/c_cross_validate.py"
        or "--scenario" not in command
    ):
        raise ValueError("refusing non-validator isolation command")

    def option_value(name: str) -> str | None:
        try:
            index = command.index(name)
        except ValueError:
            return None
        return command[index + 1] if index + 1 < len(command) else None

    scenario_value = option_value("--scenario")
    command_root = option_value("--root")
    command_out = option_value("--out")
    command_project = option_value("--project")
    if any(
        command.count(name) != 1
        for name in ("--scenario", "--root", "--out", "--project", "--mode", "--attempt-kind")
    ):
        raise ValueError("isolation command must contain one bounded scenario/root/out/project")
    if scenario_value != pending.get("scenario_id") or command_root != ".":
        raise ValueError("isolation command scenario/root does not match its queue entry")
    if option_value("--mode") != "full" or option_value("--attempt-kind") != "checkpoint":
        raise ValueError("isolation command must be a full checkpoint")
    if command_out is None or (root / command_out).resolve() != trace.resolve():
        raise ValueError("isolation command output path escapes the active trace")
    if command_project is None:
        raise ValueError("isolation command has no project")
    project_path = (root / command_project).resolve()
    if root.resolve() not in project_path.parents:
        raise ValueError("isolation command project escapes workbench root")

    preserved, before_direct = _preserve_primary_evidence(trace)
    baseline_execution_id = None
    baseline_bytes = preserved.get(trace / "validation-matrix.json")
    if baseline_bytes is not None:
        try:
            baseline_value = json.loads(baseline_bytes.decode("utf-8"))
            if isinstance(baseline_value, dict):
                baseline_execution_id = baseline_value.get("execution_id")
        except (UnicodeDecodeError, json.JSONDecodeError):
            baseline_execution_id = None
    exit_code: int
    output: str
    isolation_matrix: dict[str, Any] | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        exit_code = completed.returncode
        output = completed.stdout or ""
        matrix_path = trace / "validation-matrix.json"
        if matrix_path.is_file():
            candidate_matrix = _load_json(matrix_path)
            candidate_scenarios = candidate_matrix.get("selected_scenarios")
            if (
                candidate_matrix.get("execution_id") != baseline_execution_id
                and isinstance(candidate_scenarios, list)
                and pending.get("scenario_id") in candidate_scenarios
            ):
                isolation_matrix = candidate_matrix
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        raw = exc.stdout or ""
        output = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        output += f"\ncontroller timeout after {timeout}s\n"
    finally:
        _restore_primary_evidence(trace, preserved, before_direct)

    scenario_id = str(pending.get("scenario_id") or "unknown")
    result_dir = c_cross / "isolation" / re.sub(r"[^A-Za-z0-9_]+", "_", scenario_id).lower()
    result_dir.mkdir(parents=True, exist_ok=True)
    log_path = result_dir / "controller.log"
    log_path.write_text(output, encoding="utf-8")
    scenario_rows = isolation_matrix.get("scenarios", []) if isinstance(isolation_matrix, dict) else []
    outcome = next(
        (
            row.get("rust_impl_c_test")
            for row in scenario_rows
            if isinstance(row, dict) and row.get("scenario_id") == scenario_id
        ),
        "unresolved",
    )
    receipt = {
        "queue_id": pending.get("queue_id"),
        "scenario_id": scenario_id,
        "status": "completed" if isolation_matrix is not None else "failed",
        "outcome": outcome,
        "exit_code": exit_code,
        "execution_id": isolation_matrix.get("execution_id") if isinstance(isolation_matrix, dict) else None,
        "matrix_snapshot": (
            f"logs/trace/c-cross/checkpoints/{isolation_matrix.get('execution_id')}.json"
            if isinstance(isolation_matrix, dict) and isolation_matrix.get("execution_id")
            else None
        ),
        "log": f"logs/trace/c-cross/isolation/{result_dir.name}/controller.log",
    }
    pending.update(receipt)
    _write_json(queue_path, queue_doc)
    plan_path = c_cross / "repair-plan.json"
    if plan_path.is_file():
        plan = _load_json(plan_path)
        plan_queue = plan.get("isolation_queue")
        if isinstance(plan_queue, list):
            for item in plan_queue:
                if isinstance(item, dict) and item.get("queue_id") == pending.get("queue_id"):
                    item.update(receipt)
        remaining = [
            item for item in plan_queue
            if isinstance(item, dict) and item.get("status") == "pending"
        ] if isinstance(plan_queue, list) else []
        if not remaining:
            plan["next_action"] = "CONFIRM_C_CROSS"
            plan["status"] = "isolation_complete"
        _write_json(plan_path, plan)
    _append_jsonl(c_cross / "isolation-results.jsonl", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit/consume bounded C-cross convergence tasks.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="logs/trace")
    parser.add_argument("--project", default="flashDB_rust")
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--execute-isolation", action="store_true")
    parser.add_argument("--restore-best", action="store_true")
    args = parser.parse_args(argv)
    if args.max_rounds < 1:
        parser.error("--max-rounds must be positive")
    if args.execute_isolation and args.restore_best:
        parser.error("choose either --execute-isolation or --restore-best")

    root = Path(args.root).resolve()
    trace = (root / args.out).resolve()
    c_cross = trace / "c-cross"
    if args.restore_best:
        receipt = restore_best_snapshot(root, trace, args.project)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    if args.execute_isolation:
        receipt = execute_next_isolation(root, trace)
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt.get("status") == "completed" else 1

    matrix = _load_json(trace / "validation-matrix.json")
    plan = _load_json(c_cross / "repair-plan.json")
    attempts = _load_jsonl(c_cross / "attempts.jsonl")
    queue_path = c_cross / "isolation-queue.json"
    isolation_queue = _load_json(queue_path) if queue_path.is_file() else {"queue": []}
    packet = build_task_packet(
        matrix,
        plan,
        attempts,
        isolation_queue,
        max_rounds=args.max_rounds,
    )
    _write_json(c_cross / "task-packet.json", packet)
    print(json.dumps(packet, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
