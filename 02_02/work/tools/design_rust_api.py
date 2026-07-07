#!/usr/bin/env python3
"""Design the canonical safe Rust API from FlashDB C fact models.

This stage is intentionally a design artifact producer. It reads the C project,
API, and test models from BUILD_C_MODEL and writes rust_api_design.json. It must
not create the Rust crate or generate Rust source files.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def available_symbols(api_model: dict[str, Any]) -> set[str]:
    symbols = api_model.get("public_functions", [])
    if not isinstance(symbols, list):
        return set()
    return {item for item in symbols if isinstance(item, str)}


def as_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def rust_ident_from_c_symbol(symbol: str) -> str:
    name = re.sub(r"^fdb_", "", symbol)
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not name:
        name = "api"
    if name[0].isdigit():
        name = f"api_{name}"
    return name


def type_name_from_module(module: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", module) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Api"


def api_items_from_symbols(module: str, c_symbols: list[str]) -> list[dict[str, Any]]:
    type_name = type_name_from_module(module)
    items: list[dict[str, Any]] = []
    for symbol in sorted(dict.fromkeys(c_symbols)):
        method = rust_ident_from_c_symbol(symbol)
        items.append(
            {
                "name": method,
                "rust": f"{type_name}::{method}",
                "c_symbols": [symbol],
                "returns": "Result<(), Error>",
                "notes": "Derived from current C public API evidence.",
            }
        )
    return items


def count_list(data: dict[str, Any], key: str) -> int:
    value = data.get(key, [])
    return len(value) if isinstance(value, list) else 0


def design_api(
    c_project_model: dict[str, Any],
    c_api_model: dict[str, Any],
    c_test_model: dict[str, Any],
) -> dict[str, Any]:
    kvdb_tests = c_test_model.get("kvdb_tests", [])
    tsdb_tests = c_test_model.get("tsdb_tests", [])
    standard_scenarios = c_test_model.get("standard_scenarios", [])
    scorer_standard_cases = c_test_model.get("scorer_standard_cases", [])
    if not isinstance(kvdb_tests, list):
        kvdb_tests = []
    if not isinstance(tsdb_tests, list):
        tsdb_tests = []
    if not isinstance(standard_scenarios, list):
        standard_scenarios = []
    if not isinstance(scorer_standard_cases, list):
        scorer_standard_cases = []

    kvdb_symbols = as_string_list(c_api_model, "kvdb_symbols")
    tsdb_symbols = as_string_list(c_api_model, "tsdb_symbols")
    modules = ["error", "storage"]
    if kvdb_symbols:
        modules.append("kvdb")
    if tsdb_symbols:
        modules.append("tsdb")

    kvdb_api = api_items_from_symbols("kvdb", kvdb_symbols)
    tsdb_api = api_items_from_symbols("tsdb", tsdb_symbols)
    c_to_rust_symbol_map = {
        item["c_symbols"][0]: item["rust"]
        for item in kvdb_api + tsdb_api
        if isinstance(item.get("c_symbols"), list) and item["c_symbols"]
    }
    core_types = [type_name_from_module(module) for module in modules]

    return {
        "stage": "DESIGN_RUST_API",
        "crate_name": "flashdb_rust",
        "modules": modules,
        "core_types": core_types,
        "traits": [],
        "error_model": {
            "type": "Error",
            "result_alias": "Result<T, Error>",
            "strategy": "Map C status and validation failures observed in the current API model into typed Rust Result values.",
        },
        "storage_model": {
            "implementations": [],
            "semantics": [
                "record_append",
                "reload_scan",
                "retain_valid_records",
            ],
        },
        "kvdb_api": kvdb_api,
        "tsdb_api": tsdb_api,
        "test_api": {
            "kvdb_tests": kvdb_tests,
            "tsdb_tests": tsdb_tests,
            "standard_scenarios": standard_scenarios,
            "scorer_standard_cases": scorer_standard_cases,
            "rust_test_files": [],
            "migration_strategy": "Translate dynamically derived scorer-facing cases into Rust integration tests against the designed safe API, using registered C tests as evidence.",
        },
        "c_to_rust_symbol_map": c_to_rust_symbol_map,
        "semantic_requirements": [
            "Preserve externally observable behavior from current C tests.",
            "Use safe Rust boundaries for public APIs.",
            "Keep source-to-Rust evidence in stage artifacts.",
        ],
        "source_evidence": {
            "source_files": count_list(c_project_model, "source_files"),
            "headers": count_list(c_project_model, "headers"),
            "test_files": count_list(c_project_model, "test_files"),
            "public_functions": count_list(c_api_model, "public_functions"),
            "kvdb_symbols": count_list(c_api_model, "kvdb_symbols"),
            "tsdb_symbols": count_list(c_api_model, "tsdb_symbols"),
            "registered_tests": count_list(c_test_model, "registered_tests"),
            "kvdb_tests": len(kvdb_tests),
            "tsdb_tests": len(tsdb_tests),
        },
        "generation_boundary": {
            "creates_rust_project": False,
            "writes_rust_source": False,
            "next_stage": "GENERATE_RUST_SCAFFOLD",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Design FlashDB safe Rust API from C fact models.")
    parser.add_argument("--project-model", required=True, help="Path to c_project_model.json.")
    parser.add_argument("--api-model", required=True, help="Path to c_api_model.json.")
    parser.add_argument("--test-model", required=True, help="Path to c_test_model.json.")
    parser.add_argument("--output", required=True, help="Path to write rust_api_design.json.")
    args = parser.parse_args(argv)

    design = design_api(
        load_json(Path(args.project_model)),
        load_json(Path(args.api_model)),
        load_json(Path(args.test_model)),
    )
    write_json(Path(args.output), design)
    print("DESIGN_RUST_API: DESIGN_WRITTEN")
    print(f"crate_name={design['crate_name']}")
    print(f"kvdb_api={len(design['kvdb_api'])}")
    print(f"tsdb_api={len(design['tsdb_api'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
