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


def rust_type_name_from_c_struct(name: str) -> str:
    parts = [part for part in name.split("_") if part]
    if parts and parts[0] == "fdb":
        parts = parts[1:]
    return "Fdb" + "".join(part[:1].upper() + part[1:] for part in parts)


def rust_ffi_base_type(c_type: str) -> str:
    normalized = re.sub(r"\bconst\b", "", c_type.replace("*", " ")).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    primitive = {
        "void": "std::ffi::c_void",
        "char": "std::ffi::c_char",
        "bool": "bool",
        "int": "std::ffi::c_int",
        "size_t": "usize",
        "uint8_t": "u8",
        "uint16_t": "u16",
        "uint32_t": "u32",
        "uint64_t": "u64",
        "int8_t": "i8",
        "int16_t": "i16",
        "int32_t": "i32",
        "int64_t": "i64",
        "fdb_err_t": "i32",
        "fdb_time_t": "i64",
    }
    if normalized in primitive:
        return primitive[normalized]
    if normalized.startswith("struct "):
        return rust_type_name_from_c_struct(normalized.split(" ", 1)[1])
    if normalized.endswith("_t") and normalized.startswith("fdb_"):
        return rust_type_name_from_c_struct(normalized[:-2])
    return "std::ffi::c_void"


def rust_ffi_type(raw_type: str, pointer_depth: int, is_const: bool) -> str:
    base = rust_ffi_base_type(raw_type)
    if pointer_depth <= 0:
        return "()" if base == "std::ffi::c_void" else base
    pointer = "*const" if is_const else "*mut"
    result = base
    for depth in range(pointer_depth):
        result = f"{pointer} {result}" if depth == 0 else f"*mut {result}"
    return result


def c_type_map_from_signatures(function_signatures: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, str]] = []
    for symbol, signature in sorted(function_signatures.items()):
        if not isinstance(signature, dict):
            continue
        return_type = signature.get("return_type")
        if isinstance(return_type, dict) and isinstance(return_type.get("raw"), str):
            raw = return_type["raw"]
            resolved.setdefault(
                raw,
                {
                    "c_type": raw,
                    "rust_ffi_type": rust_ffi_type(raw, raw.count("*"), "const" in raw.split()),
                    "category": return_type.get("category", "return"),
                    "source": f"function_signatures.{symbol}.return_type",
                },
            )
        params = signature.get("params")
        if not isinstance(params, list):
            continue
        for param in params:
            if not isinstance(param, dict) or not isinstance(param.get("raw_type"), str):
                continue
            raw = param["raw_type"]
            rust_type = rust_ffi_type(raw, int(param.get("pointer_depth", 0) or 0), bool(param.get("const")))
            if rust_type == "std::ffi::c_void" and raw not in {"void", "void *", "const void *"}:
                unresolved.append(
                    {
                        "symbol": symbol,
                        "c_type": raw,
                        "reason": "no safe ABI mapping rule for current C type",
                        "source": f"function_signatures.{symbol}.params[{param.get('index', '?')}]",
                    }
                )
                continue
            resolved.setdefault(
                raw,
                {
                    "c_type": raw,
                    "rust_ffi_type": rust_type,
                    "category": param.get("canonical", "param"),
                    "ownership": param.get("ownership", "unknown"),
                    "nullable": param.get("nullable", "unknown"),
                    "source": f"function_signatures.{symbol}.params[{param.get('index', '?')}]",
                },
            )
    return {
        "rules": [
            "primitive C integers and bool map to Rust FFI primitives",
            "typedef chains keep their raw C name and map through the current ABI rule",
            "struct pointers map to pointers to #[repr(C)] Rust facade structs",
            "const pointers map to *const; mutable pointers map to *mut",
            "unknown critical-path types must be reported as unresolved",
        ],
        "resolved": resolved,
        "unresolved": unresolved,
    }


