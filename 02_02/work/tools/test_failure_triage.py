#!/usr/bin/env python3
"""Classify the first cargo test failure before BUILD_TEST_REPAIR edits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ASSERTION_RE = re.compile(r"assertion `(?P<left>[^`]+)` failed")
TEST_RE = re.compile(r"^---- (?P<test>[A-Za-z0-9_:]+) stdout ----$")
PANIC_RE = re.compile(r"thread '[^']+' .*panicked at (?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):")
COMPILER_LOCATION_RE = re.compile(r"^\s*-->\s+(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)", re.MULTILINE)
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
    match = PANIC_RE.search(log) or COMPILER_LOCATION_RE.search(log)
    if not match:
        return None, None
    try:
        line = int(match.group("line"))
    except ValueError:
        line = None
    return match.group("file"), line


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rust_source_scope(path: str | None) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    normalized = path.replace("\\", "/")
    marker = "/flashDB_rust/src/"
    if marker in normalized:
        return "flashDB_rust/src/" + normalized.split(marker, 1)[1]
    if normalized.startswith("flashDB_rust/src/"):
        return normalized
    if normalized.startswith("src/"):
        return "flashDB_rust/" + normalized
    return None


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
            ["flashDB_rust/tests/**", "logs/trace/rust_test_mapping.json"],
            "resolve test integration or public API mismatch before semantic repair",
        )
    if "assertion `left == right` failed" in log or "assertion failed:" in log:
        return (
            "test_oracle_suspect",
            False,
            ["flashDB_rust/tests/**", "logs/trace/rust_test_mapping.json"],
            "verify expected value provenance before editing implementation",
        )
    if "called `Result::unwrap()` on an `Err` value" in log or "panicked at" in log:
        return (
            "harness_suspect",
            False,
            ["flashDB_rust/tests/**", "logs/trace/rust_test_mapping.json"],
            "check setup, harness, and API integration before core semantic repair",
        )
    return (
        "insufficient_evidence",
        False,
        ["logs/trace/**"],
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
    source_scope = rust_source_scope(failure_file)
    if source_scope and (COMPILE_ERROR_RE.search(log) or "panicked at" in log):
        classification = "rust_impl_suspect"
        allow_src_edit = True
        allowed_edit_scope = [source_scope]
        next_action = "repair the evidenced Rust source location, then rerun cargo and C-cross confirmation"

    evidence_paths = ["logs/trace/cargo-test.log"]
    for name in ["rust_test_mapping.json", "validation-matrix.json", "c_test_model.json"]:
        if (out / name).exists():
            evidence_paths.append(f"logs/trace/{name}")

    record: dict[str, Any] = {
        "schema_version": 1,
        "generator": "test_failure_triage.py",
        "cargo_test_sha256": file_sha256(log_path),
        "cargo_results_sha256": file_sha256(out / "cargo-results.json"),
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


def write_triage(root: Path, out: Path, *, replace: bool = False) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    record = build_record(root, out)
    triage_path = out / "test-failure-triage.jsonl"
    with triage_path.open("w" if replace else "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify the first cargo test failure before repair.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--out", required=True, help="logs/trace directory.")
    parser.add_argument("--replace", action="store_true", help="Replace stale triage with one current record.")
    args = parser.parse_args(argv)

    record = write_triage(Path(args.root), Path(args.out), replace=args.replace)
    print("TEST_FAILURE_TRIAGE: WRITTEN")
    print(f"classification={record['classification']}")
    print(f"allow_src_edit={str(record['allow_src_edit']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
