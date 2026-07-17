#!/usr/bin/env python3
"""Validate observable outputs of the simplified FlashDB migration workflow."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import final_receipt


VALID_CROSS_RESULTS = {"pass", "fail", "not_run", "not_supported", "parse_failed", "unresolved"}
VALID_CONVERGENCE_STATES = {
    "repair_required", "restore_confirmation_required", "best_restore_failed",
    "ready_for_final", "success", "failed_final",
}


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


def queue_phase_summary(root: Path, phase_name: str) -> tuple[dict[str, Any], str | None]:
    queue, error = load_json(root / "logs" / "trace" / "repair-work-queue.json")
    if error or queue is None:
        return {}, error
    phases = queue.get("phases")
    phase = phases.get(phase_name) if isinstance(phases, dict) else None
    if not isinstance(phase, dict) or not isinstance(phase.get("summary"), dict):
        return {}, f"missing repair queue phase {phase_name}"
    return phase["summary"], None


def expected_matrix_scope(matrix: dict[str, Any]) -> dict[str, Any]:
    scenarios = matrix.get("scenarios") if isinstance(matrix.get("scenarios"), list) else []
    scope_ids = sorted({
        str(row.get("scenario_id") or row.get("source_test"))
        for row in scenarios
        if isinstance(row, dict) and (row.get("scenario_id") or row.get("source_test"))
    })
    if matrix.get("mode") == "full" and matrix.get("scope") == "all":
        scope_kind = "full"
    elif matrix.get("scope") == "selected" and matrix.get("selected_scenarios"):
        scope_kind = "targeted"
    elif matrix.get("scope") == "selected" and matrix.get("selected_suites"):
        scope_kind = "suite"
    else:
        scope_kind = "partial"
    payload = {"scope_kind": scope_kind, "mode": matrix.get("mode"), "scenario_ids": scope_ids}
    return {
        "scope_kind": scope_kind,
        "scope_ids": scope_ids,
        "scope_fingerprint": hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest(),
    }


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


def evaluate_implementation_stage(root: Path) -> tuple[str, list[str], dict[str, Any]]:
    errors = check_workspace(root, requires_project=True)
    current, current_error = _run_analysis_tool("core_impl_audit.py", "audit_workspace", root)
    if current_error or current is None:
        return "implementation_required", errors + [current_error or "implementation audit failed"], {}

    persisted, persisted_error = load_json(root / "logs" / "trace" / "implementation-audit.json")
    if persisted_error or persisted is None:
        errors.append(f"implementation-audit.json: {persisted_error}")
        persisted = {}
    else:
        for key in ("schema_version", "status", "input_fingerprint", "source_manifest", "summary", "findings"):
            if persisted.get(key) != current.get(key):
                errors.append(f"implementation-audit.json {key} is stale or inconsistent")

    tool_path = Path(__file__).resolve().with_name("core_impl_audit.py")
    spec = importlib.util.spec_from_file_location("gate_core_impl_audit", tool_path)
    if spec is None or spec.loader is None:
        errors.append("could not load core_impl_audit.py")
        return "implementation_required", errors, {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    layout, layout_error = load_json(root / "logs" / "trace" / "c-cross" / "scaffold-layout-check.json")
    if layout_error or layout is None:
        errors.append(f"c-cross/scaffold-layout-check.json: {layout_error}")
        layout = {}
    try:
        attempts = module.load_attempts(root / "logs" / "trace" / "implementation-attempts.jsonl")
        evidence = module.implementation_evidence(current, attempts, layout)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"implementation-attempts.jsonl: {exc}")
        evidence = {}

    errors.extend(check_no_c_sources_in_src(root))
    if evidence and not evidence.get("valid"):
        errors.extend(str(item) for item in evidence.get("errors", []))
    status = str(evidence.get("status") or "implementation_required")
    if current.get("status") == "pass" and status not in {"ready_for_verify", "failed_final"}:
        errors.append("passing implementation audit lacks a current checkpoint or repair attempt")
    if status == "implementation_required":
        errors.append(
            "IMPLEMENT is implementation_required; consume current audit findings before verification"
        )
    elif status not in {"ready_for_verify", "failed_final"}:
        errors.append(f"invalid IMPLEMENT convergence status: {status}")
    return status, errors, evidence


def check_implement(root: Path) -> list[str]:
    _, errors, _ = evaluate_implementation_stage(root)
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


def check_convergence(root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    cross = root / "logs" / "trace" / "c-cross"
    summary, summary_error = load_json(cross / "failure-summary.json")
    if summary_error or summary is None:
        return None, [f"c-cross/failure-summary.json: {summary_error}"]
    status = summary.get("status")
    if status not in VALID_CONVERGENCE_STATES:
        errors.append("c-cross/failure-summary.json has invalid convergence status")
    if summary.get("terminal") is not (status in {"success", "failed_final"}):
        errors.append("c-cross/failure-summary.json terminal flag does not match status")
    matrix, matrix_error = load_json(root / "logs" / "trace" / "validation-matrix.json")
    if matrix_error or matrix is None:
        errors.append(f"validation-matrix.json: {matrix_error}")
    elif summary.get("execution_id") != matrix.get("execution_id"):
        errors.append("failure-summary.json must match the current validation matrix")
    if isinstance(matrix, dict):
        expected_scope = expected_matrix_scope(matrix)
        for key, value in expected_scope.items():
            if matrix.get(key) != value:
                errors.append(f"validation-matrix.json {key} is missing or inconsistent")
    attempts, attempts_error = load_jsonl(cross / "attempts.jsonl")
    if attempts_error:
        errors.append(f"c-cross/attempts.jsonl: {attempts_error}")
    else:
        repairs_used = sum(row.get("kind") == "repair" for row in attempts or [])
        if summary.get("repair_attempts_recorded") != repairs_used:
            errors.append("failure-summary.json repair_attempts_recorded does not match attempts.jsonl")
        queue_summary, queue_error = queue_phase_summary(root, "c_cross")
        if queue_error:
            errors.append(f"repair-work-queue.json: {queue_error}")
        elif summary.get("work_queue") != queue_summary:
            errors.append("failure-summary.json work_queue does not match the current C-Cross task queue")
        if attempts and isinstance(matrix, dict) and attempts[-1].get("attempt_id") != matrix.get("execution_id"):
            errors.append("validation matrix must match the latest C-Cross attempt")
        if isinstance(matrix, dict):
            scenarios = matrix.get("scenarios")
            rows = [row for row in scenarios if isinstance(row, dict)] if isinstance(scenarios, list) else []
            all_pass = bool(rows) and all(row.get("rust_impl_c_test") == "pass" for row in rows)
            full_scope = matrix.get("mode") == "full" and matrix.get("scope") == "all"
            auto_restore = matrix.get("auto_restore") if isinstance(matrix.get("auto_restore"), dict) else {}
            if auto_restore.get("status") == "restored":
                expected_status = "restore_confirmation_required"
                expected_next_action = "run_full_confirmation"
            elif auto_restore.get("status") == "failed":
                expected_status = "best_restore_failed"
                expected_next_action = "repair_best_restore"
            elif all_pass and full_scope and matrix.get("attempt_kind") == "final":
                expected_status = "success"
                expected_next_action = "report_success"
            elif all_pass and full_scope:
                expected_status = "ready_for_final"
                expected_next_action = "run_fresh_final"
            elif queue_summary.get("queue_exhausted") is True and full_scope and matrix.get("attempt_kind") == "confirmation":
                expected_status = "failed_final"
                expected_next_action = "continue_to_test_and_report"
            else:
                expected_status = "repair_required"
                expected_next_action = "repair_next_queued_task"
            if status != expected_status:
                errors.append(
                    f"failure-summary.json status {status!r} does not match current evidence {expected_status!r}"
                )
            if summary.get("next_action") != expected_next_action:
                errors.append("failure-summary.json next_action does not match current evidence")
            matrix_convergence = matrix.get("convergence")
            if isinstance(matrix_convergence, dict):
                for key in (
                    "status", "terminal", "next_action", "repair_attempts_recorded", "work_queue",
                ):
                    if matrix_convergence.get(key) != summary.get(key):
                        errors.append(f"validation-matrix convergence {key} does not match failure-summary.json")
            else:
                errors.append("validation-matrix.json must embed the current convergence decision")
    return summary, errors


def check_verify_and_repair(root: Path) -> list[str]:
    errors = check_workspace(root, requires_project=True)
    errors.extend(check_c_cross(root, final=False))
    convergence, convergence_errors = check_convergence(root)
    errors.extend(convergence_errors)
    if convergence is not None and convergence.get("status") == "repair_required":
        pending = convergence.get("work_queue", {}).get("pending_task_ids", []) if isinstance(convergence.get("work_queue"), dict) else []
        errors.append(f"C-Cross convergence is repair_required; continue queued tasks ({len(pending)} pending)")
    elif convergence is not None and convergence.get("status") == "restore_confirmation_required":
        errors.append("C-Cross best-known source was restored; run fresh full confirmation before continuing")
    elif convergence is not None and convergence.get("status") == "best_restore_failed":
        errors.append("C-Cross best-known source restoration failed; repair the restore evidence before continuing")
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


def check_test_quality(
    root: Path,
    *,
    require_pass: bool = True,
    require_consistency: bool = True,
) -> list[str]:
    errors: list[str] = []
    mapping = root / "logs" / "trace" / "rust_test_mapping.json"
    placeholder, placeholder_error = _run_analysis_tool("placeholder_check.py", "analyze_placeholders", root, root / "flashDB_rust" / "tests", mapping)
    if placeholder_error or placeholder is None:
        errors.append(placeholder_error or "placeholder check failed to return a report")
    else:
        persisted, persisted_error = load_json(root / "logs" / "trace" / "test-placeholder-check.json")
        if persisted_error or persisted is None:
            errors.append(f"test-placeholder-check.json: {persisted_error}")
        elif any(persisted.get(key) != placeholder.get(key) for key in ("status", "issue_count", "input_fingerprint")):
            errors.append("test-placeholder-check.json is stale or does not match current inputs")
        if require_pass and placeholder.get("status") != "pass":
            errors.append("test placeholder check failed")
    if require_consistency:
        consistency, consistency_error = _run_analysis_tool("test_consistency_check.py", "analyze_consistency", root)
        if consistency_error or consistency is None:
            errors.append(consistency_error or "consistency check failed to return a report")
        else:
            persisted, persisted_error = load_json(root / "logs" / "trace" / "test-consistency.json")
            if persisted_error or persisted is None:
                errors.append(f"test-consistency.json: {persisted_error}")
            elif persisted.get("convergence_status") in {"restore_confirmation_required", "best_restore_failed"}:
                errors.append(
                    "test submission regression is not confirmed; repair/confirm the best restore and rerun Cargo, semantic review, and consistency"
                )
            elif any(persisted.get(key) != consistency.get(key) for key in ("status", "issue_count", "input_fingerprint", "semantic_review")):
                errors.append("test-consistency.json is stale or does not match current inputs")
            if require_pass and consistency.get("status") != "pass":
                errors.append("test consistency failed")
    return errors


def evaluate_test_stage(root: Path) -> tuple[str, list[str], dict[str, Any]]:
    errors: list[str] = []
    cargo, cargo_error = load_json(root / "logs" / "trace" / "cargo-results.json")
    if cargo_error or cargo is None:
        errors.append(f"cargo-results.json: {cargo_error}")
        cargo = {}
    test_attempts, test_attempt_error = load_jsonl(root / "logs" / "trace" / "test-repair-attempts.jsonl")
    test_repairs: dict[str, Any] = {}
    if test_attempt_error:
        errors.append(f"test-repair-attempts.jsonl: {test_attempt_error}")
    else:
        test_repairs, test_repair_error = _run_analysis_tool(
            "report_writer.py", "test_repair_evidence", root, cargo, test_attempts or []
        )
        if test_repair_error or test_repairs is None:
            errors.append(test_repair_error or "test repair evidence could not be validated")
            test_repairs = {}
        elif not test_repairs.get("valid"):
            errors.append("test repair evidence is stale or inconsistent with current inputs")

    placeholders, _ = load_json(root / "logs" / "trace" / "test-placeholder-check.json")
    consistency, _ = load_json(root / "logs" / "trace" / "test-consistency.json")
    test_execution = cargo.get("test_execution") if isinstance(cargo.get("test_execution"), dict) else {}
    placeholder_pass = isinstance(placeholders, dict) and placeholders.get("status") == "pass"
    cargo_pass = (
        cargo.get("build_status") == "pass"
        and cargo.get("test_status") == "pass"
        and test_execution.get("status") == "pass"
    )
    test_success = (
        cargo_pass
        and placeholder_pass
        and isinstance(consistency, dict) and consistency.get("status") == "pass"
        and consistency.get("convergence_status") not in {"restore_confirmation_required", "best_restore_failed"}
    )
    if test_success:
        status = "success"
    else:
        queue_summary, queue_error = queue_phase_summary(root, "tests")
        if queue_error:
            errors.append(f"repair-work-queue.json: {queue_error}")
            queue_summary = {}
        if queue_summary.get("queue_exhausted") is True:
            status = "failed_final"
        else:
            status = "repair_required"

    errors.extend(check_test_quality(
        root,
        require_pass=status == "success",
        require_consistency=cargo_pass and placeholder_pass,
    ))
    if status == "success" and not cargo_pass:
        errors.append("cargo-results.json must prove every dynamically mapped Rust test executed")
    if status == "repair_required":
        queue_summary, _ = queue_phase_summary(root, "tests")
        pending = queue_summary.get("pending_task_ids", []) if isinstance(queue_summary, dict) else []
        errors.append(
            f"TEST_AND_REPORT convergence is repair_required; repair next queued test ({len(pending)} pending)"
        )
    return status, errors, test_repairs


def check_test_and_report(root: Path) -> list[str]:
    errors = check_workspace(root, requires_project=True)
    convergence, convergence_errors = check_convergence(root)
    errors.extend(convergence_errors)
    cross_status = convergence.get("status") if convergence is not None else None
    if cross_status not in {"success", "failed_final"}:
        errors.append("TEST_AND_REPORT requires terminal C-Cross status success or failed_final")
    cross_failed_final = cross_status == "failed_final"
    errors.extend(check_c_cross(root, final=not cross_failed_final))
    errors.extend(check_dynamic_test_mapping(root))
    _, test_errors, _ = evaluate_test_stage(root)
    errors.extend(test_errors)
    errors.extend(require_paths(root, ["logs/trace/cargo-build.log", "logs/trace/cargo-test.log"]))
    errors.extend(check_no_c_sources_in_src(root))
    return errors


def check_final(root: Path) -> list[str]:
    deadline, deadline_error = load_json(root / "logs" / "trace" / "deadline-final.json")
    if deadline_error is None and deadline is not None and deadline.get("status") == "submission_frozen":
        errors = require_paths(root, [
            "logs/trace/submission-restore.json",
            "logs/trace/contest-control/run.json",
            "logs/trace/contest-control/freeze-requested.json",
            "logs/trace/contest-control/submission-frozen.json",
            "result/output.md",
            "result/issues/00-summary.md",
        ])
        run, _ = load_json(root / "logs" / "trace" / "contest-control" / "run.json")
        requested, _ = load_json(root / "logs" / "trace" / "contest-control" / "freeze-requested.json")
        control_frozen, _ = load_json(root / "logs" / "trace" / "contest-control" / "submission-frozen.json")
        if not isinstance(run, dict) or run.get("status") != "frozen":
            errors.append("deadline final requires a frozen watchdog run")
        elif run.get("run_id") != deadline.get("run_id"):
            errors.append("deadline final does not match the frozen watchdog run")
        if not isinstance(requested, dict) or requested.get("run_id") != deadline.get("run_id"):
            errors.append("deadline final freeze request does not match the watchdog run")
        elif isinstance(run, dict) and isinstance(run.get("freeze_clock_ns"), int) and requested.get("clock_ns", 0) < run["freeze_clock_ns"]:
            errors.append("deadline freeze occurred before the configured 540-minute boundary")
        if control_frozen != deadline:
            errors.append("deadline-final.json must match contest-control/submission-frozen.json")
        if deadline.get("termination_reason") != "contest_deadline_freeze":
            errors.append("deadline final has an invalid termination reason")
        try:
            tool_path = Path(__file__).resolve().with_name("submission_snapshot.py")
            spec = importlib.util.spec_from_file_location("gate_submission_snapshot", tool_path)
            if spec is None or spec.loader is None:
                raise RuntimeError("could not load submission_snapshot.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if deadline.get("snapshot_id") is None:
                current = module.current_manifest(root)
                recorded = deadline.get("verification", {}).get("source_manifest") if isinstance(deadline.get("verification"), dict) else None
                if current != recorded:
                    errors.append("deadline frozen fallback submission has drifted")
            else:
                verification = module.verify_current(root, str(deadline.get("snapshot_id")))
                if not verification.get("matches"):
                    errors.append("deadline restored submission does not match the frozen snapshot")
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"deadline snapshot verification failed: {exc}")
        output = root / "result" / "output.md"
        if output.is_file() and not any(
            marker in output.read_text(encoding="utf-8", errors="ignore")
            for marker in ("STATUS: SUCCESS", "STATUS: FAILED")
        ):
            errors.append("deadline final report must contain a terminal status")
        return errors

    implementation_status, implementation_errors, _ = evaluate_implementation_stage(root)
    if implementation_status == "failed_final" and not implementation_errors:
        errors = require_paths(root, ["result/output.md", "result/issues/00-summary.md"])
        output = root / "result" / "output.md"
        if output.is_file():
            text = output.read_text(encoding="utf-8", errors="ignore")
            for required in (
                "STATUS: FAILED",
                "failed_stage: `IMPLEMENT`",
                "C-Cross: `not_run`",
                "Rust tests: `not_run`",
                "unsafe ratio: `not_run`",
            ):
                if required not in text:
                    errors.append(f"IMPLEMENT failure report must contain {required}")
        errors.extend(check_no_c_sources_in_src(root))
        return errors
    errors = check_test_and_report(root)
    convergence, _ = check_convergence(root)
    cross_status = convergence.get("status") if convergence is not None else None
    test_status, _, test_repairs = evaluate_test_stage(root)
    ratio, ratio_error = load_json(root / "logs" / "trace" / "unsafe-ratio.json")
    if ratio_error or ratio is None:
        errors.append(f"unsafe-ratio.json: {ratio_error}")
        ratio = {}
    try:
        ratio_pass = float(ratio.get("unsafe_ratio")) <= 0.10
    except (TypeError, ValueError):
        ratio_pass = False
        errors.append("unsafe-ratio.json unsafe_ratio must be numeric")
    unsafe_failed_final = bool(not ratio_pass and test_repairs.get("exhausted"))
    if not ratio_pass and not unsafe_failed_final and ratio:
        errors.append("unsafe ratio is repair_required while test tasks remain queued")
    failed_final = bool(
        (cross_status == "failed_final" or test_status == "failed_final" or unsafe_failed_final)
        and (ratio_pass or unsafe_failed_final)
    )
    errors.extend(require_paths(root, [
        "logs/trace/cargo-build.log", "logs/trace/cargo-test.log",
        "logs/trace/final-verification.md", "logs/trace/09-report-and-verify.md",
        "result/output.md", "result/issues/00-summary.md",
    ]))
    output = root / "result" / "output.md"
    expected_output_status = (
        "STATUS: FAILED" if failed_final
        else "STATUS: SUCCESS" if ratio_pass and cross_status == "success" and test_status == "success"
        else "STATUS: INCOMPLETE"
    )
    if output.is_file() and expected_output_status not in output.read_text(encoding="utf-8", errors="ignore"):
        errors.append(f"result/output.md must contain {expected_output_status}")
    errors.extend(check_no_c_sources_in_src(root))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate observable FlashDB migration results.")
    parser.add_argument(
        "--stage",
        required=True,
        choices=["ANALYZE", "IMPLEMENT", "VERIFY_AND_REPAIR", "TEST_AND_REPORT", "FINAL"],
    )
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    checks = {
        "ANALYZE": check_analyze,
        "IMPLEMENT": check_implement,
        "VERIFY_AND_REPAIR": check_verify_and_repair,
        "TEST_AND_REPORT": check_test_and_report,
        "FINAL": check_final,
    }
    errors = checks[args.stage](root)
    if errors:
        if args.stage == "FINAL":
            final_receipt.invalidate(root)
        print(
            "IMPLEMENT: IMPLEMENTATION_REQUIRED"
            if args.stage == "IMPLEMENT"
            else f"{args.stage}: FAIL"
        )
        for error in errors:
            print(f"- {error}")
        return 1
    if args.stage == "FINAL":
        deadline, deadline_error = load_json(root / "logs" / "trace" / "deadline-final.json")
        is_deadline_final = bool(
            deadline_error is None
            and isinstance(deadline, dict)
            and deadline.get("status") == "submission_frozen"
        )
        if not is_deadline_final:
            output_text = (root / "result" / "output.md").read_text(encoding="utf-8", errors="ignore")
            terminal_status = "failed_final" if "STATUS: FAILED" in output_text else "success"
            try:
                final_receipt.create(root, terminal_status=terminal_status)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                final_receipt.invalidate(root)
                print("FINAL: FAIL")
                print(f"- could not create current FINAL receipt: {exc}")
                return 1
    if args.stage == "FINAL":
        output = root / "result" / "output.md"
        if output.is_file() and "STATUS: FAILED" in output.read_text(encoding="utf-8", errors="ignore"):
            print("FINAL: FAILED_FINAL")
            return 0
    if args.stage == "IMPLEMENT":
        status, _, _ = evaluate_implementation_stage(root)
        if status == "failed_final":
            print("IMPLEMENT: FAILED_FINAL")
            return 0
    if args.stage == "TEST_AND_REPORT":
        convergence, _ = check_convergence(root)
        test_status, _, _ = evaluate_test_stage(root)
        if (
            convergence is not None
            and (convergence.get("status") == "failed_final" or test_status == "failed_final")
        ):
            print("TEST_AND_REPORT: FAILED_FINAL")
            return 0
    if args.stage == "VERIFY_AND_REPAIR":
        convergence, _ = check_convergence(root)
        if convergence is not None and convergence.get("status") == "failed_final":
            print(f"{args.stage}: FAILED_FINAL")
            return 0
    print(f"{args.stage}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