def facade_functions_from_signatures(
    function_signatures: dict[str, Any],
    c_to_rust_symbol_map: dict[str, str],
) -> list[dict[str, Any]]:
    functions: list[dict[str, Any]] = []
    for symbol in sorted(c_to_rust_symbol_map):
        signature = function_signatures.get(symbol)
        if not isinstance(signature, dict):
            continue
        return_type = signature.get("return_type") if isinstance(signature.get("return_type"), dict) else {}
        raw_return = str(return_type.get("raw", "void"))
        params: list[dict[str, Any]] = []
        raw_params = signature.get("params")
        if isinstance(raw_params, list):
            for param in raw_params:
                if not isinstance(param, dict):
                    continue
                raw_type = str(param.get("raw_type", "void"))
                params.append(
                    {
                        "name": str(param.get("name", f"arg{len(params)}")),
                        "c_type": raw_type,
                        "rust_ffi_type": rust_ffi_type(raw_type, int(param.get("pointer_depth", 0) or 0), bool(param.get("const"))),
                        "safe_role": str(param.get("canonical", "param")),
                        "nullable": param.get("nullable", "unknown"),
                        "ownership": param.get("ownership", "unknown"),
                    }
                )
        functions.append(
            {
                "c_symbol": symbol,
                "rust_export": symbol,
                "source_signature": f"c_api_model.function_signatures.{symbol}",
                "return": {
                    "c_type": raw_return,
                    "rust_ffi_type": rust_ffi_type(raw_return, raw_return.count("*"), "const" in raw_return.split()),
                    "safe_mapping": str(return_type.get("category", "return")),
                },
                "params": params,
                "safe_target": c_to_rust_symbol_map[symbol],
                "required_by": ["c_runner", "scorer_case"],
            }
        )
    return functions


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


def all_semantic_obligations(c_test_model: dict[str, Any]) -> set[str]:
    obligations: set[str] = set()
    cases = c_test_model.get("scorer_standard_cases", [])
    if isinstance(cases, list):
        for case in cases:
            if not isinstance(case, dict):
                continue
            values = case.get("semantic_obligations", [])
            if isinstance(values, list):
                obligations.update(item for item in values if isinstance(item, str))
    return obligations


def design_test_api(
    kvdb_tests: list[Any],
    tsdb_tests: list[Any],
    standard_scenarios: list[Any],
    scorer_standard_cases: list[Any],
    obligations: set[str],
    owner_type: str,
) -> dict[str, Any]:
    observables: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []

    def add_observable(name: str, rust: str, reason: str) -> None:
        if not any(item["name"] == name for item in observables):
            observables.append(
                {
                    "name": name,
                    "rust": rust,
                    "test_observable": True,
                    "reason": reason,
                }
            )

    if "verify_addr_alignment" in obligations:
        add_observable("oldest_addr", f"{owner_type}::oldest_addr", "Required to verify C address alignment assertions.")
    if "verify_init_state" in obligations:
        add_observable("is_initialized", f"{owner_type}::is_initialized", "Required to verify C initialization state assertions.")
    if any(item.startswith("data_shape:cross_sector") or item.startswith("scenario:multi_status") for item in obligations):
        add_observable("sector_status", f"{owner_type}::sector_status", "Required to inspect sector boundary and status behavior in tests.")
    if "use_control_interface" in obligations:
        controls.append(
            {
                "name": "control",
                "rust": f"{owner_type}::control",
                "test_observable": True,
                "reason": "Required to preserve control-style setup observed in C tests.",
            }
        )

    return {
        "kvdb_tests": kvdb_tests,
        "tsdb_tests": tsdb_tests,
        "standard_scenarios": standard_scenarios,
        "scorer_standard_cases": scorer_standard_cases,
        "rust_test_files": [],
        "observables": observables,
        "controls": controls,
        "coverage_levels": {
            "api": "Rust test calls the API covered by the C scenario.",
            "assertion_semantic": "Rust assertions verify the same property class as C assertions.",
            "deep_semantic": "Rust test preserves C data shape, layout, and boundary conditions.",
        },
        "migration_strategy": "Translate dynamically derived scorer-facing cases into Rust integration tests against the designed safe API, using registered C tests as evidence.",
    }


def design_storage_constraints(c_project_model: dict[str, Any], c_api_model: dict[str, Any]) -> dict[str, Any]:
    macros = c_api_model.get("macros", [])
    source_files = c_project_model.get("source_files", [])
    macro_set = {item for item in macros if isinstance(item, str)} if isinstance(macros, list) else set()
    file_sources = [item for item in source_files if isinstance(item, str) and "file" in item.lower()] if isinstance(source_files, list) else []
    file_sector_mode = "FDB_USING_FILE_POSIX_MODE" in macro_set or bool(file_sources)
    if file_sector_mode:
        return {
            "backend": "file_sector_mode",
            "sector_file_pattern": "{dir}/{name}.fdb.{index}",
            "fd_cache_required": True,
            "requires_reload_scan": True,
        }
    return {
        "backend": "memory_or_custom",
        "sector_file_pattern": "",
        "fd_cache_required": False,
        "requires_reload_scan": True,
    }


