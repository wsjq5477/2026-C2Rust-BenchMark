#!/usr/bin/env python3
"""Build a deterministic C-cross repair plan from validation evidence.

This module deliberately does not edit either implementation.  It translates
the validation matrix into bounded task packets that an orchestrator can hand
to the appropriate conversion role/tool.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
from collections import defaultdict
from pathlib import Path
from typing import Any


LAYER_PRIORITY = {
    "layout": 0,
    "model": 1,
    "protocol": 1,
    "parse": 1,
    "build": 2,
    "link": 3,
    "runtime": 4,
    "assertion": 5,
    "timeout": 6,
    "full": 5,
    "unknown": 7,
}
MAX_REPAIR_EVIDENCE = 3
MAX_LOG_TAIL_CHARS = 1200


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _normalized_layer(row: dict[str, Any]) -> str:
    diagnosis = str(row.get("diagnosis") or "")
    raw = str(row.get("failure_layer") or row.get("phase") or "unknown")
    if row.get("parse_status") == "parse_failed":
        return "protocol"
    if diagnosis == "c_abi_layout_mismatch":
        return "layout"
    if diagnosis in {"c_model_signature_gap", "c_cross_harness_not_supported"}:
        return "model"
    if diagnosis == "c_cross_result_parse_failed":
        return "protocol"
    if diagnosis == "rust_staticlib_build_failed":
        return "build"
    if diagnosis == "c_runner_link_failed":
        return "link"
    if diagnosis == "c_runner_runtime_failed":
        return "runtime"
    if diagnosis in {"c_test_case_failed", "rust_implementation_failed_c_baseline"}:
        return "assertion"
    if diagnosis == "c_runner_timeout":
        return "timeout"
    return raw if raw in LAYER_PRIORITY else "unknown"


def _route(layer: str) -> tuple[str, list[str], str]:
    if layer == "layout":
        return (
            "abi-layout-tool",
            [
                "flashDB_rust/src/ffi/c_types.rs",
                "flashDB_rust/src/ffi/layout_probe.rs",
            ],
            "Regenerate or repair the compiler-derived C ABI facade before semantic repairs.",
        )
    if layer in {"model", "protocol", "parse"}:
        return (
            "c-analyzer",
            [
                "logs/trace/c_api_model.json",
                "logs/trace/c_test_model.json",
                "logs/trace/rust_api_design.json",
            ],
            "Repair the extracted model/parser mapping and regenerate dependent artifacts.",
        )
    return (
        "rust-implementer",
        ["flashDB_rust/src/**"],
        "Repair only the generated Rust implementation using the bounded failure evidence.",
    )


def _suggested_rust_scope(
    requirement_ids: list[str],
    rust_api_design: dict[str, Any] | None,
    project: str,
) -> tuple[list[str], str | None]:
    if not isinstance(rust_api_design, dict):
        return [f"{project}/src/**"], "rust_api_design unavailable"
    raw = rust_api_design.get("implementation_requirements")
    requirements = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    wanted = set(requirement_ids)
    files: set[str] = set()
    for requirement in requirements:
        if requirement.get("id") not in wanted:
            continue
        for value in _strings(requirement.get("suggested_files")):
            path = Path(value)
            if path.is_absolute() or ".." in path.parts:
                continue
            normalized = path.as_posix()
            if normalized.startswith("src/"):
                normalized = f"{project}/{normalized}"
            if normalized.startswith(f"{project}/src/") and normalized.endswith(".rs"):
                files.add(normalized)
    if files:
        return sorted(files), None
    return [f"{project}/src/**"], "no suggested_files matched the active requirements"


def _bounded_failure_evidence(row: dict[str, Any], root: Path | None) -> dict[str, Any]:
    evidence = {
        key: row.get(key)
        for key in (
            "scenario_id",
            "suite",
            "rust_impl_c_test",
            "failure_layer",
            "diagnosis",
            "reason",
            "expected",
            "actual",
            "log",
            "isolation_result",
        )
        if row.get(key) is not None
    }
    reason = evidence.get("reason")
    if isinstance(reason, str) and len(reason) > 400:
        evidence["reason"] = reason[:397] + "..."
    log = row.get("log")
    if root is not None and isinstance(log, str) and log and not Path(log).is_absolute() and ".." not in Path(log).parts:
        path = root / log
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-12:])
            evidence["log_tail"] = tail[-MAX_LOG_TAIL_CHARS:]
    return evidence


def _affected_symbols(row: dict[str, Any]) -> list[str]:
    context = row.get("repair_context")
    symbols: set[str] = set()
    if isinstance(context, dict):
        symbols.update(_strings(context.get("public_api_calls")))
        symbols.update(_strings(context.get("observed_c_symbols")))
        callback_paths = context.get("callback_paths")
        if isinstance(callback_paths, list):
            for item in callback_paths:
                if isinstance(item, dict):
                    symbols.update(_strings(item.get("functions")))
                elif isinstance(item, str):
                    symbols.update(re.findall(r"\bfdb_[A-Za-z0-9_]+\b", item))
    for key in ("reason", "diagnosis"):
        symbols.update(re.findall(r"\bfdb_[A-Za-z0-9_]+\b", str(row.get(key) or "")))
    return sorted(symbols)


def _requirement_ids(row: dict[str, Any], rust_api_design: dict[str, Any] | None) -> list[str]:
    if not isinstance(rust_api_design, dict):
        context = row.get("repair_context")
        if not isinstance(context, dict):
            return []
        fallback = _strings(context.get("semantic_obligations"))
        fallback.extend(_strings(context.get("scenario_features")))
        return list(dict.fromkeys(fallback))
    raw_requirements = rust_api_design.get("implementation_requirements")
    requirements = [item for item in raw_requirements if isinstance(item, dict)] if isinstance(raw_requirements, list) else []
    scenario_names = {
        str(value)
        for value in (row.get("scenario_id"), row.get("source_test"), row.get("scorer_case_id"))
        if isinstance(value, str) and value
    }
    symbols = set(_affected_symbols(row))
    matched: list[str] = []
    for requirement in requirements:
        requirement_id = requirement.get("id")
        if not isinstance(requirement_id, str) or not requirement_id:
            continue
        acceptance = set(_strings(requirement.get("acceptance_scenarios")))
        requirement_symbols = set(_strings(requirement.get("symbols")))
        if scenario_names & acceptance or symbols & requirement_symbols:
            matched.append(requirement_id)
    return list(dict.fromkeys(matched))


def _verification_command(
    *,
    project: str,
    out: str,
    suites: list[str],
    trigger: str,
) -> str:
    command = [
        "python3",
        "work/tools/c_cross_validate.py",
        "--root",
        ".",
        "--project",
        project,
        "--out",
        out,
        "--mode",
        "full",
        "--attempt-kind",
        "confirmation",
        "--trigger",
        trigger,
    ]
    for suite in suites:
        command.extend(["--suite", suite])
    return shlex.join(command)


def _isolation_command(
    *,
    project: str,
    out: str,
    scenario_id: str,
) -> str:
    return shlex.join(
        [
            "python3",
            "work/tools/c_cross_validate.py",
            "--root",
            ".",
            "--project",
            project,
            "--out",
            out,
            "--mode",
            "full",
            "--scenario",
            scenario_id,
            "--attempt-kind",
            "checkpoint",
            "--trigger",
            f"isolate_{re.sub(r'[^A-Za-z0-9_]+', '_', scenario_id)}",
        ]
    )


def build_repair_plan(
    matrix: dict[str, Any],
    *,
    project: str = "flashDB_rust",
    out: str = "logs/trace",
    rust_api_design: dict[str, Any] | None = None,
    root: Path | None = None,
    isolation_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_scenarios = matrix.get("scenarios")
    scenarios = [row for row in raw_scenarios if isinstance(row, dict)] if isinstance(raw_scenarios, list) else []
    failures = [
        row
        for row in scenarios
        if row.get("rust_impl_c_test") != "pass" or row.get("parse_status") == "parse_failed"
    ]
    latest_isolation: dict[str, dict[str, Any]] = {}
    for result in isolation_results or []:
        scenario_id = result.get("scenario_id") if isinstance(result, dict) else None
        if isinstance(scenario_id, str) and scenario_id:
            latest_isolation[scenario_id] = result

    repair_failures: list[dict[str, Any]] = []
    cascade_scenarios: list[str] = []
    for row in failures:
        scenario_id = str(row.get("scenario_id") or "")
        diagnosis = str(row.get("diagnosis") or "")
        isolated = latest_isolation.get(scenario_id)
        if (
            row.get("rust_impl_c_test") == "not_run"
            and diagnosis in {"c_runner_runtime_failed", "c_runner_timeout"}
            and isinstance(isolated, dict)
        ):
            if isolated.get("outcome") == "pass":
                cascade_scenarios.append(scenario_id)
                continue
            enriched = dict(row)
            enriched["isolation_result"] = {
                key: isolated.get(key)
                for key in ("status", "outcome", "exit_code", "log", "execution_id")
            }
            repair_failures.append(enriched)
            continue
        repair_failures.append(row)
    if failures and not repair_failures and latest_isolation:
        interaction = dict(failures[0])
        interaction["diagnosis"] = "c_runner_runtime_failed"
        interaction["reason"] = "all isolated cases pass; repair cross-scenario state or cleanup interaction"
        interaction["isolation_result"] = {"cascade_scenarios": sorted(cascade_scenarios)}
        repair_failures.append(interaction)

    grouped: dict[tuple[int, str, str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in repair_failures:
        layer = _normalized_layer(row)
        target, allowed_scope, _ = _route(layer)
        suite = str(row.get("suite") or "unknown")
        grouped[(LAYER_PRIORITY.get(layer, 99), layer, target, tuple(allowed_scope))].append(row)

    tasks: list[dict[str, Any]] = []
    for task_index, ((priority, layer, target, allowed_scope), rows) in enumerate(sorted(grouped.items()), start=1):
        suites = sorted({str(row.get("suite")) for row in rows if row.get("suite")})
        scenario_ids = sorted({str(row.get("scenario_id")) for row in rows if row.get("scenario_id")})
        symbols = sorted({symbol for row in rows for symbol in _affected_symbols(row)})
        requirements = list(
            dict.fromkeys(
                requirement
                for row in rows
                for requirement in _requirement_ids(row, rust_api_design)
            )
        )
        evidence_paths = sorted(
            {
                "logs/trace/validation-matrix.json",
                "logs/trace/c-cross/diagnostics.jsonl",
                *[
                    str(row.get("log"))
                    for row in rows
                    if isinstance(row.get("log"), str) and row.get("log")
                ],
            }
        )
        _, _, objective = _route(layer)
        task_scope = list(allowed_scope)
        scope_fallback_reason = None
        if target == "rust-implementer":
            task_scope, scope_fallback_reason = _suggested_rust_scope(
                requirements, rust_api_design, project
            )
        task = {
            "task_id": f"repair-{task_index:02d}-{layer}",
            "priority": priority,
            "failure_layer": layer,
            "target_agent": target,
            "scenario_ids": scenario_ids,
            "affected_symbols": symbols,
            "requirements": requirements,
            "allowed_edit_scope": task_scope,
            "evidence_paths": evidence_paths,
            "selected_suites": suites,
            "objective": objective,
            "repair_evidence": [
                _bounded_failure_evidence(row, root)
                for row in rows[:MAX_REPAIR_EVIDENCE]
            ],
            "verification_command": _verification_command(
                project=project,
                out=out,
                suites=suites,
                trigger=f"confirm_repair_{task_index:02d}_{layer}",
            ),
        }
        if scope_fallback_reason:
            task["scope_fallback_reason"] = scope_fallback_reason
        if target == "abi-layout-tool":
            task["tool_hint"] = (
                "work/tools/abi_layout_extractor.py -> work/tools/generate_rust_scaffold.py"
            )
            task["repair_method"] = (
                "Regenerate compiler-derived layout evidence and FFI types/probes; do not hand-edit the files."
            )
        tasks.append(task)

    isolation_queue: list[dict[str, Any]] = []
    for row in failures:
        diagnosis = str(row.get("diagnosis") or "")
        layer = "timeout" if diagnosis == "c_runner_timeout" else "runtime"
        if (
            row.get("rust_impl_c_test") != "not_run"
            or diagnosis not in {"c_runner_runtime_failed", "c_runner_timeout"}
        ):
            continue
        scenario_id = str(row.get("scenario_id") or "")
        if not scenario_id:
            continue
        if scenario_id in latest_isolation:
            continue
        isolation_queue.append(
            {
                "queue_id": f"isolate-{len(isolation_queue) + 1:02d}",
                "status": "pending",
                "scenario_id": scenario_id,
                "suite": str(row.get("suite") or "unknown"),
                "failure_layer": layer,
                "reason": row.get("reason"),
                "evidence_paths": [
                    path
                    for path in [row.get("log"), "logs/trace/validation-matrix.json"]
                    if isinstance(path, str) and path
                ],
                "command": _isolation_command(project=project, out=out, scenario_id=scenario_id),
            }
        )

    if not failures:
        next_action = "ADVANCE"
        status = "pass"
    elif tasks and tasks[0]["target_agent"] == "abi-layout-tool":
        next_action = "REPAIR_ABI_LAYOUT"
        status = "repair_required"
    elif tasks and tasks[0]["target_agent"] == "c-analyzer":
        next_action = "REANALYZE_C_MODEL"
        status = "repair_required"
    elif isolation_queue:
        next_action = "ISOLATE_SCENARIOS"
        status = "repair_required"
    else:
        next_action = "REPAIR_RUST"
        status = "repair_required"

    return {
        "schema_version": 1,
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        "execution_id": matrix.get("execution_id"),
        "attempt_kind": matrix.get("attempt_kind"),
        "status": status,
        "next_action": next_action,
        "failure_count": len(failures),
        "selected_suites": matrix.get("selected_suites", []),
        "clusters": tasks,
        "tasks": tasks,
        "isolation_queue": isolation_queue,
        "isolation_findings": {
            "completed_scenarios": sorted(latest_isolation),
            "cascade_scenarios": sorted(cascade_scenarios),
        },
    }


def write_repair_plan(
    matrix: dict[str, Any],
    c_cross: Path,
    *,
    project: str = "flashDB_rust",
    out: str = "logs/trace",
) -> dict[str, Any]:
    design_path = c_cross.parent / "rust_api_design.json"
    try:
        rust_api_design = _load_json(design_path) if design_path.is_file() else None
    except (OSError, ValueError, json.JSONDecodeError):
        rust_api_design = None
    plan = build_repair_plan(
        matrix,
        project=project,
        out=out,
        rust_api_design=rust_api_design,
        root=c_cross.parents[2],
        isolation_results=_load_jsonl(c_cross / "isolation-results.jsonl"),
    )
    _write_json(c_cross / "repair-plan.json", plan)
    _write_json(
        c_cross / "isolation-queue.json",
        {
            "schema_version": 1,
            "execution_id": matrix.get("execution_id"),
            "queue": plan["isolation_queue"],
        },
    )
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic C-cross repair plan.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="logs/trace")
    parser.add_argument("--project", default="flashDB_rust")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    trace = (root / args.out).resolve()
    matrix = _load_json(trace / "validation-matrix.json")
    plan = write_repair_plan(matrix, trace / "c-cross", project=args.project, out=args.out)
    print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
