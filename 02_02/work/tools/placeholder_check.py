#!/usr/bin/env python3
"""Detect deterministic placeholder patterns in mapped Rust tests."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


MARKERS = ("MIGRATION_PENDING", "PLACEHOLDER", "replace baseline coverage", "dummy test")
FORBIDDEN_MACROS = re.compile(r"\b(?:todo|unimplemented)!\s*\(")
TRIVIAL_ASSERTIONS = (
    re.compile(r"\bassert!\s*\(\s*true\s*\)"),
    re.compile(r"\bassert_eq!\s*\(\s*([^,()]+)\s*,\s*\1\s*\)"),
    re.compile(r"\bassert_ne!\s*\(\s*1\s*,\s*0\s*\)"),
    re.compile(r'''\bassert!\s*\(\s*!\s*["'][^"']*["']\.is_empty\s*\(\s*\)\s*\)'''),
)
TEST_FN = re.compile(r"#\s*\[\s*test\s*\]\s*(?:#\s*\[[^]]+\]\s*)*fn\s+([A-Za-z_][A-Za-z0-9_]*)")
ASSERTION = re.compile(r"\b(?:assert|assert_eq|assert_ne|debug_assert|debug_assert_eq|debug_assert_ne)!\s*\(")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def issue(issues: list[dict[str, Any]], code: str, file: str, test_name: str | None, message: str) -> None:
    issues.append({"code": code, "file": file, "test_name": test_name, "message": message})


def test_body(text: str, test_name: str) -> str | None:
    start = re.search(r"#\s*\[\s*test\s*\][\s\S]*?fn\s+" + re.escape(test_name) + r"\s*\([^)]*\)\s*\{", text)
    if not start:
        return None
    depth = 1
    cursor = start.end()
    while cursor < len(text) and depth:
        depth += (text[cursor] == "{") - (text[cursor] == "}")
        cursor += 1
    return text[start.end() : cursor - 1] if depth == 0 else None


def analyze_placeholders(root: Path, tests: Path, mapping_path: Path) -> dict[str, Any]:
    root = root.resolve()
    tests = tests if tests.is_absolute() else root / tests
    mapping_path = mapping_path if mapping_path.is_absolute() else root / mapping_path
    mapping = load_json(mapping_path)
    scenarios = mapping.get("scenarios", [])
    issues: list[dict[str, Any]] = []

    files = sorted(tests.rglob("*.rs")) if tests.is_dir() else []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        for marker in MARKERS:
            if marker.lower() in text.lower():
                issue(issues, "placeholder_marker", rel, None, f"found placeholder marker: {marker}")
        if FORBIDDEN_MACROS.search(text):
            issue(issues, "pending_macro", rel, None, "found todo!() or unimplemented!()")
        if re.search(r"#\s*\[\s*ignore(?:\s*=\s*[^]]+)?\s*\]", text):
            issue(issues, "ignored_test", rel, None, "mapped Rust tests must not be ignored")
        for pattern in TRIVIAL_ASSERTIONS:
            if pattern.search(text):
                issue(issues, "trivial_assertion", rel, None, "found a deterministic constant-only assertion")

    if not isinstance(scenarios, list):
        issue(issues, "invalid_mapping", str(mapping_path), None, "scenarios must be a list")
        scenarios = []
    cache: dict[Path, str] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("id", "<unknown>"))
        rust_file = scenario.get("rust_file")
        rust_test = scenario.get("rust_test")
        if scenario.get("implementation_status") != "implemented" and scenario.get("implementation_status") != "validated":
            issue(issues, "implementation_pending", str(rust_file or mapping_path), str(rust_test or scenario_id), "mapped test is not implemented")
        if not isinstance(rust_file, str) or not isinstance(rust_test, str):
            issue(issues, "incomplete_mapping", str(mapping_path), scenario_id, "rust_file and rust_test are required")
            continue
        path = root / rust_file.removeprefix("./")
        if not path.is_file():
            issue(issues, "missing_test_file", rust_file, rust_test, "mapped Rust test file does not exist")
            continue
        text = cache.setdefault(path, path.read_text(encoding="utf-8", errors="ignore"))
        names = set(TEST_FN.findall(text))
        if rust_test not in names:
            issue(issues, "missing_test_function", rust_file, rust_test, "mapped #[test] function does not exist")
            continue
        body = test_body(text, rust_test)
        if body is not None and not ASSERTION.search(body):
            issue(issues, "missing_assertion", rust_file, rust_test, "mapped test has no assertion macro")

    return {"stage": "PLACEHOLDER_CHECK", "status": "pass" if not issues else "fail", "issue_count": len(issues), "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check mapped Rust tests for deterministic placeholders.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--tests", default="flashDB_rust/tests")
    parser.add_argument("--mapping", default="logs/trace/rust_test_mapping.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = analyze_placeholders(Path(args.root), Path(args.tests), Path(args.mapping))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PLACEHOLDER_CHECK: {report['status'].upper()}")
    print(f"issues={report['issue_count']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