def test_api_owner_type(modules: list[str]) -> str:
    for module in modules:
        if module not in {"error", "storage"}:
            return type_name_from_module(module)
    return type_name_from_module(modules[0] if modules else "api")


def design_c_abi_facade(c_api_model: dict[str, Any]) -> dict[str, Any]:
    structs: list[dict[str, Any]] = []
    raw_layouts = c_api_model.get("abi_layouts", [])
    if not isinstance(raw_layouts, list):
        raw_layouts = []
    for layout in raw_layouts:
        if not isinstance(layout, dict) or not isinstance(layout.get("name"), str):
            continue
        fields = layout.get("fields", [])
        active_macros = layout.get("active_macros", [])
        notes = ["Fields reflect active C preprocessor configuration from c_api_model.abi_layouts."]
        conditional_macros = [
            macro for macro in active_macros if isinstance(macro, str) and macro.startswith("FDB_USING_")
        ] if isinstance(active_macros, list) else []
        if conditional_macros:
            notes.append("Active layout macros: " + ", ".join(sorted(conditional_macros)))
        if layout.get("error"):
            notes.append(str(layout["error"]))
        c_name = layout["name"]
        is_opaque = c_name in ("fdb_kvdb", "fdb_tsdb")
        structs.append(
            {
                "c_name": c_name,
                "rust_name": rust_type_name_from_c_struct(c_name),
                "sizeof": layout.get("sizeof"),
                "alignof": layout.get("alignof"),
                "fields": fields if isinstance(fields, list) and not is_opaque else [],
                "opaque": is_opaque,
                "notes": notes,
            }
        )
    return {"structs": structs}


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
    obligations = all_semantic_obligations(c_test_model)
    c_to_rust_symbol_map = {
        item["c_symbols"][0]: item["rust"]
        for item in kvdb_api + tsdb_api
        if isinstance(item.get("c_symbols"), list) and item["c_symbols"]
    }
    core_types = [type_name_from_module(module) for module in modules]
    facade = design_c_abi_facade(c_api_model)
    raw_signatures = c_api_model.get("function_signatures")
    function_signatures = raw_signatures if isinstance(raw_signatures, dict) else {}
    facade["functions"] = facade_functions_from_signatures(function_signatures, c_to_rust_symbol_map)
    facade["c_type_map"] = c_type_map_from_signatures(function_signatures)

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
        "storage_constraints": design_storage_constraints(c_project_model, c_api_model),
        "c_abi_facade": facade,
        "kvdb_api": kvdb_api,
        "tsdb_api": tsdb_api,
        "test_api": design_test_api(
            kvdb_tests,
            tsdb_tests,
            standard_scenarios,
            scorer_standard_cases,
            obligations,
            test_api_owner_type(modules),
        ),
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

    # Generate ffi_manifest.json from c_abi_facade
    facade = design.get("c_abi_facade", {})
    functions = facade.get("functions", [])
    required_ffi_apis = sorted([f.get("c_symbol") for f in functions if isinstance(f, dict) and f.get("c_symbol")])
    observation_apis = sorted([
        f.get("c_symbol") for f in functions
        if isinstance(f, dict) and f.get("safe_role", "").startswith("observation_")
    ])
    ffi_manifest = {
        "required_ffi_apis": required_ffi_apis,
        "observation_apis": observation_apis,
        "ffi_mappings": [
            {
                f.get("c_symbol"): {
                    "rust_wrapper": f.get("rust_export"),
                    "rust_target": f.get("safe_target", ""),
                }
            }
            for f in functions
            if isinstance(f, dict) and f.get("c_symbol") and f.get("rust_export")
        ],
    }
    output_dir = Path(args.output).parent
    write_json(output_dir / "ffi_manifest.json", ffi_manifest)

    print("DESIGN_RUST_API: DESIGN_WRITTEN")
    print(f"crate_name={design['crate_name']}")
    print(f"kvdb_api={len(design['kvdb_api'])}")
    print(f"tsdb_api={len(design['tsdb_api'])}")
    print(f"ffi_manifest_apis={len(required_ffi_apis)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
