#!/usr/bin/env python3
"""Write final FlashDB migration reports from trace artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def write_report(root: Path, output: Path, issues: Path) -> None:
    trace = root / "logs" / "trace"
    state = load_json(trace / "workflow_state.json")
    cargo = load_json(trace / "cargo-results.json")
    ratio = load_json(trace / "unsafe-ratio.json")
    design = load_json(trace / "rust_api_design.json")
    mapping = load_json(trace / "rust_test_mapping.json")

    success = (
        state.get("current_stage") == "DONE"
        and state.get("build_status") == "pass"
        and state.get("test_status") == "pass"
        and float(ratio.get("unsafe_ratio", 1.0)) <= 0.10
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
