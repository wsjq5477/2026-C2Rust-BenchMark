#!/usr/bin/env python3
"""Validate deterministic test structure and a read-only semantic review.

Semantic equivalence is reviewed by ``test-semantic-reviewer``.  This tool is
deliberately the fact checker: it verifies dynamic coverage, source evidence,
and freshness instead of trusting mapping self-declarations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import repair_work_queue
import contest_guard
import submission_snapshot


DIMENSIONS = ("scenario", "api", "data", "configuration", "lifecycle", "ordering", "assertion")
REVIEW_STATUSES = {"pass", "fail", "unresolved"}
REVIEWER_MODES = {"independent_subagent", "primary_readonly_fallback"}


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def resolve_root_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / value.removeprefix("./")).resolve()


def source_root(root: Path) -> Path:
    try:
        manifest = load_json(root / "logs" / "trace" / "input_manifest.json")
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return root.resolve()
    value = manifest.get("source_root")
    if isinstance(value, str) and value:
        return Path(value).resolve()
    return root.resolve()


def rust_test_paths(root: Path, mapping: dict[str, Any]) -> dict[str, Path]:
    values: set[str] = set()
    source_to_rust = mapping.get("source_to_rust")
    if isinstance(source_to_rust, dict):
        values.update(item for item in source_to_rust.values() if isinstance(item, str))
    scenarios = mapping.get("scenarios")
    if isinstance(scenarios, list):
        for item in scenarios:
            if isinstance(item, dict) and isinstance(item.get("rust_file"), str):
                values.add(item["rust_file"])
    paths: dict[str, Path] = {}
    for value in sorted(values):
        path = resolve_root_path(root, value)
        if path.is_file():
            paths[relative_path(root, path)] = path
    return paths


def c_source_paths(root: Path, cases: list[dict[str, Any]]) -> dict[str, Path]:
    base = source_root(root)
    paths: dict[str, Path] = {}
    for case in cases:
        value = case.get("source_file")
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        path = path.resolve() if path.is_absolute() else (base / value).resolve()
        if path.is_file():
            paths[relative_path(root, path)] = path
    return paths


def build_input_fingerprint(root: Path, test_model: dict[str, Any] | None = None, mapping: dict[str, Any] | None = None) -> dict[str, Any]:
    trace = root / "logs" / "trace"
    if test_model is None:
        test_model = load_json(trace / "c_test_model.json")
    if mapping is None:
        mapping = load_json(trace / "rust_test_mapping.json")
    cases = test_model.get("scorer_standard_cases")
    cases = [item for item in cases if isinstance(item, dict)] if isinstance(cases, list) else []
    design = trace / "rust_api_design.json"
    return {
        "c_test_model_sha256": file_sha256(trace / "c_test_model.json"),
        "rust_api_design_sha256": file_sha256(design) if design.is_file() else "missing",
        "rust_test_mapping_sha256": file_sha256(trace / "rust_test_mapping.json"),
        "c_source_files": {key: file_sha256(path) for key, path in sorted(c_source_paths(root, cases).items())},
        "rust_test_files": {key: file_sha256(path) for key, path in sorted(rust_test_paths(root, mapping).items())},
    }


def extract_rust_test_body(text: str, test_name: str) -> str:
    pattern = re.compile(r"#\s*\[\s*test\s*\]\s*fn\s+" + re.escape(test_name) + r"\s*\([^)]*\)\s*\{")
    match = pattern.search(text)
    if not match:
        return ""
    depth = 1
    cursor = match.end()
    while cursor < len(text) and depth:
        if text[cursor] == "{":
            depth += 1
        elif text[cursor] == "}":
            depth -= 1
        cursor += 1
    return text[match.end() : cursor - 1] if depth == 0 else ""


def rust_assertions(body: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", match.group("expr")).strip()
        for match in re.finditer(r"\bassert(?:_eq|_ne)?!\s*\((?P<expr>.*?)\)\s*;", body, flags=re.S)
    ]


def rust_test_functions(root: Path, mapping: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for path in rust_test_paths(root, mapping).values():
        found.update(re.findall(r"#\s*\[\s*test\s*\]\s*fn\s+([A-Za-z_][A-Za-z0-9_]*)", path.read_text(encoding="utf-8", errors="ignore")))
    return found


def add_issue(issues: list[dict[str, Any]], code: str, scenario_id: str, message: str) -> None:
    issues.append({"code": code, "scenario_id": scenario_id, "message": message})


def _safe_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return load_json(path), None
    except FileNotFoundError:
        return None, "missing"
    except (ValueError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _under(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())


def _validate_evidence(
    root: Path,
    evidence: Any,
    *,
    allowed_roots: tuple[Path, ...],
    label: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(evidence, list) or not evidence:
        return [f"{label} must contain at least one source evidence entry"]
    for index, item in enumerate(evidence, start=1):
        if not isinstance(item, dict):
            errors.append(f"{label}[{index}] must be an object")
            continue
        path_value = item.get("path")
        function = item.get("function")
        start = item.get("line_start")
        end = item.get("line_end")
        if not isinstance(path_value, str) or not isinstance(function, str) or not function:
            errors.append(f"{label}[{index}] requires path and function")
            continue
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            errors.append(f"{label}[{index}] requires a valid line range")
            continue
        path = resolve_root_path(root, path_value)
        if not path.is_file() or not any(_under(path, allowed) for allowed in allowed_roots):
            errors.append(f"{label}[{index}] path is outside the reviewed source boundary")
            continue
        if end > _line_count(path):
            errors.append(f"{label}[{index}] line range exceeds file length")
    return errors


def _fingerprint_matches(root: Path, actual: Any, expected: dict[str, Any]) -> list[str]:
    if not isinstance(actual, dict):
        return ["semantic review input_fingerprint must be an object"]
    errors: list[str] = []
    for key in ("c_test_model_sha256", "rust_api_design_sha256", "rust_test_mapping_sha256", "rust_test_files"):
        if actual.get(key) != expected.get(key):
            errors.append(f"semantic review fingerprint mismatch: {key}")
    c_files = actual.get("c_source_files")
    if not isinstance(c_files, dict):
        errors.append("semantic review fingerprint c_source_files must be an object")
    else:
        for key, digest in expected["c_source_files"].items():
            if c_files.get(key) != digest:
                errors.append(f"semantic review fingerprint missing or stale C source: {key}")
        base = source_root(root)
        for key, digest in c_files.items():
            if not isinstance(key, str) or not isinstance(digest, str):
                errors.append("semantic review fingerprint C source entries must be string pairs")
                continue
            path = resolve_root_path(root, key)
            if not path.is_file() or not _under(path, base) or file_sha256(path) != digest:
                errors.append(f"semantic review fingerprint has stale C source: {key}")
    return errors


def _review_issues(
    root: Path,
    review: dict[str, Any] | None,
    cases: list[dict[str, Any]],
    mapping_by_id: dict[str, dict[str, Any]],
    fingerprint: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "status": "missing",
        "reviewer_mode": "missing",
        "reviewed_scenarios": 0,
        "total_c_scenarios": len(cases),
        "case_statuses": {},
    }
    if review is None:
        add_issue(issues, "missing_semantic_review", "<review>", "missing logs/trace/test-semantic-review.json")
        return issues, summary
    summary.update({key: review.get(key, summary.get(key)) for key in ("status", "reviewer_mode", "reviewed_scenarios", "total_c_scenarios")})
    if review.get("schema_version") != 1:
        add_issue(issues, "invalid_semantic_review", "<review>", "schema_version must be 1")
    if review.get("reviewer_mode") not in REVIEWER_MODES:
        add_issue(issues, "invalid_semantic_review", "<review>", "reviewer_mode is invalid")
    freshness_errors = _fingerprint_matches(root, review.get("input_fingerprint"), fingerprint)
    if freshness_errors:
        summary["status"] = "stale"
        summary["freshness_errors"] = freshness_errors
        add_issue(
            issues,
            "stale_semantic_review",
            "<review>",
            "semantic review must be rerun for current inputs: " + "; ".join(freshness_errors),
        )
        return issues, summary
    if review.get("total_c_scenarios") != len(cases) or review.get("reviewed_scenarios") != len(cases):
        add_issue(issues, "incomplete_semantic_review", "<review>", "review must cover every dynamic C scenario")
    review_cases = review.get("cases")
    if not isinstance(review_cases, list):
        add_issue(issues, "invalid_semantic_review", "<review>", "cases must be a list")
        review_cases = []
    expected_ids = {str(case.get("scenario_id")) for case in cases if isinstance(case.get("scenario_id"), str)}
    seen: set[str] = set()
    c_root = source_root(root)
    rust_root = (root / "flashDB_rust" / "tests").resolve()
    for item in review_cases:
        if not isinstance(item, dict):
            add_issue(issues, "invalid_semantic_review", "<review>", "review case must be an object")
            continue
        scenario_id = item.get("scenario_id")
        if not isinstance(scenario_id, str):
            add_issue(issues, "invalid_semantic_review", "<review>", "review case requires scenario_id")
            continue
        if scenario_id in seen:
            add_issue(issues, "duplicate_semantic_review", scenario_id, "scenario reviewed more than once")
            continue
        seen.add(scenario_id)
        mapping = mapping_by_id.get(scenario_id)
        if scenario_id not in expected_ids:
            add_issue(issues, "review_case_not_in_c_model", scenario_id, "reviewed scenario is not dynamic C evidence")
            continue
        if mapping is None:
            add_issue(issues, "c_only", scenario_id, "C scenario has no Rust mapping")
            continue
        if item.get("rust_test") != mapping.get("rust_test"):
            add_issue(issues, "semantic_review_mapping_mismatch", scenario_id, "review rust_test does not match dynamic mapping")
        required = mapping.get("required_c_tests", [scenario_id])
        if isinstance(required, list) and required and item.get("c_function") not in required:
            add_issue(issues, "semantic_review_mapping_mismatch", scenario_id, "review c_function is not a registered C test for this scenario")
        status = item.get("status")
        if status not in REVIEW_STATUSES:
            add_issue(issues, "invalid_semantic_review", scenario_id, "case status must be pass, fail, or unresolved")
            continue
        summary["case_statuses"][scenario_id] = status
        dimensions = item.get("dimensions")
        if not isinstance(dimensions, dict) or any(dimensions.get(key) not in REVIEW_STATUSES for key in DIMENSIONS):
            add_issue(issues, "invalid_semantic_review", scenario_id, "case must report every semantic dimension")
        else:
            failed_dimensions = [key for key in DIMENSIONS if dimensions.get(key) != "pass"]
            if status == "pass" and failed_dimensions:
                add_issue(issues, "invalid_semantic_review", scenario_id, "pass case contains failed semantic dimensions")
            if status != "pass":
                if not failed_dimensions:
                    add_issue(issues, "invalid_semantic_review", scenario_id, "non-pass case must identify a non-pass semantic dimension")
                for dimension in failed_dimensions or ["scenario"]:
                    add_issue(issues, f"semantic_review_{dimension}", scenario_id, f"semantic reviewer marked {dimension} as {dimensions.get(dimension, status)}")
        for message in _validate_evidence(root, item.get("c_evidence"), allowed_roots=(c_root,), label="c_evidence"):
            add_issue(issues, "invalid_semantic_evidence", scenario_id, message)
        for message in _validate_evidence(root, item.get("rust_evidence"), allowed_roots=(rust_root,), label="rust_evidence"):
            add_issue(issues, "invalid_semantic_evidence", scenario_id, message)
        differences = item.get("differences")
        if status != "pass" and (not isinstance(differences, list) or not differences):
            add_issue(issues, "missing_semantic_difference", scenario_id, "non-pass review case must include concrete differences")
    for scenario_id in sorted(expected_ids - seen):
        add_issue(issues, "incomplete_semantic_review", scenario_id, "dynamic C scenario was not reviewed")
    for scenario_id in review.get("c_only", []) if isinstance(review.get("c_only"), list) else []:
        if isinstance(scenario_id, str):
            add_issue(issues, "c_only", scenario_id, "semantic reviewer reports a missing Rust scenario")
    if review.get("logic_mismatch") not in ([], None):
        if not isinstance(review.get("logic_mismatch"), list):
            add_issue(issues, "invalid_semantic_review", "<review>", "logic_mismatch must be a list")
        else:
            for item in review["logic_mismatch"]:
                scenario_id = item.get("scenario_id", item.get("c_func", "<review>")) if isinstance(item, dict) else "<review>"
                add_issue(issues, "logic_mismatch", str(scenario_id), "semantic reviewer reported a C/Rust logic mismatch")
    if review.get("status") != "pass":
        add_issue(issues, "semantic_review_not_pass", "<review>", f"semantic review status is {review.get('status', 'missing')}")
    return issues, summary


def analyze_consistency(root: Path) -> dict[str, Any]:
    root = root.resolve()
    trace = root / "logs" / "trace"
    issues: list[dict[str, Any]] = []
    try:
        test_model = load_json(trace / "c_test_model.json")
        mapping = load_json(trace / "rust_test_mapping.json")
        fingerprint = build_input_fingerprint(root, test_model, mapping)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        add_issue(issues, "missing_consistency_input", "<input>", str(exc))
        return {"stage": "TEST_CONSISTENCY_CHECK", "status": "fail", "issue_count": len(issues), "issues": issues, "total_scenarios": 0, "passed_scenarios": 0, "failed_scenarios": 0, "scenarios": [], "c_only": [], "rust_only": [], "logic_mismatch": [], "input_fingerprint": {}}
    cases_raw = test_model.get("scorer_standard_cases")
    cases = [item for item in cases_raw if isinstance(item, dict)] if isinstance(cases_raw, list) else []
    if not cases:
        add_issue(issues, "invalid_c_test_model", "<model>", "scorer_standard_cases must be a non-empty list")
    expected_ids = {str(item.get("scenario_id")) for item in cases if isinstance(item.get("scenario_id"), str)}
    scenarios_raw = mapping.get("scenarios")
    scenarios = [item for item in scenarios_raw if isinstance(item, dict)] if isinstance(scenarios_raw, list) else []
    if not isinstance(scenarios_raw, list):
        add_issue(issues, "invalid_mapping", "<mapping>", "scenarios must be a list")
    mapping_by_id = {str(item.get("id")): item for item in scenarios if isinstance(item.get("id"), str)}
    for scenario_id in sorted(expected_ids - set(mapping_by_id)):
        add_issue(issues, "c_only", scenario_id, "C scorer case has no Rust test mapping")
    for scenario_id in sorted(set(mapping_by_id) - expected_ids):
        add_issue(issues, "rust_only_mapping", scenario_id, "Rust mapping has no dynamic C scorer case")
    if mapping.get("total_scenarios") != len(expected_ids):
        add_issue(issues, "mapping_total_mismatch", "<mapping>", "mapping total_scenarios must equal dynamic C case count")

    scenario_results: list[dict[str, Any]] = []
    for scenario_id in sorted(expected_ids):
        mapping_item = mapping_by_id.get(scenario_id)
        start = len(issues)
        if mapping_item is not None:
            rust_file = mapping_item.get("rust_file")
            rust_test = mapping_item.get("rust_test")
            body = ""
            if isinstance(rust_file, str) and isinstance(rust_test, str):
                path = resolve_root_path(root, rust_file)
                if path.is_file():
                    body = extract_rust_test_body(path.read_text(encoding="utf-8", errors="ignore"), rust_test)
            if not body:
                add_issue(issues, "missing_rust_test", scenario_id, "mapped Rust #[test] function was not found")
            elif not rust_assertions(body):
                add_issue(issues, "missing_rust_assertion", scenario_id, "mapped Rust test has no assertion")
        scenario_results.append({"scenario_id": scenario_id, "issue_start": start})

    review, review_error = _safe_json(trace / "test-semantic-review.json")
    if review_error:
        review = None
    review_issues, review_summary = _review_issues(root, review, cases, mapping_by_id, fingerprint)
    issues.extend(review_issues)

    mapped_tests = {item.get("rust_test") for item in scenarios if isinstance(item.get("rust_test"), str)}
    rust_only = sorted(rust_test_functions(root, mapping) - mapped_tests)
    passed = 0
    review_case_statuses = review_summary.get("case_statuses") if isinstance(review_summary.get("case_statuses"), dict) else {}
    rendered_scenarios: list[dict[str, Any]] = []
    for result in scenario_results:
        scenario_id = result["scenario_id"]
        case_issues = [item["code"] for item in issues if item.get("scenario_id") == scenario_id]
        if case_issues:
            status = "fail"
        elif review_case_statuses.get(scenario_id) == "pass":
            status = "pass"
        elif review_case_statuses.get(scenario_id) == "fail":
            status = "fail"
        else:
            status = "unresolved"
        passed += status == "pass"
        rendered_scenarios.append({"scenario_id": scenario_id, "status": status, "issue_codes": case_issues})
    logic_mismatch = [item for item in issues if str(item.get("code", "")).startswith(("logic_mismatch", "semantic_review_"))]
    warnings = [{"code": "rust_only", "rust_test": name} for name in rust_only]
    return {
        "stage": "TEST_CONSISTENCY_CHECK",
        "status": "pass" if not issues else "fail",
        "issue_count": len(issues),
        "issues": issues,
        "warnings": warnings,
        "total_scenarios": len(expected_ids),
        "passed_scenarios": passed,
        "failed_scenarios": len(expected_ids) - passed,
        "scenarios": rendered_scenarios,
        "c_only": sorted({item["scenario_id"] for item in issues if item.get("code") == "c_only"}),
        "rust_only": rust_only,
        "logic_mismatch": logic_mismatch,
        "semantic_review": review_summary,
        "input_fingerprint": fingerprint,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate migrated Rust tests and a read-only semantic review.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--out", help="Path to write test-consistency.json.")
    parser.add_argument("--print-input-fingerprint", action="store_true", help="Print the current reviewer input fingerprint and exit.")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.print_input_fingerprint:
        try:
            print(json.dumps(build_input_fingerprint(root.resolve()), indent=2, sort_keys=True))
            return 0
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            print(f"TEST_CONSISTENCY_CHECK: FAIL\n- fingerprint: {exc}")
            return 1
    try:
        contest_guard.guard_mutation_allowed(root)
    except RuntimeError as exc:
        print(str(exc))
        return contest_guard.FINALIZE_EXIT_CODE
    report = analyze_consistency(root)
    scenario_rows = report.get("scenarios") if isinstance(report.get("scenarios"), list) else []
    task_ids = {
        str(row.get("scenario_id"))
        for row in scenario_rows
        if isinstance(row, dict) and isinstance(row.get("scenario_id"), str)
    }
    passed_ids = {
        str(row.get("scenario_id"))
        for row in scenario_rows
        if isinstance(row, dict) and isinstance(row.get("scenario_id"), str) and row.get("status") == "pass"
    }
    confirmation_id = "consistency-" + hashlib.sha256(
        json.dumps(report.get("input_fingerprint", {}), sort_keys=True).encode("utf-8")
    ).hexdigest()
    queue_phase = repair_work_queue.sync_tasks(
        root.resolve() / "logs" / "trace" / "repair-work-queue.json",
        "tests",
        task_ids,
        passed_ids=passed_ids,
        full_confirmation_id=confirmation_id,
    )
    report["work_queue"] = repair_work_queue.phase_summary(queue_phase)
    if args.out:
        write_json(Path(args.out), report)
        if report.get("total_scenarios"):
            try:
                snapshot = submission_snapshot.capture(root.resolve(), kind="validated")
                report["submission_snapshot"] = snapshot
                write_json(Path(args.out), report)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                report["submission_snapshot_error"] = str(exc)
                write_json(Path(args.out), report)
    print("TEST_CONSISTENCY_CHECK: " + report["status"].upper())
    print(f"issues={report['issue_count']}")
    for issue in report["issues"]:
        print(f"- {issue['scenario_id']}: {issue['code']}: {issue['message']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
