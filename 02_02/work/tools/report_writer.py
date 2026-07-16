#!/usr/bin/env python3
"""Write final FlashDB migration reports from trace artifacts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from collections import Counter


EXPECTED_C_CROSS_REPAIR_ATTEMPTS = 8
EXPECTED_TEST_REPAIR_ATTEMPTS = 2


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_test_input_manifest(root: Path) -> dict[str, str]:
    root = root.resolve()
    project = root / "flashDB_rust"
    trace = root / "logs" / "trace"
    files: set[Path] = set()
    for directory_name in ("src", "tests"):
        directory = project / directory_name
        if directory.is_dir():
            files.update(path for path in directory.rglob("*") if path.is_file() and not path.is_symlink())
    for filename in ("Cargo.toml", "Cargo.lock"):
        path = project / filename
        if path.is_file() and not path.is_symlink():
            files.add(path)
    mapping = trace / "rust_test_mapping.json"
    if mapping.is_file() and not mapping.is_symlink():
        files.add(mapping)
    return {path.relative_to(root).as_posix(): _sha256(path) for path in sorted(files)}


def test_repair_evidence(
    root: Path,
    cargo: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = attempts[-1] if attempts else {}
    convergence = cargo.get("repair_convergence") if isinstance(cargo.get("repair_convergence"), dict) else {}
    repairs_used = sum(row.get("kind") == "repair" for row in attempts)
    maximum = convergence.get("max_repair_attempts")
    current_manifest = current_test_input_manifest(root)
    cargo_test_log = root / "logs" / "trace" / "cargo-test.log"
    current_log_sha256 = _sha256(cargo_test_log) if cargo_test_log.is_file() else None
    test_execution = cargo.get("test_execution") if isinstance(cargo.get("test_execution"), dict) else {}
    _, test_execution_current = analyze_current_test_execution(root, cargo)
    valid = (
        bool(attempts)
        and latest.get("attempt_id") == convergence.get("attempt_id")
        and latest.get("source_manifest") == current_manifest
        and convergence.get("source_manifest") == current_manifest
        and latest.get("repair_attempts_used") == repairs_used
        and convergence.get("repair_attempts_used") == repairs_used
        and maximum == EXPECTED_TEST_REPAIR_ATTEMPTS
        and latest.get("max_repair_attempts") == maximum
        and latest.get("build_status") == cargo.get("build_status")
        and latest.get("test_status") == cargo.get("test_status")
        and latest.get("test_execution_status") == test_execution.get("status")
        and convergence.get("test_execution_status") == test_execution.get("status")
        and latest.get("cargo_test_log_sha256") == current_log_sha256
        and convergence.get("cargo_test_log_sha256") == current_log_sha256
        and test_execution.get("log_sha256") == current_log_sha256
        and test_execution_current
    )
    return {
        "valid": valid,
        "repair_attempts_used": repairs_used,
        "max_repair_attempts": maximum,
        "exhausted": bool(valid and isinstance(maximum, int) and repairs_used >= maximum),
        "test_execution_current": test_execution_current,
    }


def load_tool(filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location("report_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def analyze_current_test_execution(root: Path, cargo: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    log_path = root / "logs" / "trace" / "cargo-test.log"
    test_result = cargo.get("test") if isinstance(cargo.get("test"), dict) else {}
    returncode = test_result.get("returncode")
    if not log_path.is_file() or not isinstance(returncode, int):
        return {}, False
    try:
        cargo_tool = load_tool("cargo_capture.py")
        expected = cargo_tool.analyze_test_execution(
            root / "flashDB_rust",
            root / "logs" / "trace",
            log_path.read_text(encoding="utf-8", errors="replace"),
            returncode,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return {}, False
    persisted = cargo.get("test_execution") if isinstance(cargo.get("test_execution"), dict) else {}
    keys = (
        "status", "reason", "expected_count", "executed_count", "matched_expected_count",
        "expected_tests", "executed_tests", "missing_expected_tests", "ignored_expected_tests",
        "failed_expected_tests", "invalid_mappings", "missing_test_files", "test_files",
    )
    return expected, all(persisted.get(key) == expected.get(key) for key in keys)


def placeholder_evidence_is_current(root: Path, placeholders: dict[str, Any]) -> bool:
    try:
        placeholder_tool = load_tool("placeholder_check.py")
        expected_placeholder = placeholder_tool.analyze_placeholders(
            root,
            root / "flashDB_rust" / "tests",
            root / "logs" / "trace" / "rust_test_mapping.json",
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError, RuntimeError):
        return False
    return all(
        placeholders.get(key) == expected_placeholder.get(key)
        for key in ("status", "issue_count", "input_fingerprint")
    )


def test_evidence_is_current(root: Path, placeholders: dict[str, Any], consistency: dict[str, Any]) -> bool:
    try:
        consistency_tool = load_tool("test_consistency_check.py")
        expected_consistency = consistency_tool.analyze_consistency(root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, RuntimeError):
        return False
    return placeholder_evidence_is_current(root, placeholders) and all(
        consistency.get(key) == expected_consistency.get(key)
        for key in ("status", "issue_count", "input_fingerprint", "semantic_review")
    )


def validation_matrix_summary(matrix: dict[str, Any]) -> list[str]:
    if not matrix:
        return ["- C tests on Rust: `missing`", "- Validation matrix scenarios: `0`"]
    summary = matrix.get("summary", {})
    rust_impl = summary.get("rust_impl_c_test", {}) if isinstance(summary, dict) else {}
    if not isinstance(rust_impl, dict):
        rust_impl = {}
    parts = [f"{key}={value}" for key, value in sorted(rust_impl.items())]
    return [
        f"- C tests on Rust: `{', '.join(parts) if parts else 'no summary'}`",
        f"- Validation matrix scenarios: `{matrix.get('total_scenarios', 0)}`",
    ]


def _counter_line(label: str, counts: Counter[str]) -> str:
    parts = [f"{key}={value}" for key, value in sorted(counts.items())]
    return f"- {label}: `{', '.join(parts) if parts else 'none'}`"


def cross_diagnostics_summary(matrix: dict[str, Any], diagnostics: list[dict[str, Any]]) -> list[str]:
    scenarios = matrix.get("scenarios") if isinstance(matrix, dict) else []
    rows = [item for item in scenarios if isinstance(item, dict)] if isinstance(scenarios, list) else []
    blocking = [
        item
        for item in rows
        if item.get("rust_impl_c_test") in {"fail", "not_run", "not_supported"}
        or item.get("c_impl_c_test") in {"fail", "not_supported"}
    ]
    failure_layers = Counter(str(item.get("failure_layer")) for item in blocking if isinstance(item.get("failure_layer"), str))
    handoffs = Counter(str(item.get("handoff")) for item in blocking if isinstance(item.get("handoff"), str))
    diag_counts = Counter(
        str(item.get("diagnosis"))
        for item in diagnostics
        if isinstance(item.get("diagnosis"), str)
    )
    if not diag_counts:
        diag_counts = Counter(str(item.get("diagnosis")) for item in blocking if isinstance(item.get("diagnosis"), str))
    return [
        _counter_line("failure_layers", failure_layers),
        _counter_line("handoff", handoffs),
        _counter_line("diagnostics", diag_counts),
    ]


def final_c_cross_verified(matrix: dict[str, Any], attempts: list[dict[str, Any]]) -> bool:
    scenarios = matrix.get("scenarios") if isinstance(matrix, dict) else None
    latest_attempt = attempts[-1] if attempts else {}
    return (
        matrix.get("mode") == "full"
        and matrix.get("scope") == "all"
        and matrix.get("attempt_kind") == "final"
        and isinstance(scenarios, list)
        and bool(scenarios)
        and all(isinstance(row, dict) and row.get("rust_impl_c_test") == "pass" for row in scenarios)
        and latest_attempt.get("attempt_id") == matrix.get("execution_id")
        and latest_attempt.get("kind") == "final"
    )


def failed_c_cross_final_verified(
    matrix: dict[str, Any],
    attempts: list[dict[str, Any]],
    convergence: dict[str, Any],
) -> bool:
    scenarios = matrix.get("scenarios") if isinstance(matrix, dict) else None
    latest_attempt = attempts[-1] if attempts else {}
    repairs_used = sum(row.get("kind") == "repair" for row in attempts)
    maximum = convergence.get("max_repair_attempts")
    return (
        convergence.get("status") == "failed_final"
        and convergence.get("terminal") is True
        and maximum == EXPECTED_C_CROSS_REPAIR_ATTEMPTS
        and repairs_used >= maximum
        and convergence.get("repair_attempts_used") == repairs_used
        and convergence.get("remaining_repair_attempts") == 0
        and convergence.get("execution_id") == matrix.get("execution_id")
        and matrix.get("mode") == "full"
        and matrix.get("scope") == "all"
        and matrix.get("attempt_kind") == "confirmation"
        and isinstance(scenarios, list)
        and bool(scenarios)
        and any(isinstance(row, dict) and row.get("rust_impl_c_test") != "pass" for row in scenarios)
        and latest_attempt.get("attempt_id") == matrix.get("execution_id")
        and latest_attempt.get("kind") == "confirmation"
    )


def successful_convergence_verified(
    matrix: dict[str, Any],
    attempts: list[dict[str, Any]],
    convergence: dict[str, Any],
) -> bool:
    repairs_used = sum(row.get("kind") == "repair" for row in attempts)
    maximum = convergence.get("max_repair_attempts")
    return (
        convergence.get("status") == "success"
        and convergence.get("terminal") is True
        and maximum == EXPECTED_C_CROSS_REPAIR_ATTEMPTS
        and convergence.get("repair_attempts_used") == repairs_used
        and convergence.get("remaining_repair_attempts") == max(0, maximum - repairs_used)
        and convergence.get("execution_id") == matrix.get("execution_id")
        and final_c_cross_verified(matrix, attempts)
    )


def cross_convergence_summary(
    matrix: dict[str, Any],
    attempts: list[dict[str, Any]],
    workbench_issues: list[dict[str, Any]],
    convergence: dict[str, Any],
    test_repairs: dict[str, Any],
) -> list[str]:
    scenarios = matrix.get("scenarios") if isinstance(matrix, dict) else []
    per_test = Counter(
        str(row.get("rust_impl_c_test"))
        for row in scenarios
        if isinstance(row, dict) and isinstance(row.get("rust_impl_c_test"), str)
    ) if isinstance(scenarios, list) else Counter()
    progress_count = sum(row.get("progress") is True for row in attempts)
    no_progress_count = sum(row.get("progress") is False for row in attempts)
    latest_attempt_kind = matrix.get("attempt_kind", "missing") if isinstance(matrix, dict) else "missing"
    return [
        _counter_line("per_test", per_test),
        f"- attempts: `progress={progress_count}, no_progress={no_progress_count}`",
        f"- workbench_issues: `{len(workbench_issues)}`",
        f"- latest_attempt_kind: `{latest_attempt_kind}`",
        f"- final_c_cross: `{'verified' if final_c_cross_verified(matrix, attempts) else 'not_verified'}`",
        f"- convergence_status: `{convergence.get('status', 'missing')}`",
        "- repair_budget: `"
        f"{convergence.get('repair_attempts_used', 'unknown')}/"
        f"{convergence.get('max_repair_attempts', 'unknown')}`",
        "- test_repair_budget: `"
        f"{test_repairs.get('repair_attempts_used', 'unknown')}/"
        f"{test_repairs.get('max_repair_attempts', 'unknown')}`",
        f"- test_repair_evidence_fresh: `{'yes' if test_repairs.get('valid') else 'no'}`",
    ]


def _unsafe_ratio_passes(ratio: dict[str, Any]) -> bool:
    try:
        return float(ratio.get("unsafe_ratio", 1.0)) <= 0.10
    except (TypeError, ValueError):
        return False


def _unsafe_ratio_is_numeric(ratio: dict[str, Any]) -> bool:
    try:
        float(ratio.get("unsafe_ratio"))
        return True
    except (TypeError, ValueError):
        return False


def write_report(root: Path, output: Path, issues: Path) -> str:
    trace = root / "logs" / "trace"
    cargo = load_json(trace / "cargo-results.json")
    ratio = load_json(trace / "unsafe-ratio.json")
    design = load_json(trace / "rust_api_design.json")
    matrix = load_json(trace / "validation-matrix.json")
    diagnostics = load_jsonl(trace / "c-cross" / "diagnostics.jsonl")
    attempts = load_jsonl(trace / "c-cross" / "attempts.jsonl")
    test_attempts = load_jsonl(trace / "test-repair-attempts.jsonl")
    workbench_issues = load_jsonl(trace / "c-cross" / "workbench-issues.jsonl")
    convergence = load_json(trace / "c-cross" / "failure-summary.json")
    mapping = load_json(trace / "rust_test_mapping.json")
    placeholders = load_json(trace / "test-placeholder-check.json")
    consistency = load_json(trace / "test-consistency.json")
    semantic_review = load_json(trace / "test-semantic-review.json")
    test_execution = cargo.get("test_execution") if isinstance(cargo.get("test_execution"), dict) else {}
    evidence_current = test_evidence_is_current(root, placeholders, consistency)
    placeholder_current = placeholder_evidence_is_current(root, placeholders)
    test_repairs = test_repair_evidence(root, cargo, test_attempts)
    matrix_lines = "\n".join(validation_matrix_summary(matrix))
    diagnostics_lines = "\n".join(cross_diagnostics_summary(matrix, diagnostics))
    convergence_lines = "\n".join(
        cross_convergence_summary(matrix, attempts, workbench_issues, convergence, test_repairs)
    )

    downstream_success = (
        cargo.get("build_status") == "pass"
        and cargo.get("test_status") == "pass"
        and isinstance(cargo.get("test_execution"), dict)
        and cargo["test_execution"].get("status") == "pass"
        and placeholders.get("status") == "pass"
        and consistency.get("status") == "pass"
        and evidence_current
        and _unsafe_ratio_passes(ratio)
    )
    cargo_passed = cargo.get("build_status") == "pass" and cargo.get("test_status") == "pass"
    terminal_test_evidence = (
        evidence_current
        if cargo_passed and placeholders.get("status") == "pass"
        else placeholder_current
    )
    convergence_status = convergence.get("status")
    c_cross_success = successful_convergence_verified(matrix, attempts, convergence)
    c_cross_failed_final = failed_c_cross_final_verified(matrix, attempts, convergence)
    c_cross_terminal = c_cross_success or c_cross_failed_final
    unsafe_evidence_valid = _unsafe_ratio_is_numeric(ratio)
    test_stage_failed_final = bool(
        test_repairs["exhausted"]
        and not downstream_success
        and terminal_test_evidence
    )
    if c_cross_success and downstream_success and test_repairs["valid"]:
        status = "SUCCESS"
    elif (
        c_cross_terminal
        and test_repairs["valid"]
        and unsafe_evidence_valid
        and (downstream_success or test_stage_failed_final)
        and (c_cross_failed_final or test_stage_failed_final)
    ):
        status = "FAILED"
    else:
        status = "INCOMPLETE"
    workflow_convergence_status = (
        "success" if status == "SUCCESS"
        else "failed_final" if status == "FAILED"
        else "ready_for_final" if convergence_status == "ready_for_final"
        else "repair_required"
    )
    convergence_lines += f"\n- workflow_convergence_status: `{workflow_convergence_status}`"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"""# FlashDB C-to-Rust Final Report

