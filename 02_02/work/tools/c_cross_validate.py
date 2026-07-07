#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _relative_log_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def build_matrix(root: Path, out: Path) -> dict[str, Any]:
    trace = out
    c_cross = trace / "c-cross"
    c_cross.mkdir(parents=True, exist_ok=True)

    test_model = load_json(trace / "c_test_model.json")
    cases = test_model.get("scorer_standard_cases")
    if not isinstance(cases, list):
        raise ValueError("c_test_model.json scorer_standard_cases must be a list")

    scenarios = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        scenario_id = case.get("scenario_id")
        case_id = case.get("case_id")
        if not isinstance(scenario_id, str) or not isinstance(case_id, str):
            continue

        log = c_cross / f"{scenario_id}.log"
        log.write_text(
            "C cross-validation harness is not implemented for this scenario yet.\n",
            encoding="utf-8",
        )
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "scorer_case_id": case_id,
                "suite": case.get("suite", "unknown"),
                "c_impl_c_test": "baseline",
                "rust_impl_c_test": "not_supported",
                "c_impl_rust_test": "not_run",
                "rust_impl_rust_test": "pending",
                "diagnosis": "c_cross_harness_not_supported",
                "reason": "initial harness does not yet compile this C test pattern",
                "log": _relative_log_path(log, root),
            }
        )

    (c_cross / "cross-compile.log").write_text(
        "C cross-validation compile step not implemented in unsupported-first mode.\n",
        encoding="utf-8",
    )
    (c_cross / "cross-test.log").write_text(
        "C cross-validation test step not implemented in unsupported-first mode.\n",
        encoding="utf-8",
    )
    return {
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        "policy": "advisory",
        "total_scenarios": len(scenarios),
        "summary": {"rust_impl_c_test": {"not_supported": len(scenarios)}},
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FlashDB C tests against Rust validation facade.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--project", default="flashDB_rust", help="Rust project path, relative to root.")
    parser.add_argument("--out", default="logs/trace", help="Trace output directory, relative to root.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = (root / args.out).resolve()
    matrix = build_matrix(root, out)
    matrix_path = out / "validation-matrix.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("VERIFY_RUST_WITH_C_TESTS: MATRIX_WRITTEN")
    print(f"mapped_scenarios={matrix['total_scenarios']}")
    print("policy=advisory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
