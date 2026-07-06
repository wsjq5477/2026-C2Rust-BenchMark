#!/usr/bin/env python3
"""Design the canonical safe Rust API from FlashDB C fact models.

This stage is intentionally a design artifact producer. It reads the C project,
API, and test models from BUILD_C_MODEL and writes rust_api_design.json. It must
not create the Rust crate or generate Rust source files.
"""

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


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def available_symbols(api_model: dict[str, Any]) -> set[str]:
    symbols = api_model.get("public_functions", [])
    if not isinstance(symbols, list):
        return set()
    return {item for item in symbols if isinstance(item, str)}


def present(candidates: list[str], symbols: set[str]) -> list[str]:
    """Keep only symbols seen in the C model, preserving canonical order."""

    return [name for name in candidates if name in symbols]


def api_item(
    name: str,
    rust_symbol: str,
    c_symbols: list[str],
    returns: str,
    notes: str,
    symbols: set[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "rust": rust_symbol,
        "c_symbols": present(c_symbols, symbols),
        "returns": returns,
        "notes": notes,
    }


def count_list(data: dict[str, Any], key: str) -> int:
    value = data.get(key, [])
    return len(value) if isinstance(value, list) else 0


def design_api(
    c_project_model: dict[str, Any],
    c_api_model: dict[str, Any],
    c_test_model: dict[str, Any],
) -> dict[str, Any]:
    symbols = available_symbols(c_api_model)
    kvdb_tests = c_test_model.get("kvdb_tests", [])
    tsdb_tests = c_test_model.get("tsdb_tests", [])
    if not isinstance(kvdb_tests, list):
        kvdb_tests = []
    if not isinstance(tsdb_tests, list):
        tsdb_tests = []

    kvdb_api = [
        api_item(
            "open",
            "KvDb::open",
            ["fdb_kvdb_init"],
            "Result<KvDb, FdbError>",
            "Create a KV database over a FlashStorage implementation.",
            symbols,
        ),
        api_item(
            "set",
            "KvDb::set",
            ["fdb_kv_set"],
            "Result<(), FdbError>",
            "Store a string value through append-style records.",
            symbols,
        ),
        api_item(
            "get",
            "KvDb::get",
            ["fdb_kv_get"],
            "Result<Option<String>, FdbError>",
            "Read the latest non-deleted string value.",
            symbols,
        ),
        api_item(
            "set_blob",
            "KvDb::set_blob",
            ["fdb_kv_set_blob", "fdb_kv_to_blob"],
            "Result<(), FdbError>",
            "Store binary payloads without exposing C buffers.",
            symbols,
        ),
        api_item(
            "get_blob",
            "KvDb::get_blob",
            ["fdb_kv_get_blob", "fdb_kv_get_obj"],
            "Result<Option<Vec<u8>>, FdbError>",
            "Return owned bytes so callers do not manage C lifetimes.",
            symbols,
        ),
        api_item(
            "delete",
            "KvDb::delete",
            ["fdb_kv_del"],
            "Result<(), FdbError>",
            "Represent deletion as a tombstone record.",
            symbols,
        ),
        api_item(
            "iterate",
            "KvDb::iter",
            ["fdb_kv_iterator_init", "fdb_kv_iterate"],
            "Result<impl Iterator<Item = (String, Vec<u8>)>, FdbError>",
            "Expose iteration as a safe Rust iterator.",
            symbols,
        ),
        api_item(
            "reload",
            "KvDb::reload",
            [],
            "Result<(), FdbError>",
            "Rebuild the runtime index by scanning storage.",
            symbols,
        ),
        api_item(
            "gc",
            "KvDb::gc",
            ["fdb_kvdb_check"],
            "Result<(), FdbError>",
            "Compact obsolete records while retaining latest valid values.",
            symbols,
        ),
    ]

    tsdb_api = [
        api_item(
            "open",
            "TsDb::open",
            ["fdb_tsdb_init"],
            "Result<TsDb, FdbError>",
            "Create a time-series database over a FlashStorage implementation.",
            symbols,
        ),
        api_item(
            "append",
            "TsDb::append",
            ["fdb_tsl_append", "fdb_tsl_append_with_ts"],
            "Result<(), FdbError>",
            "Append a time-series log record, with optional explicit timestamp.",
            symbols,
        ),
        api_item(
            "iter",
            "TsDb::iter",
            ["fdb_tsl_iter", "fdb_tsl_iter_reverse"],
            "Result<impl Iterator<Item = TslRecord>, FdbError>",
            "Expose forward and reverse traversal without callbacks.",
            symbols,
        ),
        api_item(
            "query_by_time",
            "TsDb::query_by_time",
            ["fdb_tsl_iter_by_time", "fdb_tsl_query_count"],
            "Result<Vec<TslRecord>, FdbError>",
            "Return matching records for a timestamp range.",
            symbols,
        ),
        api_item(
            "set_status",
            "TsDb::set_status",
            ["fdb_tsl_set_status"],
            "Result<(), FdbError>",
            "Update a record status through a typed enum boundary.",
            symbols,
        ),
        api_item(
            "clean",
            "TsDb::clean",
            ["fdb_tsl_clean"],
            "Result<(), FdbError>",
            "Remove stale log sectors according to FlashDB semantics.",
            symbols,
        ),
        api_item(
            "reload",
            "TsDb::reload",
            [],
            "Result<(), FdbError>",
            "Rebuild TSDB state by scanning storage.",
            symbols,
        ),
    ]

    c_to_rust_symbol_map = {
        "fdb_kvdb_init": "KvDb::open",
        "fdb_kvdb_deinit": "drop(KvDb)",
        "fdb_kv_set": "KvDb::set",
        "fdb_kv_get": "KvDb::get",
        "fdb_kv_set_blob": "KvDb::set_blob",
        "fdb_kv_get_blob": "KvDb::get_blob",
        "fdb_kv_get_obj": "KvDb::get_blob",
        "fdb_kv_del": "KvDb::delete",
        "fdb_kv_iterator_init": "KvDb::iter",
        "fdb_kv_iterate": "KvDb::iter",
        "fdb_kvdb_check": "KvDb::gc",
        "fdb_tsdb_init": "TsDb::open",
        "fdb_tsdb_deinit": "drop(TsDb)",
        "fdb_tsl_append": "TsDb::append",
        "fdb_tsl_append_with_ts": "TsDb::append",
        "fdb_tsl_iter": "TsDb::iter",
        "fdb_tsl_iter_reverse": "TsDb::iter_reverse",
        "fdb_tsl_iter_by_time": "TsDb::query_by_time",
        "fdb_tsl_query_count": "TsDb::count_by_time",
        "fdb_tsl_set_status": "TsDb::set_status",
        "fdb_tsl_clean": "TsDb::clean",
        "fdb_tsl_to_blob": "TslRecord::payload",
    }

    return {
        "stage": "DESIGN_RUST_API",
        "crate_name": "flashdb_rust",
        "modules": ["error", "flash", "kvdb", "tsdb"],
        "core_types": [
            "FlashStorage",
            "MemFlash",
            "FileFlash",
            "FdbError",
            "KvDb",
            "TsDb",
            "TslRecord",
        ],
        "traits": ["FlashStorage"],
        "error_model": {
            "type": "FdbError",
            "result_alias": "Result<T, FdbError>",
            "c_success": "FDB_NO_ERR",
            "strategy": "Map C status and validation failures into typed Rust Result values.",
        },
        "storage_model": {
            "trait": "FlashStorage",
            "implementations": ["MemFlash", "FileFlash"],
            "semantics": [
                "record_append",
                "tombstone_delete",
                "reload_scan",
                "gc_retain_latest",
            ],
        },
        "kvdb_api": kvdb_api,
        "tsdb_api": tsdb_api,
        "test_api": {
            "kvdb_tests": kvdb_tests,
            "tsdb_tests": tsdb_tests,
            "rust_test_files": ["kvdb_tests.rs", "tsdb_tests.rs", "equivalence_tests.rs"],
            "migration_strategy": "Translate C registered tests into Rust integration tests against the safe API.",
        },
        "c_to_rust_symbol_map": c_to_rust_symbol_map,
        "semantic_requirements": [
            "KVDB deletion must be persisted as tombstone behavior, not immediate erase.",
            "KVDB reload must scan storage and rebuild the latest-value index.",
            "KVDB garbage collection must retain the newest valid record for each key.",
            "TSDB append must preserve timestamp ordering facts used by query-by-time tests.",
            "TSDB iteration must avoid callback-style unsafe ownership in the public API.",
            "FlashStorage is the boundary for memory-backed and file-backed test storage.",
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
