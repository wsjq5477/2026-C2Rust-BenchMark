#!/usr/bin/env python3
"""Run cargo verification commands and capture logs for staged gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import test_failure_triage


MAX_TEST_REPAIR_ATTEMPTS = 2
MAX_TEST_REPAIR_CHANGED_FILES = 4
TEST_RESULT_PATTERN = re.compile(
    r"^test\s+(?P<name>\S.*?)\s+\.\.\.\s+(?P<status>ok|FAILED|ignored)\s*$",
    re.MULTILINE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_input_manifest(project: Path, out: Path) -> dict[str, str]:
    project = project.resolve()
    root = out.resolve().parent.parent if out.name == "trace" and out.parent.name == "logs" else out.resolve().parent
    files: set[Path] = set()
    for directory_name in ("src", "tests"):
        directory = project / directory_name
        if directory.is_dir():
            files.update(path for path in directory.rglob("*") if path.is_file() and not path.is_symlink())
    for filename in ("Cargo.toml", "Cargo.lock"):
        path = project / filename
        if path.is_file() and not path.is_symlink():
            files.add(path)
    mapping = out / "rust_test_mapping.json"
    if mapping.is_file() and not mapping.is_symlink():
        files.add(mapping.resolve())
    manifest: dict[str, str] = {}
    for path in sorted(files):
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path.relative_to(project)
            key = f"flashDB_rust/{relative.as_posix()}"
        else:
            key = relative.as_posix()
        manifest[key] = _sha256(path)
    return manifest


def _read_attempts(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _changed_files(before: dict[str, Any], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def prepare_test_attempt(project: Path, out: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    attempts_path = out / "test-repair-attempts.jsonl"
    attempts = _read_attempts(attempts_path)
    manifest = test_input_manifest(project, out)
    previous_manifest = attempts[-1].get("source_manifest") if attempts else None
    changed = _changed_files(previous_manifest, manifest) if isinstance(previous_manifest, dict) else []
    repairs_used = sum(row.get("kind") == "repair" for row in attempts)
    kind = "checkpoint" if not attempts else "repair" if changed else "verification"
    if kind == "repair" and repairs_used >= MAX_TEST_REPAIR_ATTEMPTS:
        raise ValueError("test repair budget is exhausted; do not modify another version after failed_final")
    if kind == "repair" and len(changed) > MAX_TEST_REPAIR_CHANGED_FILES:
        raise ValueError(
            f"one test repair may change at most {MAX_TEST_REPAIR_CHANGED_FILES} tracked files; observed: "
            + ", ".join(changed)
        )
    return attempts, {
        "attempt_id": f"test-{time.time_ns()}",
        "kind": kind,
        "changed_files": changed,
        "source_manifest": manifest,
        "repair_attempts_used": repairs_used + (1 if kind == "repair" else 0),
        "max_repair_attempts": MAX_TEST_REPAIR_ATTEMPTS,
    }


def _append_attempt(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def record_placeholder_attempt(
    project: Path,
    out: Path,
    placeholder_report: dict[str, Any],
) -> dict[str, Any]:
    _, attempt = prepare_test_attempt(project, out)
    attempt["phase"] = "placeholder"
    attempt["placeholder_status"] = placeholder_report.get("status")
    attempt["placeholder_input_fingerprint"] = placeholder_report.get("input_fingerprint")
    repairs_used = int(attempt["repair_attempts_used"])
    if placeholder_report.get("status") == "pass":
        status, next_action = "ready_for_cargo", "run_cargo_capture"
    elif repairs_used >= MAX_TEST_REPAIR_ATTEMPTS:
        status, next_action = "failed_final", "capture_final_cargo_diagnostics"
    else:
        status, next_action = "repair_required", "return_to_test_migrator"
    attempt["stage_status"] = status
    _append_attempt(out / "test-repair-attempts.jsonl", attempt)
    convergence = {
        "status": status,
        "terminal": status == "failed_final",
        "next_action": next_action,
        "attempt_id": attempt["attempt_id"],
        "repair_attempts_used": repairs_used,
        "max_repair_attempts": MAX_TEST_REPAIR_ATTEMPTS,
        "remaining_repair_attempts": max(0, MAX_TEST_REPAIR_ATTEMPTS - repairs_used),
        "source_manifest": attempt["source_manifest"],
        "placeholder_status": placeholder_report.get("status"),
        "placeholder_input_fingerprint": placeholder_report.get("input_fingerprint"),
    }
    (out / "test-placeholder-convergence.json").write_text(
        json.dumps(convergence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return convergence


def validate_placeholder_precondition(project: Path, out: Path) -> dict[str, Any]:
    try:
        import placeholder_check

        expected = placeholder_check.analyze_placeholders(
            out.resolve().parent.parent,
            project.resolve() / "tests",
            out.resolve() / "rust_test_mapping.json",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"placeholder evidence could not be recomputed: {exc}") from exc
    try:
        persisted = json.loads((out / "test-placeholder-check.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError("fresh test-placeholder-check.json is required before Cargo") from exc
    keys = ("status", "issue_count", "input_fingerprint")
    if not isinstance(persisted, dict) or any(persisted.get(key) != expected.get(key) for key in keys):
        raise ValueError("test-placeholder-check.json is stale or inconsistent with current tests")
    attempts = _read_attempts(out / "test-repair-attempts.jsonl")
    repairs_used = sum(row.get("kind") == "repair" for row in attempts)
    if expected.get("status") != "pass" and repairs_used < MAX_TEST_REPAIR_ATTEMPTS:
        raise ValueError(
            "placeholder convergence is repair_required; return to test-migrator before Cargo"
        )
    return {
        "status": expected.get("status"),
        "repair_attempts_used": repairs_used,
        "failed_final": expected.get("status") != "pass" and repairs_used >= MAX_TEST_REPAIR_ATTEMPTS,
    }


def analyze_test_execution(project: Path, out: Path, output: str, returncode: int) -> dict[str, Any]:
    mapping_path = out / "rust_test_mapping.json"
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        mapping = {}
    except json.JSONDecodeError:
        mapping = {}
    scenarios = mapping.get("scenarios") if isinstance(mapping, dict) else None
    rows = [row for row in scenarios if isinstance(row, dict)] if isinstance(scenarios, list) else []
    expected_tests: list[str] = []
    invalid_mappings: list[str] = []
    missing_test_files: list[str] = []
    tests_root = (project.resolve() / "tests").resolve()
    for index, row in enumerate(rows):
        rust_test = row.get("rust_test")
        rust_file = row.get("rust_file")
        scenario_id = str(row.get("id") or f"mapping[{index}]")
        if not isinstance(rust_test, str) or not rust_test:
            invalid_mappings.append(f"{scenario_id}: missing rust_test")
        else:
            expected_tests.append(rust_test)
        if not isinstance(rust_file, str) or not rust_file:
            invalid_mappings.append(f"{scenario_id}: missing rust_file")
            continue
        relative = Path(rust_file)
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 3 or relative.parts[:2] != ("flashDB_rust", "tests"):
            invalid_mappings.append(f"{scenario_id}: rust_file must stay under flashDB_rust/tests/")
            continue
        unresolved_candidate = project.resolve().parent / relative
        candidate = unresolved_candidate.resolve()
        if tests_root not in candidate.parents or not candidate.is_file() or unresolved_candidate.is_symlink():
            missing_test_files.append(rust_file)

    duplicate_expected = sorted({name for name in expected_tests if expected_tests.count(name) > 1})
    if duplicate_expected:
        invalid_mappings.append("duplicate rust_test values: " + ", ".join(duplicate_expected))

    test_files = sorted(
        f"flashDB_rust/tests/{path.relative_to(tests_root).as_posix()}"
        for path in tests_root.rglob("*.rs")
        if path.is_file() and not path.is_symlink()
    ) if tests_root.is_dir() else []
    executions = [
        {"name": match.group("name"), "status": match.group("status")}
        for match in TEST_RESULT_PATTERN.finditer(output)
    ]
    executed_names = [row["name"] for row in executions]

    def matching_statuses(expected: str) -> list[str]:
        return [
            str(row["status"])
            for row in executions
            if row["name"] == expected or row["name"].endswith(f"::{expected}")
        ]

    missing_expected = sorted({name for name in expected_tests if not matching_statuses(name)})
    ignored_expected = sorted({name for name in expected_tests if "ignored" in matching_statuses(name)})
    failed_expected = sorted({name for name in expected_tests if "FAILED" in matching_statuses(name)})
    reasons: list[str] = []
    if not rows:
        reasons.append("rust_test_mapping.json contains no dynamic scenarios")
    if invalid_mappings:
        reasons.append("invalid Rust test mappings")
    if not test_files:
        reasons.append("flashDB_rust/tests contains no Rust test files")
    if missing_test_files:
        reasons.append("mapped Rust test files are missing")
    if not executions:
        reasons.append("cargo test executed zero tests")
    if missing_expected:
        reasons.append("mapped Rust tests were not executed")
    if ignored_expected:
        reasons.append("mapped Rust tests were ignored")
    if failed_expected:
        reasons.append("mapped Rust tests failed")
    if returncode != 0:
        reasons.append(f"cargo test exited with {returncode}")
    status = "pass" if not reasons else "fail"
    return {
        "status": status,
        "reason": "; ".join(reasons) if reasons else "every dynamically mapped Rust test executed",
        "expected_count": len(expected_tests),
        "executed_count": len(executions),
        "matched_expected_count": len(expected_tests) - len(missing_expected),
        "expected_tests": expected_tests,
        "executed_tests": executed_names,
        "missing_expected_tests": missing_expected,
        "ignored_expected_tests": ignored_expected,
        "failed_expected_tests": failed_expected,
        "invalid_mappings": invalid_mappings,
        "missing_test_files": sorted(set(missing_test_files)),
        "test_files": test_files,
    }


def run_command(project: Path, command: list[str], log_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=project,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {"command": command, "returncode": completed.returncode, "log": log_path.name}


def capture(project: Path, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    placeholder_precondition = validate_placeholder_precondition(project, out)
    _, attempt = prepare_test_attempt(project, out)
    results = {
        "build": run_command(project, ["cargo", "build"], out / "cargo-build.log"),
        "test": run_command(project, ["cargo", "test"], out / "cargo-test.log"),
        "fmt": run_command(project, ["cargo", "fmt", "--check"], out / "cargo-fmt.log"),
    }
    results["placeholder_precondition"] = placeholder_precondition
    results["build_status"] = "pass" if results["build"]["returncode"] == 0 else "fail"
    test_output = (out / "cargo-test.log").read_text(encoding="utf-8", errors="replace")
    results["test_execution"] = analyze_test_execution(
        project,
        out,
        test_output,
        int(results["test"]["returncode"]),
    )
    results["test_execution"]["log_sha256"] = _sha256(out / "cargo-test.log")
    results["test_status"] = results["test_execution"]["status"]
    results["fmt_status"] = "pass" if results["fmt"]["returncode"] == 0 else "fail"
    if results["test_status"] == "fail":
        root = out.parent.parent if out.name == "trace" and out.parent.name == "logs" else out.parent
        results["test_failure_triage"] = test_failure_triage.write_triage(root, out, replace=True)
    # Cargo may create Cargo.lock during the first real build.  Persist the
    # post-command manifest so freshness checks do not mistake that owned
    # build artifact for an unrecorded repair.
    attempt["source_manifest"] = test_input_manifest(project, out)
    attempt["build_status"] = results["build_status"]
    attempt["test_status"] = results["test_status"]
    attempt["test_execution_status"] = results["test_execution"]["status"]
    attempt["cargo_test_log_sha256"] = results["test_execution"]["log_sha256"]
    attempt["result"] = "pass" if results["build_status"] == "pass" and results["test_status"] == "pass" else "repair_required"
    _append_attempt(out / "test-repair-attempts.jsonl", attempt)
    results["repair_convergence"] = {
        "attempt_id": attempt["attempt_id"],
        "kind": attempt["kind"],
        "repair_attempts_used": attempt["repair_attempts_used"],
        "max_repair_attempts": attempt["max_repair_attempts"],
        "remaining_repair_attempts": max(0, MAX_TEST_REPAIR_ATTEMPTS - attempt["repair_attempts_used"]),
        "source_manifest": attempt["source_manifest"],
        "test_execution_status": attempt["test_execution_status"],
        "cargo_test_log_sha256": attempt["cargo_test_log_sha256"],
    }
    (out / "cargo-results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run cargo build/test/fmt and capture logs.")
    parser.add_argument("--project", required=True, help="Path to flashDB_rust.")
    parser.add_argument("--out", required=True, help="Output logs/trace directory.")
    args = parser.parse_args(argv)

    try:
        results = capture(Path(args.project), Path(args.out))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BUILD_TEST_REPAIR: REFUSED: {exc}")
        return 2
    print("BUILD_TEST_REPAIR: CARGO_CAPTURED")
    print(f"build_status={results['build_status']}")
    print(f"test_status={results['test_status']}")
    execution = results["test_execution"]
    print(f"mapped_tests_executed={execution['matched_expected_count']}/{execution['expected_count']}")
    if execution["status"] != "pass":
        print(f"test_execution_reason={execution['reason']}")
    if "test_failure_triage" in results:
        triage = results["test_failure_triage"]
        if triage.get("status") == "written":
            print("TEST_FAILURE_TRIAGE: WRITTEN")
            print(f"failure_count={triage['failure_count']}")
            print("classifications=" + json.dumps(triage["classifications"], sort_keys=True))
            print(f"allow_src_edit={str(triage['allow_src_edit']).lower()}")
    return 0 if results["build_status"] == "pass" and results["test_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
