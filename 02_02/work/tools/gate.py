#!/usr/bin/env python3
"""Stage gate checks for the FlashDB opencode workbench."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


WORKFLOW_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "workflow-contract.json"
try:
    WORKFLOW_CONTRACT = json.loads(WORKFLOW_CONTRACT_PATH.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise RuntimeError(f"cannot load workflow contract {WORKFLOW_CONTRACT_PATH}: {exc}") from exc
PACKET_LIMITS = WORKFLOW_CONTRACT.get("packet_limits", {})
CONTRACT_STAGES = WORKFLOW_CONTRACT.get("stages", {})


REQUIRED_INIT_STATE_KEYS = {
    "current_stage",
    "completed_stages",
    "checkpoint",
    "rust_project_path",
    "input_path_candidates",
    "build_status",
    "test_status",
    "unsafe_ratio",
    "repair_rounds",
    "blocked_issues",
}

REQUIRED_READ_STATE_KEYS = REQUIRED_INIT_STATE_KEYS | {
    "input_path",
    "input_manifest",
}

REQUIRED_MODEL_STATE_KEYS = REQUIRED_READ_STATE_KEYS | {
    "c_project_model",
    "c_api_model",
    "c_test_model",
}

REQUIRED_DESIGN_STATE_KEYS = REQUIRED_MODEL_STATE_KEYS | {
    "rust_api_design",
}

REQUIRED_C_CROSS_STATE_KEYS = REQUIRED_DESIGN_STATE_KEYS

REQUIRED_TEST_STATE_KEYS = REQUIRED_DESIGN_STATE_KEYS | {
    "rust_test_mapping",
}

VALID_MATRIX_VALUES = {"baseline", "pass", "fail", "not_run", "not_supported", "pending", "parse_failed", "unresolved"}
VALID_DIAGNOSES = {
    "rust_implementation_matches_c_baseline_for_scenario",
    "rust_implementation_failed_c_baseline",
    "c_cross_harness_not_supported",
    "blocked_before_rust_test_migration",
    "rust_test_migration_pending",
    "rust_staticlib_build_failed",
    "c_abi_layout_mismatch",
    "c_runner_link_failed",
    "c_runner_runtime_failed",
    "c_runner_timeout",
    "c_test_case_failed",
    "c_cross_result_parse_failed",
    "c_model_signature_gap",
}

VALID_FAILURE_LAYERS = {"model", "build", "layout", "link", "full", "assertion", "timeout", "protocol"}
VALID_HANDOFFS = {"none", "controller", "c-analyzer", "rust-implementer", "test-migrator", "repairer"}

VALID_TEST_TRIAGE_CLASSIFICATIONS = {
    "test_oracle_suspect",
    "rust_impl_suspect",
    "harness_suspect",
    "insufficient_evidence",
}


RUST_STRICT_KEYWORDS = frozenset({
    "as", "break", "const", "continue", "crate", "else", "enum", "extern",
    "false", "fn", "for", "if", "impl", "in", "let", "loop", "match", "mod",
    "move", "mut", "pub", "ref", "return", "self", "static", "struct",
    "super", "trait", "true", "type", "unsafe", "use", "where", "while",
    "async", "await", "dyn",
})


def safe_rust_ident(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not ident:
        ident = "item"
    if ident[0].isdigit():
        ident = f"item_{ident}"
    if ident in RUST_STRICT_KEYWORDS:
        ident = f"r#{ident}"
    return ident


def safe_rust_type(name: str, fallback: str = "GeneratedType") -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    value = "".join(part[:1].upper() + part[1:] for part in parts)
    if not value:
        value = fallback
    if value[0].isdigit():
        value = f"{fallback}{value}"
    return value


REQUIRED_SUBAGENTS = {
    "c-analyzer": ["READ_C_PROJECT", "BUILD_C_MODEL", "DESIGN_RUST_API"],
    "rust-implementer": ["GENERATE_RUST_SCAFFOLD", "REWRITE_CORE_MODULES", "VERIFY_RUST_WITH_C_TESTS"],
    "test-migrator": ["MIGRATE_TESTS"],
    "repairer": ["BUILD_TEST_REPAIR"],
}


def collect_obligations(test_model: dict[str, Any]) -> set[str]:
    obligations: set[str] = set()
    cases = test_model.get("scorer_standard_cases")
    if isinstance(cases, list):
        for case in cases:
            if not isinstance(case, dict):
                continue
            values = case.get("semantic_obligations")
            if isinstance(values, list):
                obligations.update(item for item in values if isinstance(item, str))
    return obligations


def names_from_contract_items(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    names: set[str] = set()
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
        elif isinstance(item, str):
            names.add(item)
    return names


def check_design_test_contracts(design: dict[str, Any], test_model: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    obligations = collect_obligations(test_model)
    test_api = design.get("test_api")
    if not isinstance(test_api, dict):
        return ["rust_api_design.json test_api must be an object"]
    observables = names_from_contract_items(test_api.get("observables"))
    controls = names_from_contract_items(test_api.get("controls"))

    if "verify_addr_alignment" in obligations and "oldest_addr" not in observables:
        errors.append("rust_api_design.json test_api missing observable oldest_addr for verify_addr_alignment")
    if "verify_init_state" in obligations and "is_initialized" not in observables:
        errors.append("rust_api_design.json test_api missing observable is_initialized for verify_init_state")
    if any(item.startswith("data_shape:cross_sector") or item == "scenario:multi_status_filter" for item in obligations):
        if "sector_status" not in observables:
            errors.append("rust_api_design.json test_api missing observable sector_status for sector/status obligations")
    if "use_control_interface" in obligations and "control" not in controls:
        errors.append("rust_api_design.json test_api missing control interface for use_control_interface")
    if any(item.startswith("data_shape:cross_sector") for item in obligations):
        storage_constraints = design.get("storage_constraints")
        if not isinstance(storage_constraints, dict) or storage_constraints.get("backend") != "file_sector_mode":
            errors.append("rust_api_design.json storage_constraints.backend must be file_sector_mode for cross-sector obligations")
    return errors


def check_abi_layout_contract(api_model: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    layouts = api_model.get("abi_layouts")
    if not isinstance(layouts, list) or not layouts:
        return ["c_api_model.json abi_layouts must be a non-empty list"]
    names: set[str] = set()
    for index, layout in enumerate(layouts, start=1):
        if not isinstance(layout, dict):
            errors.append(f"c_api_model.json abi_layouts entry {index} must be an object")
            continue
        name = layout.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"c_api_model.json abi_layouts entry {index} must include name")
            continue
        if name in names:
            errors.append(f"c_api_model.json abi_layouts duplicate struct {name}")
        names.add(name)
        if layout.get("error"):
            errors.append(f"c_api_model.json abi_layouts {name} has extractor error: {layout.get('error')}")
        dependency_of = layout.get("dependency_of")
        if dependency_of is not None and (
            not isinstance(dependency_of, list)
            or not dependency_of
            or not all(isinstance(item, str) and item for item in dependency_of)
        ):
            errors.append(f"c_api_model.json abi_layouts {name} dependency_of must be a non-empty string list")
        if not isinstance(layout.get("sizeof"), int) or layout.get("sizeof") <= 0:
            errors.append(f"c_api_model.json abi_layouts {name} must include positive sizeof")
        if not isinstance(layout.get("alignof"), int) or layout.get("alignof") <= 0:
            errors.append(f"c_api_model.json abi_layouts {name} must include positive alignof")
        fields = layout.get("fields")
        if not isinstance(fields, list) or not fields:
            errors.append(f"c_api_model.json abi_layouts {name} fields must be a non-empty list")
            continue
        field_names: set[str] = set()
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                errors.append(f"c_api_model.json abi_layouts {name} fields must include field names")
                continue
            field_name = field["name"]
            if field_name in field_names:
                errors.append(f"c_api_model.json abi_layouts {name} duplicate field {field_name}")
            field_names.add(field_name)
            if not isinstance(field.get("offset"), int) or field.get("offset") < 0:
                errors.append(f"c_api_model.json abi_layouts {name}.{field_name} must include offset")
            if not isinstance(field.get("sizeof"), int) or field.get("sizeof") <= 0:
                errors.append(f"c_api_model.json abi_layouts {name}.{field_name} must include positive sizeof")
    return errors


def check_deterministic_abi_field_contract(api_model: dict[str, Any]) -> list[str]:
    """Require the richer compiler-backed field shape used by new runs."""
    errors: list[str] = []
    layouts = api_model.get("abi_layouts")
    if not isinstance(layouts, list):
        return errors
    valid_kinds = {
        "scalar_or_typedef", "pointer", "array", "anonymous_struct",
        "anonymous_union", "named_struct", "named_union",
        "function_pointer", "bitfield",
    }
    for layout in layouts:
        if not isinstance(layout, dict):
            continue
        struct_name = str(layout.get("name") or "<unknown>")
        fields = layout.get("fields")
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "<unknown>")
            prefix = f"c_api_model.json abi_layouts {struct_name}.{field_name}"
            if not isinstance(field.get("raw_declarator"), str) or not field.get("raw_declarator"):
                errors.append(f"{prefix} must preserve raw_declarator")
            if field.get("kind") not in valid_kinds:
                errors.append(f"{prefix} has invalid/missing deterministic kind")
            if not isinstance(field.get("array_extents"), list):
                errors.append(f"{prefix} array_extents must be a list")
            if "pointee" not in field or "callback_signature" not in field:
                errors.append(f"{prefix} must preserve pointee and callback_signature keys")
            if field.get("kind") != "bitfield" and (
                not isinstance(field.get("alignof"), int) or field.get("alignof") <= 0
            ):
                errors.append(f"{prefix} must include compiler-confirmed field alignof")
    return errors


def check_ordered_scenario_ir(test_model: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sequences: dict[str, list[tuple[Any, Any, Any]]] = {}
    for collection, id_key in [("standard_scenarios", "id"), ("scorer_standard_cases", "scenario_id")]:
        rows = test_model.get(collection)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            scenario_id = str(row.get(id_key) or "<unknown>")
            raw_steps = row.get("scenario_ir")
            steps = [item for item in raw_steps if isinstance(item, dict)] if isinstance(raw_steps, list) else []
            if not steps:
                errors.append(f"c_test_model.json {collection}.{scenario_id} must include ordered scenario_ir")
                continue
            orders = [item.get("order") for item in steps]
            if orders != list(range(1, len(steps) + 1)):
                errors.append(f"scenario_ir order must be contiguous for {scenario_id} in {collection}")
            step_ids = [item.get("id") for item in steps]
            if not all(isinstance(item, str) and item for item in step_ids) or len(set(step_ids)) != len(step_ids):
                errors.append(f"scenario_ir step ids must be present and unique for {scenario_id} in {collection}")
            if steps[0].get("kind") != "invoke_test":
                errors.append(f"scenario_ir must begin with invoke_test for {scenario_id} in {collection}")
            for step in steps:
                if not isinstance(step.get("source_function"), str) or not step.get("source_function"):
                    errors.append(f"scenario_ir step lacks source_function for {scenario_id}")
                    break
                source_line = step.get("source_line")
                if source_line is not None and (not isinstance(source_line, int) or source_line <= 0):
                    errors.append(f"scenario_ir step has invalid source_line for {scenario_id}")
                    break
            sequence = [(item.get("kind"), item.get("call"), item.get("call_type")) for item in steps]
            previous = sequences.setdefault(scenario_id, sequence)
            if previous != sequence:
                errors.append(f"standard/scorer scenario_ir disagree for {scenario_id}")
    return errors


def check_structured_implementation_requirements(
    design: dict[str, Any], test_model: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    requirements = design.get("implementation_requirements")
    if not isinstance(requirements, list) or not requirements:
        return ["rust_api_design.json implementation_requirements must be a non-empty list"]
    identifiers = {
        item.get("id") for item in requirements
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    scenario_ids = {
        item.get("scenario_id") for item in test_model.get("scorer_standard_cases", [])
        if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)
    } if isinstance(test_model.get("scorer_standard_cases"), list) else set()
    graph: dict[str, list[str]] = {}
    for item in requirements:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            errors.append("implementation_requirements entries must include id")
            continue
        identifier = item["id"]
        for key in ["symbols", "acceptance_scenarios", "suggested_files", "dependency_ids"]:
            values = item.get(key)
            if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
                errors.append(f"implementation requirement {identifier} {key} must be a string list")
        accepted = item.get("acceptance_scenarios")
        if isinstance(accepted, list):
            unknown = sorted(set(accepted) - scenario_ids)
            if unknown:
                errors.append(f"implementation requirement {identifier} has unknown acceptance scenarios: {', '.join(unknown)}")
        files = item.get("suggested_files")
        if isinstance(files, list) and any(
            not path.startswith("src/") or ".." in Path(path).parts
            for path in files if isinstance(path, str)
        ):
            errors.append(f"implementation requirement {identifier} suggested_files must stay under src/")
        dependencies = item.get("dependency_ids")
        graph[identifier] = [value for value in dependencies if isinstance(value, str)] if isinstance(dependencies, list) else []
        unknown_dependencies = sorted(set(graph[identifier]) - identifiers)
        if unknown_dependencies:
            errors.append(f"implementation requirement {identifier} has unknown dependencies: {', '.join(unknown_dependencies)}")
        if identifier in graph[identifier]:
            errors.append(f"implementation requirement {identifier} cannot depend on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> bool:
        if identifier in visiting:
            return True
        if identifier in visited:
            return False
        visiting.add(identifier)
        cyclic = any(visit(dependency) for dependency in graph.get(identifier, []) if dependency in graph)
        visiting.remove(identifier)
        visited.add(identifier)
        return cyclic

    if any(visit(identifier) for identifier in graph):
        errors.append("implementation_requirements dependency_ids must form an acyclic graph")
    return errors


def required_signature_symbols(api_model: dict[str, Any], test_model: dict[str, Any]) -> set[str]:
    public = {
        item for item in api_model.get("public_functions", [])
        if isinstance(item, str)
    } if isinstance(api_model.get("public_functions"), list) else set()
    required = set(public)
    cases = test_model.get("scorer_standard_cases")
    if isinstance(cases, list):
        for case in cases:
            if not isinstance(case, dict):
                continue
            obligations = case.get("semantic_obligations")
            if isinstance(obligations, list):
                for obligation in obligations:
                    if isinstance(obligation, str) and obligation.startswith("calls:"):
                        symbol = obligation.split(":", 1)[1]
                        if symbol in public:
                            required.add(symbol)
            facts = case.get("semantic_facts")
            observed = facts.get("observed_c_symbols") if isinstance(facts, dict) else None
            if isinstance(observed, list):
                required.update(symbol for symbol in observed if isinstance(symbol, str) and symbol in public)
    return required


def check_function_signature_contract(api_model: dict[str, Any], test_model: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    signatures = api_model.get("function_signatures")
    if not isinstance(signatures, dict) or not signatures:
        errors.append("c_api_model.json function_signatures must be a non-empty object")
        signatures = {}

    required_symbols = required_signature_symbols(api_model, test_model)
    for symbol in sorted(required_symbols):
        signature = signatures.get(symbol)
        if not isinstance(signature, dict):
            errors.append(f"c_api_model.json function_signatures must cover required symbol {symbol}")
            continue
        if signature.get("name") != symbol:
            errors.append(f"c_api_model.json function_signatures.{symbol}.name must equal {symbol}")
        if not isinstance(signature.get("declaration"), str) or not signature["declaration"].strip().endswith(";"):
            errors.append(f"c_api_model.json function_signatures.{symbol}.declaration must be a C declaration")
        return_type = signature.get("return_type")
        if not isinstance(return_type, dict) or not isinstance(return_type.get("raw"), str) or not return_type.get("raw"):
            errors.append(f"c_api_model.json function_signatures.{symbol}.return_type.raw must be present")
        elif "unresolved:" in str(return_type.get("canonical", "")):
            errors.append(f"c_api_model.json required return type is unresolved for {symbol}")
        params = signature.get("params")
        if not isinstance(params, list):
            errors.append(f"c_api_model.json function_signatures.{symbol}.params must be a list")
            continue
        indexes = [param.get("index") for param in params if isinstance(param, dict)]
        if indexes != list(range(len(params))):
            errors.append(f"c_api_model.json function_signatures.{symbol}.params indexes must be contiguous")
        for param in params:
            if not isinstance(param, dict):
                errors.append(f"c_api_model.json function_signatures.{symbol}.params entries must be objects")
                continue
            for key in ["name", "raw_type", "canonical", "pointer_depth", "const"]:
                if key not in param:
                    errors.append(f"c_api_model.json function_signatures.{symbol}.params[{param.get('index', '?')}] missing {key}")
            if "unresolved:" in str(param.get("canonical", "")):
                errors.append(
                    f"c_api_model.json required parameter type is unresolved for {symbol} "
                    f"param {param.get('name', param.get('index', '?'))}"
                )
            raw_type = param.get("raw_type")
            typedefs = api_model.get("typedef_map")
            typedef = typedefs.get(raw_type) if isinstance(typedefs, dict) and isinstance(raw_type, str) else None
            if isinstance(typedef, dict) and int(typedef.get("pointer_depth", 0) or 0) > 0:
                if int(param.get("pointer_depth", 0) or 0) < int(typedef["pointer_depth"]):
                    errors.append(
                        f"c_api_model.json pointer typedef depth was not expanded for {symbol} param {param.get('name')}"
                    )

    for field in ["unresolved_signatures", "unresolved_types"]:
        unresolved = api_model.get(field, [])
        if not isinstance(unresolved, list):
            errors.append(f"c_api_model.json {field} must be a list")
            continue
        for index, item in enumerate(unresolved):
            if not isinstance(item, dict):
                errors.append(f"c_api_model.json {field}[{index}] must be an object")
                continue
            for key in ["symbol", "reason", "source"]:
                if not isinstance(item.get(key), str) or not item.get(key):
                    errors.append(f"c_api_model.json {field}[{index}] must include {key}")
            symbol = item.get("symbol")
            if isinstance(symbol, str) and symbol in required_symbols:
                errors.append(f"c_api_model.json {field} cannot contain required symbol {symbol}")
    return errors


def check_c_abi_facade_contract(design: dict[str, Any], api_model: dict[str, Any]) -> list[str]:
    layouts = api_model.get("abi_layouts")
    if not isinstance(layouts, list) or not layouts:
        return []
    expected = {
        layout.get("name")
        for layout in layouts
        if isinstance(layout, dict) and isinstance(layout.get("name"), str)
    }
    facade = design.get("c_abi_facade")
    structs = facade.get("structs") if isinstance(facade, dict) else None
    if not isinstance(structs, list):
        return ["rust_api_design.json c_abi_facade.structs must cover c_api_model.json abi_layouts"]
    actual = {
        item.get("c_name")
        for item in structs
        if isinstance(item, dict) and isinstance(item.get("c_name"), str)
    }
    errors: list[str] = []
    if expected != actual:
        errors.append("rust_api_design.json c_abi_facade.structs must cover c_api_model.json abi_layouts")
    for item in structs:
        if not isinstance(item, dict) or not isinstance(item.get("c_name"), str):
            errors.append("rust_api_design.json c_abi_facade.structs entries must include c_name")
            continue
        c_name = item["c_name"]
        if not isinstance(item.get("rust_name"), str) or not item.get("rust_name"):
            errors.append(f"rust_api_design.json c_abi_facade {c_name} must include rust_name")
        if not isinstance(item.get("sizeof"), int) or item.get("sizeof") <= 0:
            errors.append(f"rust_api_design.json c_abi_facade {c_name} must include positive sizeof")
        if not isinstance(item.get("alignof"), int) or item.get("alignof") <= 0:
            errors.append(f"rust_api_design.json c_abi_facade {c_name} must include positive alignof")
        if not isinstance(item.get("fields"), list) or not item.get("fields"):
            errors.append(f"rust_api_design.json c_abi_facade {c_name} fields must be a non-empty list")
        if not isinstance(item.get("notes"), list) or not item.get("notes"):
            errors.append(f"rust_api_design.json c_abi_facade {c_name} notes must be a non-empty list")

    symbol_map = design.get("c_to_rust_symbol_map")
    mapped_symbols = set(symbol_map) if isinstance(symbol_map, dict) else set()
    required_symbols = mapped_symbols | {
        item
        for key in ["common_symbols", "kvdb_symbols", "tsdb_symbols"]
        for item in api_model.get(key, [])
        if isinstance(item, str)
    }
    signatures = api_model.get("function_signatures")
    if isinstance(signatures, dict):
        required_symbols &= set(signatures)

    functions = facade.get("functions") if isinstance(facade, dict) else None
    if not isinstance(functions, list):
        errors.append("rust_api_design.json c_abi_facade.functions must be a list")
        functions = []
    actual_functions = {
        item.get("c_symbol"): item
        for item in functions
        if isinstance(item, dict) and isinstance(item.get("c_symbol"), str)
    }
    for symbol in sorted(required_symbols):
        function = actual_functions.get(symbol)
        if not isinstance(function, dict):
            errors.append(f"rust_api_design.json c_abi_facade.functions must cover required symbol {symbol}")
            continue
        if function.get("rust_export") != symbol:
            errors.append(f"rust_api_design.json c_abi_facade.functions {symbol} rust_export must equal c_symbol")
        if function.get("source_signature") != f"c_api_model.function_signatures.{symbol}":
            errors.append(f"rust_api_design.json c_abi_facade.functions {symbol} must bind source_signature")
        return_info = function.get("return")
        if not isinstance(return_info, dict) or not isinstance(return_info.get("rust_ffi_type"), str) or not return_info.get("rust_ffi_type"):
            errors.append(f"rust_api_design.json c_abi_facade.functions {symbol} return.rust_ffi_type must be present")
        else:
            signature = signatures.get(symbol) if isinstance(signatures, dict) else None
            c_return = signature.get("return_type") if isinstance(signature, dict) else None
            if isinstance(c_return, dict) and c_return.get("raw") != "void" and return_info.get("rust_ffi_type") == "()":
                errors.append(f"rust_api_design.json {symbol} maps non-void C return to Rust ()")
        params = function.get("params")
        if not isinstance(params, list):
            errors.append(f"rust_api_design.json c_abi_facade.functions {symbol} params must be a list")
        else:
            for index, param in enumerate(params):
                if not isinstance(param, dict):
                    errors.append(f"rust_api_design.json c_abi_facade.functions {symbol} params[{index}] must be an object")
                    continue
                for key in ["name", "c_type", "rust_ffi_type"]:
                    if not isinstance(param.get(key), str) or not param.get(key):
                        errors.append(f"rust_api_design.json c_abi_facade.functions {symbol} params[{index}] must include {key}")
                c_type = param.get("c_type")
                rust_type = str(param.get("rust_ffi_type") or "")
                typedefs = api_model.get("typedef_map")
                typedef = typedefs.get(c_type) if isinstance(typedefs, dict) and isinstance(c_type, str) else None
                if isinstance(typedef, dict):
                    category = typedef.get("category")
                    if int(typedef.get("pointer_depth", 0) or 0) > 0 and category != "function_pointer" and not rust_type.startswith("*"):
                        errors.append(f"rust_api_design.json {symbol} must map pointer typedef {c_type} to a Rust pointer")
                    if category == "function_pointer" and not rust_type.startswith("Option<unsafe extern \"C\" fn("):
                        errors.append(f"rust_api_design.json {symbol} must map callback typedef {c_type} to a typed callback")

    type_map = facade.get("c_type_map") if isinstance(facade, dict) else None
    if not isinstance(type_map, dict):
        errors.append("rust_api_design.json c_abi_facade.c_type_map must be an object")
    else:
        if not isinstance(type_map.get("rules"), list):
            errors.append("rust_api_design.json c_abi_facade.c_type_map.rules must be a list")
        if not isinstance(type_map.get("resolved"), dict):
            errors.append("rust_api_design.json c_abi_facade.c_type_map.resolved must be an object")
        unresolved = type_map.get("unresolved")
        if not isinstance(unresolved, list):
            errors.append("rust_api_design.json c_abi_facade.c_type_map.unresolved must be a list")
        else:
            for index, item in enumerate(unresolved):
                if not isinstance(item, dict):
                    errors.append(f"rust_api_design.json c_abi_facade.c_type_map.unresolved[{index}] must be an object")
                    continue
                symbol = item.get("symbol")
                if isinstance(symbol, str) and symbol in required_symbols:
                    errors.append(f"rust_api_design.json c_abi_facade.c_type_map.unresolved cannot contain required symbol {symbol}")
    return errors


def is_c_cross_owned_log_path(log_path: str) -> bool:
    candidate = Path(log_path)
    if candidate.is_absolute():
        return False
    parts = candidate.parts
    if len(parts) < 4 or parts[0] != "logs" or parts[1] != "trace" or parts[2] != "c-cross":
        return False
    return ".." not in parts


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"missing {path.name}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON in {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} must contain a JSON object"
    return data, None


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None, f"missing {path.name}"
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            return None, f"invalid JSONL in {path}:{line_no}: {exc}"
        if not isinstance(data, dict):
            return None, f"{path}:{line_no} must contain a JSON object"
        rows.append(data)
    return rows, None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt_path_allowed(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if path == prefix or path.startswith(prefix + "/"):
                return True
        elif fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def _receipt_pattern_within(candidate: str, allowed_patterns: list[str]) -> bool:
    if candidate in {"", "*", "**", "/"} or Path(candidate).is_absolute() or ".." in Path(candidate).parts:
        return False
    probe = candidate[:-3].rstrip("/") + "/__scope_probe__" if candidate.endswith("/**") else candidate
    return _receipt_path_allowed(probe, allowed_patterns)


def check_stage_receipt(root: Path, stage: str) -> list[str]:
    """Validate controller-owned evidence when the transactional contract is active.

    Older traces do not carry ``controller_contract_version`` and remain valid
    under their original gate contract.  New traces cannot claim completion by
    editing workflow_state.json alone: a same-root receipt, changed-file set,
    and content hashes are required.
    """
    state, state_error = load_json(root / "logs" / "trace" / "workflow_state.json")
    if state_error or not isinstance(state, dict) or not state.get("controller_contract_version"):
        return []
    # INIT_WORKSPACE is created directly and atomically by workflowctl init;
    # transactional receipts apply to delegated stages after initialization.
    if stage == "INIT_WORKSPACE":
        return []

    receipt_path = root / "logs" / "trace" / "stage-receipts" / f"{stage}.json"
    receipt, receipt_error = load_json(receipt_path)
    if receipt_error:
        return [f"transactional stage receipt: {receipt_error}"]
    assert isinstance(receipt, dict)
    errors: list[str] = []
    if receipt.get("contract_version") != state.get("controller_contract_version"):
        errors.append("stage receipt contract_version must match workflow_state.json")
    if receipt.get("stage") != stage:
        errors.append(f"stage receipt must identify {stage}")
    root_identity = receipt.get("root")
    if not isinstance(root_identity, dict) or root_identity.get("canonical") != str(root.resolve()):
        errors.append("stage receipt must come from this canonical workbench root")
    else:
        stat = root.stat()
        if root_identity.get("device") != stat.st_dev or root_identity.get("inode") != stat.st_ino:
            errors.append("stage receipt root identity does not match this worktree")
    if receipt.get("status") not in {"ready_for_gate", "pass"}:
        errors.append("stage receipt status must be ready_for_gate or pass")
    if receipt.get("unexpected_changes") not in ([], None):
        errors.append("stage receipt contains protected or out-of-scope changes")
    run_id = receipt.get("run_id")
    nonce_hash = receipt.get("nonce_sha256")
    if not isinstance(run_id, str) or not run_id:
        errors.append("stage receipt must include run_id")
    if not isinstance(nonce_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", nonce_hash):
        errors.append("stage receipt must include a hashed run nonce")

    run_rel = receipt.get("run_file")
    if not isinstance(run_rel, str) or not run_rel.startswith(f"logs/trace/stage-runs/{stage}/"):
        errors.append("stage receipt must reference its controller stage-run record")
        run = None
    else:
        run, run_error = load_json(root / run_rel)
        if run_error:
            errors.append(f"stage run record: {run_error}")
            run = None
        else:
            if run.get("run_id") != run_id or run.get("stage") != stage:
                errors.append("stage run record identity does not match receipt")
            run_hash = receipt.get("run_file_sha256")
            if not isinstance(run_hash, str) or _file_sha256(root / run_rel) != run_hash:
                errors.append("stage run record hash does not match receipt")
            run_nonce = run.get("nonce")
            if not isinstance(run_nonce, str) or hashlib.sha256(run_nonce.encode("utf-8")).hexdigest() != nonce_hash:
                errors.append("stage receipt nonce does not match controller stage-run record")
            for key in ("allowed_paths", "required_outputs", "task_packet", "task_packet_sha256", "baseline_digest"):
                if receipt.get(key) != run.get(key):
                    errors.append(f"stage receipt {key} does not match controller stage-run record")

    required = receipt.get("required_outputs")
    hashes = receipt.get("artifact_hashes")
    if not isinstance(required, list) or not required:
        errors.append("stage receipt must include required_outputs")
        required = []
    if not isinstance(hashes, dict):
        errors.append("stage receipt must include artifact_hashes")
        hashes = {}
    stage_contract = CONTRACT_STAGES.get(stage) if isinstance(CONTRACT_STAGES, dict) else None
    contract_required = stage_contract.get("required_outputs") if isinstance(stage_contract, dict) else []
    if isinstance(contract_required, list) and not set(contract_required).issubset(set(required)):
        errors.append("stage receipt removed workflow-contract required outputs")
    for rel in required:
        if not isinstance(rel, str) or not rel or ".." in Path(rel).parts:
            errors.append("stage receipt required_outputs must be safe relative paths")
            continue
        path = root / rel
        if not path.is_file():
            errors.append(f"stage receipt required output is missing: {rel}")
            continue
        # workflow_state is intentionally mutable after gate routing.  Its
        # existence/schema is validated by the stage-specific gate itself.
        if rel.endswith("workflow_state.json"):
            continue
        expected = hashes.get(rel)
        if not isinstance(expected, str) or _file_sha256(path) != expected:
            errors.append(f"stage receipt artifact changed after commit: {rel}")
    changed_files = receipt.get("changed_files")
    allowed_paths = receipt.get("allowed_paths")
    if not isinstance(changed_files, list) or not isinstance(allowed_paths, list):
        errors.append("stage receipt must include changed_files and allowed_paths")
    else:
        contract_allowed = stage_contract.get("allowed_paths") if isinstance(stage_contract, dict) else []
        if not isinstance(contract_allowed, list) or any(
            not isinstance(item, str) or not _receipt_pattern_within(item, contract_allowed)
            for item in allowed_paths
        ):
            errors.append("stage receipt allowed_paths exceed workflow contract")
        unsafe_changes = [
            item
            for item in changed_files
            if not isinstance(item, str)
            or not item
            or ".." in Path(item).parts
            or not _receipt_path_allowed(item, allowed_paths)
        ]
        if unsafe_changes:
            errors.append("stage receipt changed_files exceed allowed_paths")
        changed_hashes = receipt.get("changed_file_hashes")
        if not isinstance(changed_hashes, dict):
            errors.append("stage receipt must include changed_file_hashes")
        else:
            for item in changed_files:
                if not isinstance(item, str):
                    continue
                path = root / item
                if path.is_file() and not path.is_symlink():
                    expected = changed_hashes.get(item)
                    if not isinstance(expected, str) or _file_sha256(path) != expected:
                        errors.append(f"stage receipt changed-file hash mismatch: {item}")
    packet_rel = receipt.get("task_packet")
    if not isinstance(packet_rel, str) or not packet_rel:
        errors.append("stage receipt must reference a bounded task packet")
    else:
        packet, packet_error = load_json(root / packet_rel)
        if packet_error:
            errors.append(f"task packet: {packet_error}")
        else:
            packet_hash = receipt.get("task_packet_sha256")
            if not isinstance(packet_hash, str) or _file_sha256(root / packet_rel) != packet_hash:
                errors.append("task packet hash does not match controller stage-run record")
            if packet.get("stage") != stage:
                errors.append("task packet stage must match receipt stage")
            packet_allowed = packet.get("allowed_modification_paths")
            if not isinstance(packet_allowed, list) or packet_allowed != allowed_paths:
                errors.append("task packet allowed paths must match the committed stage scope")
            requirements = packet.get("requirements")
            scenarios = packet.get("scenarios")
            max_requirements = int(PACKET_LIMITS.get("max_requirements", 12))
            max_scenarios = int(PACKET_LIMITS.get("max_scenarios", 3))
            max_steps = int(PACKET_LIMITS.get("max_scenario_steps", 16))
            if not isinstance(requirements, list) or len(requirements) > max_requirements:
                errors.append(f"task packet requirements must be a bounded list of at most {max_requirements}")
            if not isinstance(scenarios, list) or len(scenarios) > max_scenarios:
                errors.append(f"task packet scenarios must be a bounded list of at most {max_scenarios}")
            elif any(
                not isinstance(item, dict)
                or not isinstance(item.get("scenario_ir"), list)
                or len(item["scenario_ir"]) > max_steps
                for item in scenarios
            ):
                errors.append(f"task packet scenario_ir must be present and capped at {max_steps} steps")
            completion = packet.get("completion_contract")
            if not isinstance(completion, dict) or completion.get("owner") != "workflowctl":
                errors.append("task packet completion must be owned by workflowctl")
    return errors


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def check_subagent_evidence(root: Path, required_agents: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    trace = root / "logs" / "trace"
    state, state_error = load_json(trace / "workflow_state.json")
    controller_mode = not state_error and bool(state.get("controller_contract_version"))
    registry, registry_error = load_json(trace / "agent-registry.json")
    if registry_error:
        errors.append(f"agent-registry.json: {registry_error}")
    else:
        agents = registry.get("subagents")
        if isinstance(agents, dict):
            agent_items = agents
        elif isinstance(agents, list):
            agent_items = {
                item.get("name"): item for item in agents if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
        else:
            agent_items = {}
        required = required_agents or set(REQUIRED_SUBAGENTS)
        for name, stages in REQUIRED_SUBAGENTS.items():
            if name not in required:
                continue
            entry = agent_items.get(name)
            if not isinstance(entry, dict):
                errors.append(f"agent-registry.json missing subagent {name}")
                continue
            path = entry.get("path")
            if path != f"work/skills/{name}.md":
                errors.append(f"agent-registry.json {name} path must be work/skills/{name}.md")
            if entry.get("mode") != "subagent":
                errors.append(f"agent-registry.json {name} mode must be subagent")
            entry_stages = entry.get("stages")
            if not isinstance(entry_stages, list) or not set(stages).issubset(set(entry_stages)):
                errors.append(f"agent-registry.json {name} stages must include {', '.join(stages)}")

    rows, rows_error = load_jsonl(trace / "subagent-invocations.jsonl")
    if rows_error:
        errors.append(f"subagent-invocations.jsonl: {rows_error}")
    else:
        seen: set[str] = set()
        successful_stages: dict[str, set[str]] = {name: set() for name in REQUIRED_SUBAGENTS}
        allowed_modes = {"native", "generic_subagent", "isolated_proxy", "primary_fallback"}
        c_analyzer_success_stages: set[str] = set()
        for index, row in enumerate(rows, start=1):
            agent = row.get("agent")
            success = row.get("status") in {"pass", "success"}
            if agent in (required_agents or set(REQUIRED_SUBAGENTS)) and success:
                seen.add(agent)
                if isinstance(row.get("stage"), str):
                    successful_stages.setdefault(str(agent), set()).add(row["stage"])
            if agent == "c-analyzer" and row.get("status") in {"pass", "success"}:
                stage = row.get("stage")
                if isinstance(stage, str):
                    c_analyzer_success_stages.add(stage)
            if row.get("mode") not in allowed_modes:
                errors.append(f"subagent-invocations.jsonl record {index} has invalid mode")
            if not isinstance(row.get("stage"), str) or not row.get("stage"):
                errors.append(f"subagent-invocations.jsonl record {index} must include stage")
            if not isinstance(row.get("status"), str) or not row.get("status"):
                errors.append(f"subagent-invocations.jsonl record {index} must include status")
            if controller_mode and agent in REQUIRED_SUBAGENTS:
                stage = row.get("stage")
                expected_receipt_stage = "DESIGN_RUST_API" if stage == "C_ANALYSIS" else stage
                valid_stages = {"C_ANALYSIS"} if agent == "c-analyzer" else set(REQUIRED_SUBAGENTS[agent])
                if stage not in valid_stages:
                    errors.append(f"subagent-invocations.jsonl record {index} has invalid stage for {agent}")
                receipt_rel = row.get("artifact_receipt")
                expected_prefix = f"logs/trace/stage-receipts/{expected_receipt_stage}/"
                if (
                    not isinstance(receipt_rel, str)
                    or not receipt_rel.startswith(expected_prefix)
                    or ".." in Path(receipt_rel).parts
                ):
                    errors.append(
                        f"subagent-invocations.jsonl record {index} must reference an immutable {expected_prefix}<run_id>.json receipt"
                    )
                else:
                    receipt_path = root / receipt_rel
                    receipt, receipt_error = load_json(receipt_path)
                    if receipt_error:
                        errors.append(f"subagent invocation receipt {index}: {receipt_error}")
                    else:
                        if (
                            receipt.get("status") != "pass"
                            or receipt.get("run_id") != row.get("run_id")
                            or receipt.get("stage") != expected_receipt_stage
                            or receipt.get("receipt_path") != receipt_rel
                        ):
                            errors.append(f"subagent-invocations.jsonl record {index} receipt is not gate-passed")
                        recorded_hash = row.get("artifact_receipt_sha256")
                        if not isinstance(recorded_hash, str) or _file_sha256(receipt_path) != recorded_hash:
                            errors.append(f"subagent-invocations.jsonl record {index} receipt hash mismatch")
            if row.get("mode") == "primary_fallback":
                failures = row.get("consecutive_failures")
                if not isinstance(failures, int) or failures < 3:
                    errors.append("primary_fallback records must include consecutive_failures >= 3")
                reason = row.get("fallback_to_primary_reason")
                if not isinstance(reason, str) or not reason.strip():
                    errors.append("primary_fallback records must include fallback_to_primary_reason")
                abort_run_ids = row.get("fallback_abort_runs")
                if (
                    not isinstance(failures, int)
                    or not isinstance(abort_run_ids, list)
                    or len(abort_run_ids) < failures
                    or len(set(abort_run_ids)) != len(abort_run_ids)
                ):
                    errors.append("primary_fallback records must reference distinct workflowctl abort runs")
                else:
                    abort_rows, abort_error = load_jsonl(trace / "stage-aborts.jsonl")
                    if abort_error:
                        errors.append(f"stage-aborts.jsonl: {abort_error}")
                    else:
                        valid_abort_stages = set(REQUIRED_SUBAGENTS.get(str(agent), []))
                        matched = {
                            item.get("run_id")
                            for item in abort_rows or []
                            if item.get("agent") == agent and item.get("stage") in valid_abort_stages
                        }
                        missing_aborts = [run_id for run_id in abort_run_ids if run_id not in matched]
                        if missing_aborts:
                            errors.append(
                                "primary_fallback abort evidence is missing: "
                                + ", ".join(str(item) for item in missing_aborts)
                            )
        required = required_agents or set(REQUIRED_SUBAGENTS)
        missing = sorted(required - seen)
        if missing:
            errors.append(f"subagent-invocations.jsonl missing records for: {', '.join(missing)}")
        individual_c_stages = {"READ_C_PROJECT", "BUILD_C_MODEL", "DESIGN_RUST_API"}
        if individual_c_stages & c_analyzer_success_stages:
            errors.append("c-analyzer must be recorded as one C_ANALYSIS invocation, not per C stage")
        if "c-analyzer" in seen and "C_ANALYSIS" not in c_analyzer_success_stages:
            errors.append("subagent-invocations.jsonl must include c-analyzer success record with stage C_ANALYSIS")
        if controller_mode:
            for agent in sorted(required - {"c-analyzer"}):
                missing_stages = sorted(set(REQUIRED_SUBAGENTS[agent]) - successful_stages.get(agent, set()))
                if missing_stages:
                    errors.append(
                        f"subagent-invocations.jsonl missing successful {agent} stages: {', '.join(missing_stages)}"
                    )
    return errors


def check_init_workspace(root: Path) -> list[str]:
    errors: list[str] = []
    required_paths = [
        root / "result",
        root / "result" / "issues",
        root / "logs",
        root / "logs" / "trace",
        root / "logs" / "interaction.md",
    ]
    for path in required_paths:
        if not path.exists():
            errors.append(f"missing {path.relative_to(root)}")

    if (root / "flashDB_rust").exists():
        errors.append("flashDB_rust must not exist during INIT_WORKSPACE checkpoint")

    state_path = root / "logs" / "trace" / "workflow_state.json"
    state, json_error = load_json(state_path)
    if json_error:
        errors.append(f"workflow_state.json: {json_error}")
        return errors

    missing_keys = sorted(REQUIRED_INIT_STATE_KEYS - set(state))
    if missing_keys:
        errors.append(f"workflow_state.json missing keys: {', '.join(missing_keys)}")

    if state.get("current_stage") != "INIT_WORKSPACE":
        errors.append("workflow_state.json current_stage must be INIT_WORKSPACE")
    if state.get("checkpoint") != "INIT_WORKSPACE":
        errors.append("workflow_state.json checkpoint must be INIT_WORKSPACE")

    completed = state.get("completed_stages")
    if not isinstance(completed, list) or "BOOTSTRAP" not in completed or "INIT_WORKSPACE" not in completed:
        errors.append("workflow_state.json completed_stages must include BOOTSTRAP and INIT_WORKSPACE")

    candidates = state.get("input_path_candidates")
    if not isinstance(candidates, list) or "/app/code/judge-assets/02_02_c_to_rust/code/FlashDB" not in candidates:
        errors.append("workflow_state.json input_path_candidates must include the platform FlashDB path")

    if state.get("rust_project_path") != "flashDB_rust":
        errors.append("workflow_state.json rust_project_path must be flashDB_rust")

    stage_log = root / "logs" / "trace" / "01-init-workspace.md"
    if not stage_log.exists():
        errors.append("missing logs/trace/01-init-workspace.md")

    return errors


def check_common_workspace(root: Path) -> list[str]:
    errors: list[str] = []
    required_paths = [
        root / "result",
        root / "result" / "issues",
        root / "logs",
        root / "logs" / "trace",
        root / "logs" / "interaction.md",
    ]
    for path in required_paths:
        if not path.exists():
            errors.append(f"missing {path.relative_to(root)}")
    if (root / "flashDB_rust").exists():
        errors.append("flashDB_rust must not exist before GENERATE_RUST_SCAFFOLD")
    return errors


def check_common_after_scaffold(root: Path) -> list[str]:
    errors: list[str] = []
    required_paths = [
        root / "result",
        root / "result" / "issues",
        root / "logs",
        root / "logs" / "trace",
        root / "logs" / "interaction.md",
    ]
    for path in required_paths:
        if not path.exists():
            errors.append(f"missing {path.relative_to(root)}")
    return errors


def check_project_command(project: Path, command: list[str], label: str) -> list[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"{label} could not run: {exc}"]
    if completed.returncode == 0:
        return []
    tail = "\n".join(completed.stdout.splitlines()[-20:])
    return [f"{label} failed:\n{tail}"]


def check_no_c_sources_in_src(root: Path) -> list[str]:
    if list((root / "flashDB_rust" / "src").rglob("*.c")):
        return ["flashDB_rust/src must not contain C source files"]
    return []


def check_typed_ffi_scaffold(project: Path, design: dict[str, Any]) -> list[str]:
    facade = design.get("c_abi_facade")
    if not isinstance(facade, dict):
        return []
    structs = facade.get("structs")
    functions = facade.get("functions")
    if not isinstance(structs, list):
        structs = []
    if not isinstance(functions, list):
        functions = []
    if not structs and not functions:
        return []

    errors: list[str] = []
    ffi_mod = project / "src" / "ffi" / "mod.rs"
    c_types = project / "src" / "ffi" / "c_types.rs"
    c_abi = project / "src" / "ffi" / "c_abi.rs"
    layout_probe = project / "src" / "ffi" / "layout_probe.rs"
    for path in [ffi_mod, c_types, c_abi, layout_probe]:
        if not path.exists():
            errors.append(f"missing {path.relative_to(project)}")
    if errors:
        return errors

    ffi_mod_text = ffi_mod.read_text(encoding="utf-8", errors="ignore")
    c_types_text = c_types.read_text(encoding="utf-8", errors="ignore")
    c_abi_text = c_abi.read_text(encoding="utf-8", errors="ignore")
    layout_text = layout_probe.read_text(encoding="utf-8", errors="ignore")
    for module in ["c_types", "c_abi", "layout_probe"]:
        if f"pub mod {module};" not in ffi_mod_text:
            errors.append(f"src/ffi/mod.rs missing pub mod {module};")

    for item in structs:
        if not isinstance(item, dict) or not isinstance(item.get("c_name"), str):
            continue
        rust_name = safe_rust_type(str(item.get("rust_name") or item["c_name"]), "CAbiStruct")
        if "#[repr(C)]" not in c_types_text or f"pub struct {rust_name}" not in c_types_text:
            errors.append(f"src/ffi/c_types.rs must define #[repr(C)] struct {rust_name}")
        if "_opaque" in c_types_text:
            errors.append("src/ffi/c_types.rs must not use opaque placeholder layout fields")
        if f"core::mem::size_of::<{rust_name}>()" not in layout_text:
            errors.append(f"src/ffi/layout_probe.rs must export size probe for {rust_name}")
        fields = item.get("fields")
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                continue
            field_name = safe_rust_ident(field["name"])
            if f"pub {field_name}:" not in c_types_text:
                errors.append(f"src/ffi/c_types.rs must include field {rust_name}.{field_name}")
            if f"offset_of!({rust_name}, {field_name})" not in layout_text:
                errors.append(f"src/ffi/layout_probe.rs must export offset probe for {rust_name}.{field_name}")

    for function in functions:
        if not isinstance(function, dict) or not isinstance(function.get("rust_export"), str):
            continue
        export = safe_rust_ident(function["rust_export"])
        if f'pub extern "C" fn {export}(' not in c_abi_text:
            errors.append(f"src/ffi/c_abi.rs must export typed C ABI function {export}")
        empty_c_void_signature = f"fn {export}() -> *mut c_void"
        if empty_c_void_signature in c_abi_text or f"fn {export}() -> *mut std::ffi::c_void" in c_abi_text:
            errors.append(f"src/ffi/c_abi.rs must not use untyped c_void placeholder for {export}")
        params = function.get("params")
        if isinstance(params, list):
            for index, param in enumerate(params):
                if not isinstance(param, dict):
                    continue
                name = safe_rust_ident(str(param.get("name") or f"arg{index}"))
                rust_type = str(param.get("rust_ffi_type") or "").strip()
                if rust_type and f"{name}: {rust_type}" not in c_abi_text:
                    errors.append(f"src/ffi/c_abi.rs must preserve typed param {export}.{name}")
        return_info = function.get("return")
        return_type = str(return_info.get("rust_ffi_type") or "").strip() if isinstance(return_info, dict) else ""
        if return_type and return_type != "()" and f"fn {export}(" in c_abi_text and f") -> {return_type}" not in c_abi_text:
            errors.append(f"src/ffi/c_abi.rs must preserve typed return for {export}")
    return errors


def extract_current_ffi_signature(source: str, symbol: str) -> str | None:
    """Extract one Rust extern-C signature without being confused by callback parentheses."""
    match = re.search(
        rf'pub\s+extern\s+"C"\s+fn\s+{re.escape(symbol)}\s*\(',
        source,
    )
    if match is None:
        return None
    open_paren = source.find("(", match.start())
    depth = 0
    close_paren: int | None = None
    for index in range(open_paren, len(source)):
        character = source[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
    if close_paren is None:
        return None
    params = source[open_paren + 1:close_paren]
    cursor = close_paren + 1
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    return_type = "()"
    if source[cursor:cursor + 2] == "->":
        cursor += 2
        end = cursor
        while end < len(source) and source[end] not in "{;":
            end += 1
        if end >= len(source):
            return None
        return_type = source[cursor:end].strip()
    normalized_params = re.sub(r"\s+", "", params)
    # Rust accepts an optional trailing comma in a multi-line parameter list.
    # It must not turn a formatted generated facade into a different ABI
    # contract and tempt a worker to edit a frozen file.
    if normalized_params.endswith(","):
        normalized_params = normalized_params[:-1]
    normalized_return = re.sub(r"\s+", "", return_type)
    return f"{symbol}({normalized_params})->{normalized_return}"


def check_rewrite_ownership_manifest(
    project: Path,
    manifest: dict[str, Any],
) -> list[str]:
    """Validate controller-consumable, model-independent rewrite ownership."""
    errors: list[str] = []
    ownership = manifest.get("rewrite_ownership")
    if not isinstance(ownership, dict) or ownership.get("schema_version") != 1:
        return ["scaffold-manifest.json must contain rewrite_ownership schema_version 1"]

    category_names = [
        "core_owned_paths",
        "facade_owned_paths",
        "frozen_contract_paths",
        "shared_readonly_paths",
    ]
    categories: dict[str, set[str]] = {}
    for name in category_names:
        values = ownership.get(name)
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            errors.append(f"scaffold-manifest.json rewrite_ownership.{name} must be a string list")
            categories[name] = set()
            continue
        invalid = sorted(
            item for item in values
            if Path(item).is_absolute() or ".." in Path(item).parts or item.startswith("/")
        )
        if invalid:
            errors.append(f"rewrite_ownership.{name} contains unsafe paths: {', '.join(invalid)}")
        categories[name] = set(values)

    for index, left_name in enumerate(category_names):
        for right_name in category_names[index + 1:]:
            overlap = sorted(categories[left_name] & categories[right_name])
            if overlap:
                errors.append(
                    f"rewrite ownership categories {left_name}/{right_name} overlap: "
                    + ", ".join(overlap)
                )

    generated = manifest.get("files")
    generated_paths = set(generated) if isinstance(generated, dict) else set()
    classified = set().union(*(categories[name] for name in category_names))
    missing = sorted(generated_paths - classified)
    unknown = sorted(classified - generated_paths)
    if missing:
        errors.append("rewrite ownership does not classify generated files: " + ", ".join(missing))
    if unknown:
        errors.append("rewrite ownership references files absent from manifest: " + ", ".join(unknown))
    for relative in sorted(classified):
        path = project / relative
        if not path.is_file() or path.is_symlink():
            errors.append(f"rewrite ownership path must be a regular generated file: {relative}")

    placeholders = manifest.get("placeholder_modules")
    placeholder_paths = {
        entry.get("path") for entry in placeholders.values()
        if isinstance(placeholders, dict) and isinstance(entry, dict) and isinstance(entry.get("path"), str)
    } if isinstance(placeholders, dict) else set()
    missing_core = sorted(placeholder_paths - categories["core_owned_paths"])
    if missing_core:
        errors.append("placeholder modules must be core-owned: " + ", ".join(missing_core))

    ffi_functions = manifest.get("ffi_functions")
    ffi_paths = {
        entry.get("path") for entry in ffi_functions.values()
        if isinstance(ffi_functions, dict) and isinstance(entry, dict) and isinstance(entry.get("path"), str)
    } if isinstance(ffi_functions, dict) else set()
    missing_facade = sorted(ffi_paths - categories["facade_owned_paths"])
    if missing_facade:
        errors.append("FFI stub files must be facade-owned: " + ", ".join(missing_facade))

    frozen_symbols = ownership.get("frozen_contract_symbols")
    if not isinstance(frozen_symbols, list):
        errors.append("rewrite_ownership.frozen_contract_symbols must be a list")
        frozen_symbols = []
    seen_symbols: set[str] = set()
    for entry in frozen_symbols:
        if not isinstance(entry, dict):
            errors.append("frozen_contract_symbols entries must be objects")
            continue
        symbol = entry.get("symbol")
        relative = entry.get("path")
        signature = entry.get("signature")
        signature_hash = entry.get("signature_sha256")
        if not all(isinstance(item, str) and item for item in [symbol, relative, signature, signature_hash]):
            errors.append("frozen_contract_symbols entries must contain symbol/path/signature/signature_sha256")
            continue
        if symbol in seen_symbols:
            errors.append(f"duplicate frozen contract symbol: {symbol}")
        seen_symbols.add(symbol)
        actual_hash = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        if actual_hash != signature_hash:
            errors.append(f"frozen contract signature hash mismatch: {symbol}")
        if relative not in categories["facade_owned_paths"]:
            errors.append(f"frozen contract symbol path must be facade-owned: {symbol}:{relative}")
        if not isinstance(ffi_functions, dict) or symbol not in ffi_functions:
            errors.append(f"frozen contract symbol is absent from ffi_functions: {symbol}")
        source_path = project / relative
        if source_path.is_file():
            source = source_path.read_text(encoding="utf-8", errors="ignore")
            current_signature = extract_current_ffi_signature(source, symbol)
            expected_signature = re.sub(r"\s+", "", signature)
            if current_signature != expected_signature:
                errors.append(f"frozen external signature changed: {symbol}")
            symbol_match = re.search(
                rf'pub\s+extern\s+"C"\s+fn\s+{re.escape(symbol)}\s*\(', source
            )
            prefix = source[max(0, symbol_match.start() - 160):symbol_match.start()] if symbol_match else ""
            if "#[no_mangle]" not in prefix:
                errors.append(f"frozen external symbol lost #[no_mangle]: {symbol}")
    if isinstance(ffi_functions, dict):
        missing_frozen = sorted(set(ffi_functions) - seen_symbols)
        if missing_frozen:
            errors.append("FFI functions missing frozen signature contracts: " + ", ".join(missing_frozen))
    return errors


def require_state(
    root: Path,
    required_keys: set[str],
    stage: str,
    completed_required: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    state, json_error = load_json(root / "logs" / "trace" / "workflow_state.json")
    if json_error:
        return None, [f"workflow_state.json: {json_error}"]
    assert state is not None
    missing_keys = sorted(required_keys - set(state))
    if missing_keys:
        errors.append(f"workflow_state.json missing keys: {', '.join(missing_keys)}")
    if state.get("current_stage") != stage and not (stage == "REPORT_AND_VERIFY" and state.get("current_stage") == "DONE"):
        errors.append(f"workflow_state.json current_stage must be {stage}")
    if state.get("checkpoint") != stage:
        errors.append(f"workflow_state.json checkpoint must be {stage}")
    completed = state.get("completed_stages")
    if not isinstance(completed, list) or not all(item in completed for item in completed_required):
        errors.append(f"workflow_state.json completed_stages must include {', '.join(completed_required)}")
    return state, errors


def check_read_c_project(root: Path) -> list[str]:
    errors = check_common_workspace(root)

    state_path = root / "logs" / "trace" / "workflow_state.json"
    state, json_error = load_json(state_path)
    if json_error:
        errors.append(f"workflow_state.json: {json_error}")
        return errors

    missing_keys = sorted(REQUIRED_READ_STATE_KEYS - set(state))
    if missing_keys:
        errors.append(f"workflow_state.json missing keys: {', '.join(missing_keys)}")

    if state.get("current_stage") != "READ_C_PROJECT":
        errors.append("workflow_state.json current_stage must be READ_C_PROJECT")
    if state.get("checkpoint") != "READ_C_PROJECT":
        errors.append("workflow_state.json checkpoint must be READ_C_PROJECT")

    completed = state.get("completed_stages")
    if not isinstance(completed, list) or not all(
        item in completed for item in ["BOOTSTRAP", "INIT_WORKSPACE", "READ_C_PROJECT"]
    ):
        errors.append("workflow_state.json completed_stages must include BOOTSTRAP, INIT_WORKSPACE, and READ_C_PROJECT")

    if state.get("input_manifest") != "logs/trace/input_manifest.json":
        errors.append("workflow_state.json input_manifest must be logs/trace/input_manifest.json")

    manifest_path = root / "logs" / "trace" / "input_manifest.json"
    manifest, manifest_error = load_json(manifest_path)
    if manifest_error:
        errors.append(f"input_manifest.json: {manifest_error}")
        return errors

    required_manifest_keys = {
        "source_root",
        "src_dir",
        "tests_dir",
        "core_sources",
        "test_sources",
        "headers",
        "build_files",
        "counts",
    }
    missing_manifest = sorted(required_manifest_keys - set(manifest))
    if missing_manifest:
        errors.append(f"input_manifest.json missing keys: {', '.join(missing_manifest)}")

    if manifest.get("src_dir") != "src":
        errors.append("input_manifest.json src_dir must be src")
    if manifest.get("tests_dir") != "tests":
        errors.append("input_manifest.json tests_dir must be tests")
    if not isinstance(manifest.get("core_sources"), list) or not manifest.get("core_sources"):
        errors.append("input_manifest.json core_sources must be a non-empty list")
    if not isinstance(manifest.get("test_sources"), list) or not manifest.get("test_sources"):
        errors.append("input_manifest.json test_sources must be a non-empty list")

    stage_log = root / "logs" / "trace" / "02-read-c-project.md"
    if not stage_log.exists():
        errors.append("missing logs/trace/02-read-c-project.md")

    return errors


def check_build_c_model(root: Path) -> list[str]:
    errors = check_common_workspace(root)

    state_path = root / "logs" / "trace" / "workflow_state.json"
    state, json_error = load_json(state_path)
    if json_error:
        errors.append(f"workflow_state.json: {json_error}")
        return errors

    missing_keys = sorted(REQUIRED_MODEL_STATE_KEYS - set(state))
    if missing_keys:
        errors.append(f"workflow_state.json missing keys: {', '.join(missing_keys)}")

    if state.get("current_stage") != "BUILD_C_MODEL":
        errors.append("workflow_state.json current_stage must be BUILD_C_MODEL")
    if state.get("checkpoint") != "BUILD_C_MODEL":
        errors.append("workflow_state.json checkpoint must be BUILD_C_MODEL")

    completed = state.get("completed_stages")
    required_stages = ["BOOTSTRAP", "INIT_WORKSPACE", "READ_C_PROJECT", "BUILD_C_MODEL"]
    if not isinstance(completed, list) or not all(item in completed for item in required_stages):
        errors.append("workflow_state.json completed_stages must include BOOTSTRAP, INIT_WORKSPACE, READ_C_PROJECT, and BUILD_C_MODEL")

    expected_paths = {
        "c_project_model": "logs/trace/c_project_model.json",
        "c_api_model": "logs/trace/c_api_model.json",
        "c_test_model": "logs/trace/c_test_model.json",
    }
    for key, expected in expected_paths.items():
        if state.get(key) != expected:
            errors.append(f"workflow_state.json {key} must be {expected}")

    project_model, project_error = load_json(root / "logs" / "trace" / "c_project_model.json")
    api_model, api_error = load_json(root / "logs" / "trace" / "c_api_model.json")
    test_model, test_error = load_json(root / "logs" / "trace" / "c_test_model.json")

    for name, error in [
        ("c_project_model.json", project_error),
        ("c_api_model.json", api_error),
        ("c_test_model.json", test_error),
    ]:
        if error:
            errors.append(f"{name}: {error}")
    if project_error or api_error or test_error:
        return errors

    modules = project_model.get("modules")
    if not isinstance(modules, dict):
        errors.append("c_project_model.json modules must be an object")
    else:
        for module_name in ["kvdb", "tsdb", "tests"]:
            if not modules.get(module_name):
                errors.append(f"c_project_model.json modules.{module_name} must be non-empty")

    include_graph = project_model.get("include_graph")
    if not isinstance(include_graph, dict) or not include_graph:
        errors.append("c_project_model.json include_graph must be non-empty")

    public_functions = api_model.get("public_functions")
    if not isinstance(public_functions, list) or not public_functions:
        errors.append("c_api_model.json public_functions must be non-empty")

    if not api_model.get("kvdb_symbols"):
        errors.append("c_api_model.json kvdb_symbols must be non-empty")
    if not api_model.get("tsdb_symbols"):
        errors.append("c_api_model.json tsdb_symbols must be non-empty")
    manifest, manifest_error = load_json(root / "logs" / "trace" / "input_manifest.json")
    if not manifest_error:
        digest = manifest.get("input_digest")
        for name, model in [("c_project_model.json", project_model), ("c_api_model.json", api_model), ("c_test_model.json", test_model)]:
            if "input_digest" in model and (not isinstance(digest, str) or not digest or model.get("input_digest") != digest):
                errors.append(f"{name} input_digest must match input_manifest.json")
    macro_values = api_model.get("macro_values")
    if macro_values is not None and (not isinstance(macro_values, dict) or not macro_values):
        errors.append("c_api_model.json macro_values must be a non-empty object")
    elif isinstance(macro_values, dict) and any(
        not isinstance(value, dict)
        or not isinstance(value.get("raw_expression"), str)
        or value.get("evaluation_status") not in {"literal", "expression"}
        for value in macro_values.values()
    ):
        errors.append("c_api_model.json macro_values entries must describe expression and evaluation status")
    errors.extend(check_abi_layout_contract(api_model))
    if state.get("controller_contract_version"):
        errors.extend(check_deterministic_abi_field_contract(api_model))
    errors.extend(check_function_signature_contract(api_model, test_model))
    if (
        not state.get("controller_contract_version")
        and (
            (root / "logs" / "trace" / "agent-registry.json").exists()
            or (root / "logs" / "trace" / "subagent-invocations.jsonl").exists()
        )
    ):
        errors.extend(check_subagent_evidence(root, {"c-analyzer"}))

    if not isinstance(test_model.get("test_functions"), list) or not test_model.get("test_functions"):
        errors.append("c_test_model.json test_functions must be non-empty")
    if not test_model.get("kvdb_tests"):
        errors.append("c_test_model.json kvdb_tests must be non-empty")
    if not test_model.get("tsdb_tests"):
        errors.append("c_test_model.json tsdb_tests must be non-empty")
    scenarios = test_model.get("standard_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("c_test_model.json standard_scenarios must be a non-empty list")
    else:
        scenario_ids = [
            item.get("id")
            for item in scenarios
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        if len(scenario_ids) != len(scenarios):
            errors.append("c_test_model.json every standard scenario must have a string id")
        if len(set(scenario_ids)) != len(scenario_ids):
            errors.append("c_test_model.json standard scenario ids must be unique")
        registered = test_model.get("registered_tests")
        scenario_parents = {
            item.get("parent_test", item.get("name"))
            for item in scenarios
            if isinstance(item, dict)
        }
        registered_names = {item for item in registered if isinstance(item, str)} if isinstance(registered, list) else set()
        missing_registered = sorted(registered_names - scenario_parents)
        if missing_registered:
            errors.append(
                f"c_test_model.json standard_scenarios do not cover registered tests: {', '.join(missing_registered)}"
            )
    scorer_cases = test_model.get("scorer_standard_cases")
    if not isinstance(scorer_cases, list) or not scorer_cases:
        errors.append("c_test_model.json scorer_standard_cases must be a non-empty dynamic list")
    else:
        case_ids = [
            item.get("case_id")
            for item in scorer_cases
            if isinstance(item, dict) and isinstance(item.get("case_id"), str)
        ]
        case_names = [
            item.get("case_name")
            for item in scorer_cases
            if isinstance(item, dict) and isinstance(item.get("case_name"), str)
        ]
        if len(case_ids) != len(scorer_cases) or len(set(case_ids)) != len(case_ids):
            errors.append("c_test_model.json scorer_standard_cases case_id values must be present and unique")
        if len(case_names) != len(scorer_cases) or len(set(case_names)) != len(case_names):
            errors.append("c_test_model.json scorer_standard_cases case_name values must be present and unique")
        scenario_id_set = set(scenario_ids) if isinstance(scenarios, list) else set()
        case_scenario_ids = {
            item.get("scenario_id")
            for item in scorer_cases
            if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)
        }
        if case_scenario_ids != scenario_id_set:
            errors.append("c_test_model.json scorer_standard_cases must match standard_scenarios by scenario_id")
        for item in scorer_cases:
            if not isinstance(item, dict):
                continue
            obligations = item.get("semantic_obligations")
            if not isinstance(obligations, list) or not obligations:
                errors.append(f"scorer case {item.get('case_name')} must declare semantic_obligations")
    if state.get("controller_contract_version"):
        errors.extend(check_ordered_scenario_ir(test_model))

    stage_log = root / "logs" / "trace" / "03-build-c-model.md"
    if not stage_log.exists():
        errors.append("missing logs/trace/03-build-c-model.md")

    return errors


def check_design_rust_api(root: Path) -> list[str]:
    errors = check_common_workspace(root)

    state_path = root / "logs" / "trace" / "workflow_state.json"
    state, json_error = load_json(state_path)
    if json_error:
        errors.append(f"workflow_state.json: {json_error}")
        return errors

    missing_keys = sorted(REQUIRED_DESIGN_STATE_KEYS - set(state))
    if missing_keys:
        errors.append(f"workflow_state.json missing keys: {', '.join(missing_keys)}")

    if state.get("current_stage") != "DESIGN_RUST_API":
        errors.append("workflow_state.json current_stage must be DESIGN_RUST_API")
    if state.get("checkpoint") != "DESIGN_RUST_API":
        errors.append("workflow_state.json checkpoint must be DESIGN_RUST_API")

    completed = state.get("completed_stages")
    required_stages = ["BOOTSTRAP", "INIT_WORKSPACE", "READ_C_PROJECT", "BUILD_C_MODEL", "DESIGN_RUST_API"]
    if not isinstance(completed, list) or not all(item in completed for item in required_stages):
        errors.append(
            "workflow_state.json completed_stages must include BOOTSTRAP, INIT_WORKSPACE, "
            "READ_C_PROJECT, BUILD_C_MODEL, and DESIGN_RUST_API"
        )

    expected_paths = {
        "input_manifest": "logs/trace/input_manifest.json",
        "c_project_model": "logs/trace/c_project_model.json",
        "c_api_model": "logs/trace/c_api_model.json",
        "c_test_model": "logs/trace/c_test_model.json",
        "rust_api_design": "logs/trace/rust_api_design.json",
    }
    for key, expected in expected_paths.items():
        if state.get(key) != expected:
            errors.append(f"workflow_state.json {key} must be {expected}")

    design, design_error = load_json(root / "logs" / "trace" / "rust_api_design.json")
    if design_error:
        errors.append(f"rust_api_design.json: {design_error}")
    else:
        if design.get("crate_name") != "flashdb_rust":
            errors.append("rust_api_design.json crate_name must be flashdb_rust")
        manifest, manifest_error = load_json(root / "logs" / "trace" / "input_manifest.json")
        if "input_digest" in design and (manifest_error or design.get("input_digest") != manifest.get("input_digest")):
            errors.append("rust_api_design.json input_digest must match input_manifest.json")

        modules = design.get("modules")
        if not isinstance(modules, list) or not modules or not all(isinstance(item, str) and item for item in modules):
            errors.append("rust_api_design.json modules must be a non-empty list of module names")

        core_types = design.get("core_types")
        if not isinstance(core_types, list):
            errors.append("rust_api_design.json core_types must be a list")

        traits = design.get("traits")
        if not isinstance(traits, list):
            errors.append("rust_api_design.json traits must be a list")

        if not isinstance(design.get("kvdb_api"), list) or not design.get("kvdb_api"):
            errors.append("rust_api_design.json kvdb_api must be a non-empty list")
        if not isinstance(design.get("tsdb_api"), list) or not design.get("tsdb_api"):
            errors.append("rust_api_design.json tsdb_api must be a non-empty list")
        if not isinstance(design.get("test_api"), dict):
            errors.append("rust_api_design.json test_api must be an object")

        error_model = design.get("error_model")
        if not isinstance(error_model, dict) or not error_model:
            errors.append("rust_api_design.json error_model must be a non-empty object")

        storage_model = design.get("storage_model")
        implementations = storage_model.get("implementations") if isinstance(storage_model, dict) else None
        if not isinstance(storage_model, dict) or not isinstance(implementations, list):
            errors.append("rust_api_design.json storage_model.implementations must be a list")

        storage_constraints = design.get("storage_constraints")
        if storage_constraints is not None and not isinstance(storage_constraints, dict):
            errors.append("rust_api_design.json storage_constraints must be an object when present")

        ffi_strategy = design.get("ffi_strategy")
        required_ffi_strategy = {
            "kind": "c_facade_with_sidecar_state",
            "c_struct_ownership": "caller_owned",
        }
        if ffi_strategy is None:
            pass
        elif not isinstance(ffi_strategy, dict):
            errors.append("rust_api_design.json ffi_strategy must be an object")
        else:
            for key, expected in required_ffi_strategy.items():
                if ffi_strategy.get(key) != expected:
                    errors.append(f"rust_api_design.json ffi_strategy.{key} must be {expected}")
            for key in ["sidecar_key", "user_data", "callback_lock_rule", "facade_sync"]:
                if not isinstance(ffi_strategy.get(key), str) or not ffi_strategy[key].strip():
                    errors.append(f"rust_api_design.json ffi_strategy.{key} must be a non-empty string")

        symbol_map = design.get("c_to_rust_symbol_map")
        if not isinstance(symbol_map, dict):
            errors.append("rust_api_design.json c_to_rust_symbol_map must be an object")
        elif not all(isinstance(key, str) and isinstance(value, str) for key, value in symbol_map.items()):
            errors.append("rust_api_design.json c_to_rust_symbol_map keys and values must be strings")

        test_model, test_model_error = load_json(root / "logs" / "trace" / "c_test_model.json")
        if test_model_error:
            errors.append(f"c_test_model.json: {test_model_error}")
        else:
            errors.extend(check_design_test_contracts(design, test_model))
            if state.get("controller_contract_version"):
                errors.extend(check_structured_implementation_requirements(design, test_model))
        api_model, api_model_error = load_json(root / "logs" / "trace" / "c_api_model.json")
        if api_model_error:
            errors.append(f"c_api_model.json: {api_model_error}")
        else:
            errors.extend(check_c_abi_facade_contract(design, api_model))

    stage_log = root / "logs" / "trace" / "04-design-rust-api.md"
    try:
        stage_log_text = stage_log.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append("missing logs/trace/04-design-rust-api.md; stage log must be 中文")
    else:
        if not contains_cjk(stage_log_text):
            errors.append("logs/trace/04-design-rust-api.md must use 中文")

    return errors


def check_generate_rust_scaffold(root: Path) -> list[str]:
    errors = check_common_after_scaffold(root)
    required_stages = [
        "BOOTSTRAP",
        "INIT_WORKSPACE",
        "READ_C_PROJECT",
        "BUILD_C_MODEL",
        "DESIGN_RUST_API",
        "GENERATE_RUST_SCAFFOLD",
    ]
    state, state_errors = require_state(root, REQUIRED_DESIGN_STATE_KEYS, "GENERATE_RUST_SCAFFOLD", required_stages)
    errors.extend(state_errors)
    if state is None:
        return errors

    project = root / "flashDB_rust"
    for rel_path in ["Cargo.toml", "src/lib.rs", "tests"]:
        if not (project / rel_path).exists():
            errors.append(f"missing flashDB_rust/{rel_path}")

    design, design_error = load_json(root / "logs" / "trace" / "rust_api_design.json")
    if design_error:
        errors.append(f"rust_api_design.json: {design_error}")
    else:
        modules = design.get("modules", [])
        if not isinstance(modules, list):
            errors.append("rust_api_design.json modules must be a list")
        else:
            lib_rs = project / "src" / "lib.rs"
            lib_text = lib_rs.read_text(encoding="utf-8", errors="ignore") if lib_rs.exists() else ""
            for module in modules:
                if isinstance(module, str):
                    if not (project / "src" / f"{module}.rs").exists():
                        errors.append(f"missing flashDB_rust/src/{module}.rs")
                    if f"pub mod {module};" not in lib_text:
                        errors.append(f"src/lib.rs missing pub mod {module};")
            errors.extend(check_typed_ffi_scaffold(project, design))

    if project.exists():
        errors.extend(
            check_project_command(
                project,
                ["cargo", "fmt", "--all", "--", "--check"],
                "generated scaffold cargo fmt",
            )
        )
        errors.extend(check_project_command(project, ["cargo", "check", "--all-targets"], "generated scaffold cargo check"))

    if state.get("controller_contract_version"):
        manifest, manifest_error = load_json(root / "logs" / "trace" / "scaffold-manifest.json")
        if manifest_error:
            errors.append(f"scaffold-manifest.json: {manifest_error}")
        elif not isinstance(manifest.get("files"), (dict, list)) or not manifest.get("files"):
            errors.append("scaffold-manifest.json must record generated file hashes")
        else:
            errors.extend(check_rewrite_ownership_manifest(project, manifest))
        layout, layout_error = load_json(
            root / "logs" / "trace" / "c-cross" / "scaffold-layout-check.json"
        )
        if layout_error:
            errors.append(f"scaffold-layout-check.json: {layout_error}")
        elif layout.get("phase") != "layout" or layout.get("status") != "pass":
            errors.append("compiler-confirmed scaffold ABI layout must pass before REWRITE_CORE_MODULES")

    stage_log = root / "logs" / "trace" / "05-generate-rust-scaffold.md"
    if not stage_log.exists():
        errors.append("missing logs/trace/05-generate-rust-scaffold.md")
    return errors


def check_rewrite_core_modules(root: Path) -> list[str]:
    errors = check_common_after_scaffold(root)
    required_stages = [
        "BOOTSTRAP",
        "INIT_WORKSPACE",
        "READ_C_PROJECT",
        "BUILD_C_MODEL",
        "DESIGN_RUST_API",
        "GENERATE_RUST_SCAFFOLD",
        "REWRITE_CORE_MODULES",
    ]
    state, state_errors = require_state(root, REQUIRED_DESIGN_STATE_KEYS, "REWRITE_CORE_MODULES", required_stages)
    errors.extend(state_errors)
    if state is None:
        return errors

    project = root / "flashDB_rust"
    design, design_error = load_json(root / "logs" / "trace" / "rust_api_design.json")
    manifest, manifest_error = load_json(root / "logs" / "trace" / "scaffold-manifest.json")
    if manifest_error:
        errors.append(f"scaffold-manifest.json: {manifest_error}")
    else:
        errors.extend(check_rewrite_ownership_manifest(project, manifest))
        if isinstance(design, dict):
            errors.extend(check_typed_ffi_scaffold(project, design))
        rewrite_state, rewrite_state_error = load_json(root / "logs" / "trace" / "rewrite-state.json")
        if rewrite_state_error:
            errors.append(f"rewrite-state.json: {rewrite_state_error}")
        else:
            manifest_path = root / "logs" / "trace" / "scaffold-manifest.json"
            if rewrite_state.get("manifest_sha256") != _file_sha256(manifest_path):
                errors.append("static REWRITE ownership manifest changed after controller initialization")
            if rewrite_state.get("phase") != "READY" or rewrite_state.get("status") != "ready_for_finish":
                errors.append("static REWRITE state must be READY before the stage gate")
            core_revision = rewrite_state.get("core_revision")
            facade_revision = rewrite_state.get("facade_revision")
            if not isinstance(core_revision, int) or core_revision < 1:
                errors.append("static REWRITE must have a completed core revision")
            if not isinstance(facade_revision, int) or facade_revision < 1:
                errors.append("static REWRITE must have a completed facade revision")
            if rewrite_state.get("facade_based_on_core_revision") != core_revision:
                errors.append("latest facade evidence is stale for the current core revision")
            latest = rewrite_state.get("latest_receipts")
            ownership = manifest.get("rewrite_ownership", {}) if isinstance(manifest, dict) else {}
            owner_keys = {
                "IMPLEMENT_CORE": "core_owned_paths",
                "WIRE_FACADE": "facade_owned_paths",
            }
            for role, owner_key in owner_keys.items():
                receipt_rel = latest.get(role) if isinstance(latest, dict) else None
                if not isinstance(receipt_rel, str):
                    errors.append(f"static REWRITE has no latest {role} receipt")
                    continue
                receipt, receipt_error = load_json(root / receipt_rel)
                if receipt_error:
                    errors.append(f"{role} receipt: {receipt_error}")
                    continue
                if receipt.get("role") != role or receipt.get("status") != "complete":
                    errors.append(f"latest {role} receipt must be complete and role-bound")
                if receipt.get("parent_run_id") != rewrite_state.get("parent_run_id"):
                    errors.append(f"latest {role} receipt belongs to another REWRITE parent run")
                expected_revision = core_revision if role == "IMPLEMENT_CORE" else facade_revision
                if receipt.get("revision") != expected_revision:
                    errors.append(f"latest {role} receipt has a stale revision")
                if role == "WIRE_FACADE" and receipt.get("based_on_core_revision") != core_revision:
                    errors.append("latest WIRE_FACADE receipt is not based on the latest core revision")
                allowed = set(ownership.get(owner_key, [])) if isinstance(ownership, dict) else set()
                changed = receipt.get("changed_files")
                invalid = [
                    item for item in changed if isinstance(item, str)
                    if item.removeprefix("flashDB_rust/") not in allowed
                ] if isinstance(changed, list) else []
                if invalid:
                    errors.append(f"{role} receipt contains paths owned by another role: {', '.join(invalid)}")
                generated = manifest.get("files", {}) if isinstance(manifest, dict) else {}
                actual_owner_changes = {
                    f"flashDB_rust/{item}"
                    for item in allowed
                    if not (project / item).is_file()
                    or not isinstance(generated.get(item), dict)
                    or generated[item].get("sha256") != _file_sha256(project / item)
                }
                recorded_owner_changes = set(changed) if isinstance(changed, list) else set()
                if actual_owner_changes != recorded_owner_changes:
                    errors.append(f"latest {role} receipt does not match cumulative owner diff")
                recorded_hashes = receipt.get("changed_file_hashes")
                if not isinstance(recorded_hashes, dict):
                    errors.append(f"latest {role} receipt has no changed-file hashes")
                else:
                    stale_hashes = [
                        item for item, expected in recorded_hashes.items()
                        if not isinstance(item, str)
                        or not isinstance(expected, str)
                        or not (root / item).is_file()
                        or _file_sha256(root / item) != expected
                    ]
                    if stale_hashes:
                        errors.append(f"latest {role} receipt hashes are stale: {', '.join(stale_hashes)}")
                check_rel = receipt.get("check_receipt")
                check, check_error = load_json(root / check_rel) if isinstance(check_rel, str) else (None, "missing")
                if (
                    check_error
                    or not isinstance(check, dict)
                    or check.get("status") != "pass"
                    or check.get("role") != role
                    or check.get("revision") != receipt.get("attempt")
                ):
                    errors.append(f"latest {role} receipt must reference a passing bounded check")
    modules = design.get("modules", []) if not design_error and isinstance(design, dict) else []
    if not isinstance(modules, list) or not modules:
        errors.append("rust_api_design.json modules must be available for REWRITE_CORE_MODULES")
    else:
        for module in modules:
            if not isinstance(module, str):
                continue
            rel_path = f"src/{module}.rs"
            path = project / rel_path
            if not path.exists() or not path.read_text(encoding="utf-8", errors="ignore").strip():
                errors.append(f"flashDB_rust/{rel_path} must exist and be non-empty")
            elif "todo!()" in path.read_text(encoding="utf-8", errors="ignore") or "unimplemented!()" in path.read_text(encoding="utf-8", errors="ignore"):
                errors.append(f"flashDB_rust/{rel_path} must not contain todo!() or unimplemented!()")

    errors.extend(check_no_c_sources_in_src(root))
    batches, batches_error = load_jsonl(root / "logs" / "trace" / "core_rewrite_batches.jsonl")
    if batches_error:
        errors.append(f"core_rewrite_batches.jsonl: {batches_error}")
    elif not batches:
        errors.append("core_rewrite_batches.jsonl must contain at least one implementation batch")
    else:
        required_obligations: set[str] = set()
        if isinstance(design, dict):
            requirements = design.get("implementation_requirements")
            if isinstance(requirements, list):
                required_obligations = {
                    item.get("id") for item in requirements
                    if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
                }
        implemented_obligations: set[str] = set()
        for index, batch in enumerate(batches, start=1):
            if batch.get("stage") != "REWRITE_CORE_MODULES":
                errors.append(f"core_rewrite_batches.jsonl record {index} stage must be REWRITE_CORE_MODULES")
            if batch.get("status") not in {"complete", "pass"}:
                errors.append(f"core_rewrite_batches.jsonl record {index} must include complete/pass status")
            changed_files = batch.get("changed_files")
            if not isinstance(changed_files, list) or not changed_files:
                errors.append(f"core_rewrite_batches.jsonl record {index} must include changed_files")
            elif any(
                not isinstance(path, str)
                or not path.startswith("flashDB_rust/src/")
                or ".." in Path(path).parts
                for path in changed_files
            ):
                errors.append(f"core_rewrite_batches.jsonl record {index} changed_files must stay under flashDB_rust/src/")
            obligations = batch.get("obligations")
            if not isinstance(obligations, list) or not obligations:
                errors.append(f"core_rewrite_batches.jsonl record {index} must include implemented obligations")
            elif not all(isinstance(item, str) and item for item in obligations):
                errors.append(f"core_rewrite_batches.jsonl record {index} obligations must be non-empty strings")
            else:
                implemented_obligations.update(obligations)
        missing_obligations = sorted(required_obligations - implemented_obligations)
        if missing_obligations:
            errors.append(
                "core_rewrite_batches.jsonl must cover all rust_api_design.json implementation_requirements: "
                + ", ".join(missing_obligations)
            )
        if state.get("controller_contract_version"):
            receipt, receipt_error = load_json(
                root / "logs" / "trace" / "stage-receipts" / "REWRITE_CORE_MODULES.json"
            )
            if receipt_error:
                errors.append(f"REWRITE_CORE_MODULES receipt: {receipt_error}")
            else:
                actual_changes = {
                    item for item in receipt.get("changed_files", [])
                    if isinstance(item, str) and item.startswith("flashDB_rust/src/")
                }
                claimed_changes = {
                    item
                    for batch in batches
                    if isinstance(batch, dict)
                    for item in batch.get("changed_files", [])
                    if isinstance(item, str)
                }
                unchanged_claims = sorted(claimed_changes - actual_changes)
                if unchanged_claims:
                    errors.append(
                        "core_rewrite_batches.jsonl claims files absent from the controller REWRITE baseline: "
                        + ", ".join(unchanged_claims)
                    )
    if state.get("controller_contract_version"):
        audit_tool = Path(__file__).resolve().with_name("core_impl_audit.py")
        spec = importlib.util.spec_from_file_location("core_impl_audit", audit_tool)
        if spec is None or spec.loader is None:
            errors.append("core_impl_audit.py could not be loaded")
        else:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            audit = module.audit(
                root=root,
                project=project,
                manifest_path=root / "logs" / "trace" / "scaffold-manifest.json",
                design_path=root / "logs" / "trace" / "rust_api_design.json",
            )
            audit_path = root / "logs" / "trace" / "implementation-audit.json"
            audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            if audit.get("status") != "pass":
                findings = audit.get("findings")
                rendered = [
                    f"{item.get('code')}:{item.get('evidence', {}).get('symbol') or item.get('evidence', {}).get('path') or item.get('evidence', {}).get('module') or 'unknown'}"
                    for item in findings[:20]
                    if isinstance(item, dict)
                ] if isinstance(findings, list) else []
                errors.append("core implementation audit failed: " + (", ".join(rendered) or "unknown finding"))
    if project.exists():
        errors.extend(check_project_command(project, ["cargo", "fmt", "--all", "--", "--check"], "rewritten project cargo fmt"))
        errors.extend(check_project_command(project, ["cargo", "build", "--release"], "rewritten project release build"))
    if not (root / "logs" / "trace" / "06-rewrite-core-modules.md").exists():
        errors.append("missing logs/trace/06-rewrite-core-modules.md")
    return errors


def check_validation_matrix(root: Path, *, allow_not_supported: bool = True, require_pass: bool = True) -> list[str]:
    errors: list[str] = []
    matrix, matrix_error = load_json(root / "logs" / "trace" / "validation-matrix.json")
    if matrix_error:
        return [f"validation-matrix.json: {matrix_error}"]

    test_model, test_model_error = load_json(root / "logs" / "trace" / "c_test_model.json")
    if test_model_error:
        return [f"c_test_model.json: {test_model_error}"]

    scorer_cases = test_model.get("scorer_standard_cases")
    invocations = test_model.get("registered_test_invocations")
    matrix_scenarios = matrix.get("scenarios")
    if not isinstance(scorer_cases, list):
        errors.append("c_test_model.json scorer_standard_cases must be a list")
    if not isinstance(matrix_scenarios, list):
        errors.append("validation-matrix.json scenarios must be a list")
    if not isinstance(scorer_cases, list) or not isinstance(matrix_scenarios, list):
        return errors

    expected_pair_by_scenario = {
        item.get("scenario_id"): item.get("case_id")
        for item in scorer_cases
        if isinstance(item, dict)
        and isinstance(item.get("scenario_id"), str)
        and isinstance(item.get("case_id"), str)
    }
    expected_scenario_ids = {
        item.get("scenario_id")
        for item in invocations
        if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)
    } if isinstance(invocations, list) and invocations else set(expected_pair_by_scenario)
    expected_case_ids = set(expected_pair_by_scenario.values())
    if not expected_scenario_ids:
        errors.append("c_test_model.json must provide registered_test_invocations or scorer_standard_cases scenarios")
    if not (isinstance(invocations, list) and invocations) and len(expected_scenario_ids) != len(scorer_cases):
        errors.append("c_test_model.json scorer_standard_cases scenario_id values must be present and unique")
    if len(expected_case_ids) != len(scorer_cases):
        errors.append("c_test_model.json scorer_standard_cases case_id values must be present and unique")
    if errors:
        return errors

    if matrix.get("total_scenarios") != len(expected_scenario_ids):
        errors.append("validation-matrix.json total_scenarios must equal registered invocation count")

    actual_scenario_ids = {
        item.get("scenario_id")
        for item in matrix_scenarios
        if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)
    }
    actual_case_ids = {
        item.get("scorer_case_id")
        for item in matrix_scenarios
        if isinstance(item, dict) and isinstance(item.get("scorer_case_id"), str)
    }
    if len(actual_scenario_ids) != len(matrix_scenarios):
        errors.append("validation-matrix.json scenario_id values must be present and unique")
    if len(actual_case_ids) != sum(1 for item in matrix_scenarios if isinstance(item, dict) and isinstance(item.get("scorer_case_id"), str)):
        errors.append("validation-matrix.json scorer_case_id values must be unique when present")

    missing_scenarios = sorted(expected_scenario_ids - actual_scenario_ids)
    extra_scenarios = sorted(actual_scenario_ids - expected_scenario_ids)
    if missing_scenarios:
        errors.append(f"validation-matrix.json missing scorer scenarios: {', '.join(missing_scenarios)}")
    if extra_scenarios:
        errors.append(f"validation-matrix.json contains unknown scorer scenarios: {', '.join(extra_scenarios)}")

    extra_case_ids = sorted(actual_case_ids - expected_case_ids, key=lambda item: int(item) if item.isdigit() else item)
    if extra_case_ids:
        errors.append(f"validation-matrix.json contains unknown scorer cases: {', '.join(extra_case_ids)}")

    rust_impl_failures: list[str] = []
    for item in matrix_scenarios:
        if not isinstance(item, dict):
            errors.append("validation-matrix.json scenarios entries must be objects")
            continue
        scenario_id_value = item.get("scenario_id")
        scenario_id = scenario_id_value if isinstance(scenario_id_value, str) else "<unknown>"
        scorer_case_id = item.get("scorer_case_id")
        if isinstance(scenario_id_value, str) and isinstance(scorer_case_id, str):
            expected_case_id = expected_pair_by_scenario.get(scenario_id_value)
            if expected_case_id is not None and scorer_case_id != expected_case_id:
                errors.append(
                    "validation-matrix.json scorer_case_id does not match scorer_standard_cases "
                    f"for scenario {scenario_id}: expected {expected_case_id}, got {scorer_case_id}"
                )

        has_blocking_value = False
        is_c_cross_exempt = "depends_on_private" in str(item.get("reason") or "")
        for key in ["c_impl_c_test", "rust_impl_c_test", "c_impl_rust_test", "rust_impl_rust_test"]:
            value = item.get(key)
            if value not in VALID_MATRIX_VALUES:
                errors.append(f"validation-matrix.json {key} has unknown value for scenario {scenario_id}: {value}")
                continue
            if value == "fail":
                has_blocking_value = True
            if key == "rust_impl_c_test" and value in {"not_run", "unresolved", "parse_failed"}:
                has_blocking_value = True
            if value == "not_supported":
                if not is_c_cross_exempt:
                    has_blocking_value = True
                if not allow_not_supported and not is_c_cross_exempt:
                    errors.append(f"validation-matrix.json not_supported is not allowed for scenario {scenario_id}")

        if item.get("rust_impl_c_test") == "fail" and isinstance(scenario_id, str):
            rust_impl_failures.append(scenario_id)

        if has_blocking_value:
            diagnosis = item.get("diagnosis")
            log_path = item.get("log")
            failure_layer = item.get("failure_layer")
            handoff = item.get("handoff")
            source_runner = item.get("source_runner")
            source_test = item.get("source_test")
            if not isinstance(failure_layer, str) or failure_layer not in VALID_FAILURE_LAYERS:
                errors.append(f"validation-matrix.json failure_layer must be present for scenario {scenario_id}")
            if not isinstance(handoff, str) or handoff not in VALID_HANDOFFS or (handoff == "none" and diagnosis != "c_cross_result_parse_failed"):
                errors.append(f"validation-matrix.json handoff must be present for scenario {scenario_id}")
            if not isinstance(source_runner, str) or not source_runner:
                errors.append(f"validation-matrix.json source_runner must be present for scenario {scenario_id}")
            if not isinstance(source_test, str) or not source_test:
                errors.append(f"validation-matrix.json source_test must be present for scenario {scenario_id}")
            if not isinstance(diagnosis, str) or diagnosis not in VALID_DIAGNOSES:
                errors.append(f"validation-matrix.json diagnosis must be a known value for scenario {scenario_id}")
            if not isinstance(log_path, str) or not log_path:
                errors.append(f"validation-matrix.json log must be present for scenario {scenario_id}")
            elif not is_c_cross_owned_log_path(log_path):
                errors.append(
                    "validation-matrix.json log must stay under logs/trace/c-cross/ "
                    f"for scenario {scenario_id}: {log_path}"
                )

    if rust_impl_failures and require_pass:
        errors.append(
            "Rust implementation failed C baseline scenarios: "
            + ", ".join(sorted(rust_impl_failures))
        )

    return errors


def check_c_cross_layered_evidence(root: Path) -> list[str]:
    errors: list[str] = []
    trace = root / "logs" / "trace"
    c_cross = trace / "c-cross"
    required = [
        c_cross / "build-check.json",
        c_cross / "layout-check.json",
        c_cross / "link-check.json",
        c_cross / "case-results.jsonl",
        c_cross / "diagnostics.jsonl",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing {path.relative_to(root)}")
    if errors:
        return errors

    matrix, matrix_error = load_json(trace / "validation-matrix.json")
    if matrix_error:
        return [f"validation-matrix.json: {matrix_error}"]
    if matrix.get("mode") != "full":
        errors.append("validation-matrix.json mode must be full for VERIFY_RUST_WITH_C_TESTS")

    for filename, expected_phase in [
        ("build-check.json", "build"),
        ("layout-check.json", "layout"),
        ("link-check.json", "link"),
    ]:
        data, data_error = load_json(c_cross / filename)
        if data_error:
            errors.append(f"{filename}: {data_error}")
            continue
        if data.get("phase") != expected_phase:
            errors.append(f"{filename} phase must be {expected_phase}")
        if data.get("status") != "pass":
            errors.append(f"{filename} status must be pass for VERIFY_RUST_WITH_C_TESTS")

    case_rows, case_error = load_jsonl(c_cross / "case-results.jsonl")
    if case_error:
        errors.append(f"case-results.jsonl: {case_error}")
        case_rows = []
    diagnostics, diag_error = load_jsonl(c_cross / "diagnostics.jsonl")
    if diag_error:
        errors.append(f"diagnostics.jsonl: {diag_error}")
        diagnostics = []

    scenarios = matrix.get("scenarios")
    if isinstance(scenarios, list):
        matrix_ids = {
            item.get("scenario_id")
            for item in scenarios
            if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)
        }
        case_ids = {
            item.get("scenario_id")
            for item in case_rows or []
            if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)
        }
        if matrix_ids != case_ids:
            errors.append("case-results.jsonl scenario_id set must match validation-matrix.json scenarios")
    for index, row in enumerate(case_rows or [], start=1):
        if not isinstance(row, dict):
            errors.append(f"case-results.jsonl record {index} must be an object")
            continue
        if row.get("phase") not in {"build", "layout", "link", "full"}:
            errors.append(f"case-results.jsonl record {index} has invalid phase")
        is_c_cross_exempt = (
            row.get("rust_impl_c_test") == "not_supported"
            and "depends_on_private" in str(row.get("reason") or "")
        )
        if row.get("phase") != "full" or (row.get("rust_impl_c_test") != "pass" and not is_c_cross_exempt):
            errors.append(f"case-results.jsonl record {index} must be full/pass for VERIFY_RUST_WITH_C_TESTS")

    for index, row in enumerate(diagnostics or [], start=1):
        if not isinstance(row, dict):
            errors.append(f"diagnostics.jsonl record {index} must be an object")
            continue
        if row.get("phase") not in {"build", "layout", "link", "full"}:
            errors.append(f"diagnostics.jsonl record {index} has invalid phase")
        diagnosis = row.get("diagnosis")
        if not isinstance(diagnosis, str) or not diagnosis:
            errors.append(f"diagnostics.jsonl record {index} must include diagnosis")
        handoff = row.get("handoff")
        if not isinstance(handoff, str) or handoff not in VALID_HANDOFFS or handoff == "none":
            errors.append(f"diagnostics.jsonl record {index} must include actionable handoff")
        log_path = row.get("log")
        if isinstance(log_path, str) and log_path and not is_c_cross_owned_log_path(log_path):
            errors.append(f"diagnostics.jsonl record {index} log must stay under logs/trace/c-cross/")
    return errors


def check_c_cross_intermediate_evidence(root: Path) -> list[str]:
    errors: list[str] = []
    trace = root / "logs" / "trace"
    c_cross = trace / "c-cross"
    matrix, matrix_error = load_json(trace / "validation-matrix.json")
    if matrix_error:
        return [f"validation-matrix.json: {matrix_error}"]

    link_check, link_error = load_json(c_cross / "link-check.json")
    if not link_error and link_check.get("status") == "pass":
        ffi_manifest, ffi_error = load_json(trace / "ffi_manifest.json")
        if ffi_error:
            errors.append(f"ffi_manifest.json: {ffi_error}")
        else:
            suite_requirements = ffi_manifest.get("suite_requirements")
            aggregate = ffi_manifest.get("required_ffi_apis")
            if not isinstance(suite_requirements, dict) or not suite_requirements:
                errors.append("ffi_manifest.json must retain per-suite requirements")
            if not isinstance(aggregate, list):
                errors.append("ffi_manifest.json required_ffi_apis must be a list")
            if isinstance(suite_requirements, dict) and isinstance(aggregate, list):
                expected = {
                    symbol
                    for item in suite_requirements.values()
                    if isinstance(item, dict)
                    for symbol in item.get("required_ffi_apis", [])
                    if isinstance(symbol, str)
                }
                if set(aggregate) != expected:
                    errors.append("ffi_manifest.json aggregate must equal the union of per-suite requirements")
                selected = matrix.get("selected_suites")
                if isinstance(selected, list) and not set(selected).issubset(set(suite_requirements)):
                    errors.append("ffi_manifest.json must include every successfully linked selected suite")

    for filename, expected_phase in [("build-check.json", "build"), ("layout-check.json", "layout"), ("link-check.json", "link")]:
        data, data_error = load_json(c_cross / filename)
        if data_error:
            errors.append(f"{filename}: {data_error}")
            continue
        if data.get("phase") != expected_phase:
            errors.append(f"{filename} phase must be {expected_phase}")

    if matrix.get("mode") != "full":
        errors.append("intermediate C-cross stage completion requires mode full")
    if matrix.get("scope", "all") != "all":
        errors.append("intermediate C-cross stage completion requires all-suite scope")
    errors.extend(check_validation_matrix(root, allow_not_supported=True, require_pass=False))

    case_rows, case_error = load_jsonl(c_cross / "case-results.jsonl")
    if case_error:
        errors.append(f"case-results.jsonl: {case_error}")
        case_rows = []
    diagnostics, diagnostics_error = load_jsonl(c_cross / "diagnostics.jsonl")
    if diagnostics_error:
        errors.append(f"diagnostics.jsonl: {diagnostics_error}")
        diagnostics = []
    scenarios = matrix.get("scenarios")
    scenario_rows = [row for row in scenarios if isinstance(row, dict)] if isinstance(scenarios, list) else []
    matrix_ids = {row.get("scenario_id") for row in scenario_rows}
    case_ids = {
        row.get("scenario_id")
        for row in case_rows or []
        if isinstance(row, dict)
    }
    if matrix_ids != case_ids:
        errors.append("case-results.jsonl scenario_id set must match validation-matrix.json scenarios")

    for row in scenario_rows:
        status = row.get("rust_impl_c_test")
        if status == "pass":
            continue
        scenario_id = str(row.get("scenario_id") or "<unknown>")
        if not isinstance(row.get("diagnosis"), str) or not isinstance(row.get("log"), str):
            errors.append(f"non-pass C-cross scenario lacks actionable evidence: {scenario_id}")
        if row.get("diagnosis") == "c_cross_result_parse_failed" and not any(
            isinstance(item, dict) and item.get("scenario_id") == row.get("scenario_id")
            for item in diagnostics or []
        ):
            errors.append(f"parse failure lacks diagnostics evidence: {scenario_id}")
    return errors


def check_c_cross_final_evidence(root: Path) -> list[str]:
    errors: list[str] = []
    trace = root / "logs" / "trace"
    matrix, matrix_error = load_json(trace / "validation-matrix.json")
    if matrix_error:
        return [f"validation-matrix.json: {matrix_error}"]
    if matrix.get("mode") != "full":
        errors.append("final C-cross requires mode full")
    if matrix.get("scope", "all") != "all":
        errors.append("final C-cross requires all-suite scope")
    if matrix.get("attempt_kind") != "final":
        errors.append("final C-cross requires attempt_kind final")

    errors.extend(check_validation_matrix(root, allow_not_supported=False))
    errors.extend(check_c_cross_layered_evidence(root))
    scenarios = matrix.get("scenarios")
    if isinstance(scenarios, list):
        failed_ids = [
            str(row.get("scenario_id") or "<unknown>")
            for row in scenarios
            if isinstance(row, dict)
            and row.get("rust_impl_c_test") != "pass"
            and not (
                row.get("rust_impl_c_test") == "not_supported"
                and "depends_on_private" in str(row.get("reason") or "")
            )
        ]
        if failed_ids:
            errors.append("final C-cross requires every scenario to pass: " + ", ".join(sorted(failed_ids)))

    attempts, attempt_error = load_jsonl(trace / "c-cross" / "attempts.jsonl")
    if attempt_error:
        errors.append(f"attempts.jsonl: {attempt_error}")
    execution_id = matrix.get("execution_id")
    matching_attempts = [row for row in attempts or [] if row.get("attempt_id") == execution_id]
    if not matching_attempts or matching_attempts[-1].get("kind") != "final":
        errors.append("final C-cross matrix must have a matching final attempt record")
    if not attempts or attempts[-1].get("attempt_id") != execution_id or attempts[-1].get("kind") != "final":
        errors.append("final C-cross matrix must match the latest attempt record")
    return errors


def check_c_cross_repair_transaction(root: Path) -> list[str]:
    receipt, receipt_error = load_json(
        root / "logs" / "trace" / "stage-receipts" / "VERIFY_RUST_WITH_C_TESTS.json"
    )
    if receipt_error:
        return [f"VERIFY_RUST_WITH_C_TESTS receipt: {receipt_error}"]
    run_rel = receipt.get("run_file")
    run, run_error = load_json(root / run_rel) if isinstance(run_rel, str) else (None, "missing")
    if run_error or not isinstance(run, dict):
        return [f"VERIFY_RUST_WITH_C_TESTS run: {run_error}"]
    entry_action = str(run.get("entry_action") or "")
    controlled_actions = {
        "REPAIR_RUST",
        "REPAIR_RUST_WITH_C_TESTS",
        "REPAIR_ABI_LAYOUT",
        "REANALYZE_C_MODEL",
        "CONFIRM_C_CROSS",
        "RESTORE_BEST",
        "ISOLATE_SCENARIOS",
    }
    if entry_action not in controlled_actions:
        return []

    errors: list[str] = []
    before = run.get("attempt_records_before")
    attempts, attempts_error = load_jsonl(root / "logs" / "trace" / "c-cross" / "attempts.jsonl")
    if attempts_error:
        return [f"attempts.jsonl: {attempts_error}"]
    if not isinstance(before, int) or before < 0 or before > len(attempts or []):
        return ["repair stage run has invalid attempt_records_before"]
    new_attempts = [row for row in (attempts or [])[before:] if isinstance(row, dict)]

    if entry_action == "ISOLATE_SCENARIOS":
        isolation_before = run.get("isolation_records_before")
        isolation_rows, isolation_error = load_jsonl(
            root / "logs" / "trace" / "c-cross" / "isolation-results.jsonl"
        )
        if isolation_error:
            return [f"isolation-results.jsonl: {isolation_error}"]
        if (
            not isinstance(isolation_before, int)
            or isolation_before < 0
            or len(isolation_rows or []) != isolation_before + 1
        ):
            errors.append("ISOLATE_SCENARIOS must consume exactly one pending isolation record")
        return errors

    confirmation_actions = {
        "REPAIR_ABI_LAYOUT",
        "REANALYZE_C_MODEL",
        "CONFIRM_C_CROSS",
        "RESTORE_BEST",
    }
    if entry_action in confirmation_actions:
        confirmations = [row for row in new_attempts if row.get("kind") == "confirmation"]
        if len(confirmations) != 1:
            errors.append(f"{entry_action} must produce exactly one new full confirmation attempt")
        if entry_action == "RESTORE_BEST":
            changed = receipt.get("changed_files")
            restore_receipts = [
                path for path in changed
                if isinstance(path, str)
                and path.startswith("logs/trace/c-cross/snapshots/restores/")
                and path.endswith("/receipt.json")
            ] if isinstance(changed, list) else []
            if len(restore_receipts) != 1:
                errors.append("RESTORE_BEST must create one tool-owned restore receipt")
        return errors

    new_repairs = [
        row for row in new_attempts if row.get("kind") == "repair"
    ]
    if len(new_repairs) != 1:
        errors.append("REPAIR_RUST transaction must produce exactly one new machine repair attempt")
        return errors

    changed = receipt.get("changed_files")
    actual_src = {
        path for path in changed
        if isinstance(path, str) and path.startswith("flashDB_rust/src/")
    } if isinstance(changed, list) else set()
    declared = {
        path for path in new_repairs[0].get("changed_files", [])
        if isinstance(path, str)
    } if isinstance(new_repairs[0].get("changed_files"), list) else set()
    if not actual_src:
        errors.append("REPAIR_RUST transaction must actually change at least one Rust src file")
    if actual_src != declared:
        errors.append(
            "repair attempt changed_files must exactly match receipt Rust src diff: "
            f"actual={sorted(actual_src)}, declared={sorted(declared)}"
        )
    attempt_hashes = new_repairs[0].get("changed_file_hashes")
    receipt_hashes = receipt.get("changed_file_hashes")
    if isinstance(attempt_hashes, dict) and isinstance(receipt_hashes, dict):
        mismatched = [
            path for path in sorted(actual_src)
            if attempt_hashes.get(path) != receipt_hashes.get(path)
        ]
        if mismatched:
            errors.append("repair attempt hashes do not match committed files: " + ", ".join(mismatched))
    else:
        errors.append("repair attempt and receipt must include changed-file hashes")
    return errors


def check_verify_rust_with_c_tests(root: Path) -> list[str]:
    errors = check_common_after_scaffold(root)
    required_stages = [
        "BOOTSTRAP",
        "INIT_WORKSPACE",
        "READ_C_PROJECT",
        "BUILD_C_MODEL",
        "DESIGN_RUST_API",
        "GENERATE_RUST_SCAFFOLD",
        "REWRITE_CORE_MODULES",
        "VERIFY_RUST_WITH_C_TESTS",
    ]
    state, state_errors = require_state(root, REQUIRED_C_CROSS_STATE_KEYS, "VERIFY_RUST_WITH_C_TESTS", required_stages)
    errors.extend(state_errors)
    if state is None:
        return errors
    errors.extend(check_c_cross_intermediate_evidence(root))
    errors.extend(check_c_cross_repair_transaction(root))
    if not (root / "logs" / "trace" / "c-cross" / "layout-check.log").exists():
        errors.append("missing logs/trace/c-cross/layout-check.log")
    if not (root / "logs" / "trace" / "06-5-verify-rust-with-c-tests.md").exists():
        errors.append("missing logs/trace/06-5-verify-rust-with-c-tests.md")
    if state.get("controller_contract_version") and isinstance(
        load_json(root / "logs" / "trace" / "validation-matrix.json")[0], dict
    ):
        matrix = load_json(root / "logs" / "trace" / "validation-matrix.json")[0] or {}
        scenarios = matrix.get("scenarios")
        non_pass = [
            row for row in scenarios
            if isinstance(row, dict) and row.get("rust_impl_c_test") != "pass"
        ] if isinstance(scenarios, list) else []
        if non_pass:
            repair_plan, repair_error = load_json(root / "logs" / "trace" / "c-cross" / "repair-plan.json")
            if repair_error:
                errors.append(f"repair-plan.json: {repair_error}")
            elif not isinstance(repair_plan.get("clusters"), list) or not repair_plan.get("clusters"):
                errors.append("non-pass C-cross evidence requires a non-empty machine repair plan")
    errors.extend(check_no_c_sources_in_src(root))
    return errors


def check_dynamic_test_mapping(root: Path) -> list[str]:
    errors: list[str] = []
    mapping, mapping_error = load_json(root / "logs" / "trace" / "rust_test_mapping.json")
    if mapping_error:
        return [f"rust_test_mapping.json: {mapping_error}"]
    if "kvdb" not in mapping or "tsdb" not in mapping:
        errors.append("rust_test_mapping.json must contain kvdb and tsdb sections")
        return errors

    test_model, test_model_error = load_json(root / "logs" / "trace" / "c_test_model.json")
    if test_model_error:
        return [f"c_test_model.json: {test_model_error}"]

    c_scenarios = test_model.get("standard_scenarios")
    scorer_cases = test_model.get("scorer_standard_cases")
    rust_scenarios = mapping.get("scenarios")
    if not isinstance(c_scenarios, list):
        errors.append("c_test_model.json standard_scenarios must be a list")
    if not isinstance(scorer_cases, list):
        errors.append("c_test_model.json scorer_standard_cases must be a list")
    if not isinstance(rust_scenarios, list):
        errors.append("rust_test_mapping.json scenarios must be a list")
    if not isinstance(c_scenarios, list) or not isinstance(scorer_cases, list) or not isinstance(rust_scenarios, list):
        return errors

    c_ids = {
        item.get("scenario_id", item.get("id"))
        for item in scorer_cases
        if isinstance(item, dict) and isinstance(item.get("scenario_id", item.get("id")), str)
    }
    rust_ids = {
        item.get("id")
        for item in rust_scenarios
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    missing_ids = sorted(c_ids - rust_ids)
    extra_ids = sorted(rust_ids - c_ids)
    if missing_ids:
        errors.append(f"missing Rust mappings for C scenarios: {', '.join(missing_ids)}")
    if extra_ids:
        errors.append(f"Rust mapping contains unknown C scenarios: {', '.join(extra_ids)}")
    if len(rust_ids) != len(rust_scenarios):
        errors.append("rust_test_mapping.json scenario ids must be present and unique")

    incomplete = sorted(
        str(item.get("id"))
        for item in rust_scenarios
        if isinstance(item, dict) and item.get("coverage") != "semantic"
    )
    if incomplete:
        errors.append(f"Rust scenario mappings are not semantic: {', '.join(incomplete)}")
    if mapping.get("total_scenarios") != len(c_ids):
        errors.append("rust_test_mapping.json total_scenarios must equal scorer-standard case count")
    if mapping.get("total_scorer_cases") != len(c_ids):
        errors.append("rust_test_mapping.json total_scorer_cases must equal scorer-standard case count")

    scorer_case_ids = {
        item.get("case_id")
        for item in scorer_cases
        if isinstance(item, dict) and isinstance(item.get("case_id"), str)
    }
    rust_case_ids = {
        item.get("scorer_case_id")
        for item in rust_scenarios
        if isinstance(item, dict) and isinstance(item.get("scorer_case_id"), str)
    }
    missing_case_ids = sorted(scorer_case_ids - rust_case_ids, key=lambda item: int(item) if item.isdigit() else item)
    extra_case_ids = sorted(rust_case_ids - scorer_case_ids, key=lambda item: int(item) if item.isdigit() else item)
    if missing_case_ids:
        errors.append(f"missing Rust mappings for scorer cases: {', '.join(missing_case_ids)}")
    if extra_case_ids:
        errors.append(f"Rust mapping contains unknown scorer cases: {', '.join(extra_case_ids)}")
    if len(rust_case_ids) != len(rust_scenarios):
        errors.append("rust_test_mapping.json scorer_case_id values must be present and unique")

    obligation_gaps: list[str] = []
    for item in rust_scenarios:
        if not isinstance(item, dict):
            continue
        obligations = item.get("semantic_obligations")
        if not isinstance(obligations, list) or not obligations:
            obligation_gaps.append(str(item.get("id")))
            continue
        if item.get("coverage") == "semantic":
            validated = item.get("validated_obligations")
            if not isinstance(validated, list) or set(obligations) - set(validated):
                obligation_gaps.append(str(item.get("id")))
    if obligation_gaps:
        errors.append(f"Rust scenario mappings lack validated scorer obligations: {', '.join(sorted(obligation_gaps))}")
    unmapped = mapping.get("unmapped")
    if isinstance(unmapped, list) and unmapped:
        errors.append("rust_test_mapping.json unmapped must be empty for MIGRATE_TESTS")

    project = root / "flashDB_rust"
    source_to_rust = mapping.get("source_to_rust")
    rust_test_files = []
    if isinstance(source_to_rust, dict):
        rust_test_files = [
            str(path)
            for path in source_to_rust.values()
            if isinstance(path, str) and path.startswith("flashDB_rust/tests/")
        ]
    if not rust_test_files:
        errors.append("rust_test_mapping.json source_to_rust must declare generated Rust test files")

    pending_files = []
    for rust_path in rust_test_files:
        rel_path = rust_path.removeprefix("flashDB_rust/")
        path = project / rel_path
        if not path.exists():
            errors.append(f"missing {rust_path}")
        elif "MIGRATION_PENDING" in path.read_text(encoding="utf-8", errors="ignore"):
            pending_files.append(rel_path)
    if pending_files:
        errors.append(f"Rust tests still contain MIGRATION_PENDING markers: {', '.join(pending_files)}")
    return errors


def check_test_consistency(root: Path) -> list[str]:
    tool_path = Path(__file__).resolve().with_name("test_consistency_check.py")
    spec = importlib.util.spec_from_file_location("test_consistency_check", tool_path)
    if spec is None or spec.loader is None:
        return ["test_consistency_check.py could not be loaded"]
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.analyze_consistency(root)
    report_path = root / "logs" / "trace" / "test-consistency.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report.get("status") != "pass":
        issues = report.get("issues", [])
        rendered = []
        if isinstance(issues, list):
            for issue in issues[:10]:
                if isinstance(issue, dict):
                    rendered.append(f"{issue.get('scenario_id')}: {issue.get('code')}")
        detail = "; ".join(rendered) if rendered else "unknown consistency issue"
        return [f"test consistency failed: {detail}"]
    return []


def check_test_placeholders(root: Path) -> list[str]:
    mapping_path = root / "logs" / "trace" / "rust_test_mapping.json"
    if not mapping_path.exists():
        return ["missing logs/trace/rust_test_mapping.json"]
    tool_path = Path(__file__).resolve().with_name("placeholder_check.py")
    spec = importlib.util.spec_from_file_location("placeholder_check", tool_path)
    if spec is None or spec.loader is None:
        return ["placeholder_check.py could not be loaded"]
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.analyze_placeholders(
        root,
        root / "flashDB_rust" / "tests",
        mapping_path,
    )
    report_path = root / "logs" / "trace" / "test-placeholder-check.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report.get("status") != "pass":
        issues = report.get("issues", [])
        rendered = [
            f"{item.get('test_name') or item.get('file')}: {item.get('code')}"
            for item in issues[:10]
            if isinstance(item, dict)
        ] if isinstance(issues, list) else []
        return ["test placeholder check failed: " + ("; ".join(rendered) or "unknown placeholder issue")]
    return []


def check_migrate_tests(root: Path) -> list[str]:
    errors = check_common_after_scaffold(root)
    required_stages = [
        "BOOTSTRAP",
        "INIT_WORKSPACE",
        "READ_C_PROJECT",
        "BUILD_C_MODEL",
        "DESIGN_RUST_API",
        "GENERATE_RUST_SCAFFOLD",
        "REWRITE_CORE_MODULES",
        "VERIFY_RUST_WITH_C_TESTS",
        "MIGRATE_TESTS",
    ]
    state, state_errors = require_state(root, REQUIRED_TEST_STATE_KEYS, "MIGRATE_TESTS", required_stages)
    errors.extend(state_errors)
    if state is None:
        return errors
    if state.get("controller_contract_version") and state.get("c_cross_functional_status") == "repair_required":
        errors.append("C-cross repair queue must converge or exhaust its explicit budget before MIGRATE_TESTS")

    errors.extend(check_dynamic_test_mapping(root))
    errors.extend(check_test_placeholders(root))
    errors.extend(check_test_consistency(root))

    if not (root / "logs" / "trace" / "07-migrate-tests.md").exists():
        errors.append("missing logs/trace/07-migrate-tests.md")
    return errors


def check_build_test_repair(root: Path) -> list[str]:
    errors = check_common_after_scaffold(root)
    required_stages = [
        "BOOTSTRAP",
        "INIT_WORKSPACE",
        "READ_C_PROJECT",
        "BUILD_C_MODEL",
        "DESIGN_RUST_API",
        "GENERATE_RUST_SCAFFOLD",
        "REWRITE_CORE_MODULES",
        "VERIFY_RUST_WITH_C_TESTS",
        "MIGRATE_TESTS",
        "BUILD_TEST_REPAIR",
    ]
    state, state_errors = require_state(root, REQUIRED_TEST_STATE_KEYS, "BUILD_TEST_REPAIR", required_stages)
    errors.extend(state_errors)
    if state is None:
        return errors
    if state.get("build_status") != "pass":
        errors.append("workflow_state.json build_status must be pass")
    if state.get("test_status") != "pass":
        errors.append("workflow_state.json test_status must be pass")

    results, results_error = load_json(root / "logs" / "trace" / "cargo-results.json")
    if results_error:
        errors.append(f"cargo-results.json: {results_error}")
    else:
        if results.get("build_status") != "pass":
            errors.append("cargo-results.json build_status must be pass")
        if results.get("test_status") != "pass":
            errors.append("cargo-results.json test_status must be pass")
    for name in ["cargo-build.log", "cargo-test.log", "08-build-test-repair.md"]:
        if not (root / "logs" / "trace" / name).exists():
            errors.append(f"missing logs/trace/{name}")
    errors.extend(check_test_failure_triage(root, state))
    errors.extend(check_no_c_sources_in_src(root))
    return errors


def check_test_failure_triage(root: Path, state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    triage_path = root / "logs" / "trace" / "test-failure-triage.jsonl"
    triage_required = bool(state.get("test_failure_triage_required"))
    if not triage_required and not triage_path.exists():
        return errors

    rows, rows_error = load_jsonl(triage_path)
    if rows_error:
        return [f"test-failure-triage.jsonl: {rows_error}"]
    if not rows:
        return ["test-failure-triage.jsonl must contain at least one triage record when test failure triage is required"]

    for index, row in enumerate(rows, start=1):
        classification = row.get("classification")
        if classification not in VALID_TEST_TRIAGE_CLASSIFICATIONS:
            errors.append(f"test-failure-triage.jsonl record {index} has invalid classification")
        evidence_paths = row.get("evidence_paths")
        if not isinstance(evidence_paths, list) or not evidence_paths:
            errors.append(f"test-failure-triage.jsonl record {index} must include evidence_paths")
        allowed_edit_scope = row.get("allowed_edit_scope")
        if not isinstance(allowed_edit_scope, list) or not allowed_edit_scope:
            errors.append(f"test-failure-triage.jsonl record {index} must include allowed_edit_scope")
        if not isinstance(row.get("allow_src_edit"), bool):
            errors.append(f"test-failure-triage.jsonl record {index} must include boolean allow_src_edit")
        if classification == "test_oracle_suspect" and row.get("allow_src_edit"):
            errors.append("test_oracle_suspect triage records must not allow src edits")
        if row.get("allow_src_edit") is False and any(
            isinstance(scope, str) and scope.rstrip("/").startswith("flashDB_rust/src")
            for scope in (allowed_edit_scope if isinstance(allowed_edit_scope, list) else [])
        ):
            errors.append(
                f"test-failure-triage.jsonl record {index} forbids src edits but includes src in allowed_edit_scope"
            )

    if state.get("controller_contract_version") and rows:
        if len(rows) != 1:
            errors.append("controller-owned test triage must contain exactly one current record")
        tool_path = Path(__file__).resolve().with_name("test_failure_triage.py")
        spec = importlib.util.spec_from_file_location("test_failure_triage", tool_path)
        if spec is None or spec.loader is None:
            errors.append("test_failure_triage.py could not be loaded")
        else:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            expected_triage = module.build_record(root, root / "logs" / "trace")
            if rows[-1] != expected_triage:
                errors.append("controller-owned test triage does not match current cargo evidence")

        receipt, receipt_error = load_json(
            root / "logs" / "trace" / "stage-receipts" / "BUILD_TEST_REPAIR.json"
        )
        if receipt_error:
            errors.append(f"BUILD_TEST_REPAIR receipt: {receipt_error}")
        else:
            changed_files = receipt.get("changed_files")
            repair_changes = [
                path
                for path in changed_files if isinstance(path, str)
                if path.startswith("flashDB_rust/") or path == "logs/trace/rust_test_mapping.json"
            ] if isinstance(changed_files, list) else []
            packet_rel = receipt.get("task_packet")
            packet, packet_error = load_json(root / packet_rel) if isinstance(packet_rel, str) else (None, "missing")
            authorization = packet.get("triage_authorization") if isinstance(packet, dict) else None
            if packet_error and repair_changes:
                errors.append(f"BUILD_TEST_REPAIR task packet: {packet_error}")
            scopes = [
                scope for scope in authorization.get("allowed_edit_scope", [])
                if isinstance(scope, str)
            ] if isinstance(authorization, dict) and isinstance(authorization.get("allowed_edit_scope"), list) else []
            if not isinstance(authorization, dict) and repair_changes:
                errors.append("BUILD_TEST_REPAIR edits require begin-time triage authorization")
            if not isinstance(authorization, dict) or authorization.get("allow_src_edit") is not True:
                forbidden_src = [path for path in repair_changes if path.startswith("flashDB_rust/src/")]
                if forbidden_src:
                    errors.append(
                        "BUILD_TEST_REPAIR changed Rust src despite allow_src_edit=false: "
                        + ", ".join(forbidden_src)
                    )
            outside_scope = [path for path in repair_changes if not _receipt_path_allowed(path, scopes)]
            if outside_scope:
                errors.append(
                    "BUILD_TEST_REPAIR changes exceed latest triage scope: "
                    + ", ".join(outside_scope)
                )
    return errors


def check_report_and_verify(root: Path) -> list[str]:
    errors = check_common_after_scaffold(root)
    required_stages = [
        "BOOTSTRAP",
        "INIT_WORKSPACE",
        "READ_C_PROJECT",
        "BUILD_C_MODEL",
        "DESIGN_RUST_API",
        "GENERATE_RUST_SCAFFOLD",
        "REWRITE_CORE_MODULES",
        "VERIFY_RUST_WITH_C_TESTS",
        "MIGRATE_TESTS",
        "BUILD_TEST_REPAIR",
        "REPORT_AND_VERIFY",
    ]
    state, state_errors = require_state(root, REQUIRED_TEST_STATE_KEYS, "REPORT_AND_VERIFY", required_stages)
    errors.extend(state_errors)
    if state is None:
        return errors
    if state.get("current_stage") != "DONE":
        errors.append("workflow_state.json current_stage must be DONE for final report")
    if state.get("build_status") != "pass" or state.get("test_status") != "pass":
        errors.append("workflow_state.json build_status and test_status must be pass")
    errors.extend(check_c_cross_final_evidence(root))
    errors.extend(check_dynamic_test_mapping(root))
    errors.extend(check_test_placeholders(root))
    errors.extend(check_test_consistency(root))
    errors.extend(check_subagent_evidence(root))

    ratio, ratio_error = load_json(root / "logs" / "trace" / "unsafe-ratio.json")
    if ratio_error:
        errors.append(f"unsafe-ratio.json: {ratio_error}")
    else:
        try:
            value = float(ratio.get("unsafe_ratio"))
        except (TypeError, ValueError):
            errors.append("unsafe-ratio.json unsafe_ratio must be numeric")
        else:
            if value > 0.10:
                errors.append("unsafe-ratio.json unsafe_ratio must be <= 0.10")

    for name in ["cargo-build.log", "cargo-test.log", "final-verification.md", "09-report-and-verify.md"]:
        if not (root / "logs" / "trace" / name).exists():
            errors.append(f"missing logs/trace/{name}")
    output = root / "result" / "output.md"
    issues = root / "result" / "issues" / "00-summary.md"
    if not output.exists():
        errors.append("missing result/output.md")
    elif "STATUS: SUCCESS" not in output.read_text(encoding="utf-8", errors="ignore"):
        errors.append("result/output.md must contain STATUS: SUCCESS")
    if not issues.exists():
        errors.append("missing result/issues/00-summary.md")

    errors.extend(check_no_c_sources_in_src(root))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate staged FlashDB migration workbench outputs.")
    parser.add_argument("--stage", required=True, help="Stage name to validate.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    stage = args.stage.upper()

    if stage == "INIT_WORKSPACE":
        errors = check_init_workspace(root)
    elif stage == "READ_C_PROJECT":
        errors = check_read_c_project(root)
    elif stage == "BUILD_C_MODEL":
        errors = check_build_c_model(root)
    elif stage == "DESIGN_RUST_API":
        errors = check_design_rust_api(root)
    elif stage == "GENERATE_RUST_SCAFFOLD":
        errors = check_generate_rust_scaffold(root)
    elif stage == "REWRITE_CORE_MODULES":
        errors = check_rewrite_core_modules(root)
    elif stage == "VERIFY_RUST_WITH_C_TESTS":
        errors = check_verify_rust_with_c_tests(root)
    elif stage == "MIGRATE_TESTS":
        errors = check_migrate_tests(root)
    elif stage == "BUILD_TEST_REPAIR":
        errors = check_build_test_repair(root)
    elif stage == "REPORT_AND_VERIFY":
        errors = check_report_and_verify(root)
    else:
        print(f"{stage}: FAIL")
        print(f"unsupported stage for this checkpoint: {stage}")
        return 2
    if errors:
        print(f"{stage}: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    errors.extend(check_stage_receipt(root, stage))

    if errors:
        print(f"{stage}: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"{stage}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
