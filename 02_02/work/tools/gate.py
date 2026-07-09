#!/usr/bin/env python3
"""Stage gate checks for the FlashDB opencode workbench."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


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

VALID_MATRIX_VALUES = {"baseline", "pass", "fail", "not_run", "not_supported", "pending"}
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
    "c_test_case_failed",
    "c_cross_result_parse_failed",
    "c_model_signature_gap",
}

VALID_FAILURE_LAYERS = {"build", "layout", "link", "full"}
VALID_HANDOFFS = {"none", "c-analyzer", "rust-implementer", "test-migrator", "repairer"}

VALID_TEST_TRIAGE_CLASSIFICATIONS = {
    "test_oracle_suspect",
    "rust_impl_suspect",
    "harness_suspect",
    "insufficient_evidence",
}


def safe_rust_ident(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not ident:
        ident = "item"
    if ident[0].isdigit():
        ident = f"item_{ident}"
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


def required_signature_symbols(api_model: dict[str, Any], test_model: dict[str, Any]) -> set[str]:
    public = {
        item for item in api_model.get("public_functions", [])
        if isinstance(item, str)
    } if isinstance(api_model.get("public_functions"), list) else set()
    required = {
        item
        for key in ["kvdb_symbols", "tsdb_symbols"]
        for item in api_model.get(key, [])
        if isinstance(item, str)
    }
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
        for key in ["kvdb_symbols", "tsdb_symbols"]
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


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def check_subagent_evidence(root: Path) -> list[str]:
    errors: list[str] = []
    trace = root / "logs" / "trace"
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
        for name, stages in REQUIRED_SUBAGENTS.items():
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
        allowed_modes = {"native", "generic_subagent", "isolated_proxy", "primary_fallback"}
        c_analyzer_success_stages: set[str] = set()
        for index, row in enumerate(rows, start=1):
            agent = row.get("agent")
            if agent in REQUIRED_SUBAGENTS:
                seen.add(agent)
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
            if row.get("mode") == "primary_fallback":
                failures = row.get("consecutive_failures")
                if not isinstance(failures, int) or failures < 3:
                    errors.append("primary_fallback records must include consecutive_failures >= 3")
                reason = row.get("fallback_to_primary_reason")
                if not isinstance(reason, str) or not reason.strip():
                    errors.append("primary_fallback records must include fallback_to_primary_reason")
        missing = sorted(set(REQUIRED_SUBAGENTS) - seen)
        if missing:
            errors.append(f"subagent-invocations.jsonl missing records for: {', '.join(missing)}")
        individual_c_stages = {"READ_C_PROJECT", "BUILD_C_MODEL", "DESIGN_RUST_API"}
        if individual_c_stages & c_analyzer_success_stages:
            errors.append("c-analyzer must be recorded as one C_ANALYSIS invocation, not per C stage")
        if "c-analyzer" in seen and "C_ANALYSIS" not in c_analyzer_success_stages:
            errors.append("subagent-invocations.jsonl must include c-analyzer success record with stage C_ANALYSIS")
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
    errors.extend(check_abi_layout_contract(api_model))
    errors.extend(check_function_signature_contract(api_model, test_model))

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
    if not (root / "logs" / "trace" / "06-rewrite-core-modules.md").exists():
        errors.append("missing logs/trace/06-rewrite-core-modules.md")
    return errors


def check_validation_matrix(root: Path, *, allow_not_supported: bool = True) -> list[str]:
    errors: list[str] = []
    matrix, matrix_error = load_json(root / "logs" / "trace" / "validation-matrix.json")
    if matrix_error:
        return [f"validation-matrix.json: {matrix_error}"]

    test_model, test_model_error = load_json(root / "logs" / "trace" / "c_test_model.json")
    if test_model_error:
        return [f"c_test_model.json: {test_model_error}"]

    scorer_cases = test_model.get("scorer_standard_cases")
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
    expected_scenario_ids = set(expected_pair_by_scenario)
    expected_case_ids = set(expected_pair_by_scenario.values())
    if len(expected_scenario_ids) != len(scorer_cases):
        errors.append("c_test_model.json scorer_standard_cases scenario_id values must be present and unique")
    if len(expected_case_ids) != len(scorer_cases):
        errors.append("c_test_model.json scorer_standard_cases case_id values must be present and unique")
    if errors:
        return errors

    if matrix.get("total_scenarios") != len(scorer_cases):
        errors.append("validation-matrix.json total_scenarios must equal scorer-standard case count")

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
    if len(actual_case_ids) != len(matrix_scenarios):
        errors.append("validation-matrix.json scorer_case_id values must be present and unique")

    missing_scenarios = sorted(expected_scenario_ids - actual_scenario_ids)
    extra_scenarios = sorted(actual_scenario_ids - expected_scenario_ids)
    if missing_scenarios:
        errors.append(f"validation-matrix.json missing scorer scenarios: {', '.join(missing_scenarios)}")
    if extra_scenarios:
        errors.append(f"validation-matrix.json contains unknown scorer scenarios: {', '.join(extra_scenarios)}")

    missing_case_ids = sorted(expected_case_ids - actual_case_ids, key=lambda item: int(item) if item.isdigit() else item)
    extra_case_ids = sorted(actual_case_ids - expected_case_ids, key=lambda item: int(item) if item.isdigit() else item)
    if missing_case_ids:
        errors.append(f"validation-matrix.json missing scorer cases: {', '.join(missing_case_ids)}")
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
        for key in ["c_impl_c_test", "rust_impl_c_test", "c_impl_rust_test", "rust_impl_rust_test"]:
            value = item.get(key)
            if value not in VALID_MATRIX_VALUES:
                errors.append(f"validation-matrix.json {key} has unknown value for scenario {scenario_id}: {value}")
                continue
            if value == "fail":
                has_blocking_value = True
            if value == "not_supported":
                has_blocking_value = True
                if not allow_not_supported:
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
            if not isinstance(handoff, str) or handoff not in VALID_HANDOFFS or handoff == "none":
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

    if rust_impl_failures:
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
        if row.get("phase") != "full" or row.get("rust_impl_c_test") != "pass":
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
    errors.extend(check_validation_matrix(root, allow_not_supported=False))
    errors.extend(check_c_cross_layered_evidence(root))
    if not (root / "logs" / "trace" / "c-cross" / "layout-check.log").exists():
        errors.append("missing logs/trace/c-cross/layout-check.log")
    if not (root / "logs" / "trace" / "06-5-verify-rust-with-c-tests.md").exists():
        errors.append("missing logs/trace/06-5-verify-rust-with-c-tests.md")
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

    errors.extend(check_dynamic_test_mapping(root))
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
    errors.extend(check_validation_matrix(root, allow_not_supported=True))
    errors.extend(check_dynamic_test_mapping(root))
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

    print(f"{stage}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