STATUS: {status}

## Artifacts

- Rust project: `flashDB_rust`
- Trace directory: `logs/trace`
- Result issues: `result/issues/00-summary.md`

## Build and Test

- build_status: `{cargo.get('build_status', 'unknown')}`
- test_status: `{cargo.get('test_status', 'unknown')}`
- cargo_build_returncode: `{cargo.get('build', {}).get('returncode', 'unknown')}`
- cargo_test_returncode: `{cargo.get('test', {}).get('returncode', 'unknown')}`
- mapped_test_execution_status: `{test_execution.get('status', 'missing')}`
- mapped_tests_executed: `{test_execution.get('matched_expected_count', 'unknown')}/{test_execution.get('expected_count', 'unknown')}`
- mapped_test_execution_reason: `{test_execution.get('reason', 'missing')}`

## Unsafe

- unsafe_ratio: `{ratio.get('unsafe_ratio', 'unknown')}`
- unsafe_lines: `{ratio.get('unsafe_lines', 'unknown')}`

## Rust API

- crate_name: `{design.get('crate_name', 'unknown')}`
- modules: `{', '.join(design.get('modules', [])) if isinstance(design.get('modules'), list) else 'unknown'}`
- unmapped_symbols: `{len(design.get('unmapped_symbols', [])) if isinstance(design.get('unmapped_symbols'), list) else 'unknown'}`

