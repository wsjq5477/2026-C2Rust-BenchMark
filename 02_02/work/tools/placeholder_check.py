#!/usr/bin/env python3
"""Detect deterministic placeholder patterns in mapped Rust tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import contest_guard


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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def c_source_fingerprint(root: Path) -> dict[str, str]:
    trace = root / "logs" / "trace"
    try:
        model = load_json(trace / "c_test_model.json")
        manifest = load_json(trace / "input_manifest.json")
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return {}
    source_root = Path(manifest.get("source_root", root)).resolve() if isinstance(manifest.get("source_root"), str) else root.resolve()
    cases = model.get("scorer_standard_cases")
    files = {
        item.get("source_file")
        for item in cases
        if isinstance(item, dict) and isinstance(item.get("source_file"), str) and item["source_file"]
    } if isinstance(cases, list) else set()
    result: dict[str, str] = {}
    for value in sorted(files):
        path = Path(value)
        path = path.resolve() if path.is_absolute() else (source_root / path).resolve()
        if path.is_file():
            result[relative_path(root, path)] = file_sha256(path)
    return result


def input_fingerprint(root: Path, tests: Path, mapping_path: Path) -> dict[str, Any]:
    files = sorted(tests.rglob("*.rs")) if tests.is_dir() else []
    trace = root / "logs" / "trace"
    c_model = trace / "c_test_model.json"
    design = trace / "rust_api_design.json"
    return {
        "c_test_model_sha256": file_sha256(c_model) if c_model.is_file() else "missing",
        "rust_api_design_sha256": file_sha256(design) if design.is_file() else "missing",
        "rust_test_mapping_sha256": file_sha256(mapping_path) if mapping_path.is_file() else "missing",
        "c_source_files": c_source_fingerprint(root),
        "rust_test_files": {
            relative_path(root, path): file_sha256(path)
            for path in files
        },
    }


def issue(
    issues: list[dict[str, Any]],
    code: str,
    file: str,
    test_name: str | None,
    message: str,
    scenario_id: str | None = None,
) -> None:
    issues.append({"code": code, "file": file, "test_name": test_name, "scenario_id": scenario_id, "message": message})


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
    fingerprint = input_fingerprint(root, tests, mapping_path)
    try:
        mapping = load_json(mapping_path)
    except FileNotFoundError:
        return {
            "stage": "PLACEHOLDER_CHECK",
            "status": "fail",
            "issue_count": 1,
            "issues": [{
                "code": "missing_mapping",
                "file": str(mapping_path),
                "test_name": None,
                "message": "missing rust_test_mapping.json",
            }],
            "input_fingerprint": fingerprint,
        }
    except json.JSONDecodeError as exc:
        return {
            "stage": "PLACEHOLDER_CHECK",
            "status": "fail",
            "issue_count": 1,
            "issues": [{
                "code": "invalid_mapping",
                "file": str(mapping_path),
                "test_name": None,
                "message": f"invalid rust_test_mapping.json: {exc}",
            }],
            "input_fingerprint": fingerprint,
        }
    scenarios = mapping.get("scenarios", [])
    issues: list[dict[str, Any]] = []

    files = sorted(tests.rglob("*.rs")) if tests.is_dir() else []
    if not files:
        issue(issues, "empty_test_directory", relative_path(root, tests), None, "flashDB_rust/tests contains no Rust test files")
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
    elif not scenarios:
        issue(issues, "empty_mapping", str(mapping_path), None, "scenarios must contain dynamically mapped Rust tests")
    cache: dict[Path, str] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("id", "<unknown>"))
        rust_file = scenario.get("rust_file")
        rust_test = scenario.get("rust_test")
        if not isinstance(rust_file, str) or not isinstance(rust_test, str):
            issue(issues, "incomplete_mapping", str(mapping_path), None, "rust_file and rust_test are required", scenario_id)
            continue
        path = root / rust_file.removeprefix("./")
        if not path.is_file():
            issue(issues, "missing_test_file", rust_file, rust_test, "mapped Rust test file does not exist", scenario_id)
            continue
        text = cache.setdefault(path, path.read_text(encoding="utf-8", errors="ignore"))
        names = set(TEST_FN.findall(text))
        if rust_test not in names:
            issue(issues, "missing_test_function", rust_file, rust_test, "mapped #[test] function does not exist", scenario_id)
            continue
        body = test_body(text, rust_test)
        if body is not None and not ASSERTION.search(body):
            issue(issues, "missing_assertion", rust_file, rust_test, "mapped test has no assertion macro", scenario_id)

    rendered_scenarios: list[dict[str, Any]] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict) or not isinstance(scenario.get("id"), str):
            continue
        scenario_id = scenario["id"]
        rust_file = scenario.get("rust_file")
        rust_test = scenario.get("rust_test")
        case_issues = [
            item["code"]
            for item in issues
            if item.get("scenario_id") == scenario_id
            or (
                item.get("scenario_id") is None
                and (
                    item.get("file") == rust_file
                    or (isinstance(rust_test, str) and item.get("test_name") == rust_test)
                    or item.get("code") in {"empty_test_directory", "invalid_mapping", "empty_mapping"}
                )
            )
        ]
        rendered_scenarios.append({
            "scenario_id": scenario_id,
            "status": "pass" if not case_issues else "fail",
            "issue_codes": sorted(set(case_issues)),
        })

    return {
        "stage": "PLACEHOLDER_CHECK",
        "status": "pass" if not issues else "fail",
        "issue_count": len(issues),
        "issues": issues,
        "scenarios": rendered_scenarios,
        "input_fingerprint": fingerprint,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check mapped Rust tests for deterministic placeholders.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--tests", default="flashDB_rust/tests")
    parser.add_argument("--mapping", default="logs/trace/rust_test_mapping.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        contest_guard.guard_mutation_allowed(Path(args.root))
    except RuntimeError as exc:
        print(str(exc))
        return contest_guard.FINALIZE_EXIT_CODE
    report = analyze_placeholders(Path(args.root), Path(args.tests), Path(args.mapping))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        import cargo_capture

        convergence = cargo_capture.record_placeholder_attempt(
            Path(args.root) / "flashDB_rust",
            output.parent,
            report,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PLACEHOLDER_CONVERGENCE: REFUSED: {exc}")
        return 2
    print(f"PLACEHOLDER_CHECK: {report['status'].upper()}")
    print(f"issues={report['issue_count']}")
    print(f"convergence_status={convergence['status']}")
    print(f"repair_queue_pending={len(convergence.get('work_queue', {}).get('pending_task_ids', []))}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
