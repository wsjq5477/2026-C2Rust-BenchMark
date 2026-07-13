#!/usr/bin/env python3
"""Classify the first cargo test failure before BUILD_TEST_REPAIR edits."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ASSERTION_RE = re.compile(r"assertion `(?P<left>[^`]+)` failed")
TEST_RE = re.compile(r"^---- (?P<test>[A-Za-z0-9_:]+) stdout ----$")
PANIC_RE = re.compile(r"thread '[^']+' .*panicked at (?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):")
COMPILE_ERROR_RE = re.compile(r"^error\[E[0-9]+\]: (?P<message>.+)$", re.MULTILINE)
LEFT_RIGHT_RE = re.compile(r"left: (?P<left>.+)\s+right: (?P<right>.+)", re.DOTALL)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def find_first_failed_test(log: str) -> str:
    for line in log.splitlines():
        match = TEST_RE.match(line.strip())
        if match:
            return match.group("test").split("::")[-1]
    match = re.search(r"failures:\s*\n\s*(?P<test>[A-Za-z0-9_:]+)", log)
    if match:
        return match.group("test").split("::")[-1]
    return "unknown"


def find_failure_location(log: str) -> tuple[str | None, int | None]:
    match = PANIC_RE.search(log)
    if not match:
        return None, None
    try:
        line = int(match.group("line"))
    except ValueError:
        line = None
    return match.group("file"), line


def find_assertion(log: str) -> str | None:
    match = ASSERTION_RE.search(log)
    if match:
        return match.group("left")
    return None


def find_expected_actual(log: str) -> tuple[Any, Any]:
    match = LEFT_RIGHT_RE.search(log)
    if not match:
        return None, None
    left = match.group("left").splitlines()[0].strip()
    right = match.group("right").splitlines()[0].strip()
    return right, left


def classify(log: str) -> tuple[str, bool, list[str], str]:
    if COMPILE_ERROR_RE.search(log):
        return (
            "harness_suspect",
            False,
            ["flashDB_rust/tests", "flashDB_rust/src"],
            "resolve test integration or public API mismatch before semantic repair",
        )
    if "assertion `left == right` failed" in log or "assertion failed:" in log:
        return (
            "test_oracle_suspect",
            False,
            ["flashDB_rust/tests", "logs/trace/rust_test_mapping.json"],
            "verify expected value provenance before editing implementation",
        )
    if "called `Result::unwrap()` on an `Err` value" in log or "panicked at" in log:
        return (
            "harness_suspect",
            False,
            ["flashDB_rust/tests", "flashDB_rust/src"],
            "check setup, harness, and API integration before core semantic repair",
        )
    return (
        "insufficient_evidence",
        False,
        ["logs/trace"],
        "collect a narrower failing test log and C evidence before repair",
    )


def build_record(root: Path, out: Path) -> dict[str, Any]:
    log_path = out / "cargo-test.log"
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    failed_test = find_first_failed_test(log)
    failure_file, failure_line = find_failure_location(log)
    assertion = find_assertion(log)
    expected, actual = find_expected_actual(log)
    classification, allow_src_edit, allowed_edit_scope, next_action = classify(log)

    evidence_paths = ["logs/trace/cargo-test.log"]
    for name in ["rust_test_mapping.json", "validation-matrix.json", "c_test_model.json"]:
        if (out / name).exists():
            evidence_paths.append(f"logs/trace/{name}")

    record: dict[str, Any] = {
        "failed_test": failed_test,
        "failure_kind": "assertion_mismatch" if classification == "test_oracle_suspect" else "cargo_test_failure",
        "classification": classification,
        "assertion": assertion,
        "expected": expected,
        "actual": actual,
        "failure_file": failure_file,
        "failure_line": failure_line,
        "evidence_paths": evidence_paths,
        "allowed_edit_scope": allowed_edit_scope,
        "allow_src_edit": allow_src_edit,
        "next_action": next_action,
    }
    return record


def update_state(out: Path) -> None:
    state_path = out / "workflow_state.json"
    state = load_json(state_path)
    state["test_failure_triage_required"] = True
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_triage(root: Path, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    record = build_record(root, out)
    triage_path = out / "test-failure-triage.jsonl"
    with triage_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    update_state(out)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify the first cargo test failure before repair.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--out", required=True, help="logs/trace directory.")
    args = parser.parse_args(argv)

    record = write_triage(Path(args.root), Path(args.out))
    print("TEST_FAILURE_TRIAGE: WRITTEN")
    print(f"classification={record['classification']}")
    print(f"allow_src_edit={str(record['allow_src_edit']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
