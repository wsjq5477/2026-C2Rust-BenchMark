#!/usr/bin/env python3
"""Merge bounded per-scenario semantic reviews into the current review ledger."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import contest_guard


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def merge(root: Path, partial_path: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    partial = _load(partial_path)
    model = _load(root / "logs" / "trace" / "c_test_model.json")
    expected = {
        str(row.get("scenario_id"))
        for row in (model.get("scorer_standard_cases") if isinstance(model.get("scorer_standard_cases"), list) else [])
        if isinstance(row, dict) and isinstance(row.get("scenario_id"), str)
    }
    if not expected:
        raise ValueError("c_test_model.json has no dynamic scorer scenarios")
    if partial.get("schema_version") != 1 or not isinstance(partial.get("input_fingerprint"), dict):
        raise ValueError("partial semantic review requires schema_version 1 and input_fingerprint")
    partial_cases = partial.get("cases")
    if not isinstance(partial_cases, list) or not partial_cases:
        raise ValueError("partial semantic review must contain at least one case")

    try:
        current = _load(output)
    except FileNotFoundError:
        current = {}
    if current and current.get("input_fingerprint") != partial.get("input_fingerprint"):
        current = {}
    cases = {
        str(row.get("scenario_id")): row
        for row in (current.get("cases") if isinstance(current.get("cases"), list) else [])
        if isinstance(row, dict) and isinstance(row.get("scenario_id"), str)
    }
    for row in partial_cases:
        if not isinstance(row, dict) or not isinstance(row.get("scenario_id"), str):
            raise ValueError("partial semantic review case requires scenario_id")
        scenario_id = row["scenario_id"]
        if scenario_id not in expected:
            raise ValueError(f"partial semantic review contains unknown scenario: {scenario_id}")
        cases[scenario_id] = row

    statuses = {scenario_id: row.get("status") for scenario_id, row in cases.items()}
    missing = expected - set(cases)
    if not missing and statuses and all(value == "pass" for value in statuses.values()):
        status = "pass"
    elif any(value == "fail" for value in statuses.values()):
        status = "fail"
    else:
        status = "unresolved"
    mismatches = [
        {"scenario_id": scenario_id, "detail": difference}
        for scenario_id, row in cases.items()
        if row.get("status") != "pass"
        for difference in (row.get("differences") if isinstance(row.get("differences"), list) else [])
    ]
    result = {
        "schema_version": 1,
        "status": status,
        "reviewer_mode": partial.get("reviewer_mode", "independent_subagent"),
        "input_fingerprint": partial["input_fingerprint"],
        "total_c_scenarios": len(expected),
        "reviewed_scenarios": len(set(cases) & expected),
        "c_only": sorted(missing),
        "rust_only": sorted(set(current.get("rust_only", [])) | set(partial.get("rust_only", []))),
        "logic_mismatch": mismatches,
        "cases": [cases[scenario_id] for scenario_id in sorted(cases)],
    }
    _atomic(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge one bounded semantic review into the current ledger.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="logs/trace/test-semantic-review.json")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        contest_guard.guard_mutation_allowed(root)
        input_path = Path(args.input)
        if not input_path.is_absolute():
            input_path = root / input_path
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = root / output_path
        result = merge(root, input_path, output_path)
    except RuntimeError as exc:
        print(str(exc))
        return contest_guard.FINALIZE_EXIT_CODE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SEMANTIC_REVIEW_MERGE: REFUSED: {exc}")
        return 2
    print(f"SEMANTIC_REVIEW_MERGE: {result['status'].upper()}")
    print(f"reviewed_scenarios={result['reviewed_scenarios']}/{result['total_c_scenarios']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