## Tests

- mapped_scenarios: `{mapping.get('total_scenarios', 'unknown')}`
- extension_tests: `{len(mapping.get('extension', [])) if isinstance(mapping.get('extension'), list) else 'unknown'}`
- unmapped_tests_or_symbols: `{len(mapping.get('unmapped', [])) if isinstance(mapping.get('unmapped'), list) else 'unknown'}`
- placeholder_status: `{placeholders.get('status', 'missing')}`
- placeholder_issue_count: `{placeholders.get('issue_count', 'unknown')}`
- semantic_consistency_status: `{consistency.get('status', 'missing')}`
- semantic_consistency_issue_count: `{consistency.get('issue_count', 'unknown')}`
- semantic_scenarios: `passed={consistency.get('passed_scenarios', 'unknown')}, failed={consistency.get('failed_scenarios', 'unknown')}`
- semantic_review_status: `{semantic_review.get('status', 'missing')}`
- semantic_reviewer_mode: `{semantic_review.get('reviewer_mode', 'missing')}`
- semantic_reviewed_scenarios: `{semantic_review.get('reviewed_scenarios', 'unknown')}/{semantic_review.get('total_c_scenarios', 'unknown')}`
- test_evidence_fresh: `{'yes' if evidence_current else 'no'}`

## Cross Validation Matrix

