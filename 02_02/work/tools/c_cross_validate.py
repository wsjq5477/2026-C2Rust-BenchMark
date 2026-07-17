#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import repair_work_queue
import contest_guard


MAX_LOCAL_CHANGED_FILES = 3
MAX_ARCHITECTURE_CHANGED_FILES = 6
LOCAL_STALLS_BEFORE_ARCHITECTURE = 2


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def implementation_preflight(
    root: Path,
    out: Path,
    *,
    project_name: str = "flashDB_rust",
) -> tuple[dict[str, Any], dict[str, Any]]:
    tool_path = Path(__file__).resolve().with_name("core_impl_audit.py")
    spec = importlib.util.spec_from_file_location("c_cross_core_impl_audit", tool_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load core_impl_audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.audit_workspace(root, project_name)
    implementation_attempts = module.load_attempts(out / "implementation-attempts.jsonl")
    layout_path = out / "c-cross" / "scaffold-layout-check.json"
    try:
        layout = load_json(layout_path)
    except (OSError, ValueError, json.JSONDecodeError):
        layout = {}
    c_cross_attempts = _read_jsonl(out / "c-cross" / "attempts.jsonl")
    try:
        current_matrix = load_json(out / "validation-matrix.json")
    except (OSError, ValueError, json.JSONDecodeError):
        current_matrix = {}
    latest_cross_attempt = c_cross_attempts[-1] if c_cross_attempts else {}
    existing_cross_chain = bool(
        c_cross_attempts
        and latest_cross_attempt.get("attempt_id") == current_matrix.get("execution_id")
        and latest_cross_attempt.get("kind") in {"checkpoint", "repair", "confirmation", "final"}
        and isinstance(latest_cross_attempt.get("source_manifest"), dict)
    )
    if existing_cross_chain:
        audit_pass = result.get("status") == "pass"
        evidence = {
            "status": "ready_for_verify" if audit_pass else "implementation_required",
            "terminal": False,
            "next_action": "continue_c_cross_chain" if audit_pass else "return_to_implement",
            "valid": audit_pass,
            "errors": [] if audit_pass else ["current Rust sources contain scaffold residue"],
            "attempt_id": latest_cross_attempt.get("attempt_id"),
            "attempt_kind": latest_cross_attempt.get("kind"),
            "basis": "existing_c_cross_chain",
            "input_fingerprint": result.get("input_fingerprint"),
            "source_manifest": result.get("source_manifest"),
        }
    else:
        evidence = module.implementation_evidence(
            result,
            implementation_attempts,
            layout,
        )
        evidence["basis"] = "initial_implement_gate"
    result["convergence"] = evidence
    _write_json(out / "implementation-audit.json", result)
    return result, evidence


def _relative_log_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _write(path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _command_text(command: list[str], cwd: Path | None = None) -> str:
    prefix = f"(cd {cwd} && )" if cwd else ""
    return prefix + " ".join(command)


def _safe_c_suffix(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()


def _run(command: list[str], *, cwd: Path | None = None, timeout: float = 60) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        return -124, f"{stdout}{stderr}\nTIMEOUT: killed after {timeout}s\n"
    stdout = completed.stdout.decode("utf-8", errors="replace") if isinstance(completed.stdout, bytes) else (completed.stdout or "")
    stderr = completed.stderr.decode("utf-8", errors="replace") if isinstance(completed.stderr, bytes) else (completed.stderr or "")
    return completed.returncode, f"{stdout}{stderr}"


def parse_runner_test_results(output: str, expected_tests: list[str], exit_code: int) -> dict[str, Any]:
    start_pattern = re.compile(r"^\s*Running:\s*([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)
    failure_pattern = re.compile(r"^\s*FAIL\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$", re.MULTILINE)
    started = start_pattern.findall(output)
    failure_matches = failure_pattern.findall(output)

    # Build disambiguated started list: when same C function appears multiple times,
    # map the N-th occurrence to the N-th expected entry with that source_test.
    # Expected entries may include scenario_ids like test_xxx__2 that map to source_test test_xxx.
    # We use invocation_index from registered_test_invocations to disambiguate.
    source_test_by_scenario: dict[str, str] = {}
    invocation_order: dict[str, list[str]] = {}
    for entry in expected_tests:
        parts = entry.rsplit("__", 1)
        source = parts[0]
        source_test_by_scenario[entry] = source
        invocation_order.setdefault(source, []).append(entry)

    # Map each "Running: <name>" to a specific scenario_id using invocation order
    started_scenarios: list[str] = []
    invocation_counter: dict[str, int] = {}
    unexpected_repeated_starts: list[str] = []
    for name in started:
        scenarios_for_name = invocation_order.get(name, [name])
        idx = invocation_counter.get(name, 0)
        if idx < len(scenarios_for_name):
            started_scenarios.append(scenarios_for_name[idx])
        else:
            started_scenarios.append(name)
            unexpected_repeated_starts.append(name)
        invocation_counter[name] = idx + 1

    # Map FAIL lines similarly
    failures: dict[str, str] = {}
    fail_counter: dict[str, int] = {}
    for test_name, detail in failure_matches:
        normalized = " ".join(detail.split())
        scenarios_for_name = invocation_order.get(test_name, [test_name])
        idx = fail_counter.get(test_name, 0)
        scenario = scenarios_for_name[idx] if idx < len(scenarios_for_name) else test_name
        fail_counter[test_name] = idx + 1
        if scenario in failures:
            failures[scenario] = f"{failures[scenario]} | {normalized}"
        else:
            failures[scenario] = normalized

    expected_set = set(expected_tests)
    started_set = set(started_scenarios)
    unknown_started = sorted(set(started) - set(source_test_by_scenario.values()))
    unknown_failed = sorted(set(failures) - expected_set)
    failed_without_start = sorted(set(failures) - started_set)
    reasons: list[str] = []
    if unknown_started:
        reasons.append("unknown started tests: " + ", ".join(unknown_started))
    if unexpected_repeated_starts:
        reasons.append("unexpected repeated start: " + ", ".join(sorted(unexpected_repeated_starts)))
    if unknown_failed:
        reasons.append("unknown failed tests: " + ", ".join(unknown_failed))
    # A timeout can lose buffered C stdout while still preserving stderr FAIL
    # lines.  Such a FAIL is still attributable and must not turn every other
    # scenario in the suite into a synthetic parse failure.
    warnings: list[str] = []
    if failed_without_start:
        message = "failed tests missing start records: " + ", ".join(failed_without_start)
        if exit_code == 0:
            reasons.append(message)
        else:
            warnings.append(message)
    if exit_code == 0 and failures:
        reasons.append("successful runner reported test failures")
    if exit_code == 0 and started_set != expected_set:
        reasons.append("successful runner did not start all expected tests")
    if exit_code not in {0, -124} and not failures:
        reasons.append("nonzero runner exit has no attributed test failure")
    if exit_code == -124 and not failures and not started_set:
        reasons.append("timed out runner has no started or failed test evidence")

    runtime_failed: list[str] = []
    if exit_code not in {0, -124} and not failures and started_scenarios:
        crashed = started_scenarios[-1]
        failures[crashed] = f"runner exited with {exit_code} while {crashed} was active"
        runtime_failed.append(crashed)
    failed = [name for name in expected_tests if name in failures]
    timed_out: list[str] = []
    if exit_code == -124 and started_scenarios:
        last_started = started_scenarios[-1]
        if last_started not in failures:
            timed_out.append(last_started)
    passed = [name for name in expected_tests if name in started_set and name not in failures and name not in timed_out]
    not_run = [
        name for name in expected_tests
        if name not in started_set and name not in failures and name not in timed_out
    ]
    status = "parse_failed" if reasons else ("partial" if exit_code == -124 or warnings else "parsed")
    return {
        "status": status,
        "started": [name for name in expected_tests if name in started_set],
        "passed": passed,
        "failed": failed,
        "runtime_failed": runtime_failed,
        "timed_out": timed_out,
        "not_run": not_run,
        "failures": failures,
        "warnings": warnings,
        "exit_code": exit_code,
        "reason": "; ".join(reasons) if reasons else "runner output mapped to expected tests",
    }


def _normalized_failure_reason(reason: Any) -> str:
    text = " ".join(str(reason or "unknown failure").split())
    text = re.sub(r"0x[0-9A-Fa-f]+", "<addr>", text)
    return text


def failure_fingerprint(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("failure_layer") or row.get("phase") or "unknown"),
            str(row.get("suite") or "unknown"),
            str(row.get("scenario_id") or row.get("source_test") or "unknown"),
            _normalized_failure_reason(row.get("reason")),
        ]
    )


def _matrix_outcomes(matrix: dict[str, Any] | None) -> dict[str, Any]:
    scenarios = matrix.get("scenarios") if isinstance(matrix, dict) else []
    rows = [row for row in scenarios if isinstance(row, dict)] if isinstance(scenarios, list) else []
    passed: set[str] = set()
    failed: set[str] = set()
    not_run: set[str] = set()
    failures: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_test = str(row.get("scenario_id") or row.get("source_test") or "unknown")
        status = row.get("rust_impl_c_test")
        if status == "pass":
            passed.add(source_test)
        elif status == "not_run":
            not_run.add(source_test)
            failures[source_test] = row
        else:
            failed.add(source_test)
            failures[source_test] = row
    return {
        "passed": passed,
        "failed": failed,
        "not_run": not_run,
        "failures": failures,
        "fingerprints": {failure_fingerprint(row) for row in failures.values()},
    }


def _matrix_scope_ids(matrix: dict[str, Any] | None) -> list[str]:
    scenarios = matrix.get("scenarios") if isinstance(matrix, dict) else []
    return sorted({
        str(row.get("scenario_id") or row.get("source_test"))
        for row in scenarios if isinstance(row, dict) and (row.get("scenario_id") or row.get("source_test"))
    }) if isinstance(scenarios, list) else []


def _matrix_scope_kind(matrix: dict[str, Any] | None) -> str:
    if not isinstance(matrix, dict):
        return "unknown"
    if matrix.get("mode") == "full" and matrix.get("scope", "all") == "all":
        return "full"
    if matrix.get("scope") == "selected":
        suites = matrix.get("selected_suites")
        scenarios = matrix.get("selected_scenarios")
        if isinstance(scenarios, list) and scenarios:
            return "targeted"
        if isinstance(suites, list) and suites:
            return "suite"
    return "partial"


def matrix_scope_fingerprint(matrix: dict[str, Any] | None) -> str:
    payload = {
        "scope_kind": _matrix_scope_kind(matrix),
        "mode": matrix.get("mode") if isinstance(matrix, dict) else None,
        "scenario_ids": _matrix_scope_ids(matrix),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def annotate_matrix_scope(matrix: dict[str, Any]) -> dict[str, Any]:
    matrix["scope_kind"] = _matrix_scope_kind(matrix)
    matrix["scope_ids"] = _matrix_scope_ids(matrix)
    matrix["scope_fingerprint"] = matrix_scope_fingerprint(matrix)
    return matrix


def compare_attempt(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    before = _matrix_outcomes(previous)
    after = _matrix_outcomes(current)
    previous_scope = before["passed"] | before["failed"] | before["not_run"]
    current_scope = after["passed"] | after["failed"] | after["not_run"]
    regression = bool((before["passed"] & current_scope) - after["passed"])
    progress_reasons: list[str] = []
    if after["passed"] - before["passed"]:
        progress_reasons.append("passed set increased")

    layer_order = {
        "model": 0,
        "protocol": 0,
        "scaffold": 1,
        "build": 2,
        "layout": 3,
        "link": 4,
        "runtime": 5,
        "full": 5,
        "assertion": 5,
        "timeout": 5,
    }
    for source_test in sorted(set(before["failures"]) & set(after["failures"])):
        before_row = before["failures"][source_test]
        after_row = after["failures"][source_test]
        before_layer = str(before_row.get("failure_layer") or before_row.get("phase") or "unknown")
        after_layer = str(after_row.get("failure_layer") or after_row.get("phase") or "unknown")
        if layer_order.get(after_layer, -1) > layer_order.get(before_layer, -1):
            progress_reasons.append(f"{source_test} advanced from {before_layer} to {after_layer}")
        elif failure_fingerprint(before_row) != failure_fingerprint(after_row):
            progress_reasons.append(f"{source_test} advanced to a different assertion or error")

    progress = bool(progress_reasons) and not regression
    return {
        "progress": progress,
        "regression": regression,
        "progress_reasons": progress_reasons,
        "before": {
            "passed": sorted(before["passed"]),
            "failed": sorted(before["failed"]),
            "not_run": sorted(before["not_run"]),
        },
        "after": {
            "passed": sorted(after["passed"]),
            "failed": sorted(after["failed"]),
            "not_run": sorted(after["not_run"]),
        },
        "fingerprints_before": sorted(before["fingerprints"]),
        "fingerprints_after": sorted(after["fingerprints"]),
        "comparable_fingerprints": sorted(
            failure_fingerprint(row)
            for source_test, row in after["failures"].items()
            if source_test in previous_scope
        ),
        "scope_relation": (
            "same"
            if matrix_scope_fingerprint(previous) == matrix_scope_fingerprint(current)
            else "overlap"
            if previous_scope & current_scope
            else "disjoint"
        ),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest(project_root: Path) -> dict[str, str]:
    project_root = project_root.resolve()
    source_root = project_root / "src"
    if source_root.is_dir():
        symlinks = sorted(path for path in source_root.rglob("*") if path.is_symlink())
        if symlinks:
            raise ValueError(
                "flashDB_rust/src/** must not contain symlinks: "
                + ", ".join(path.relative_to(project_root).as_posix() for path in symlinks)
            )
    return {
        f"flashDB_rust/{path.relative_to(project_root).as_posix()}": _sha256(path)
        for path in _project_snapshot_files(project_root)
    }


def _implementation_source_manifest(project_root: Path) -> dict[str, str]:
    project_root = project_root.resolve()
    files: set[Path] = set()
    src = project_root / "src"
    if src.is_dir():
        files.update(
            path
            for path in src.rglob("*.rs")
            if path.is_file() and not path.is_symlink()
        )
    cargo = project_root / "Cargo.toml"
    if cargo.is_file() and not cargo.is_symlink():
        files.add(cargo)
    return {
        path.relative_to(project_root).as_posix(): _sha256(path)
        for path in sorted(files)
    }


def _manifest_changed_files(before: dict[str, Any], after: dict[str, str]) -> list[str]:
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def _repair_rows(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in attempts if row.get("kind") == "repair"]


def validate_repair_request(
    attempts: list[dict[str, Any]],
    *,
    repair_kind: str,
    cluster_scenarios: list[str],
    declared_changed_files: list[str],
    current_source_manifest: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    if not cluster_scenarios:
        errors.append("repair attempts require at least one dynamically selected --scenario")
    file_limit = MAX_LOCAL_CHANGED_FILES if repair_kind == "local" else MAX_ARCHITECTURE_CHANGED_FILES
    if len(set(declared_changed_files)) > file_limit:
        errors.append(f"{repair_kind} repair may change at most {file_limit} Rust source files")
    if attempts and attempts[-1].get("regression") is True:
        errors.append("latest repair regressed previously passing scenarios; restore best-known and confirm before another repair")
    previous_manifest = attempts[-1].get("source_manifest") if attempts else None
    if not isinstance(previous_manifest, dict):
        errors.append("repair requires a prior checkpoint with a complete Rust source manifest")
    else:
        actual_changed = _manifest_changed_files(previous_manifest, current_source_manifest)
        if set(actual_changed) != set(declared_changed_files):
            errors.append(
                "declared --changed-file values must exactly match the Rust source diff: "
                + ", ".join(actual_changed or ["<none>"])
            )
    same_cluster = [
        row for row in _repair_rows(attempts)
        if row.get("cluster_scenarios") == cluster_scenarios
    ]
    stalled_local = same_cluster[-LOCAL_STALLS_BEFORE_ARCHITECTURE:]
    local_escalation_ready = (
        len(stalled_local) == LOCAL_STALLS_BEFORE_ARCHITECTURE
        and all(row.get("repair_kind") == "local" and row.get("progress") is False for row in stalled_local)
    )
    if repair_kind == "architecture" and not local_escalation_ready:
        errors.append("architecture repair requires two no-progress local repairs for the same cluster")
    if repair_kind == "local" and local_escalation_ready:
        errors.append("local strategy is stalled; run a fresh read-only architecture review before an architecture repair")
    return errors


def validate_final_request(
    previous_matrix: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    current_source_manifest: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(previous_matrix, dict):
        return ["final requires a current full result in ready_for_final state"]
    annotate_matrix_scope(previous_matrix)
    convergence = previous_matrix.get("convergence")
    if previous_matrix.get("scope_kind") != "full":
        errors.append("final requires a preceding full-scope validation")
    rows = previous_matrix.get("scenarios")
    scenarios = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if not scenarios or any(row.get("rust_impl_c_test") != "pass" for row in scenarios):
        errors.append("final is only valid after every full-scope scenario passed")
    if not isinstance(convergence, dict) or convergence.get("status") != "ready_for_final":
        errors.append("final requires current ready_for_final convergence evidence")
    if not attempts or attempts[-1].get("attempt_id") != previous_matrix.get("execution_id"):
        errors.append("final requires the latest attempt to match the ready_for_final matrix")
    elif attempts[-1].get("source_manifest") != current_source_manifest:
        errors.append("Rust src/** changed after ready_for_final; record and confirm the change before final")
    if attempts and attempts[-1].get("regression") is True:
        errors.append("final is blocked until the restored best source receives full confirmation")
    return errors


def _attempt_score(matrix: dict[str, Any]) -> list[int]:
    outcomes = _matrix_outcomes(matrix)
    layer_rank = {
        "model": 0,
        "protocol": 0,
        "build": 1,
        "layout": 2,
        "link": 3,
        "runtime": 4,
        "full": 4,
        "assertion": 5,
        "timeout": 4,
    }
    depth = sum(
        layer_rank.get(str(row.get("failure_layer") or row.get("phase") or "unknown"), 0)
        for row in outcomes["failures"].values()
    )
    # Lexicographic order: pass count dominates, then fewer not-run/fail rows,
    # then how far remaining failures advanced through the validation stack.
    return [len(outcomes["passed"]), -len(outcomes["not_run"]), -len(outcomes["failed"]), depth]


def _project_snapshot_files(project_root: Path) -> list[Path]:
    result: set[Path] = set()
    directory = project_root / "src"
    if directory.is_dir():
        result.update(path for path in directory.rglob("*") if path.is_file() and not path.is_symlink())
    return sorted(result)


def _snapshot_project(
    c_cross: Path,
    project_root: Path,
    *,
    attempt_id: str,
    score: list[int],
    scope_fingerprint: str,
    scenario_ids: list[str],
) -> dict[str, Any] | None:
    project_root = project_root.resolve()
    files = _project_snapshot_files(project_root)
    if not files:
        return None
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", attempt_id)
    snapshot_root = c_cross / "snapshots" / safe_id
    file_root = snapshot_root / "files"
    manifest_files: list[dict[str, str]] = []
    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    for source in files:
        relative = source.relative_to(project_root)
        destination = file_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest_files.append({"path": relative.as_posix(), "sha256": _sha256(destination)})
    manifest = {
        "schema_version": 1,
        "attempt_id": attempt_id,
        "score": score,
        "scope_kind": "full",
        "scope_fingerprint": scope_fingerprint,
        "scenario_ids": scenario_ids,
        "project_name": project_root.name,
        "source_scope": "src/**",
        "files": manifest_files,
    }
    _write_json(snapshot_root / "manifest.json", manifest)
    best = {
        "attempt_id": attempt_id,
        "score": score,
        "scope_kind": "full",
        "scope_fingerprint": scope_fingerprint,
        "scenario_ids": scenario_ids,
        "snapshot": f"logs/trace/c-cross/snapshots/{safe_id}",
        "manifest": f"logs/trace/c-cross/snapshots/{safe_id}/manifest.json",
        "file_count": len(manifest_files),
        "source_scope": "src/**",
    }
    _write_json(c_cross / "snapshots" / "best.json", best)
    return best


def _load_best_known(c_cross: Path) -> dict[str, Any] | None:
    path = c_cross / "snapshots" / "best.json"
    if not path.is_file():
        return None
    try:
        value = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value


def _load_best_matrix(c_cross: Path, best: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(best, dict) or not isinstance(best.get("attempt_id"), str):
        return None
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", best["attempt_id"])
    path = c_cross / "checkpoints" / f"{safe_id}.json"
    if not path.is_file():
        return None
    try:
        return load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def restore_best_known(c_cross: Path, project_root: Path) -> dict[str, Any]:
    best = _load_best_known(c_cross)
    if not isinstance(best, dict) or not isinstance(best.get("attempt_id"), str):
        raise ValueError("no best-known Rust source snapshot is available")
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", best["attempt_id"])
    snapshot_root = c_cross / "snapshots" / safe_id
    manifest = load_json(snapshot_root / "manifest.json")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("best-known snapshot manifest has no source files")

    expected: dict[Path, str] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not isinstance(row.get("sha256"), str):
            raise ValueError("best-known snapshot manifest contains an invalid file entry")
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "src":
            raise ValueError(f"best-known snapshot path is outside src/**: {relative}")
        source = snapshot_root / "files" / relative
        if not source.is_file() or _sha256(source) != row["sha256"]:
            raise ValueError(f"best-known snapshot file is missing or corrupt: {relative}")
        expected[relative] = row["sha256"]

    project_root = project_root.resolve()
    current_files = _project_snapshot_files(project_root)
    restored_files: list[str] = []
    removed_files: list[str] = []
    for current in current_files:
        relative = current.relative_to(project_root)
        if relative not in expected:
            current.unlink()
            removed_files.append(f"flashDB_rust/{relative.as_posix()}")
    for relative in sorted(expected):
        source = snapshot_root / "files" / relative
        destination = project_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        restored_files.append(f"flashDB_rust/{relative.as_posix()}")

    evidence = {
        "status": "restored",
        "best_attempt_id": best["attempt_id"],
        "restored_files": restored_files,
        "removed_files": removed_files,
        "next_action": "run_full_confirmation",
        "source_manifest": _source_manifest(project_root),
    }
    _write_json(c_cross / "restore-best.json", evidence)
    return evidence


def auto_restore_regressed_full_attempt(
    c_cross: Path,
    project_root: Path,
    queue_path: Path,
    attempt: dict[str, Any],
    matrix: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if attempt.get("regression") is not True or matrix.get("scope_kind") != "full":
        return None
    queue = repair_work_queue.load_queue(queue_path)
    phases = queue.get("phases") if isinstance(queue.get("phases"), dict) else {}
    queue_phase = phases.get("c_cross") if isinstance(phases.get("c_cross"), dict) else {
        "phase": "c_cross", "sweep": 1, "tasks": {}, "dynamic_task_ids": []
    }
    restore_error = None
    restored: dict[str, Any] | None = None
    try:
        restored = restore_best_known(c_cross, project_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        restore_error = str(exc)
    status = "restore_confirmation_required" if restored is not None else "best_restore_failed"
    convergence = {
        "status": status,
        "terminal": False,
        "next_action": "run_full_confirmation" if restored is not None else "repair_best_restore",
        "repair_attempts_recorded": len(_repair_rows(attempts)),
        "work_queue": repair_work_queue.phase_summary(queue_phase),
    }
    restore_result = {
        "status": restored.get("status") if restored is not None else "failed",
        "reason": "full_scope_score_regression",
        "best_attempt_id": restored.get("best_attempt_id") if restored is not None else None,
        "source_manifest": restored.get("source_manifest") if restored is not None else None,
        "error": restore_error,
    }
    return convergence, restore_result


def record_attempt(
    c_cross: Path,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    attempt_kind: str,
    trigger: str,
    changed_files: list[str],
    project_root: Path | None = None,
    repair_kind: str | None = None,
    cluster_scenarios: list[str] | None = None,
    source_manifest: dict[str, str] | None = None,
    actual_changed_files: list[str] | None = None,
) -> dict[str, Any]:
    changed_file_hashes: dict[str, str | None] = {}
    if attempt_kind == "repair":
        if not changed_files:
            raise ValueError("repair attempts require at least one --changed-file under flashDB_rust/src/")
        invalid_changes = [
            path
            for path in changed_files
            if (
                Path(path).is_absolute()
                or ".." in Path(path).parts
                or len(Path(path).parts) < 3
                or Path(path).parts[0] != "flashDB_rust"
                or Path(path).parts[1] != "src"
            )
        ]
        if invalid_changes:
            raise ValueError(
                "repair changed_files must stay under flashDB_rust/src/: " + ", ".join(sorted(invalid_changes))
            )
        for path in changed_files:
            if project_root is None:
                # Direct unit callers may not have a workbench root.  The CLI
                # always supplies project_root and therefore records a real
                # content hash for every repair edit.
                changed_file_hashes[path] = None
                continue
            relative = Path(*Path(path).parts[1:])
            unresolved_candidate = project_root.resolve() / relative
            candidate = unresolved_candidate.resolve()
            source_root = (project_root.resolve() / "src").resolve()
            if source_root not in candidate.parents or not candidate.is_file() or unresolved_candidate.is_symlink():
                raise ValueError(f"repair changed_file is missing, unsafe, or not a regular src file: {path}")
            changed_file_hashes[path] = _sha256(candidate)

    attempts_path = c_cross / "attempts.jsonl"
    prior_attempts = _read_jsonl(attempts_path)
    attempt_id = str(current.get("execution_id") or f"attempt-{time.time_ns()}")
    annotate_matrix_scope(current)
    comparison = compare_attempt(previous, current)
    prior_stalled = int(prior_attempts[-1].get("stalled_rounds", 0)) if prior_attempts else 0
    stalled_rounds = 0 if previous is None or comparison["progress"] else prior_stalled + 1
    outcomes = Counter(
        str(row.get("rust_impl_c_test") or "unresolved")
        for row in current.get("scenarios", [])
        if isinstance(row, dict)
    )
    diagnostics_history = c_cross / "diagnostics-history" / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', attempt_id)}.jsonl"
    diagnostics_path = c_cross / "diagnostics.jsonl"
    if diagnostics_path.exists():
        diagnostics_history.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(diagnostics_path, diagnostics_history)

    best_known = _load_best_known(c_cross)
    score = _attempt_score(current)
    full_scope = current.get("scope_kind") == "full"
    best_matrix = _load_best_matrix(c_cross, best_known) if full_scope else None
    best_score = best_known.get("score") if isinstance(best_known, dict) else None
    if best_matrix is not None:
        annotate_matrix_scope(best_matrix)
        best_comparison = compare_attempt(best_matrix, current)
        same_full_scope = best_matrix.get("scope_fingerprint") == current.get("scope_fingerprint")
        if (
            same_full_scope
            and best_comparison["regression"]
            and isinstance(best_score, list)
            and score <= best_score
        ):
            comparison["regression"] = True
            comparison["progress"] = False
            comparison["progress_reasons"] = []
            comparison["fingerprints_before"] = best_comparison["fingerprints_before"]
            comparison["comparable_fingerprints"] = best_comparison["comparable_fingerprints"]
        elif same_full_scope and isinstance(best_score, list) and score > best_score:
            # A higher full-scope score is useful overall even if the exact pass
            # set changed. Preserve the changed-set evidence without treating
            # the improved candidate as an automatic rollback.
            comparison["regression"] = False
            if best_comparison["regression"]:
                comparison["progress_reasons"].append("full score improved with a changed pass set")
    best_scope_compatible = isinstance(best_known, dict) and best_known.get("source_scope") == "src/**"
    snapshot_error = None
    if (
        project_root is not None
        and full_scope
        and not comparison["regression"]
        and (not best_scope_compatible or not isinstance(best_score, list) or score > best_score)
    ):
        try:
            best_known = _snapshot_project(
                c_cross,
                project_root,
                attempt_id=attempt_id,
                score=score,
                scope_fingerprint=str(current["scope_fingerprint"]),
                scenario_ids=list(current["scope_ids"]),
            ) or best_known
        except (OSError, ValueError) as exc:
            snapshot_error = str(exc)

    record = {
        "attempt_id": attempt_id,
        "attempt": len(prior_attempts) + 1,
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        "kind": attempt_kind,
        "trigger": trigger,
        "suite": sorted({
            str(row.get("suite"))
            for row in current.get("scenarios", [])
            if isinstance(row, dict) and row.get("suite")
        }),
        "changed_files": list(changed_files),
        "changed_file_hashes": changed_file_hashes,
        "actual_changed_files": list(actual_changed_files or []),
        "repair_kind": repair_kind if attempt_kind == "repair" else None,
        "cluster_scenarios": list(cluster_scenarios or []),
        "source_manifest": dict(source_manifest or {}),
        "repair_attempts_recorded": len(_repair_rows(prior_attempts)) + (1 if attempt_kind == "repair" else 0),
        "result": "pass" if outcomes and set(outcomes) == {"pass"} else "continue_with_failures",
        "summary": dict(sorted(outcomes.items())),
        "matrix_snapshot": f"logs/trace/c-cross/checkpoints/{attempt_id}.json",
        "diagnostics_snapshot": (
            f"logs/trace/c-cross/diagnostics-history/{diagnostics_history.name}"
            if diagnostics_path.exists()
            else None
        ),
        "progress": comparison["progress"],
        "regression": comparison["regression"],
        "progress_reasons": comparison["progress_reasons"],
        "fingerprints": {
            "before": comparison["fingerprints_before"],
            "after": comparison["fingerprints_after"],
            "comparable": comparison["comparable_fingerprints"],
        },
        "stalled_rounds": stalled_rounds,
        "score": score,
        "scope_kind": current.get("scope_kind"),
        "scope_ids": current.get("scope_ids"),
        "scope_fingerprint": current.get("scope_fingerprint"),
        "best_known": best_known,
        "snapshot_error": snapshot_error,
        "restore_best_available": bool(comparison["regression"] and best_known),
    }
    _append_jsonl(attempts_path, record)

    return record


def _suite_for_case(case: dict[str, Any]) -> str:
    suite = case.get("suite")
    if isinstance(suite, str) and suite:
        return suite
    return "unknown"


def _find_c_project_root(root: Path, trace: Path) -> Path | None:
    state_path = trace / "workflow_state.json"
    if state_path.exists():
        state = load_json(state_path)
        input_path = state.get("input_path")
        if isinstance(input_path, str) and Path(input_path).exists():
            return Path(input_path).resolve()
    candidates = [
        root / "judge-assets" / "code" / "FlashDB",
        root.parent / "judge-assets" / "code" / "FlashDB",
        root.parent.parent / "judge-assets" / "code" / "FlashDB",
    ]
    for candidate in candidates:
        if (candidate / "tests").is_dir() and any((candidate / "inc").glob("*.h")):
            return candidate.resolve()
    return None


def _rust_staticlib(project: Path) -> Path:
    if os.name == "nt":
        return project / "target" / "release" / "flashdb_rust.lib"
    return project / "target" / "release" / "libflashdb_rust.a"


def _c_include_args(c_root: Path, c_cross: Path) -> list[str]:
    generated_include = c_cross / "include"
    generated_include.mkdir(parents=True, exist_ok=True)
    inc = c_root / "inc"
    if inc.is_dir():
        for template in sorted(inc.glob("*_template.h")):
            target_name = template.name.replace("_template.h", ".h")
            if not (inc / target_name).exists():
                content = template.read_text(encoding="utf-8", errors="ignore")
                content = "#include <stdbool.h>\n#include <time.h>\n" + content
                (generated_include / target_name).write_text(
                    content,
                    encoding="utf-8",
                )
    args = ["-I", str(generated_include), "-I", str(c_root / "tests"), "-I", str(c_root / "inc")]
    return args


def _build_rust_staticlib(project: Path) -> tuple[bool, str]:
    command = ["cargo", "build", "--release"]
    code, output = _run(command, cwd=project)
    text = f"$ {_command_text(command, project)}\n{output}\n"
    lib = _rust_staticlib(project)
    if code != 0:
        text += f"cargo exited with {code}\n"
        return False, text
    if not lib.exists():
        text += f"missing Rust staticlib: {lib}\n"
        return False, text
    text += f"staticlib={lib}\n"
    return True, text


def _discover_suite_runner(suite: str, c_root: Path) -> Path | None:
    tests_dir = c_root / "tests"
    if not tests_dir.is_dir():
        return None
    candidates = []
    for source in sorted(tests_dir.glob("*.c")):
        text = source.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"\bmain\s*\(", text):
            continue
        score = 0
        lower_name = source.name.lower()
        if suite.lower() in lower_name:
            score += 10
        if re.search(r"\bTEST_RUN\s*\(", text):
            score += 3
        candidates.append((score, source))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item[0], item[1].as_posix()))[0][1]


def _included_c_sources(source: Path, tests_dir: Path, seen: set[Path] | None = None) -> set[Path]:
    seen = seen or set()
    source = source.resolve()
    if source in seen or not source.is_file():
        return seen
    seen.add(source)
    text = source.read_text(encoding="utf-8", errors="ignore")
    for included in re.findall(r'^\s*#\s*include\s+"([^"/]+\.c)"', text, flags=re.MULTILINE):
        local = source.parent / included
        _included_c_sources(local if local.is_file() else tests_dir / included, tests_dir, seen)
    return seen


def _test_side_sources(
    c_root: Path,
    runner: Path,
    cases: list[dict[str, Any]],
    *,
    ignored_sources: set[Path] | None = None,
    extra_sources: set[Path] | None = None,
) -> list[Path]:
    tests_dir = c_root / "tests"
    included = _included_c_sources(runner, tests_dir)
    sources = set(included)
    sources.update(path.resolve() for path in (extra_sources or set()) if path.is_file())
    ignored = {path.resolve() for path in (ignored_sources or set())}
    for case in cases:
        source_file = case.get("source_file")
        if not isinstance(source_file, str):
            continue
        source = c_root / source_file
        if source.is_file() and source.resolve() not in included and source.resolve() not in ignored:
            sources.add(source.resolve())
    return sorted(sources)


def _create_filtered_runner(
    source: Path,
    c_root: Path,
    c_cross: Path,
    case: dict[str, Any],
    suite_case_count: int,
) -> tuple[Path | None, Path | None, Path | None, str]:
    """Create a generated runner that executes one TEST_RUN/RUN_TEST call.

    The platform C source remains read-only.  When the runner contains no
    recognizable test macro, a suite with exactly one modeled case is already
    isolated; otherwise we return an actionable unsupported reason.
    """

    scenario_id = str(case.get("scenario_id") or "unknown")
    test_function = str(case.get("test_function") or case.get("source_test") or scenario_id)
    invocation_index = case.get("invocation_index")
    target_index = invocation_index if isinstance(invocation_index, int) and invocation_index > 0 else 1
    case_source_value = case.get("source_file")
    case_source = (c_root / case_source_value).resolve() if isinstance(case_source_value, str) else None
    pattern = re.compile(r"\b(?:TEST_RUN|RUN_TEST)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")

    def invocation_matches(value: str) -> list[re.Match[str]]:
        result: list[re.Match[str]] = []
        for match in pattern.finditer(value):
            line_prefix = value[value.rfind("\n", 0, match.start()) + 1:match.start()]
            if re.match(r"\s*#\s*define\b", line_prefix):
                continue
            result.append(match)
        return result

    candidates = [source]
    if case_source is not None and case_source.is_file() and case_source != source.resolve():
        candidates.append(case_source)
    target_source = next(
        (
            candidate
            for candidate in candidates
            if invocation_matches(candidate.read_text(encoding="utf-8", errors="ignore"))
        ),
        None,
    )
    if target_source is None:
        if suite_case_count == 1:
            return source, None, None, "runner already contains only one modeled scenario"
        return None, None, None, (
            f"cannot isolate {scenario_id}: runner/test source has no supported TEST_RUN/RUN_TEST invocations"
        )

    text = target_source.read_text(encoding="utf-8", errors="ignore")
    matches = invocation_matches(text)
    if not matches:
        return None, None, None, f"cannot isolate {scenario_id}: no test registration calls found"

    seen: dict[str, int] = {}
    kept = False
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        function = match.group(1)
        seen[function] = seen.get(function, 0) + 1
        keep = function == test_function and seen[function] == target_index
        pieces.append(text[cursor:match.start()])
        pieces.append(match.group(0) if keep else "((void)0)")
        cursor = match.end()
        kept = kept or keep
    pieces.append(text[cursor:])
    if not kept:
        return None, None, None, (
            f"cannot isolate {scenario_id}: {test_function} invocation {target_index} not found in {target_source}"
        )

    isolation_dir = c_cross / "isolation" / _safe_c_suffix(scenario_id)
    isolation_dir.mkdir(parents=True, exist_ok=True)
    generated_target = isolation_dir / target_source.name
    _write(generated_target, "".join(pieces))
    if target_source.resolve() == source.resolve():
        generated_runner = generated_target
        replaced_source = None
        extra_source = None
    else:
        generated_runner = isolation_dir / source.name
        _write(generated_runner, source.read_text(encoding="utf-8", errors="ignore"))
        replaced_source = target_source.resolve()
        extra_source = generated_target
    _write_json(
        isolation_dir / "filter.json",
        {
            "scenario_id": scenario_id,
            "source_runner": source.as_posix(),
            "source_runner_sha256": _sha256(source),
            "source_registration_file": target_source.as_posix(),
            "source_registration_sha256": _sha256(target_source),
            "generated_runner": generated_runner.as_posix(),
            "generated_runner_sha256": _sha256(generated_runner),
            "generated_registration_file": generated_target.as_posix(),
            "generated_registration_sha256": _sha256(generated_target),
            "test_function": test_function,
            "invocation_index": target_index,
            "matched_invocations": len(matches),
        },
    )
    return generated_runner, replaced_source, extra_source, f"generated filtered runner for {scenario_id}"


def _write_ffi_manifest(
    suite: str,
    c_root: Path,
    c_cross: Path,
    trace: Path,
    objects: list[Path],
    root: Path,
) -> str:
    manifest_path = trace / "ffi_manifest.json"
    public_api: set[str] = set()
    api_path = trace / "c_api_model.json"
    if api_path.exists():
        api = load_json(api_path)
        public_api = {item for item in api.get("public_functions", []) if isinstance(item, str)}
    linker = shutil.which("ld")
    symbol_tool = shutil.which("nm") or shutil.which("llvm-nm")
    if not objects or linker is None or symbol_tool is None:
        _write_json(manifest_path, {
            "required_ffi_apis": [],
            "suite_requirements": {},
            "reason": "partial-link tools or test objects unavailable",
        })
        return "ffi manifest skipped: partial-link tools or test objects unavailable\n"
    combined = c_cross / f"test-side-{_safe_c_suffix(suite)}.o"
    code, output = _run([linker, "-r", *[str(path) for path in objects], "-o", str(combined)])
    log = f"$ {_command_text([linker, '-r', *[str(path) for path in objects], '-o', str(combined)])}\n{output}\n"
    if code != 0:
        _write_json(manifest_path, {
            "required_ffi_apis": [],
            "suite_requirements": {},
            "reason": "test-side partial link failed",
        })
        return log
    code, output = _run([symbol_tool, "-u", str(combined)])
    log += f"$ {_command_text([symbol_tool, '-u', str(combined)])}\n{output}\n"
    symbols = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)$", output, flags=re.MULTILINE))
    required = sorted(symbols & public_api)
    existing = load_json(manifest_path) if manifest_path.exists() else {}
    suite_requirements = existing.get("suite_requirements") if isinstance(existing, dict) else None
    suite_requirements = dict(suite_requirements) if isinstance(suite_requirements, dict) else {}
    suite_requirements[suite] = {
        "required_ffi_apis": required,
        "object": _relative_log_path(combined, root),
    }
    aggregate = sorted({
        symbol
        for item in suite_requirements.values()
        if isinstance(item, dict)
        for symbol in item.get("required_ffi_apis", [])
        if isinstance(symbol, str)
    })
    _write_json(manifest_path, {
        "required_ffi_apis": aggregate,
        "suite_requirements": suite_requirements,
        "source": "test_side_undefined_symbols",
    })
    return log


def _compile_suite_runner(
    suite: str,
    c_root: Path,
    c_cross: Path,
    rust_lib: Path,
    cases: list[dict[str, Any]] | None = None,
    isolation_case: dict[str, Any] | None = None,
    suite_case_count: int | None = None,
) -> tuple[bool, Path | None, str]:
    source = None
    if cases:
        runner_names = {str(case.get("runner")) for case in cases if isinstance(case.get("runner"), str)}
        if len(runner_names) == 1:
            candidate = c_root / next(iter(runner_names))
            if candidate.is_file():
                source = candidate
    source = source or _discover_suite_runner(suite, c_root)
    if source is None:
        return False, None, f"missing discovered C test runner for suite: {suite}\n"
    original_source = source.resolve()
    isolation_note = ""
    replaced_source: Path | None = None
    extra_source: Path | None = None
    if isolation_case is not None:
        source, replaced_source, extra_source, isolation_note = _create_filtered_runner(
            original_source,
            c_root,
            c_cross,
            isolation_case,
            suite_case_count if isinstance(suite_case_count, int) else len(cases or []),
        )
        if source is None:
            return False, None, isolation_note + "\n"
        binary = source.parent / "runner"
    else:
        binary = c_cross / f"{suite}_runner"
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        return False, None, "missing C compiler: cc/gcc/clang not found\n"
    sources = _test_side_sources(
        c_root,
        source,
        cases or [],
        ignored_sources=(
            {path for path in {original_source, replaced_source} if path is not None}
            if isolation_case is not None
            else None
        ),
        extra_sources={extra_source} if extra_source is not None else None,
    )
    runner_dir = c_cross / "runners" / _safe_c_suffix(source.stem)
    runner_dir.mkdir(parents=True, exist_ok=True)
    objects: list[Path] = []
    output_parts: list[str] = [f"isolation={isolation_note}\n"] if isolation_note else []
    for index, test_source in enumerate(sources):
        obj = runner_dir / f"{index}-{_safe_c_suffix(test_source.stem)}.o"
        compile_command = [
            cc,
            "-O0",
            "-g3",
            "-Wall",
            "-Wno-format",
            *_c_include_args(c_root, c_cross),
            "-c",
            str(test_source),
            "-o",
            str(obj),
        ]
        code, output = _run(compile_command)
        output_parts.append(f"$ {_command_text(compile_command)}\n{output}\n")
        if code != 0:
            return False, binary, "".join(output_parts) + f"cc exited with {code}\n"
        objects.append(obj)
    trace = c_cross.parent
    workbench_root = trace.parent.parent
    output_parts.append(_write_ffi_manifest(suite, c_root, c_cross, trace, objects, workbench_root))
    command = [
        cc,
        "-O0",
        "-g3",
        "-Wall",
        "-Wno-format",
        *[str(obj) for obj in objects],
        str(rust_lib),
        "-o",
        str(binary),
        "-lpthread",
        "-ldl",
        "-lm",
    ]
    code, output = _run(command)
    text = "".join(output_parts) + f"$ {_command_text(command)}\n{output}\n"
    if code != 0:
        text += f"cc exited with {code}\n"
        return False, binary, text
    return True, binary, text


def _run_suite_runner(suite: str, binary: Path, c_cross: Path) -> tuple[bool | str, str, str]:
    run_dir = c_cross / f"{suite}_run"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = c_cross / f"{suite}_runner.log"
    if shutil.which("stdbuf"):
        command = ["stdbuf", "-oL", "-eL", str(binary.resolve())]
        capture_mode = "stdbuf_line_buffered"
    else:
        command = [str(binary.resolve())]
        capture_mode = "pipe_buffering_fallback"
    code, output = _run(command, cwd=run_dir, timeout=60)
    text = f"capture_mode={capture_mode}\n$ {_command_text(command, run_dir)}\n{output}\n"
    _write(log_path, text)
    if code == -124:
        return "timeout", text, f"{suite} runner timeout after 60s, see {log_path}"
    if code != 0:
        text += f"runner exited with {code}\n"
        _write(log_path, text)
        return False, text, f"{suite} runner failed, see {log_path}"
    return True, text, f"{suite} original C runner passed"


def _layout_structs(trace: Path) -> list[dict[str, Any]]:
    design_path = trace / "rust_api_design.json"
    if design_path.exists():
        design = load_json(design_path)
        facade = design.get("c_abi_facade")
        structs = facade.get("structs") if isinstance(facade, dict) else []
        if isinstance(structs, list):
            result = [item for item in structs if isinstance(item, dict) and isinstance(item.get("c_name"), str)]
            if result:
                return result
    api_path = trace / "c_api_model.json"
    if not api_path.exists():
        return []
    api_model = load_json(api_path)
    layouts = api_model.get("abi_layouts")
    if not isinstance(layouts, list):
        return []
    result: list[dict[str, Any]] = []
    for layout in layouts:
        if not isinstance(layout, dict) or not isinstance(layout.get("name"), str):
            continue
        result.append(
            {
                "c_name": layout["name"],
                "sizeof": layout.get("sizeof"),
                "alignof": layout.get("alignof"),
                "fields": layout.get("fields", []),
                "notes": [],
            }
        )
    return result


def _layout_headers(c_root: Path, structs: list[dict[str, Any]]) -> list[str]:
    headers = [
        str(item.get("header"))
        for item in structs
        if isinstance(item.get("header"), str) and item.get("header")
    ]
    headers = [header.removeprefix("inc/") for header in headers]
    if not headers:
        inc = c_root / "inc"
        if inc.is_dir():
            headers = [path.relative_to(inc).as_posix() for path in sorted(inc.glob("*.h"))]
    return sorted(dict.fromkeys(headers))


def _layout_checker_source(structs: list[dict[str, Any]], headers: list[str]) -> str:
    lines = [
        "#include <stddef.h>",
        "#include <stdint.h>",
        "#include <stdio.h>",
        "#include <stdbool.h>",
        "#include <time.h>",
    ]
    lines.extend(f'#include "{header}"' for header in headers)
    lines.append("")
    for struct in structs:
        c_name = struct["c_name"]
        suffix = _safe_c_suffix(c_name)
        lines.append(f"extern size_t rust_sizeof_{suffix}(void);")
        lines.append(f"extern size_t rust_alignof_{suffix}(void);")
        fields = struct.get("fields", [])
        if isinstance(fields, list):
            for field in fields:
                if isinstance(field, dict) and isinstance(field.get("name"), str):
                    lines.append(f"extern size_t rust_offsetof_{suffix}_{_safe_c_suffix(field['name'])}(void);")
    lines.extend(
        [
            "",
            "int main(void) {",
            "  int failures = 0;",
            '  printf("[LAYOUT CHECK] start\\n");',
        ]
    )
    for struct in structs:
        c_name = struct["c_name"]
        suffix = _safe_c_suffix(c_name)
        lines.extend(
            [
                f"  if (sizeof(struct {c_name}) != rust_sizeof_{suffix}()) {{",
                f'    printf("[LAYOUT MISMATCH] struct={c_name} sizeof c=%zu rust=%zu\\n", sizeof(struct {c_name}), rust_sizeof_{suffix}());',
                "    failures++;",
                "  }",
                f"  if (_Alignof(struct {c_name}) != rust_alignof_{suffix}()) {{",
                f'    printf("[LAYOUT MISMATCH] struct={c_name} alignof c=%zu rust=%zu\\n", (size_t)_Alignof(struct {c_name}), rust_alignof_{suffix}());',
                "    failures++;",
                "  }",
                f"  if (sizeof(struct {c_name}) == rust_sizeof_{suffix}() && _Alignof(struct {c_name}) == rust_alignof_{suffix}()) {{",
                f'    printf("[LAYOUT OK] struct={c_name} sizeof=%zu alignof=%zu\\n", sizeof(struct {c_name}), (size_t)_Alignof(struct {c_name}));',
                "  }",
            ]
        )
        fields = struct.get("fields", [])
        if not isinstance(fields, list):
            fields = []
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                continue
            field_name = field["name"]
            field_suffix = _safe_c_suffix(field_name)
            lines.extend(
                [
                    f"  if (rust_offsetof_{suffix}_{field_suffix}() == (size_t)-1) {{",
                    f'    printf("[LAYOUT MISMATCH] field={c_name}.{field_name} offset c=%zu rust=missing\\n", offsetof(struct {c_name}, {field_name}));',
                    f'    printf("possible_reason=active macro added field {field_name} that Rust omitted\\n");',
                    "    failures++;",
                    f"  }} else if (offsetof(struct {c_name}, {field_name}) != rust_offsetof_{suffix}_{field_suffix}()) {{",
                    f'    printf("[LAYOUT MISMATCH] field={c_name}.{field_name} offset c=%zu rust=%zu\\n", offsetof(struct {c_name}, {field_name}), rust_offsetof_{suffix}_{field_suffix}());',
                    "    failures++;",
                    "  } else {",
                    f'    printf("[LAYOUT OK] struct={c_name} field={field_name} offset=%zu\\n", offsetof(struct {c_name}, {field_name}));',
                    "  }",
                ]
            )
    lines.extend(
        [
            "  if (failures) {",
            '    printf("[LAYOUT CHECK] fail\\n");',
            "    return 1;",
            "  }",
            '  printf("[LAYOUT CHECK] pass\\n");',
            "  return 0;",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_layout_checker(
    c_root: Path,
    c_cross: Path,
    rust_lib: Path,
    trace: Path,
    *,
    artifact_name: str = "layout",
    log_path_override: Path | None = None,
) -> tuple[bool, str]:
    structs = _layout_structs(trace)
    headers = _layout_headers(c_root, structs)
    if artifact_name == "layout":
        source = c_cross / "layout_checker.c"
        binary = c_cross / "layout_checker"
        log_path = c_cross / "layout-check.log"
    else:
        safe_name = _safe_c_suffix(artifact_name)
        source = c_cross / f"{safe_name}_checker.c"
        binary = c_cross / f"{safe_name}_checker"
        log_path = c_cross / f"{safe_name}-check.log"
    if log_path_override is not None:
        log_path = log_path_override
    source.write_text(_layout_checker_source(structs, headers), encoding="utf-8")
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        text = "missing C compiler: cc/gcc/clang not found\n"
        _write(log_path, text)
        return False, text
    command = [
        cc,
        "-std=c11",
        "-O0",
        "-g3",
        "-Wall",
        "-Wno-format",
        *_c_include_args(c_root, c_cross),
        str(source),
        str(rust_lib),
        "-o",
        str(binary),
        "-lpthread",
        "-ldl",
        "-lm",
    ]
    code, output = _run(command)
    text = f"$ {_command_text(command)}\n{output}\n"
    if code != 0:
        text += f"layout checker compile exited with {code}\n"
        _write(log_path, text)
        return False, text
    code, output = _run([str(binary.resolve())], cwd=c_cross)
    text += f"$ {_command_text([str(binary.resolve())], c_cross)}\n{output}\n"
    if code != 0:
        text += f"layout checker exited with {code}\n"
        _write(log_path, text)
        return False, text
    _write(log_path, text)
    return True, text


def run_scaffold_layout_check(
    root: Path,
    out: Path,
    *,
    project_name: str = "flashDB_rust",
) -> dict[str, Any]:
    """Build the current Rust project and validate layout without formal C-cross state."""

    trace = out
    c_cross = trace / "c-cross"
    c_cross.mkdir(parents=True, exist_ok=True)
    log_path = c_cross / "scaffold-layout-check.log"
    check_path = c_cross / "scaffold-layout-check.json"
    try:
        c_root = _find_c_project_root(root, trace)
    except Exception as exc:
        result = {
            "phase": "layout",
            "status": "fail",
            "build_status": "not_run",
            "layout_status": "not_run",
            "reason": f"cannot resolve scaffold layout inputs: {exc}",
            "log": _relative_log_path(log_path, root),
        }
        _write(log_path, result["reason"] + "\n")
        _write_json(check_path, result)
        return result
    project = (root / project_name).resolve()
    if c_root is None:
        result = {
            "phase": "layout",
            "status": "fail",
            "build_status": "not_run",
            "layout_status": "not_run",
            "reason": "FlashDB C project root not found",
            "log": _relative_log_path(log_path, root),
        }
        _write(log_path, result["reason"] + "\n")
        _write_json(check_path, result)
        return result
    if not project.is_dir():
        result = {
            "phase": "layout",
            "status": "fail",
            "build_status": "not_run",
            "layout_status": "not_run",
            "reason": f"Rust project not found: {project}",
            "log": _relative_log_path(log_path, root),
        }
        _write(log_path, result["reason"] + "\n")
        _write_json(check_path, result)
        return result

    try:
        build_ok, build_output = _build_rust_staticlib(project)
    except Exception as exc:
        result = {
            "phase": "layout",
            "status": "fail",
            "build_status": "fail",
            "layout_status": "not_run",
            "reason": f"current Rust staticlib build could not run: {exc}",
            "log": _relative_log_path(log_path, root),
        }
        _write(log_path, result["reason"] + "\n")
        _write_json(check_path, result)
        return result
    layout_ok = False
    layout_output = "layout not run because scaffold staticlib build failed\n"
    if build_ok:
        try:
            layout_ok, layout_output = _run_layout_checker(
                c_root,
                c_cross,
                _rust_staticlib(project),
                trace,
                artifact_name="scaffold-layout",
                log_path_override=log_path,
            )
        except Exception as exc:
            layout_ok = False
            layout_output = f"scaffold layout checker could not run: {exc}\n"
    _write(log_path, build_output + "\n" + layout_output)
    try:
        struct_count = len(_layout_structs(trace))
    except Exception:
        struct_count = 0
    result = {
        "phase": "layout",
        "status": "pass" if build_ok and layout_ok else "fail",
        "build_status": "pass" if build_ok else "fail",
        "layout_status": "pass" if layout_ok else "fail" if build_ok else "not_run",
        "source_manifest": _implementation_source_manifest(project),
        "struct_count": struct_count,
        "reason": "current Rust ABI layout matches compiler evidence" if build_ok and layout_ok else "current Rust ABI layout validation failed",
        "log": _relative_log_path(log_path, root),
    }
    _write_json(check_path, result)
    return result


def _malformed_row(index: int, case: Any, c_cross: Path, root: Path) -> dict[str, Any]:
    scenario_id = f"malformed_case_{index}"
    log = c_cross / f"{scenario_id}.log"
    if isinstance(case, dict):
        missing_fields = []
        if not isinstance(case.get("scenario_id"), str):
            missing_fields.append("scenario_id")
        if not isinstance(case.get("case_id"), str):
            missing_fields.append("case_id")
        if not isinstance(case.get("suite"), str) or not case.get("suite"):
            missing_fields.append("suite")
        reason = f"malformed scorer_standard_cases entry at index {index}: missing or non-string {', '.join(missing_fields)}"
    else:
        reason = f"malformed scorer_standard_cases entry at index {index}: expected object, got {type(case).__name__}"
    _write(log, reason + "\n")
    return {
        "scenario_id": scenario_id,
        "scorer_case_id": scenario_id,
        "suite": "unknown",
        "phase": "build",
        "failure_layer": "build",
        "source_runner": "unknown",
        "source_test": scenario_id,
        "c_impl_c_test": "baseline",
        "rust_impl_c_test": "not_supported",
        "c_impl_rust_test": "not_run",
        "rust_impl_rust_test": "pending",
        "diagnosis": "c_cross_harness_not_supported",
        "reason": reason,
        "log": _relative_log_path(log, root),
        "handoff": "primary",
    }


def _malformed_invocation_row(index: int, invocation: Any, c_cross: Path, root: Path) -> dict[str, Any]:
    scenario_id = f"malformed_invocation_{index}"
    log = c_cross / f"{scenario_id}.log"
    required = ["suite", "runner", "test_function", "scenario_id", "source_file"]
    missing = [key for key in required if not isinstance(invocation, dict) or not isinstance(invocation.get(key), str) or not invocation.get(key)]
    reason = (
        f"malformed registered_test_invocations entry at index {index}: missing or non-string {', '.join(missing)}"
        if isinstance(invocation, dict)
        else f"malformed registered_test_invocations entry at index {index}: expected object, got {type(invocation).__name__}"
    )
    _write(log, reason + "\n")
    return {
        "scenario_id": scenario_id,
        "suite": "unknown",
        "phase": "model",
        "failure_layer": "model",
        "source_runner": "unknown",
        "source_test": scenario_id,
        "c_impl_c_test": "baseline",
        "rust_impl_c_test": "unresolved",
        "c_impl_rust_test": "not_run",
        "rust_impl_rust_test": "pending",
        "diagnosis": "c_model_signature_gap",
        "reason": reason,
        "log": _relative_log_path(log, root),
        "handoff": "controller",
    }


def _repair_context_by_scenario(test_model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for collection in ["scorer_standard_cases", "standard_scenarios"]:
        cases = test_model.get(collection)
        if not isinstance(cases, list):
            continue
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("scenario_id") or case.get("id"), str):
                continue
            scenario_id = str(case.get("scenario_id") or case.get("id"))
            facts = case.get("semantic_facts") if isinstance(case.get("semantic_facts"), dict) else {}
            context = {
                "semantic_obligations": case.get("semantic_obligations", []),
                "public_api_calls": facts.get("public_api_calls", []),
                "observed_c_symbols": facts.get("observed_c_symbols", []),
                "data_shape": facts.get("data_shape", {}),
                "scenario_features": facts.get("scenario_features", []),
                "semantic_markers": facts.get("semantic_markers", []),
                "callback_paths": facts.get("callback_paths", []),
                "assertion_details": facts.get("assertion_details", []),
            }
            # scorer_standard_cases carry expanded helper evidence and take
            # precedence over the shallower registered-scenario snapshot.
            if scenario_id not in contexts or collection == "scorer_standard_cases":
                contexts[scenario_id] = context
    return contexts


def _source_evidence_by_scenario(test_model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = test_model.get("registered_test_invocations")
    if not isinstance(raw, list):
        return {}
    evidence: dict[str, dict[str, Any]] = {}
    repair_contexts = _repair_context_by_scenario(test_model)
    invocation_counter: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        runner = item.get("runner")
        test_function = item.get("test_function") or item.get("name")
        scenario_id = item.get("scenario_id")
        scenarios = [scenario_id] if isinstance(scenario_id, str) and scenario_id else item.get("scenarios")
        invocation_index = item.get("invocation_index")
        if not isinstance(scenarios, list) and isinstance(test_function, str):
            # Derive scenario from invocation_index if not provided
            idx = invocation_counter.get(test_function, 0) + 1
            invocation_counter[test_function] = idx
            if invocation_index is not None and invocation_index > 1:
                scenarios = [f"{test_function}__{invocation_index}"]
            else:
                scenarios = [test_function]
        if not isinstance(test_function, str) or not isinstance(scenarios, list):
            continue
        for scenario in scenarios:
            item_evidence: dict[str, Any] = {"source_test": test_function}
            invocation_idx = invocation_index if isinstance(invocation_index, int) else None
            if invocation_idx is not None:
                item_evidence["invocation_index"] = invocation_idx
            if isinstance(runner, str) and runner:
                item_evidence["source_runner"] = runner
            runner_order = item.get("runner_order")
            if isinstance(runner_order, int):
                item_evidence["runner_order"] = runner_order
            source_file = item.get("source_file")
            if isinstance(source_file, str) and source_file:
                item_evidence["source_file"] = source_file
            if isinstance(scenario, str) and scenario in repair_contexts:
                item_evidence["repair_context"] = repair_contexts[scenario]
            evidence[scenario] = item_evidence
    return evidence


def _expected_tests_by_suite(
    cases: list[dict[str, Any]],
    source_evidence: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for case in cases:
        scenario_id = str(case["scenario_id"])
        suite = _suite_for_case(case)
        source_test = source_evidence.get(scenario_id, {}).get("source_test", scenario_id)
        tests = result.setdefault(suite, [])
        # When same source_test maps to multiple scenarios,
        # include each scenario_id in expected_tests list instead of deduplicating by source_test.
        # This allows parse_runner_test_results to match multiple Running: lines to different scenario_ids.
        tests.append(scenario_id)
    return result


def _handoff_for_diagnosis(diagnosis: str) -> str:
    if diagnosis in {"c_model_signature_gap", "c_cross_harness_not_supported", "c_cross_result_parse_failed"}:
        return "primary"
    if diagnosis in {
        "rust_staticlib_build_failed",
        "c_abi_layout_mismatch",
        "c_runner_link_failed",
        "c_runner_runtime_failed",
        "c_runner_timeout",
        "c_test_case_failed",
        "rust_implementation_failed_c_baseline",
    }:
        return "rust-implementer"
    return "none"


def _suite_result_rows(
    cases: list[dict[str, Any]],
    suite_results: dict[str, tuple[str, str]],
    suite_test_results: dict[str, dict[str, Any]],
    suite_phases: dict[str, str],
    suite_diagnoses: dict[str, str],
    source_evidence: dict[str, dict[str, Any]],
    c_cross: Path,
    root: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        scenario_id = str(case["scenario_id"])
        suite = _suite_for_case(case)
        status, reason = suite_results.get(
            suite,
            ("not_supported", f"no original C runner is available for suite {suite}"),
        )
        log = c_cross / f"{scenario_id}.log"
        phase = suite_phases.get(suite, "full")
        diagnosis = suite_diagnoses.get(suite)
        evidence = source_evidence.get(scenario_id, {})
        source_test = evidence.get("source_test", scenario_id)
        source_runner = evidence.get("source_runner", f"{suite}_runner")
        parsed = suite_test_results.get(suite)
        if phase == "full" and parsed is not None:
            if scenario_id in parsed.get("passed", []):
                status = "pass"
                diagnosis = "rust_implementation_matches_c_baseline_for_scenario"
                reason = f"{source_test} passed in original C runner"
            elif scenario_id in parsed.get("runtime_failed", []):
                status = "fail"
                diagnosis = "c_runner_runtime_failed"
                reason = str(parsed.get("failures", {}).get(scenario_id) or f"{source_test} crashed")
            elif scenario_id in parsed.get("failed", []):
                status = "fail"
                diagnosis = "c_test_case_failed"
                reason = str(parsed.get("failures", {}).get(scenario_id) or f"{source_test} failed")
            elif scenario_id in parsed.get("timed_out", []):
                status = "not_run"
                diagnosis = "c_runner_timeout"
                reason = f"{source_test} was running when {suite} runner timed out"
            elif scenario_id in parsed.get("not_run", []):
                status = "not_run"
                if parsed.get("exit_code") == -124:
                    diagnosis = "c_runner_timeout"
                    reason = f"{source_test} was not run because {suite} runner timed out"
                else:
                    diagnosis = "c_runner_runtime_failed"
                    reason = f"{source_test} was not run before the runner exited"
            else:
                status = "unresolved"
                diagnosis = "c_cross_result_parse_failed"
                reason = f"no parsed result for expected scenario {scenario_id}"
        if not diagnosis:
            if status == "pass":
                diagnosis = "rust_implementation_matches_c_baseline_for_scenario"
            elif status == "fail":
                diagnosis = "rust_implementation_failed_c_baseline"
            else:
                diagnosis = "c_cross_harness_not_supported"
        repair_context = evidence.get("repair_context")
        log_text = f"suite={suite}\nsource_test={source_test}\nstatus={status}\nreason={reason}\n"
        if isinstance(repair_context, dict):
            log_text += "repair_context=" + json.dumps(repair_context, ensure_ascii=False, sort_keys=True) + "\n"
        _write(log, log_text)
        row = {
                "scenario_id": scenario_id,
                "suite": suite,
                "phase": phase,
                "failure_layer": (
                    "assertion" if diagnosis == "c_test_case_failed"
                    else "timeout" if diagnosis == "c_runner_timeout"
                    else "protocol" if diagnosis == "c_cross_result_parse_failed"
                    else phase
                ),
                "source_runner": source_runner,
                "source_test": source_test,
                "c_impl_c_test": "baseline",
                "rust_impl_c_test": status,
                "c_impl_rust_test": "not_run",
                "rust_impl_rust_test": "pending",
                "diagnosis": diagnosis,
                "reason": reason,
                "log": _relative_log_path(log, root),
                "handoff": _handoff_for_diagnosis(diagnosis),
            }
        if isinstance(repair_context, dict):
            row["repair_context"] = repair_context
        if isinstance(parsed, dict):
            row["parse_status"] = parsed.get("status")
            row["parse_reason"] = parsed.get("reason")
        rows.append(row)
        if isinstance(case.get("case_id"), str) and case["case_id"]:
            rows[-1]["scorer_case_id"] = case["case_id"]
    return rows


def _verification_results(scenarios: list[dict[str, Any]]) -> tuple[str, str]:
    outcomes = [str(item.get("rust_impl_c_test") or "unresolved") for item in scenarios]
    if any(item.get("parse_status") == "parse_failed" for item in scenarios):
        return "CONTINUE_WITH_FAILURES", "unresolved"
    if outcomes and all(value == "pass" for value in outcomes):
        return "PASS", "pass"
    if any(value in {"unresolved", "parse_failed"} for value in outcomes):
        return "CONTINUE_WITH_FAILURES", "unresolved"
    if any(value == "pass" for value in outcomes):
        return "CONTINUE_WITH_FAILURES", "partial"
    return "CONTINUE_WITH_FAILURES", "failed"


def convergence_status(
    matrix: dict[str, Any],
    attempts: list[dict[str, Any]],
    queue_phase: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenarios = matrix.get("scenarios")
    rows = [row for row in scenarios if isinstance(row, dict)] if isinstance(scenarios, list) else []
    all_pass = bool(rows) and all(row.get("rust_impl_c_test") == "pass" for row in rows)
    full_scope = matrix.get("mode") == "full" and matrix.get("scope") == "all"
    attempt_kind = matrix.get("attempt_kind")
    if all_pass and full_scope and attempt_kind == "final":
        status, terminal, next_action = "success", True, "report_success"
    elif all_pass and full_scope:
        status, terminal, next_action = "ready_for_final", False, "run_fresh_final"
    else:
        queue_decision = repair_work_queue.convergence(
            queue_phase or {"tasks": {}, "dynamic_task_ids": []},
            current_full_confirmation_id=(
                str(matrix.get("execution_id"))
                if full_scope and attempt_kind == "confirmation"
                else None
            ),
        )
        status = str(queue_decision["status"])
        terminal = bool(queue_decision["terminal"])
        next_action = str(queue_decision["next_action"])
    result = {
        "status": status,
        "terminal": terminal,
        "next_action": next_action,
        "repair_attempts_recorded": len(_repair_rows(attempts)),
    }
    if queue_phase is not None:
        result["work_queue"] = repair_work_queue.phase_summary(queue_phase)
    return result


def _write_failure_summary(
    matrix: dict[str, Any],
    c_cross: Path,
    attempts: list[dict[str, Any]] | None = None,
    queue_phase: dict[str, Any] | None = None,
    convergence_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write actionable failures and the per-task convergence decision."""
    scenarios = matrix.get("scenarios")
    failures = []
    if isinstance(scenarios, list):
        for row in scenarios:
            if not isinstance(row, dict) or row.get("rust_impl_c_test") == "pass":
                continue
            failures.append({
                key: row.get(key)
                for key in (
                    "scenario_id", "scorer_case_id", "suite", "failure_layer",
                    "diagnosis", "reason", "log", "handoff",
                )
            })
    convergence = convergence_override or convergence_status(matrix, attempts or [], queue_phase)
    guidance_by_status = {
        "repair_required": "Repair the next queued scenario or shared-root cluster, then run targeted and affected-suite validation.",
        "restore_confirmation_required": "The best-known Rust source was restored; run an unfiltered full confirmation before any repair or final attempt.",
        "best_restore_failed": "Best-known source restoration failed; do not continue to report or final.",
        "failed_final": "Every remaining repair task is exhausted and a full confirmation preserved the failures.",
        "ready_for_final": "Run a fresh full final verification.",
        "success": "Fresh full final verification passed.",
    }
    summary = {
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        **convergence,
        "execution_id": matrix.get("execution_id"),
        "failures": failures,
        "guidance": guidance_by_status.get(str(convergence.get("status")), "Validation has no legal terminal action."),
    }
    _write_json(c_cross / "failure-summary.json", summary)
    return summary


def _has_complete_attempt_evidence(matrix: dict[str, Any], root: Path) -> bool:
    scenarios = matrix.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return False
    try:
        diagnostics = _read_jsonl(root / "logs" / "trace" / "c-cross" / "diagnostics.jsonl")
    except (OSError, ValueError, json.JSONDecodeError):
        diagnostics = []
    parse_diagnostics = {
        str(row.get("scenario_id")): row
        for row in diagnostics
        if isinstance(row, dict)
        and row.get("diagnosis") == "c_cross_result_parse_failed"
        and isinstance(row.get("scenario_id"), str)
    }
    for row in scenarios:
        if not isinstance(row, dict) or not isinstance(row.get("scenario_id"), str):
            return False
        status = row.get("rust_impl_c_test")
        if status not in {"pass", "fail", "not_run", "unresolved", "not_supported", "parse_failed"}:
            return False
        parse_failed = row.get("parse_status") == "parse_failed" or status == "parse_failed"
        if status == "pass" and not parse_failed:
            continue
        log = row.get("log")
        if not isinstance(log, str) or not log.startswith("logs/trace/c-cross/"):
            return False
        if not (root / log).is_file():
            return False
        if parse_failed:
            diagnostic = parse_diagnostics.get(row["scenario_id"])
            if not isinstance(row.get("parse_reason"), str) or not row.get("parse_reason"):
                return False
            if (
                not isinstance(diagnostic, dict)
                or not isinstance(diagnostic.get("handoff"), str)
                or diagnostic.get("handoff") in {"", "none"}
            ):
                return False
            continue
        if (
            not isinstance(row.get("diagnosis"), str)
            or not row.get("diagnosis")
            or not isinstance(row.get("handoff"), str)
            or row.get("handoff") in {"", "none"}
        ):
            return False
    return True


def build_matrix(
    root: Path,
    out: Path,
    project_name: str = "flashDB_rust",
    mode: str = "full",
    selected_suites: set[str] | None = None,
    selected_scenarios: set[str] | None = None,
    attempt_kind: str = "checkpoint",
    trigger: str = "manual",
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    if mode not in {"build", "layout", "link", "full"}:
        raise ValueError(f"unsupported c-cross mode: {mode}")
    trace = out
    c_cross = trace / "c-cross"
    c_cross.mkdir(parents=True, exist_ok=True)
    # Deferred convergence is no longer part of the C-CROSS contract. Remove a
    # stale artifact from older workbench runs so it cannot be mistaken for
    # current evidence.
    (c_cross / "deferred.jsonl").unlink(missing_ok=True)
    (trace / "ffi_manifest.json").unlink(missing_ok=True)

    test_model = load_json(trace / "c_test_model.json")
    malformed = []
    valid_cases: list[dict[str, Any]] = []
    raw_invocations = test_model.get("registered_test_invocations")
    scorer_cases = test_model.get("scorer_standard_cases")
    scorer_case_by_scenario = {
        item.get("scenario_id"): item.get("case_id")
        for item in scorer_cases
        if isinstance(item, dict)
        and isinstance(item.get("scenario_id"), str)
        and isinstance(item.get("case_id"), str)
    } if isinstance(scorer_cases, list) else {}
    if isinstance(raw_invocations, list) and raw_invocations:
        legacy_occurrences: dict[tuple[str, str], int] = {}
        for index, invocation in enumerate(raw_invocations):
            case = dict(invocation) if isinstance(invocation, dict) else invocation
            if isinstance(case, dict):
                scenarios = case.get("scenarios")
                if not isinstance(case.get("scenario_id"), str) and isinstance(scenarios, list) and len(scenarios) == 1 and isinstance(scenarios[0], str):
                    case["scenario_id"] = scenarios[0]
                if not isinstance(case.get("source_file"), str) and isinstance(case.get("runner"), str):
                    case["source_file"] = case["runner"]
                if not isinstance(case.get("runner_order"), int):
                    case["runner_order"] = case.get("order", index + 1)
                key = (str(case.get("runner") or ""), str(case.get("test_function") or ""))
                legacy_occurrences[key] = legacy_occurrences.get(key, 0) + 1
                if not isinstance(case.get("invocation_index"), int):
                    case["invocation_index"] = legacy_occurrences[key]
                if not isinstance(case.get("source_line"), int):
                    case["source_line"] = case["runner_order"]
            if (
                not isinstance(case, dict)
                or not isinstance(case.get("suite"), str)
                or not case.get("suite")
                or not isinstance(case.get("runner"), str)
                or not case.get("runner")
                or not isinstance(case.get("test_function"), str)
                or not case.get("test_function")
                or not isinstance(case.get("scenario_id"), str)
                or not case.get("scenario_id")
                or not isinstance(case.get("source_file"), str)
                or not case.get("source_file")
            ):
                malformed.append(_malformed_invocation_row(index, invocation, c_cross, root))
                continue
            scorer_case_id = scorer_case_by_scenario.get(case["scenario_id"])
            if isinstance(scorer_case_id, str):
                case["case_id"] = scorer_case_id
            valid_cases.append(case)
    else:
        raw_cases = scorer_cases
        if not isinstance(raw_cases, list):
            raise ValueError("c_test_model.json registered_test_invocations must be a non-empty list")
        for index, case in enumerate(raw_cases):
            if (
                not isinstance(case, dict)
                or not isinstance(case.get("scenario_id"), str)
                or not isinstance(case.get("case_id"), str)
                or not isinstance(case.get("suite"), str)
                or not case.get("suite")
            ):
                malformed.append(_malformed_row(index, case, c_cross, root))
            else:
                valid_cases.append(case)

    all_valid_cases = list(valid_cases)
    available_suites = {_suite_for_case(case) for case in valid_cases}
    available_scenarios = {str(case["scenario_id"]) for case in valid_cases}
    if selected_suites is not None:
        unknown_suites = sorted(selected_suites - available_suites)
        if unknown_suites:
            raise ValueError("unknown requested C-cross suites: " + ", ".join(unknown_suites))
        valid_cases = [case for case in valid_cases if _suite_for_case(case) in selected_suites]
    if selected_scenarios is not None:
        unknown_scenarios = sorted(selected_scenarios - available_scenarios)
        if unknown_scenarios:
            raise ValueError("unknown requested C-cross scenarios: " + ", ".join(unknown_scenarios))
        valid_cases = [case for case in valid_cases if str(case["scenario_id"]) in selected_scenarios]
        filtered_scenarios = {str(case["scenario_id"]) for case in valid_cases}
        excluded_by_suite = sorted(selected_scenarios - filtered_scenarios)
        if excluded_by_suite:
            raise ValueError(
                "requested scenarios are excluded by --suite selection: " + ", ".join(excluded_by_suite)
            )
        selected_counts = Counter(_suite_for_case(case) for case in valid_cases)
        ambiguous_suites = sorted(suite for suite, count in selected_counts.items() if count > 1)
        if ambiguous_suites:
            raise ValueError(
                "scenario isolation accepts at most one scenario per suite: " + ", ".join(ambiguous_suites)
            )

    enabled_cases = [case for case in valid_cases if case.get("c_cross", {}).get("enabled", True)]
    not_enabled_cases = [case for case in valid_cases if not case.get("c_cross", {}).get("enabled", True)]
    not_enabled_rows: list[dict[str, Any]] = []
    for case in not_enabled_cases:
        c_cross_info = case.get("c_cross", {})
        scenario_id = str(case["scenario_id"])
        log = c_cross / f"{scenario_id}.log"
        reason = c_cross_info.get("reason", "c_cross_disabled_by_design")
        _write(log, f"scenario_id={scenario_id}\nstatus=not_supported\nreason={reason}\nc_cross.enabled=False\n")
        not_enabled_rows.append({
            "scenario_id": scenario_id,
            "scorer_case_id": str(case["case_id"]),
            "suite": _suite_for_case(case),
            "phase": "full",
            "failure_layer": "full",
            "source_runner": f"{_suite_for_case(case)}_runner",
            "source_test": scenario_id,
            "c_impl_c_test": "baseline",
            "rust_impl_c_test": "not_supported",
            "c_impl_rust_test": "not_run",
            "rust_impl_rust_test": "pending",
            "diagnosis": "c_cross_harness_not_supported",
            "reason": reason,
            "log": _relative_log_path(log, root),
            "handoff": "primary",
        })

    compile_log: list[str] = []
    test_log: list[str] = []
    suite_results: dict[str, tuple[str, str]] = {}
    suite_test_results: dict[str, dict[str, Any]] = {}
    suite_phases: dict[str, str] = {}
    suite_diagnoses: dict[str, str] = {}
    diagnostics: list[dict[str, Any]] = []
    source_evidence = _source_evidence_by_scenario(test_model)
    expected_tests_by_suite = _expected_tests_by_suite(enabled_cases, source_evidence)
    c_root = _find_c_project_root(root, trace)
    project = (root / project_name).resolve()
    suites = sorted({_suite_for_case(case) for case in enabled_cases})

    if c_root is None:
        reason = "FlashDB C project root not found"
        compile_log.append(reason + "\n")
        _write_json(c_cross / "build-check.json", {"phase": "build", "status": "not_supported", "reason": reason})
        _write_json(c_cross / "layout-check.json", {"phase": "layout", "status": "not_run", "reason": reason})
        _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
        for suite in suites:
            suite_results[suite] = ("not_supported", reason)
            suite_phases[suite] = "build"
            suite_diagnoses[suite] = "c_cross_harness_not_supported"
    elif not project.exists():
        reason = f"Rust project not found: {project}"
        compile_log.append(reason + "\n")
        _write_json(c_cross / "build-check.json", {"phase": "build", "status": "fail", "reason": reason})
        _write_json(c_cross / "layout-check.json", {"phase": "layout", "status": "not_run", "reason": reason})
        _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
        for suite in suites:
            suite_results[suite] = ("fail", reason)
            suite_phases[suite] = "build"
            suite_diagnoses[suite] = "rust_staticlib_build_failed"
    else:
        rust_ok, rust_output = _build_rust_staticlib(project)
        compile_log.append(rust_output)
        _write_json(
            c_cross / "build-check.json",
            {
                "phase": "build",
                "status": "pass" if rust_ok else "fail",
                "command": "cargo build --release",
                "log": _relative_log_path(c_cross / "cross-compile.log", root),
                "staticlib": _relative_log_path(_rust_staticlib(project), root) if rust_ok else None,
            },
        )
        if not rust_ok:
            reason = "Rust staticlib build failed"
            _write_json(c_cross / "layout-check.json", {"phase": "layout", "status": "not_run", "reason": reason})
            _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
            for suite in suites:
                suite_results[suite] = ("fail", reason)
                suite_phases[suite] = "build"
                suite_diagnoses[suite] = "rust_staticlib_build_failed"
        elif mode == "build":
            reason = "stopped after build mode"
            _write_json(c_cross / "layout-check.json", {"phase": "layout", "status": "not_run", "reason": reason})
            _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
            for suite in suites:
                suite_results[suite] = ("pending", reason)
                suite_phases[suite] = "build"
                suite_diagnoses[suite] = "blocked_before_rust_test_migration"
        else:
            rust_lib = _rust_staticlib(project)
            layout_ok, layout_output = _run_layout_checker(c_root, c_cross, rust_lib, trace)
            compile_log.append(layout_output)
            _write_json(
                c_cross / "layout-check.json",
                {
                    "phase": "layout",
                    "status": "pass" if layout_ok else "fail",
                    "diagnosis": "pass" if layout_ok else "c_abi_layout_mismatch",
                    "log": _relative_log_path(c_cross / "layout-check.log", root),
                },
            )
            if not layout_ok:
                reason = "layout mismatch or layout checker failure; see logs/trace/c-cross/layout-check.log"
                _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
                for suite in suites:
                    suite_results[suite] = ("fail", reason)
                    suite_phases[suite] = "layout"
                    suite_diagnoses[suite] = "c_abi_layout_mismatch"
                for case in valid_cases:
                    diagnostics.append(
                        {
                            "phase": "layout",
                            "diagnosis": "c_abi_layout_mismatch",
                            "scenario_id": str(case["scenario_id"]),
                            "scorer_case_id": str(case["case_id"]),
                            "suite": _suite_for_case(case),
                            "handoff": "rust-implementer",
                            "reason": reason,
                            "log": _relative_log_path(c_cross / "layout-check.log", root),
                        }
                    )
            elif mode == "layout":
                reason = "stopped after layout mode"
                _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
                for suite in suites:
                    suite_results[suite] = ("pending", reason)
                    suite_phases[suite] = "layout"
                    suite_diagnoses[suite] = "blocked_before_rust_test_migration"
            else:
                link_suites: dict[str, str] = {}
                link_reasons: dict[str, str] = {}
                compiled_binaries: dict[str, Path] = {}
                for suite in suites:
                    suite_cases = [case for case in enabled_cases if _suite_for_case(case) == suite]
                    isolation_case = suite_cases[0] if selected_scenarios is not None and len(suite_cases) == 1 else None
                    original_suite_count = sum(
                        1 for case in all_valid_cases if _suite_for_case(case) == suite
                    )
                    ok, binary, output = _compile_suite_runner(
                        suite,
                        c_root,
                        c_cross,
                        rust_lib,
                        suite_cases,
                        isolation_case=isolation_case,
                        suite_case_count=original_suite_count,
                    )
                    compile_log.append(output)
                    if not ok or binary is None:
                        reason = f"{suite} original C runner failed to compile"
                        suite_results[suite] = ("fail", reason)
                        suite_phases[suite] = "link"
                        suite_diagnoses[suite] = "c_runner_link_failed"
                        link_suites[suite] = "fail"
                        link_reasons[suite] = reason
                        diagnostics.append(
                            {
                                "phase": "link",
                                "diagnosis": "c_runner_link_failed",
                                "suite": suite,
                                "handoff": "rust-implementer",
                                "reason": reason,
                                "log": _relative_log_path(c_cross / "cross-compile.log", root),
                            }
                        )
                        continue
                    compiled_binaries[suite] = binary
                    link_suites[suite] = "pass"
                _write_json(
                    c_cross / "link-check.json",
                    {
                        "phase": "link",
                        "status": "pass" if link_suites and all(value == "pass" for value in link_suites.values()) else "fail",
                        "suites": link_suites,
                        "reasons": link_reasons,
                        "log": _relative_log_path(c_cross / "cross-compile.log", root),
                    },
                )
                if mode == "link":
                    test_log.append("No C runner executed in link mode.\n")
                    for suite in suites:
                        if suite not in suite_results:
                            suite_results[suite] = ("pending", "stopped after link mode")
                            suite_phases[suite] = "link"
                            suite_diagnoses[suite] = "blocked_before_rust_test_migration"
                else:
                    for suite, binary in compiled_binaries.items():
                        run_status, run_output, run_reason = _run_suite_runner(suite, binary, c_cross)
                        normalized_status = "timeout" if run_status == "timeout" else "pass" if run_status is True else "fail"
                        test_log.append(run_output)
                        suite_results[suite] = (
                            normalized_status,
                            run_reason,
                        )
                        suite_test_results[suite] = parse_runner_test_results(
                            run_output,
                            expected_tests_by_suite.get(suite, []),
                            0 if normalized_status == "pass" else -124 if normalized_status == "timeout" else 1,
                        )
                        suite_phases[suite] = "full"
                        suite_diagnoses[suite] = (
                            "rust_implementation_matches_c_baseline_for_scenario"
                            if normalized_status == "pass"
                            else "c_runner_timeout" if normalized_status == "timeout" else "c_runner_runtime_failed"
                        )
                        if normalized_status != "pass":
                            diagnostics.append(
                                {
                                    "phase": "full",
                                    "diagnosis": suite_diagnoses[suite],
                                    "suite": suite,
                                    "handoff": "rust-implementer",
                                    "reason": run_reason,
                                    "log": _relative_log_path(c_cross / f"{suite}_runner.log", root),
                                }
                            )
                    for suite in suites:
                        suite_phases.setdefault(suite, "link")

    _write(c_cross / "cross-compile.log", "\n".join(compile_log))
    _write(c_cross / "cross-test.log", "\n".join(test_log) if test_log else "No C runner executed.\n")

    scenarios = malformed + not_enabled_rows + _suite_result_rows(
        enabled_cases,
        suite_results,
        suite_test_results,
        suite_phases,
        suite_diagnoses,
        source_evidence,
        c_cross,
        root,
    )
    _write_jsonl(c_cross / "case-results.jsonl", scenarios)
    # Add per-scenario diagnostics with the semantic context needed by a
    # targeted repair.  Suite-level diagnostics alone cannot distinguish an
    # assertion from a timeout or an unstarted scenario.
    for scenario_row in scenarios:
        parse_failed = scenario_row.get("parse_status") == "parse_failed"
        if scenario_row.get("rust_impl_c_test") in {"fail", "not_run", "unresolved"} or parse_failed:
            diagnostic = {
                "phase": scenario_row.get("phase", "full"),
                "diagnosis": "c_cross_result_parse_failed" if parse_failed else scenario_row.get("diagnosis"),
                "scenario_id": scenario_row.get("scenario_id"),
                "scorer_case_id": scenario_row.get("scorer_case_id"),
                "suite": scenario_row.get("suite"),
                "handoff": "primary" if parse_failed else scenario_row.get("handoff"),
                "reason": scenario_row.get("parse_reason") if parse_failed else scenario_row.get("reason"),
                "log": scenario_row.get("log"),
                "failure_layer": "protocol" if parse_failed else scenario_row.get("failure_layer"),
            }
            if isinstance(scenario_row.get("repair_context"), dict):
                diagnostic["repair_context"] = scenario_row["repair_context"]
            diagnostics.append(diagnostic)
    _write_jsonl(c_cross / "diagnostics.jsonl", diagnostics)
    workbench_issues = [
        {
            "stage": "VERIFY_RUST_WITH_C_TESTS",
            "type": "toolchain_defect",
            "owner": "controller",
            "tool": "c_cross_validate.py",
            "reason": row.get("parse_reason") if row.get("parse_status") == "parse_failed" else row.get("reason"),
            "evidence": row.get("log"),
            "affected_scenarios": [row.get("scenario_id")],
            "status": "unresolved",
        }
        for row in scenarios
        if row.get("rust_impl_c_test") == "unresolved" or row.get("parse_status") == "parse_failed"
    ]
    _write_jsonl(c_cross / "workbench-issues.jsonl", workbench_issues)
    summary = Counter(item["rust_impl_c_test"] for item in scenarios)
    stage_result, verification_result = _verification_results(scenarios)
    return annotate_matrix_scope({
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        "policy": "strict",
        "mode": mode,
        "scope": "selected" if selected_suites is not None or selected_scenarios is not None else "all",
        "selected_suites": sorted({_suite_for_case(case) for case in valid_cases}),
        "selected_scenarios": sorted(selected_scenarios or []),
        "attempt_kind": attempt_kind,
        "trigger": trigger,
        "changed_files": list(changed_files or []),
        "total_scenarios": len(scenarios),
        "summary": {"rust_impl_c_test": dict(sorted(summary.items()))},
        "stage_result": stage_result,
        "verification_result": verification_result,
        "scenarios": scenarios,
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FlashDB original C tests against the Rust C ABI staticlib.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--project", default="flashDB_rust", help="Rust project path, relative to root.")
    parser.add_argument("--out", default="logs/trace", help="Trace output directory, relative to root.")
    parser.add_argument("--mode", choices=["build", "layout", "link", "full"], default="full", help="C-cross checkpoint depth.")
    parser.add_argument("--suite", action="append", dest="suites", help="Run only a suite discovered from the current C test model. Repeatable.")
    parser.add_argument("--scenario", action="append", dest="scenarios", help="Run one generated, filtered scenario runner. Repeatable.")
    parser.add_argument(
        "--scaffold-layout-only",
        action="store_true",
        help="Build the current Rust project and check ABI layout without writing validation-matrix.json or attempts.jsonl.",
    )
    parser.add_argument(
        "--attempt-kind",
        choices=["checkpoint", "repair", "confirmation", "final"],
        default="checkpoint",
        help="Classify this execution for convergence and final-gate policy.",
    )
    parser.add_argument(
        "--repair-kind",
        choices=["local", "architecture"],
        default="local",
        help="Bound a repair as a local edit or a post-stall architecture edit.",
    )
    parser.add_argument("--trigger", default="manual", help="Machine-stable reason for this execution.")
    parser.add_argument("--changed-file", action="append", default=[], help="File changed before a repair execution. Repeatable.")
    parser.add_argument(
        "--restore-best",
        action="store_true",
        help="Restore the best-known src/** snapshot after regression, then exit. A full confirmation is required next.",
    )
    args = parser.parse_args(argv)

    try:
        contest_guard.guard_mutation_allowed(Path(args.root))
    except RuntimeError as exc:
        print(str(exc))
        return contest_guard.FINALIZE_EXIT_CODE

    root = Path(args.root).resolve()
    out = (root / args.out).resolve()
    c_cross = out / "c-cross"
    project_root = (root / args.project).resolve()
    if args.restore_best:
        restore_attempts = _read_jsonl(c_cross / "attempts.jsonl")
        if not restore_attempts or restore_attempts[-1].get("regression") is not True:
            parser.error("--restore-best is only allowed immediately after a recorded regression")
        try:
            restored = restore_best_known(c_cross, project_root)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        print("VERIFY_RUST_WITH_C_TESTS: BEST_KNOWN_RESTORED")
        print(f"best_attempt_id={restored['best_attempt_id']}")
        print("next_action=run_full_confirmation")
        return 0

    if args.attempt_kind == "repair":
        if not args.changed_file:
            parser.error("--attempt-kind repair requires at least one --changed-file flashDB_rust/src/<file>")
        invalid_repair_paths = [
            value
            for value in args.changed_file
            if (
                Path(value).is_absolute()
                or ".." in Path(value).parts
                or len(Path(value).parts) < 3
                or Path(value).parts[0:2] != ("flashDB_rust", "src")
            )
        ]
        if invalid_repair_paths:
            parser.error("repair --changed-file must stay under flashDB_rust/src/")
    elif args.repair_kind != "local":
        parser.error("--repair-kind architecture is only valid with --attempt-kind repair")
    if args.attempt_kind in {"confirmation", "final"} and (
        args.mode != "full" or args.suites or args.scenarios
    ):
        parser.error(f"--attempt-kind {args.attempt_kind} requires unfiltered --mode full scope")

    if args.scaffold_layout_only:
        result = run_scaffold_layout_check(root, out, project_name=args.project)
        print("GENERATE_RUST_SCAFFOLD: LAYOUT_CHECK_WRITTEN")
        print(f"stage_result={'PASS' if result['status'] == 'pass' else 'FAIL'}")
        print(f"verification_result={result['status']}")
        return 0 if result["status"] == "pass" else 1

    try:
        implementation_audit, implementation_convergence = implementation_preflight(
            root,
            out,
            project_name=args.project,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print("VERIFY_RUST_WITH_C_TESTS: IMPLEMENTATION_REQUIRED")
        print(f"reason=implementation preflight could not run: {exc}")
        print("next_action=return_to_implement")
        return 2
    if (
        implementation_audit.get("status") != "pass"
        or implementation_convergence.get("status") != "ready_for_verify"
        or implementation_convergence.get("valid") is not True
    ):
        terminal = implementation_convergence.get("status") == "failed_final"
        print(
            "VERIFY_RUST_WITH_C_TESTS: "
            + ("IMPLEMENTATION_FAILED_FINAL" if terminal else "IMPLEMENTATION_REQUIRED")
        )
        print(f"implementation_audit={_relative_log_path(out / 'implementation-audit.json', root)}")
        print(
            "next_action="
            + ("report_implementation_failure" if terminal else "return_to_implement")
        )
        return 2

    matrix_path = out / "validation-matrix.json"
    previous_matrix = load_json(matrix_path) if matrix_path.exists() else None
    attempts_before = _read_jsonl(c_cross / "attempts.jsonl")
    source_manifest = _source_manifest(project_root)
    cluster_scenarios = sorted(set(args.scenarios or []))
    actual_changed_files: list[str] = []
    previous_manifest = attempts_before[-1].get("source_manifest") if attempts_before else None
    source_changes = (
        _manifest_changed_files(previous_manifest, source_manifest)
        if isinstance(previous_manifest, dict)
        else []
    )
    if args.attempt_kind == "final":
        final_errors = validate_final_request(previous_matrix, attempts_before, source_manifest)
        if final_errors:
            parser.error("; ".join(final_errors))
    if args.attempt_kind == "repair":
        if isinstance(previous_manifest, dict):
            actual_changed_files = source_changes
        queue = repair_work_queue.load_queue(out / "repair-work-queue.json")
        phase = queue.get("phases", {}).get("c_cross") if isinstance(queue.get("phases"), dict) else None
        tasks = phase.get("tasks") if isinstance(phase, dict) and isinstance(phase.get("tasks"), dict) else {}
        terminal_tasks = [
            scenario_id
            for scenario_id in cluster_scenarios
            if isinstance(tasks.get(scenario_id), dict)
            and tasks[scenario_id].get("state") in {"confirmed_pass", "exhausted"}
        ]
        if terminal_tasks:
            parser.error("repair task is already terminal: " + ", ".join(terminal_tasks))
        request_errors = validate_repair_request(
            attempts_before,
            repair_kind=args.repair_kind,
            cluster_scenarios=cluster_scenarios,
            declared_changed_files=args.changed_file,
            current_source_manifest=source_manifest,
        )
        if request_errors:
            parser.error("; ".join(request_errors))
    elif source_changes:
        restore_evidence_path = c_cross / "restore-best.json"
        restore_evidence = load_json(restore_evidence_path) if restore_evidence_path.is_file() else {}
        restored_confirmation = (
            args.attempt_kind == "confirmation"
            and bool(attempts_before)
            and attempts_before[-1].get("regression") is True
            and restore_evidence.get("status") == "restored"
            and restore_evidence.get("source_manifest") == source_manifest
        )
        if not restored_confirmation:
            parser.error(
                "Rust src/** changed since the latest C-Cross attempt; record a bounded targeted repair with "
                "--attempt-kind repair --scenario ... --changed-file ..."
            )
    matrix = build_matrix(
        root,
        out,
        project_name=args.project,
        mode=args.mode,
        selected_suites=set(args.suites) if args.suites else None,
        selected_scenarios=set(args.scenarios) if args.scenarios else None,
        attempt_kind=args.attempt_kind,
        trigger=args.trigger,
        changed_files=args.changed_file,
    )
    matrix["implementation_audit"] = {
        "status": implementation_audit.get("status"),
        "input_fingerprint": implementation_audit.get("input_fingerprint"),
        "attempt_id": implementation_convergence.get("attempt_id"),
        "basis": implementation_convergence.get("basis"),
    }
    execution_id = f"{time.time_ns()}-{_safe_c_suffix(args.attempt_kind)}-{_safe_c_suffix(args.trigger)}"
    matrix["execution_id"] = execution_id
    attempt = record_attempt(
        c_cross,
        previous_matrix,
        matrix,
        attempt_kind=args.attempt_kind,
        trigger=args.trigger,
        changed_files=args.changed_file,
        project_root=project_root,
        repair_kind=args.repair_kind if args.attempt_kind == "repair" else None,
        cluster_scenarios=cluster_scenarios,
        source_manifest=source_manifest,
        actual_changed_files=actual_changed_files,
    )
    matrix["attempt"] = {
        "attempt_id": attempt["attempt_id"],
        "number": attempt["attempt"],
        "result": attempt["result"],
        "changed_file_hashes": attempt["changed_file_hashes"],
        "progress": attempt["progress"],
        "regression": attempt["regression"],
        "stalled_rounds": attempt["stalled_rounds"],
        "best_known": attempt["best_known"],
    }
    attempts_after = attempts_before + [attempt]
    queue_path = out / "repair-work-queue.json"
    auto_restore = auto_restore_regressed_full_attempt(
        c_cross,
        project_root,
        queue_path,
        attempt,
        matrix,
        attempts_after,
    )
    if auto_restore is not None:
        convergence, restore_result = auto_restore
        queue = repair_work_queue.load_queue(queue_path)
        phases = queue.get("phases") if isinstance(queue.get("phases"), dict) else {}
        queue_phase = phases.get("c_cross") if isinstance(phases.get("c_cross"), dict) else {
            "phase": "c_cross", "sweep": 1, "tasks": {}, "dynamic_task_ids": []
        }
        matrix["auto_restore"] = restore_result
        matrix["convergence"] = convergence
        _write_failure_summary(
            matrix,
            c_cross,
            attempts_after,
            queue_phase,
            convergence_override=convergence,
        )
        _write_json(out / "c-cross" / "checkpoints" / f"{execution_id}.json", matrix)
        _write_json(matrix_path, matrix)
        print("VERIFY_RUST_WITH_C_TESTS: " + (
            "BEST_KNOWN_AUTO_RESTORED" if restore_result.get("status") == "restored" else "BEST_KNOWN_RESTORE_FAILED"
        ))
        print(f"convergence_status={convergence['status']}")
        print(f"next_action={convergence['next_action']}")
        return 1
    outcomes = _matrix_outcomes(matrix)
    fingerprints = {
        scenario_id: failure_fingerprint(row)
        for scenario_id, row in outcomes["failures"].items()
    }
    queue_phase: dict[str, Any]
    if args.attempt_kind == "repair":
        progress_ids: set[str] = set()
        before_outcomes = _matrix_outcomes(previous_matrix)
        for scenario_id in cluster_scenarios:
            if scenario_id in outcomes["passed"]:
                progress_ids.add(scenario_id)
                continue
            before_row = before_outcomes["failures"].get(scenario_id)
            after_row = outcomes["failures"].get(scenario_id)
            if before_row is not None and after_row is not None and failure_fingerprint(before_row) != failure_fingerprint(after_row):
                progress_ids.add(scenario_id)
        queue_phase = repair_work_queue.record_attempt(
            queue_path,
            "c_cross",
            cluster_scenarios,
            attempt_id=attempt["attempt_id"],
            progress_ids=progress_ids,
            passed_ids=outcomes["passed"],
            fingerprints=fingerprints,
            changed_files=args.changed_file,
            repair_kind=args.repair_kind,
        )
    else:
        full_scope = matrix.get("mode") == "full" and matrix.get("scope", "all") == "all"
        queue_phase = repair_work_queue.sync_tasks(
            queue_path,
            "c_cross",
            outcomes["passed"] | outcomes["failed"] | outcomes["not_run"],
            passed_ids=outcomes["passed"],
            full_confirmation_id=(
                attempt["attempt_id"]
                if full_scope and args.attempt_kind == "confirmation"
                else None
            ),
            fingerprints=fingerprints,
        )
    convergence = convergence_status(matrix, attempts_after, queue_phase)
    matrix["convergence"] = convergence
    _write_failure_summary(matrix, c_cross, attempts_after, queue_phase)
    _write_json(out / "c-cross" / "checkpoints" / f"{execution_id}.json", matrix)
    _write_json(matrix_path, matrix)
    counts = matrix["summary"]["rust_impl_c_test"]
    print("VERIFY_RUST_WITH_C_TESTS: MATRIX_WRITTEN")
    print(f"mapped_scenarios={matrix['total_scenarios']}")
    print(f"policy={matrix['policy']}")
    print("rust_impl_c_test=" + ",".join(f"{key}:{value}" for key, value in sorted(counts.items())))
    print(f"stage_result={matrix['stage_result']}")
    print(f"verification_result={matrix['verification_result']}")
    print(f"convergence_status={convergence['status']}")
    queue_summary = convergence.get("work_queue", {})
    print(f"repair_queue_pending={len(queue_summary.get('pending_task_ids', []))}")
    if not _has_complete_attempt_evidence(matrix, root):
        return 1
    return 1 if convergence["status"] == "repair_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
