#!/usr/bin/env python3
"""Stage gate checks for the FlashDB opencode workbench."""

from __future__ import annotations

import argparse
import json
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

REQUIRED_TEST_STATE_KEYS = REQUIRED_DESIGN_STATE_KEYS | {
    "rust_test_mapping",
}


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


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


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
    else:
        for symbol in ["fdb_kvdb_init", "fdb_tsdb_init"]:
            if symbol not in public_functions:
                errors.append(f"c_api_model.json public_functions missing {symbol}")

    if not api_model.get("kvdb_symbols"):
        errors.append("c_api_model.json kvdb_symbols must be non-empty")
    if not api_model.get("tsdb_symbols"):
        errors.append("c_api_model.json tsdb_symbols must be non-empty")

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
        if not isinstance(modules, list) or not all(item in modules for item in ["error", "flash", "kvdb", "tsdb"]):
            errors.append("rust_api_design.json modules must include error, flash, kvdb, and tsdb")

        core_types = design.get("core_types")
        required_types = ["FlashStorage", "MemFlash", "FileFlash", "FdbError", "KvDb", "TsDb", "TslRecord"]
        if not isinstance(core_types, list) or not all(item in core_types for item in required_types):
            errors.append("rust_api_design.json core_types missing required FlashDB Rust types")

        traits = design.get("traits")
        if not isinstance(traits, list) or "FlashStorage" not in traits:
            errors.append("rust_api_design.json traits must include FlashStorage")

        if not isinstance(design.get("kvdb_api"), list) or not design.get("kvdb_api"):
            errors.append("rust_api_design.json kvdb_api must be a non-empty list")
        if not isinstance(design.get("tsdb_api"), list) or not design.get("tsdb_api"):
            errors.append("rust_api_design.json tsdb_api must be a non-empty list")
        if not isinstance(design.get("test_api"), dict):
            errors.append("rust_api_design.json test_api must be an object")

        error_model = design.get("error_model")
        if not isinstance(error_model, dict) or error_model.get("result_alias") != "Result<T, FdbError>":
            errors.append("rust_api_design.json error_model.result_alias must be Result<T, FdbError>")

        storage_model = design.get("storage_model")
        implementations = storage_model.get("implementations") if isinstance(storage_model, dict) else None
        if not isinstance(implementations, list) or not all(item in implementations for item in ["MemFlash", "FileFlash"]):
            errors.append("rust_api_design.json storage_model.implementations must include MemFlash and FileFlash")

        symbol_map = design.get("c_to_rust_symbol_map")
        if not isinstance(symbol_map, dict):
            errors.append("rust_api_design.json c_to_rust_symbol_map must be an object")
        else:
            if symbol_map.get("fdb_kvdb_init") != "KvDb::open":
                errors.append("rust_api_design.json c_to_rust_symbol_map.fdb_kvdb_init must be KvDb::open")
            if symbol_map.get("fdb_tsdb_init") != "TsDb::open":
                errors.append("rust_api_design.json c_to_rust_symbol_map.fdb_tsdb_init must be TsDb::open")

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
    for rel_path in ["Cargo.toml", "src/lib.rs", "src/error.rs", "src/flash.rs", "src/kvdb.rs", "src/tsdb.rs", "tests"]:
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
    for rel_path in ["src/error.rs", "src/flash.rs", "src/kvdb.rs", "src/tsdb.rs"]:
        path = project / rel_path
        if not path.exists() or not path.read_text(encoding="utf-8", errors="ignore").strip():
            errors.append(f"flashDB_rust/{rel_path} must exist and be non-empty")
        elif "todo!()" in path.read_text(encoding="utf-8", errors="ignore") or "unimplemented!()" in path.read_text(encoding="utf-8", errors="ignore"):
            errors.append(f"flashDB_rust/{rel_path} must not contain todo!() or unimplemented!()")

    if list((project / "src").glob("*.c")):
        errors.append("flashDB_rust/src must not contain C source files")
    if not (root / "logs" / "trace" / "06-rewrite-core-modules.md").exists():
        errors.append("missing logs/trace/06-rewrite-core-modules.md")
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
    rust_scenarios = mapping.get("scenarios")
    if not isinstance(c_scenarios, list):
        errors.append("c_test_model.json standard_scenarios must be a list")
    if not isinstance(rust_scenarios, list):
        errors.append("rust_test_mapping.json scenarios must be a list")
    if not isinstance(c_scenarios, list) or not isinstance(rust_scenarios, list):
        return errors

    c_ids = {
        item.get("id")
        for item in c_scenarios
        if isinstance(item, dict) and isinstance(item.get("id"), str)
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
        errors.append("rust_test_mapping.json total_scenarios must equal extracted C scenario count")
    unmapped = mapping.get("unmapped")
    if isinstance(unmapped, list) and unmapped:
        errors.append("rust_test_mapping.json unmapped must be empty for MIGRATE_TESTS")

    project = root / "flashDB_rust"
    pending_files = []
    for rel_path in ["tests/kvdb_tests.rs", "tests/tsdb_tests.rs", "tests/equivalence_tests.rs"]:
        path = project / rel_path
        if path.exists() and "MIGRATION_PENDING" in path.read_text(encoding="utf-8", errors="ignore"):
            pending_files.append(rel_path)
    if pending_files:
        errors.append(f"Rust tests still contain MIGRATION_PENDING markers: {', '.join(pending_files)}")
    return errors


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
        "MIGRATE_TESTS",
    ]
    state, state_errors = require_state(root, REQUIRED_TEST_STATE_KEYS, "MIGRATE_TESTS", required_stages)
    errors.extend(state_errors)
    if state is None:
        return errors

    project = root / "flashDB_rust"
    for rel_path in ["tests/kvdb_tests.rs", "tests/tsdb_tests.rs", "tests/equivalence_tests.rs"]:
        path = project / rel_path
        if not path.exists():
            errors.append(f"missing flashDB_rust/{rel_path}")
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "assert!" not in text and "assert_eq!" not in text:
                errors.append(f"flashDB_rust/{rel_path} must contain assertions")

    errors.extend(check_dynamic_test_mapping(root))

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
    errors.extend(check_dynamic_test_mapping(root))

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

    if list((root / "flashDB_rust").rglob("*.c")):
        errors.append("final Rust project must not contain C source files")
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