{matrix_lines}

## Cross Validation Diagnostics

{diagnostics_lines}

## Cross Validation Convergence

{convergence_lines}
""",
        encoding="utf-8",
    )

    issues.parent.mkdir(parents=True, exist_ok=True)
    failures = [
        item for item in matrix.get("scenarios", [])
        if isinstance(item, dict) and item.get("rust_impl_c_test") != "pass"
    ] if isinstance(matrix.get("scenarios"), list) else []
    issue_lines = "\n".join(
        f"- {item.get('scenario_id')}: {item.get('reason', item.get('diagnosis', 'failed'))}"
        for item in failures
    ) if failures else "- None"
    if test_execution.get("status") != "pass":
        issue_lines += "\n- Rust test execution: " + str(test_execution.get("reason", "missing execution evidence"))
    semantic_differences = semantic_review.get("logic_mismatch") if isinstance(semantic_review.get("logic_mismatch"), list) else []
    if semantic_differences:
        issue_lines += "\n" + "\n".join(
            f"- semantic review {item.get('scenario_id', item.get('c_func', '<unknown>'))}: {item.get('detail', 'logic mismatch')}"
            for item in semantic_differences
            if isinstance(item, dict)
        )
    issues.write_text(
        f"""# 00 - Summary

## Status

STATUS: {status}

## Known Issues

{issue_lines}

## Extension Compatibility

- unmapped_symbols: `{len(design.get('unmapped_symbols', [])) if isinstance(design.get('unmapped_symbols'), list) else 'unknown'}`
- excluded_sources: `{len(design.get('excluded_sources', [])) if isinstance(design.get('excluded_sources'), list) else 'unknown'}`
- unmapped_tests_or_symbols: `{len(mapping.get('unmapped', [])) if isinstance(mapping.get('unmapped'), list) else 'unknown'}`
""",
        encoding="utf-8",
    )
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write final result/output.md and result/issues/00-summary.md.")
    parser.add_argument("--root", default=".", help="Workbench root.")
    parser.add_argument("--output", required=True, help="Output markdown report path.")
    parser.add_argument("--issues", required=True, help="Issues summary markdown path.")
    args = parser.parse_args(argv)

    status = write_report(Path(args.root), Path(args.output), Path(args.issues))
    print(f"REPORT_AND_VERIFY: {status}")
    return 1 if status == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
