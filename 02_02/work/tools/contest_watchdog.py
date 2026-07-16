#!/usr/bin/env python3
"""Independent 540-minute submission freeze watchdog.

Normal repair scheduling does not consult elapsed time.  This process exists
only to preserve and freeze the best validated submission before the contest's
600-minute hard timeout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import contest_guard
import submission_snapshot


_STARTED_PROCESSES: list[subprocess.Popen[str]] = []


def _clock_ns() -> int:
    clock = getattr(time, "CLOCK_BOOTTIME", None)
    return time.clock_gettime_ns(clock) if clock is not None else time.monotonic_ns()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 1:
        return False
    for process in _STARTED_PROCESSES:
        if process.pid == pid:
            return process.poll() is None
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def start(root: Path, *, freeze_after_seconds: float) -> dict[str, Any]:
    root = root.resolve()
    control = root / contest_guard.CONTROL_DIR
    control.mkdir(parents=True, exist_ok=True)
    existing = _read(control / "run.json")
    if existing.get("status") in {"starting", "ready", "running"} and _pid_alive(existing.get("watchdog_pid")):
        return existing

    submission_snapshot.unprotect_submission(root)
    for name in (
        "ready.json",
        "freeze-requested.json",
        "submission-frozen.json",
        "stop-requested.json",
        "freeze-error.json",
    ):
        try:
            (control / name).unlink()
        except FileNotFoundError:
            pass

    run_id = f"contest-{uuid.uuid4().hex}"
    started = _clock_ns()
    run = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "starting",
        "started_clock_ns": started,
        "freeze_after_seconds": freeze_after_seconds,
        "freeze_clock_ns": started + int(freeze_after_seconds * 1_000_000_000),
        "started_wall_time_ns": time.time_ns(),
        "boot_id": _boot_id(),
        "watchdog_pid": None,
    }
    _atomic_json(control / "run.json", run)
    log = (control / "watchdog.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "_watch",
            "--root",
            str(root),
            "--run-id",
            run_id,
        ],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    _STARTED_PROCESSES.append(process)
    log.close()
    run["watchdog_pid"] = process.pid
    _atomic_json(control / "run.json", run)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        ready = _read(control / "ready.json")
        if ready.get("run_id") == run_id and ready.get("watchdog_pid") == process.pid:
            current = _read(control / "run.json")
            return current or run
        if process.poll() is not None:
            raise RuntimeError(f"contest watchdog exited before ready: {process.returncode}")
        time.sleep(0.05)
    process.terminate()
    raise RuntimeError("contest watchdog did not become ready")


def _write_deadline_report(root: Path, restore: dict[str, Any]) -> None:
    snapshot_id = str(restore.get("snapshot_id") or "no_validated_snapshot")
    score = restore.get("score_vector")
    best_score = (
        submission_snapshot._load_json(root / submission_snapshot.SNAPSHOT_ROOT / snapshot_id / "score.json")
        if restore.get("snapshot_id")
        else {}
    )
    all_expected = set(best_score.get("failed") or []) | set(best_score.get("judge_case_passed") or [])
    passed = set(best_score.get("judge_case_passed") or [])
    failed = sorted(all_expected - passed)
    status = "SUCCESS" if all_expected and not failed else "FAILED"
    output = root / "result" / "output.md"
    issues = root / "result" / "issues" / "00-summary.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    issues.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "# FlashDB C-to-Rust Final Report\n\n"
        f"STATUS: {status}\n\n"
        "## Contest Deadline Finalization\n\n"
        "- termination_reason: `contest_deadline_freeze`\n"
        f"- restored_snapshot: `{snapshot_id}`\n"
        f"- score_vector: `{score}`\n"
        f"- judge_cases_passed: `{len(passed)}/{len(all_expected)}`\n",
        encoding="utf-8",
    )
    issue_lines = "\n".join(f"- {item}: not passed in restored best snapshot" for item in failed) or "- None"
    issues.write_text(
        "# 00 - Summary\n\n"
        f"STATUS: {status}\n\n"
        "## Termination\n\n- `contest_deadline_freeze`\n\n"
        f"## Known Issues\n\n{issue_lines}\n",
        encoding="utf-8",
    )


def freeze(root: Path, *, run_id: str) -> dict[str, Any]:
    root = root.resolve()
    control = root / contest_guard.CONTROL_DIR
    requested = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "freeze_requested",
        "clock_ns": _clock_ns(),
        "wall_time_ns": time.time_ns(),
    }
    _atomic_json(control / "freeze-requested.json", requested)
    # Let an already-open atomic file replacement settle; do not wait for the
    # business task or model session to finish.
    time.sleep(0.2)
    try:
        restore = submission_snapshot.restore_best(root, reason="contest_deadline")
        first = submission_snapshot.verify_current(root, restore["snapshot_id"])
        if not first["matches"]:
            restore = submission_snapshot.restore_best(root, reason="contest_deadline")
        second = submission_snapshot.verify_current(root, restore["snapshot_id"])
        if not second["matches"]:
            raise RuntimeError("submission drifted after deadline restore")
    except ValueError as exc:
        current = submission_snapshot.current_manifest(root)
        restore = {
            "status": "current_state_frozen",
            "reason": "contest_deadline",
            "snapshot_id": None,
            "score_vector": None,
            "fallback_reason": str(exc),
        }
        second = {"matches": True, "snapshot_id": None, "source_manifest": current, "fallback": "no_validated_snapshot"}
        _atomic_json(root / "logs" / "trace" / "submission-restore.json", restore)
    _write_deadline_report(root, restore)
    protected = submission_snapshot.protect_submission(root)
    frozen = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "submission_frozen",
        "termination_reason": "contest_deadline_freeze",
        "snapshot_id": restore.get("snapshot_id"),
        "score_vector": restore.get("score_vector"),
        "protected_files": protected,
        "verification": second,
        "clock_ns": _clock_ns(),
        "wall_time_ns": time.time_ns(),
    }
    # Publish the terminal run state before the public frozen sentinel.  FINAL
    # validation treats submission-frozen.json as the commit marker, so every
    # file it depends on must already describe the same completed freeze.
    run = _read(control / "run.json")
    if run.get("run_id") != run_id:
        raise RuntimeError("contest run changed while freezing submission")
    run["status"] = "frozen"
    run["frozen_clock_ns"] = frozen["clock_ns"]
    run["frozen_wall_time_ns"] = frozen["wall_time_ns"]
    _atomic_json(control / "run.json", run)
    _atomic_json(root / "logs" / "trace" / "deadline-final.json", frozen)
    _atomic_json(control / "submission-frozen.json", frozen)
    return frozen


def watch(root: Path, *, run_id: str) -> int:
    root = root.resolve()
    control = root / contest_guard.CONTROL_DIR
    run = _read(control / "run.json")
    if run.get("run_id") != run_id:
        return 2
    run["watchdog_pid"] = os.getpid()
    run["status"] = "ready"
    _atomic_json(control / "run.json", run)
    _atomic_json(control / "ready.json", {"run_id": run_id, "watchdog_pid": os.getpid(), "status": "ready"})
    while True:
        stop = _read(control / "stop-requested.json")
        if stop.get("run_id") == run_id:
            run["status"] = "stopped"
            run["stopped_wall_time_ns"] = time.time_ns()
            _atomic_json(control / "run.json", run)
            return 0
        if _clock_ns() >= int(run["freeze_clock_ns"]):
            try:
                freeze(root, run_id=run_id)
            except Exception as exc:  # noqa: BLE001 - persist fatal watchdog evidence
                _atomic_json(control / "freeze-error.json", {"run_id": run_id, "error": str(exc), "wall_time_ns": time.time_ns()})
                run["status"] = "freeze_failed"
                _atomic_json(control / "run.json", run)
                return 1
            return 0
        time.sleep(min(1.0, max(0.05, (int(run["freeze_clock_ns"]) - _clock_ns()) / 1_000_000_000)))


def stop(root: Path) -> dict[str, Any]:
    root = root.resolve()
    control = root / contest_guard.CONTROL_DIR
    run = _read(control / "run.json")
    if not run:
        return {"status": "not_started"}
    _atomic_json(control / "stop-requested.json", {"run_id": run.get("run_id"), "status": "stop_requested"})
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and _pid_alive(run.get("watchdog_pid")):
        time.sleep(0.05)
    stopped = _read(control / "run.json")
    return {
        "status": stopped.get("status", "stop_requested"),
        "run_id": run.get("run_id"),
        "watchdog_alive": _pid_alive(run.get("watchdog_pid")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the contest submission freeze watchdog.")
    sub = parser.add_subparsers(dest="command", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--root", default=".")
    start_parser.add_argument("--freeze-after-minutes", type=float, default=540.0)
    start_parser.add_argument("--freeze-after-seconds", type=float, help=argparse.SUPPRESS)
    for name in ("status", "stop", "finalize-now"):
        item = sub.add_parser(name)
        item.add_argument("--root", default=".")
    watch_parser = sub.add_parser("_watch")
    watch_parser.add_argument("--root", required=True)
    watch_parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.command == "start":
            seconds = args.freeze_after_seconds if args.freeze_after_seconds is not None else args.freeze_after_minutes * 60.0
            result = start(root, freeze_after_seconds=seconds)
        elif args.command == "status":
            result = contest_guard.contest_state(root)
        elif args.command == "stop":
            result = stop(root)
        elif args.command == "finalize-now":
            run = _read(root / contest_guard.CONTROL_DIR / "run.json")
            run_id = str(run.get("run_id") or f"manual-{uuid.uuid4().hex}")
            result = freeze(root, run_id=run_id)
        else:
            return watch(root, run_id=args.run_id)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"CONTEST_WATCHDOG: REFUSED: {exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
