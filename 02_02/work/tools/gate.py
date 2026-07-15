#!/usr/bin/env python3
"""Validate observable outputs of the simplified FlashDB migration workflow."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


VALID_CROSS_RESULTS = {"pass", "fail", "not_run", "not_supported", "parse_failed", "unresolved"}


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    return (data, None) if isinstance(data, dict) else (None, "must be a JSON object")


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None, "missing"
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            return None, f"invalid JSONL: {exc}"
        if not isinstance(item, dict):
            return None, "JSONL rows must be objects"
        rows.append(item)
    return rows, None


def require_paths(root: Path, paths: list[str]) -> list[str]:
    return [f"missing {path}" for path in paths if not (root / path).exists()]


def check_workspace(root: Path, *, requires_project: bool) -> list[str]:
    errors = require_paths(root, ["result", "result/issues", "logs", "logs/trace", "logs/interaction.md"])
    project = root / "flashDB_rust"
    if requires_project and not project.is_dir():
        errors.append("missing flashDB_rust")
    if not requires_project and project.exists():
        errors.append("flashDB_rust must not exist before IMPLEMENT")
    return errors


def check_no_c_sources_in_src(root: Path) -> list[str]:
    src = root / "flashDB_rust" / "src"
    return ["flashDB_rust/src must not contain C source files"] if src.is_dir() and list(src.rglob("*.c")) else []


def check_analyze(root: Path) -> list[str]:
    errors = check_workspace(root, requires_project=False)
    trace = root / "logs" / "trace"
    names = {
        "input_manifest.json": "manifest",
        "c_project_model.json": "project",
        "c_api_model.json": "api",
        "c_test_model.json": "tests",
        "rust_api_design.json": "design",
    }
    data: dict[str, dict[str, Any]] = {}
    for filename, key in names.items():
        item, error = load_json(trace / filename)
        if error:
            errors.append(f"{filename}: {error}")
        elif item is not None:
            data[key] = item
    errors.extend(require_paths(root, [
        "logs/trace/input-source-baseline.json",
        "logs/trace/02-read-c-project.md",
        "logs/trace/03-build-c-model.md",
        "logs/trace/04-design-rust-api.md",
    ]))
    if errors:
        return errors
    manifest, project, api, tests, design = (data[key] for key in ("manifest", "project", "api", "tests", "design"))
    digest = manifest.get("input_digest")
    if not isinstance(digest, str) or not digest:
        errors.append("input_manifest.json must contain input_digest")
    for filename, item in [("c_project_model.json", project), ("c_api_model.json", api), ("c_test_model.json", tests), ("rust_api_design.json", design)]:
        if item.get("input_digest") != digest:
            errors.append(f"{filename} input_digest must match input_manifest.json")
    for key in ("core_sources", "test_sources", "headers"):
        if not isinstance(manifest.get(key), list) or not manifest[key]:
            errors.append(f"input_manifest.json {key} must be a non-empty list")
    if not isinstance(project.get("modules"), dict) or not project["modules"]:
        errors.append("c_project_model.json modules must be a non-empty object")
    if not isinstance(api.get("public_functions"), list) or not api["public_functions"]:
        errors.append("c_api_model.json public_functions must be non-empty")
    layouts = api.get("abi_layouts")
    if not isinstance(layouts, list) or not layouts:
        errors.append("c_api_model.json abi_layouts must be a non-empty dynamic list")
    scenarios = tests.get("scorer_standard_cases")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("c_test_model.json scorer_standard_cases must be a non-empty dynamic list")
    elif any(not isinstance(item, dict) or not isinstance(item.get("scenario_id"), str) or not isinstance(item.get("case_id"), str) for item in scenarios):
        errors.append("every scorer_standard_case must contain scenario_id and case_id")
    facade = design.get("c_abi_facade")
    if not isinstance(facade, dict) or not isinstance(facade.get("functions"), list) or not facade["functions"]:
        errors.append("rust_api_design.json must include non-empty c_abi_facade.functions")
    return errors


def matrix_scenario_ids(root: Path) -> tuple[set[str], list[str]]:
    tests, error = load_json(root / "logs" / "trace" / "c_test_model.json")
    if error or tests is None:
        return set(), [f"c_test_model.json: {error}"]
    cases = tests.get("scorer_standard_cases")
    if not isinstance(cases, list):
        return set(), ["c_test_model.json scorer_standard_cases must be a list"]
    ids = {item.get("scenario_id") for item in cases if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)}
    return ids, [] if len(ids) == len(cases) else ["scorer_standard_cases scenario_id values must be present and unique"]


def check_c_cross(root: Path, *, final: bool) -> list[str]:
    errors: list[str] = []
    trace = root / "logs" / "trace"
    cross = trace / "c-cross"
    matrix, matrix_error = load_json(trace / "validation-matrix.json")
    if matrix_error or matrix is None:
        return [f"validation-matrix.json: {matrix_error}"]
    if matrix.get("mode") != "full" or matrix.get("scope") != "all":
        errors.append("validation-matrix.json must cover full/all C-Cross")
    if final and matrix.get("attempt_kind") != "final":
        errors.append("final verification requires a fresh final C-Cross attempt")
    expected_ids, id_errors = matrix_scenario_ids(root)
    errors.extend(id_errors)
    scenarios = matrix.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return errors + ["validation-matrix.json scenarios must be non-empty"]
    actual_ids = {item.get("scenario_id") for item in scenarios if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)}
    if actual_ids != expected_ids:
        errors.append("validation-matrix scenarios must match dynamically discovered scorer cases")
    for item in scenarios:
        if not isinstance(item, dict):
            errors.append("validation-matrix scenarios must be objects")
            continue
        status = item.get("rust_impl_c_test")
        scenario_id = item.get("scenario_id", "<unknown>")
        if status not in VALID_CROSS_RESULTS:
            errors.append(f"scenario {scenario_id} has invalid rust_impl_c_test")
            continue
        if status != "pass":
            log = item.get("log")
            if not isinstance(item.get("diagnosis"), str) or not item["diagnosis"]:
                errors.append(f"non-pass scenario lacks diagnosis: {scenario_id}")
            if not isinstance(log, str) or not log.startswith("logs/trace/c-cross/") or not (root / log).is_file():
                errors.append(f"non-pass scenario lacks owned log: {scenario_id}")
            if final:
                errors.append(f"final C-Cross scenario did not pass: {scenario_id}")
    for filename, phase in [("build-check.json", "build"), ("layout-check.json", "layout"), ("link-check.json", "link")]:
        item, error = load_json(cross / filename)
        if error or item is None:
            errors.append(f"c-cross/{filename}: {error}")
        elif item.get("phase") != phase:
            errors.append(f"c-cross/{filename} phase must be {phase}")
        elif final and item.get("status") != "pass":
            errors.append(f"c-cross/{filename} must pass for final verification")
    if not (cross / "layout-check.log").is_file():
        errors.append("missing logs/trace/c-cross/layout-check.log")
    attempts, attempt_error = load_jsonl(cross / "attempts.jsonl")
    if attempt_error:
        errors.append(f"c-cross/attempts.jsonl: {attempt_error}")
    elif final and (not attempts or attempts[-1].get("attempt_id") != matrix.get("execution_id") or attempts[-1].get("kind") != "final"):
        errors.append("final matrix must match the latest final attempt")
    return errors


def check_verify_and_repair(root: Path) -> list[str]:
    errors = check_workspace(root, requires_project=True)
    errors.extend(check_c_cross(root, final=False))
    errors.extend(require_paths(root, ["logs/trace/c-cross/failure-summary.json"]))
    errors.extend(check_no_c_sources_in_src(root))
    return errors


def check_dynamic_test_mapping(root: Path) -> list[str]:
    errors: list[str] = []
    mapping, mapping_error = load_json(root / "logs" / "trace" / "rust_test_mapping.json")
    if mapping_error or mapping is None:
        return [f"rust_test_mapping.json: {mapping_error}"]
    expected_ids, id_errors = matrix_scenario_ids(root)
    errors.extend(id_errors)
    scenarios = mapping.get("scenarios")
    if not isinstance(scenarios, list):
        return errors + ["rust_test_mapping.json scenarios must be a list"]
    actual_ids = {item.get("id") for item in scenarios if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if actual_ids != expected_ids or len(actual_ids) != len(scenarios):
        errors.append("Rust test mappings must be one-to-one with dynamic C scenarios")
    if mapping.get("total_scenarios") != len(expected_ids):
        errors.append("rust_test_mapping.json total_scenarios must equal dynamic scorer case count")
    for item in scenarios:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("rust_file"), str) or not isinstance(item.get("rust_test"), str):
            errors.append(f"Rust mapping lacks Rust test location: {item.get('id', '<unknown>')}")
        if not isinstance(item.get("source_file"), str) or not item["source_file"]:
            errors.append(f"Rust mapping lacks dynamic C source location: {item.get('id', '<unknown>')}")
    if mapping.get("unmapped") not in ([], None):
        errors.append("rust_test_mapping.json unmapped must be empty")
    return errors


def _run_analysis_tool(filename: str, function: str, *args: Any) -> tuple[dict[str, Any] | None, str | None]:
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        return None, f"could not load {filename}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = getattr(module, function)(*args)
    return result if isinstance(result, dict) else None, None


def check_test_quality(root: Path) -> list[str]:
    errors: list[str] = []
    mapping = root / "logs" / "trace" / "rust_test_mapping.json"
    placeholder, placeholder_error = _run_analysis_tool("placeholder_check.py", "analyze_placeholders", root, root / "flashDB_rust" / "tests", mapping)
    consistency, consistency_error = _run_analysis_tool("test_consistency_check.py", "analyze_consistency", root)
    if placeholder_error or placeholder is None:
        errors.append(placeholder_error or "placeholder check failed to return a report")
    else:
        persisted, persisted_error = load_json(root / "logs" / "trace" / "test-placeholder-check.json")
        if persisted_error or persisted is None:
            errors.append(f"test-placeholder-check.json: {persisted_error}")
        elif any(persisted.get(key) != placeholder.get(key) for key in ("status", "issue_count", "input_fingerprint")):
            errors.append("test-placeholder-check.json is stale or does not match current inputs")
        if placeholder.get("status") != "pass":
            errors.append("test placeholder check failed")
    if consistency_error or consistency is None:
        errors.append(consistency_error or "consistency check failed to return a report")
    else:
        persisted, persisted_error = load_json(root / "logs" / "trace" / "test-consistency.json")
        if persisted_error or persisted is None:
            errors.append(f"test-consistency.json: {persisted_error}")
        elif any(persisted.get(key) != consistency.get(key) for key in ("status", "issue_count", "input_fingerprint", "semantic_review")):
            errors.append("test-consistency.json is stale or does not match current inputs")
        if consistency.get("status") != "pass":
            errors.append("test consistency failed")
    return errors


def check_final(root: Path) -> list[str]:
    errors = check_workspace(root, requires_project=True)
    errors.extend(check_c_cross(root, final=True))
    errors.extend(check_dynamic_test_mapping(root))
    errors.extend(check_test_quality(root))
    cargo, cargo_error = load_json(root / "logs" / "trace" / "cargo-results.json")
    if cargo_error or cargo is None:
        errors.append(f"cargo-results.json: {cargo_error}")
    elif cargo.get("build_status") != "pass" or cargo.get("test_status") != "pass":
        errors.append("cargo-results.json build_status and test_status must be pass")
    ratio, ratio_error = load_json(root / "logs" / "trace" / "unsafe-ratio.json")
    if ratio_error or ratio is None:
        errors.append(f"unsafe-ratio.json: {ratio_error}")
    else:
        try:
            if float(ratio.get("unsafe_ratio")) > 0.10:
                errors.append("unsafe-ratio.json unsafe_ratio must be <= 0.10")
        except (TypeError, ValueError):
            errors.append("unsafe-ratio.json unsafe_ratio must be numeric")
    errors.extend(require_paths(root, [
        "logs/trace/cargo-build.log", "logs/trace/cargo-test.log",
        "logs/trace/final-verification.md", "logs/trace/09-report-and-verify.md",
        "result/output.md", "result/issues/00-summary.md",
    ]))
    output = root / "result" / "output.md"
    if output.is_file() and "STATUS: SUCCESS" not in output.read_text(encoding="utf-8", errors="ignore"):
        errors.append("result/output.md must contain STATUS: SUCCESS")
    errors.extend(check_no_c_sources_in_src(root))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate observable FlashDB migration results.")
    parser.add_argument("--stage", required=True, choices=["ANALYZE", "VERIFY_AND_REPAIR", "FINAL"])
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    checks = {
        "ANALYZE": check_analyze,
        "VERIFY_AND_REPAIR": check_verify_and_repair,
        "FINAL": check_final,
    }
    errors = checks[args.stage](root)
    if errors:
        print(f"{args.stage}: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"{args.stage}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
