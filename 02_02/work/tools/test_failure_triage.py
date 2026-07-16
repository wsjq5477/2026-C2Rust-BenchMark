#!/usr/bin/env python3
"""Extract every cargo test failure without guessing assertion provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


TEST_RE = re.compile(r"^---- (?P<test>[A-Za-z0-9_:]+) stdout ----$", re.MULTILINE)
PANIC_RE = re.compile(r"thread '[^']+' .*panicked at (?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):")
COMPILER_LOCATION_RE = re.compile(r"^\s*-->\s+(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)", re.MULTILINE)
COMPILE_ERROR_RE = re.compile(r"^error(?:\[E[0-9]+\])?: (?P<message>.+)$", re.MULTILINE)
ASSERTION_RE = re.compile(r"assertion(?: `(?P<kind>[^`]+)`)? failed(?::\s*(?P<expr>.+))?")
LEFT_RIGHT_RE = re.compile(r"left: (?P<left>.+)\s+right: (?P<right>.+)", re.DOTALL)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def find_failed_tests(log: str) -> list[str]:
    names = [match.group("test").split("::")[-1] for match in TEST_RE.finditer(log)]
    if names:
        return _unique(names)
    match = re.search(r"(?:^|\n)failures:\s*\n(?P<body>(?:\s+[A-Za-z0-9_:]+\s*\n)+)", log)
    if not match:
        return []
    return _unique([
        line.strip().split("::")[-1]
        for line in match.group("body").splitlines()
        if line.strip()
    ])


def failure_sections(log: str) -> dict[str, str]:
    matches = list(TEST_RE.finditer(log))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(log)
        body = log[match.end():end]
        failures_offset = body.find("\nfailures:")
        if failures_offset >= 0:
            body = body[:failures_offset]
        sections[match.group("test").split("::")[-1]] = body
    return sections


def find_failure_location(text: str) -> tuple[str | None, int | None]:
    match = PANIC_RE.search(text) or COMPILER_LOCATION_RE.search(text)
    if not match:
        return None, None
    return match.group("file"), int(match.group("line"))


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


def find_assertion(text: str) -> str | None:
    match = ASSERTION_RE.search(text)
    if not match:
        return None
    return match.group("expr") or match.group("kind") or "assertion failed"


def find_expected_actual(text: str) -> tuple[Any, Any]:
    match = LEFT_RIGHT_RE.search(text)
    if not match:
        return None, None
    left = match.group("left").splitlines()[0].strip()
    right = match.group("right").splitlines()[0].strip()
    return right, left


def mapping_by_test(out: Path) -> dict[str, dict[str, Any]]:
    mapping = load_json(out / "rust_test_mapping.json")
    scenarios = mapping.get("scenarios")
    if not isinstance(scenarios, list):
        return {}
    return {
        item["rust_test"]: item
        for item in scenarios
        if isinstance(item, dict) and isinstance(item.get("rust_test"), str)
    }


def classify_failure(text: str, failure_file: str | None) -> tuple[str, bool, list[str], str]:
    source_scope = rust_source_scope(failure_file)
    if source_scope:
        return (
            "rust_impl_suspect",
            True,
            [source_scope],
            "repair the evidenced Rust source location, then rerun cargo and final C-cross",
        )
    if COMPILE_ERROR_RE.search(text):
        return (
            "harness_suspect",
            False,
            [],
            "resolve the evidenced test or integration compile error before semantic review",
        )
    if ASSERTION_RE.search(text):
        return (
            "insufficient_evidence",
            False,
            [],
            "compare the mapped C test/helper and Rust test before choosing test_oracle_suspect or rust_impl_suspect",
        )
    return (
        "insufficient_evidence",
        False,
        [],
        "inspect the mapped setup, lifecycle, and implementation evidence before editing",
    )


def evidence_paths(out: Path) -> list[str]:
    names = [
        "cargo-test.log",
        "rust_test_mapping.json",
        "validation-matrix.json",
        "c_test_model.json",
        "test-semantic-review.json",
        "test-consistency.json",
    ]
    return [f"logs/trace/{name}" for name in names if (out / name).exists()]


def build_records(root: Path, out: Path) -> list[dict[str, Any]]:
    log_path = out / "cargo-test.log"
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    sections = failure_sections(log)
    failed_tests = find_failed_tests(log)
    if not failed_tests and COMPILE_ERROR_RE.search(log):
        failed_tests = ["<compile>"]
    mappings = mapping_by_test(out)
    records: list[dict[str, Any]] = []
    for failed_test in failed_tests or ["unknown"]:
        text = sections.get(failed_test, log)
        failure_file, failure_line = find_failure_location(text)
        assertion = find_assertion(text)
        expected, actual = find_expected_actual(text)
        classification, allow_src_edit, allowed_edit_scope, next_action = classify_failure(text, failure_file)
        mapping = mappings.get(failed_test, {})
        rust_file = mapping.get("rust_file") if isinstance(mapping.get("rust_file"), str) else None
        inspection_scope = [value for value in [
            rust_file,
            mapping.get("source_file") if isinstance(mapping.get("source_file"), str) else None,
            "logs/trace/rust_test_mapping.json",
            "logs/trace/c_test_model.json",
            "logs/trace/test-semantic-review.json",
            "logs/trace/validation-matrix.json",
        ] if isinstance(value, str) and value]
        records.append({
            "schema_version": 2,
            "generator": "test_failure_triage.py",
            "cargo_test_sha256": file_sha256(log_path),
            "failed_test": failed_test,
            "scenario_id": mapping.get("id") if isinstance(mapping.get("id"), str) else None,
            "c_source_file": mapping.get("source_file") if isinstance(mapping.get("source_file"), str) else None,
            "required_c_tests": mapping.get("required_c_tests") if isinstance(mapping.get("required_c_tests"), list) else [],
            "failure_kind": "assertion_mismatch" if assertion else "cargo_test_failure",
            "classification": classification,
            "assertion": assertion,
            "expected": expected,
            "actual": actual,
            "failure_file": failure_file,
            "failure_line": failure_line,
            "evidence_paths": evidence_paths(out),
            "inspection_scope": _unique(inspection_scope),
            "allowed_edit_scope": allowed_edit_scope,
            "allow_src_edit": allow_src_edit,
            "next_action": next_action,
        })
    return records


def write_triage(root: Path, out: Path, *, replace: bool = False) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    records = build_records(root, out)
    triage_path = out / "test-failure-triage.jsonl"
    with triage_path.open("w" if replace else "a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    classifications = Counter(record["classification"] for record in records)
    return {
        "status": "written",
        "log": "test-failure-triage.jsonl",
        "failure_count": len(records),
        "classifications": dict(sorted(classifications.items())),
        "allow_src_edit": any(record["allow_src_edit"] for record in records),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract every cargo test failure before evidence-driven repair.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--out", required=True, help="logs/trace directory.")
    parser.add_argument("--replace", action="store_true", help="Replace stale triage with the current failure set.")
    args = parser.parse_args(argv)

    summary = write_triage(Path(args.root), Path(args.out), replace=args.replace)
    print("TEST_FAILURE_TRIAGE: WRITTEN")
    print(f"failure_count={summary['failure_count']}")
    print("classifications=" + json.dumps(summary["classifications"], sort_keys=True))
    print(f"allow_src_edit={str(summary['allow_src_edit']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
