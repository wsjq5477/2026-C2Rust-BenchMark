#!/usr/bin/env python3
"""Write final FlashDB migration reports from trace artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from collections import Counter


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


def cross_convergence_summary(
    matrix: dict[str, Any],
    attempts: list[dict[str, Any]],
    workbench_issues: list[dict[str, Any]],
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
    ]


def write_report(root: Path, output: Path, issues: Path) -> None:
    trace = root / "logs" / "trace"
    state = load_json(trace / "workflow_state.json")
    cargo = load_json(trace / "cargo-results.json")
    ratio = load_json(trace / "unsafe-ratio.json")
    design = load_json(trace / "rust_api_design.json")
    matrix = load_json(trace / "validation-matrix.json")
    diagnostics = load_jsonl(trace / "c-cross" / "diagnostics.jsonl")
    attempts = load_jsonl(trace / "c-cross" / "attempts.jsonl")
    workbench_issues = load_jsonl(trace / "c-cross" / "workbench-issues.jsonl")
    mapping = load_json(trace / "rust_test_mapping.json")
    matrix_lines = "\n".join(validation_matrix_summary(matrix))
    diagnostics_lines = "\n".join(cross_diagnostics_summary(matrix, diagnostics))
    convergence_lines = "\n".join(cross_convergence_summary(matrix, attempts, workbench_issues))

    success = (
        state.get("current_stage") == "DONE"
        and state.get("build_status") == "pass"
        and state.get("test_status") == "pass"
        and float(ratio.get("unsafe_ratio", 1.0)) <= 0.10
        and final_c_cross_verified(matrix, attempts)
    )
    status = "SUCCESS" if success else "FAILED"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"""# FlashDB C-to-Rust Final Report

STATUS: {status}

## Artifacts

- Rust project: `flashDB_rust`
- Trace directory: `logs/trace`
- Result issues: `result/issues/00-summary.md`

## Build and Test

- build_status: `{state.get('build_status', 'unknown')}`
- test_status: `{state.get('test_status', 'unknown')}`
- cargo_build_returncode: `{cargo.get('build', {}).get('returncode', 'unknown')}`
- cargo_test_returncode: `{cargo.get('test', {}).get('returncode', 'unknown')}`

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
    blocked = state.get("blocked_issues", [])
    issue_lines = "\n".join(f"- {item}" for item in blocked) if blocked else "- None"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write final result/output.md and result/issues/00-summary.md.")
    parser.add_argument("--root", default=".", help="Workbench root.")
    parser.add_argument("--output", required=True, help="Output markdown report path.")
    parser.add_argument("--issues", required=True, help="Issues summary markdown path.")
    args = parser.parse_args(argv)

    write_report(Path(args.root), Path(args.output), Path(args.issues))
    print("REPORT_AND_VERIFY: REPORT_WRITTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
