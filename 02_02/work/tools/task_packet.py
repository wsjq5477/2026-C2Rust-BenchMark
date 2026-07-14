#!/usr/bin/env python3
"""Build a bounded, evidence-linked task packet for one workflow stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
from pathlib import Path
from typing import Any


FINISHED_STATUSES = {"complete", "completed", "pass", "passed", "resolved", "skipped"}
CONTRACT_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "workflow-contract.json"
VERIFY_TRACE_OUTPUTS = [
    "logs/trace/c-cross/**",
    "logs/trace/validation-matrix.json",
    "logs/trace/ffi_manifest.json",
    "logs/trace/06-5-verify-rust-with-c-tests.md",
]
BUILD_TRACE_OUTPUTS = [
    "logs/trace/rust_test_mapping.json",
    "logs/trace/cargo-results.json",
    "logs/trace/cargo-build.log",
    "logs/trace/cargo-test.log",
    "logs/trace/cargo-fmt.log",
    "logs/trace/test-repair/**",
    "logs/trace/08-build-test-repair.md",
    "result/issues/repair_trace.jsonl",
]


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_last_jsonl_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    latest: dict[str, Any] | None = None
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} record {index} is invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path} record {index} must be an object")
        latest = value
    return latest


def apply_test_triage_scope(packet: dict[str, Any], triage: dict[str, Any] | None) -> None:
    """Make BUILD diagnostic-only until machine triage grants a narrow repair scope."""
    allowed = list(BUILD_TRACE_OUTPUTS)
    if triage:
        allow_src = triage.get("allow_src_edit") is True
        raw_scope = triage.get("allowed_edit_scope")
        for raw in raw_scope if isinstance(raw_scope, list) else []:
            if not isinstance(raw, str) or not raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
                continue
            scope = raw.rstrip("/")
            if scope in {"flashDB_rust/tests", "flashDB_rust/src", "logs/trace"}:
                scope += "/**"
            if scope.startswith("flashDB_rust/src") and not allow_src:
                continue
            if (
                scope.startswith("flashDB_rust/src/")
                or scope == "flashDB_rust/src/**"
                or scope.startswith("flashDB_rust/tests/")
                or scope == "flashDB_rust/tests/**"
                or scope == "result/issues/repair_trace.jsonl"
            ):
                allowed.append(scope)
    packet["allowed_modification_paths"] = list(dict.fromkeys(allowed))
    packet.setdefault("command_notes", []).append(
        "This packet is diagnostic-only until test-failure-triage.jsonl grants the listed narrow edit scope."
        if not triage
        else "Edits must stay within the latest machine triage allowed_edit_scope; allow_src_edit=false forbids every src change."
    )


def load_workflow_contract(path: Path | None = None) -> dict[str, Any]:
    contract_path = path or CONTRACT_PATH
    contract = load_json(contract_path)
    if contract.get("schema_version") != 1:
        raise ValueError(f"{contract_path} has unsupported schema_version")
    if not isinstance(contract.get("stages"), dict):
        raise ValueError(f"{contract_path} must define stages")
    if not isinstance(contract.get("protected_paths"), list):
        raise ValueError(f"{contract_path} must define protected_paths")
    limits = contract.get("packet_limits")
    if not isinstance(limits, dict) or any(
        not isinstance(limits.get(key), int) or limits[key] < 1
        for key in ("max_requirements", "max_scenarios", "max_scenario_steps")
    ):
        raise ValueError(f"{contract_path} must define positive packet_limits")
    for stage, stage_contract in contract["stages"].items():
        if not isinstance(stage, str) or not isinstance(stage_contract, dict):
            raise ValueError(f"{contract_path} contains an invalid stage contract")
        for key in ("allowed_paths", "required_outputs"):
            value = stage_contract.get(key)
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                raise ValueError(f"{contract_path} stage {stage} must define {key}")
    return contract


def normalize_stage(stage: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", stage.strip()).strip("_").upper()
    if not value:
        raise ValueError("stage must contain at least one letter or digit")
    return value


def string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def selected_repair_node(repair_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not repair_plan:
        return None
    if isinstance(repair_plan.get("task"), dict):
        return repair_plan["task"]
    if repair_plan.get("next_action") == "ISOLATE_SCENARIOS":
        queue = repair_plan.get("isolation_queue")
        if isinstance(queue, list):
            selected = next(
                (item for item in queue if isinstance(item, dict) and item.get("status", "pending") == "pending"),
                None,
            )
            if isinstance(selected, dict):
                return selected
    tasks = repair_plan.get("tasks")
    if not isinstance(tasks, list):
        tasks = repair_plan.get("clusters")
    if isinstance(tasks, list):
        selected = next(
            (item for item in tasks if isinstance(item, dict) and item.get("status", "pending") not in FINISHED_STATUSES),
            None,
        )
        return selected if isinstance(selected, dict) else None
    return None


def extract_repair_focus(repair_plan: dict[str, Any] | None) -> dict[str, list[str]]:
    focus: dict[str, set[str]] = {
        "requirement_ids": set(),
        "scenario_ids": set(),
        "symbols": set(),
        "allowed_paths": set(),
    }
    if not repair_plan:
        return {key: [] for key in focus}

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        status = str(node.get("status", "")).lower()
        if status in FINISHED_STATUSES:
            return
        for key, value in node.items():
            normalized = key.lower()
            values = string_values(value)
            if "requirement" in normalized and ("id" in normalized or normalized.endswith("requirements")):
                focus["requirement_ids"].update(values)
            elif any(token in normalized for token in ["scenario", "case", "test_name", "failed_test"]):
                focus["scenario_ids"].update(values)
            elif any(token in normalized for token in ["symbol", "api_name", "c_api"]):
                focus["symbols"].update(values)
            elif any(token in normalized for token in ["allowed_edit_scope", "allowed_path", "changed_file"]):
                focus["allowed_paths"].update(values)
            visit(value)

    selected: Any = selected_repair_node(repair_plan)
    # A repair plan may be produced by an older controller without a task
    # collection.  Preserve compatibility while ensuring modern plans expose
    # only one bounded active cluster to the weak-model worker.
    visit(selected if selected is not None else repair_plan)
    return {key: sorted(values) for key, values in focus.items()}


def requirement_list(design: dict[str, Any]) -> list[dict[str, Any]]:
    values = design.get("implementation_requirements", [])
    return [item for item in values if isinstance(item, dict) and isinstance(item.get("id"), str)] if isinstance(values, list) else []


def scenario_list(test_model: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ["standard_scenarios", "scorer_standard_cases"]:
        values = test_model.get(key, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("scenario_id", item.get("id", item.get("case_name", ""))))
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            copy = dict(item)
            copy.setdefault("id", identifier)
            result.append(copy)
    return sorted(
        result,
        key=lambda item: (
            item.get("order") if isinstance(item.get("order"), int) else 10**9,
            str(item.get("id", "")),
        ),
    )


def requirement_strings(requirement: dict[str, Any], key: str) -> set[str]:
    value = requirement.get(key, [])
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def choose_requirements(
    requirements: list[dict[str, Any]],
    focus: dict[str, list[str]],
    limit: int,
) -> list[dict[str, Any]]:
    requested_ids = set(focus["requirement_ids"])
    requested_scenarios = set(focus["scenario_ids"])
    requested_symbols = set(focus["symbols"])
    selected = [item for item in requirements if str(item["id"]) in requested_ids]
    if not selected:
        selected = [
            item
            for item in requirements
            if bool(requirement_strings(item, "acceptance_scenarios") & requested_scenarios)
            or bool(requirement_strings(item, "symbols") & requested_symbols)
        ]
    if not selected:
        selected = requirements[:limit]

    by_id = {str(item["id"]): item for item in requirements}
    expanded: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_with_dependencies(item: dict[str, Any]) -> None:
        identifier = str(item["id"])
        if identifier in seen:
            return
        dependencies = item.get("dependency_ids", [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if isinstance(dependency, str) and dependency in by_id:
                    add_with_dependencies(by_id[dependency])
        seen.add(identifier)
        expanded.append(item)

    for item in selected:
        add_with_dependencies(item)
    if len(expanded) <= limit:
        return expanded
    prioritized = list(selected)
    queue = [
        dependency
        for item in selected
        for dependency in item.get("dependency_ids", [])
        if isinstance(dependency, str)
    ]
    queued = set(queue)
    while queue:
        identifier = queue.pop(0)
        dependency = by_id.get(identifier)
        if dependency is None:
            continue
        prioritized.append(dependency)
        for nested in dependency.get("dependency_ids", []):
            if isinstance(nested, str) and nested not in queued:
                queued.add(nested)
                queue.append(nested)
    prioritized.extend(expanded)
    deduplicated: list[dict[str, Any]] = []
    seen.clear()
    for item in prioritized:
        identifier = str(item["id"])
        if identifier not in seen:
            seen.add(identifier)
            deduplicated.append(item)
    return deduplicated[: max(1, limit)]


def scenario_identity(scenario: dict[str, Any]) -> set[str]:
    identities: set[str] = set()
    for key in ["id", "scenario_id", "name", "parent_test", "case_id", "case_name"]:
        value = scenario.get(key)
        if isinstance(value, str) and value:
            identities.add(value)
    return identities


def choose_scenarios(
    scenarios: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    focus: dict[str, list[str]],
    limit: int,
) -> list[dict[str, Any]]:
    direct = set(focus["scenario_ids"])
    if direct:
        direct_matches = [scenario for scenario in scenarios if scenario_identity(scenario) & direct]
        if direct_matches:
            return direct_matches[: max(1, limit)]
    wanted = set(focus["scenario_ids"])
    wanted.update(
        scenario
        for requirement in requirements
        for scenario in requirement_strings(requirement, "acceptance_scenarios")
    )
    candidates = [scenario for scenario in scenarios if scenario_identity(scenario) & wanted]
    acceptance_by_requirement = {
        str(requirement["id"]): requirement_strings(requirement, "acceptance_scenarios")
        for requirement in requirements
    }
    uncovered = set(acceptance_by_requirement)
    chosen: list[dict[str, Any]] = []
    remaining = list(candidates)
    while remaining and uncovered and len(chosen) < limit:
        best = max(
            remaining,
            key=lambda scenario: sum(
                bool(scenario_identity(scenario) & acceptance_by_requirement[identifier])
                for identifier in uncovered
            ),
        )
        coverage = {
            identifier
            for identifier in uncovered
            if scenario_identity(best) & acceptance_by_requirement[identifier]
        }
        if not coverage:
            break
        chosen.append(best)
        remaining.remove(best)
        uncovered.difference_update(coverage)
    chosen.extend(remaining[: max(0, limit - len(chosen))])
    if not chosen:
        wanted_symbols = set(focus["symbols"])
        chosen = []
        for scenario in scenarios:
            steps = scenario.get("scenario_ir", [])
            if isinstance(steps, list) and any(
                isinstance(step, dict) and str(step.get("call", "")) in wanted_symbols
                for step in steps
            ):
                chosen.append(scenario)
    if not chosen:
        chosen = scenarios[:limit]
    return chosen[: max(1, limit)]


def compact_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "invariant",
        "symbols",
        "acceptance_scenarios",
        "suggested_files",
        "dependency_ids",
        "derived_from",
    ]
    return {key: requirement[key] for key in keys if key in requirement}


def compact_scenario(scenario: dict[str, Any], max_steps: int) -> dict[str, Any]:
    raw_steps = scenario.get("scenario_ir", [])
    all_steps = [step for step in raw_steps if isinstance(step, dict)] if isinstance(raw_steps, list) else []
    relevant_steps = [
        step
        for step in all_steps
        if step.get("kind") in {"invoke_test", "assertion", "control", "callback_dispatch"}
        or step.get("call_type") in {"public_api", "helper"}
    ]
    selected_steps = relevant_steps[:max_steps]
    step_keys = [
        "id",
        "order",
        "kind",
        "call",
        "call_type",
        "source_function",
        "source_line",
        "call_path",
        "command",
        "expression",
        "callback_targets",
        "expands_to",
        "expansion_anchor",
        "expansion_ref",
    ]
    steps = []
    for step in selected_steps:
        compact_step = {key: step[key] for key in step_keys if key in step}
        expression = compact_step.get("expression")
        if isinstance(expression, str) and len(expression) > 240:
            compact_step["expression"] = expression[:237] + "..."
            compact_step["expression_truncated"] = True
        steps.append(compact_step)
    compact: dict[str, Any] = {
        "id": str(scenario.get("id", scenario.get("scenario_id", ""))),
        "name": str(scenario.get("name", scenario.get("parent_test", ""))),
        "suite": scenario.get("suite"),
        "source_file": scenario.get("source_file"),
        "tags": [item for item in scenario.get("tags", []) if isinstance(item, str)]
        if isinstance(scenario.get("tags"), list)
        else [],
        "scenario_ir": steps[:max_steps],
    }
    omitted = len(all_steps) - len(selected_steps)
    if omitted:
        compact["omitted_scenario_steps"] = omitted
    return compact


def _project_path(path: str, rust_project: str) -> str:
    if rust_project == "flashDB_rust":
        return path
    if path == "flashDB_rust":
        return rust_project
    if path.startswith("flashDB_rust/"):
        return rust_project.rstrip("/") + path[len("flashDB_rust") :]
    return path


def stage_profile(
    stage: str,
    rust_project: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_workflow_contract()
    cargo = f"{rust_project}/Cargo.toml"
    common_prohibitions = [
        "Do not edit work/**, INSTRUCTION.md, .opencode/**, design_doc/**, evaluation tests, or platform C input.",
        "Do not copy or link the C implementation into the final Rust crate.",
        "Do not use git, /tmp backups, cp-based source snapshots, or scaffold regeneration to reset a stage; workflowctl owns retry baselines.",
        "Do not claim a scenario passes without machine-generated evidence.",
        "Do not read entire trace models when this bounded packet contains the required evidence.",
    ]
    profiles: dict[str, dict[str, Any]] = {
        "INIT_WORKSPACE": {
            "objective": "Initialize controller-owned trace and result directories for this conversion run.",
            "verification_commands": [],
        },
        "READ_C_PROJECT": {
            "objective": "Inventory the immutable C input and record reproducible file evidence.",
            "verification_commands": [
                'python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json',
            ],
        },
        "BUILD_C_MODEL": {
            "objective": "Build deterministic C project, API, ABI, and registered-test models.",
            "verification_commands": [
                "python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace",
            ],
        },
        "DESIGN_RUST_API": {
            "objective": "Derive the Rust API and structured implementation requirements from the C models.",
            "verification_commands": [
                "python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json",
            ],
        },
        "GENERATE_RUST_SCAFFOLD": {
            "objective": "Generate an ABI-compatible Rust scaffold from the current design artifact.",
            "verification_commands": [
                f"python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project {rust_project} --manifest logs/trace/scaffold-manifest.json",
                f"cargo fmt --manifest-path {cargo} -- --check",
                f"cargo build --release --manifest-path {cargo}",
                f"python3 work/tools/c_cross_validate.py --root . --project {rust_project} --out logs/trace --scaffold-layout-only",
            ],
        },
        "REWRITE_CORE_MODULES": {
            "objective": "Controller-only parent for static CORE/FACADE rewrite workers.",
            "verification_commands": [],
            "command_notes": [
                "Do not implement, audit, format, or finish this parent packet. workflowctl releases one exact-owner worker packet at a time.",
            ],
        },
        "VERIFY_RUST_WITH_C_TESTS": {
            "objective": "Use C-cross evidence to repair the selected failing scenarios without weakening their assertions.",
            "verification_commands": [
                f"cargo build --release --manifest-path {cargo}",
                f"python3 work/tools/c_cross_validate.py --root . --project {rust_project} --out logs/trace --mode full --attempt-kind checkpoint --trigger task-packet-checkpoint",
            ],
        },
        "MIGRATE_TESTS": {
            "objective": "Translate the selected registered C scenarios into deep Rust tests against the designed API.",
            "verification_commands": [
                f"python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project {rust_project} --mapping logs/trace/rust_test_mapping.json",
                f"python3 work/tools/placeholder_check.py --root . --tests {rust_project}/tests --mapping logs/trace/rust_test_mapping.json --output logs/trace/test-placeholder-check.json",
                "python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json",
                f"cargo test --manifest-path {cargo}",
            ],
            "command_notes": [
                "migrate_tests.py initializes the mapping only; implement the selected tests and evidence before running the checks.",
            ],
        },
        "BUILD_TEST_REPAIR": {
            "objective": "Apply the smallest repair allowed by current failure triage and preserve already passing behavior.",
            "verification_commands": [
                f"python3 work/tools/cargo_capture.py --project {rust_project} --out logs/trace",
            ],
            "command_notes": [
                "workflowctl regenerates trusted triage from cargo evidence at finish; agents must not write triage or controller state.",
            ],
        },
        "REPORT_AND_VERIFY": {
            "objective": "Generate final reports from verified machine evidence for workflowctl to commit and gate.",
            "verification_commands": [
                f"python3 work/tools/c_cross_validate.py --root . --project {rust_project} --out logs/trace --mode full --attempt-kind final --trigger final_verification",
                f"python3 work/tools/unsafe_ratio.py --project {rust_project} --out logs/trace/unsafe-ratio.json",
                "python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json",
                "python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md",
            ],
            "command_notes": [
                "A non-zero final C-cross result is truthful evidence, not permission to stop; continue all report commands and let workflowctl choose DONE or DONE_WITH_FAILURES.",
                "Never run gate.py directly; workflowctl finish owns the final gate and state commit.",
            ],
        },
    }
    profile_stage = {
        "REPAIR_RUST_WITH_C_TESTS": "VERIFY_RUST_WITH_C_TESTS",
        "C_CROSS_REPAIR": "VERIFY_RUST_WITH_C_TESTS",
        "REWRITE_IN_RUST": "REWRITE_CORE_MODULES",
    }.get(stage, stage)
    stage_contract = contract["stages"].get(profile_stage)
    profile = profiles.get(
        profile_stage,
        {
            "objective": f"Complete {stage} using only the selected evidence in this packet.",
            "verification_commands": [],
        },
    )
    result = dict(profile)
    if isinstance(stage_contract, dict):
        result["allowed_paths"] = [
            _project_path(path, rust_project) for path in stage_contract["allowed_paths"]
        ]
        result["evidence_paths"] = [
            _project_path(path, rust_project) for path in stage_contract["required_outputs"]
        ]
    else:
        result["allowed_paths"] = ["logs/trace/**"]
        result["evidence_paths"] = [f"logs/trace/task-packets/{stage}.json"]
    if profile_stage == "VERIFY_RUST_WITH_C_TESTS":
        result["allowed_paths"] = [f"{rust_project}/src/**", *VERIFY_TRACE_OUTPUTS]
    result["prohibitions"] = common_prohibitions
    result["protected_paths"] = list(contract["protected_paths"])
    return result


def build_task_packet(
    stage: str,
    design: dict[str, Any],
    test_model: dict[str, Any],
    repair_plan: dict[str, Any] | None = None,
    rust_project: str = "flashDB_rust",
    max_requirements: int | None = None,
    max_scenarios: int | None = None,
    max_steps: int | None = None,
) -> dict[str, Any]:
    normalized_stage = normalize_stage(stage)
    contract = load_workflow_contract()
    limits = contract["packet_limits"]
    max_requirements = int(limits["max_requirements"]) if max_requirements is None else max_requirements
    max_scenarios = int(limits["max_scenarios"]) if max_scenarios is None else max_scenarios
    max_steps = int(limits["max_scenario_steps"]) if max_steps is None else max_steps
    if max_requirements < 1 or max_scenarios < 1 or max_steps < 1:
        raise ValueError("packet limits must all be positive")
    design_digest = design.get("input_digest")
    test_digest = test_model.get("input_digest")
    if design_digest and test_digest and design_digest != test_digest:
        raise ValueError("design and test model input_digest values do not match")

    focus = extract_repair_focus(repair_plan)
    requirements = requirement_list(design)
    selected_requirements = choose_requirements(requirements, focus, max_requirements)
    scenarios = scenario_list(test_model)
    selected_scenarios = choose_scenarios(scenarios, selected_requirements, focus, max_scenarios)
    active_repair = selected_repair_node(repair_plan)
    repair_evidence = active_repair.get("repair_evidence", []) if isinstance(active_repair, dict) else []
    bounded_repair_evidence = []
    for item in repair_evidence[:3] if isinstance(repair_evidence, list) else []:
        if not isinstance(item, dict):
            continue
        compact = dict(item)
        for key, value in list(compact.items()):
            if isinstance(value, str) and len(value) > 1200:
                compact[key] = value[:1197] + "..."
        bounded_repair_evidence.append(compact)
    profile = stage_profile(normalized_stage, rust_project, contract)
    verify_stages = {"VERIFY_RUST_WITH_C_TESTS", "REPAIR_RUST_WITH_C_TESTS", "C_CROSS_REPAIR"}
    if normalized_stage in verify_stages and repair_plan is not None:
        source_prefix = rust_project.rstrip("/") + "/src/"
        scoped_paths = [
            path
            for path in focus["allowed_paths"]
            if not Path(path).is_absolute()
            and ".." not in Path(path).parts
            and (path.startswith(source_prefix) or path.startswith("logs/trace/"))
        ]
        action = str(repair_plan.get("next_action") or "REPAIR_RUST")
        if action == "ISOLATE_SCENARIOS":
            profile["allowed_paths"] = list(VERIFY_TRACE_OUTPUTS)
            profile["verification_commands"] = [
                "python3 work/tools/c_cross_converge.py --root . --execute-isolation",
            ]
        elif action == "CONFIRM_C_CROSS":
            profile["allowed_paths"] = list(VERIFY_TRACE_OUTPUTS)
            profile["verification_commands"] = [
                f"python3 work/tools/c_cross_validate.py --root . --project {rust_project} --out logs/trace --mode full --attempt-kind confirmation --trigger post-isolation-confirmation",
            ]
        elif action == "RESTORE_BEST":
            profile["allowed_paths"] = [f"{rust_project}/src/**", *VERIFY_TRACE_OUTPUTS]
            profile["verification_commands"] = [
                f"python3 work/tools/c_cross_converge.py --root . --project {rust_project} --restore-best",
                f"cargo build --release --manifest-path {rust_project}/Cargo.toml",
                f"python3 work/tools/c_cross_validate.py --root . --project {rust_project} --out logs/trace --mode full --attempt-kind confirmation --trigger best-snapshot-restored",
            ]
        elif action == "REANALYZE_C_MODEL":
            profile["allowed_paths"] = [
                "logs/trace/c_project_model.json",
                "logs/trace/c_api_model.json",
                "logs/trace/c_test_model.json",
                "logs/trace/rust_api_design.json",
                *VERIFY_TRACE_OUTPUTS,
            ]
            profile["verification_commands"] = [
                "python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace",
                "python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json",
                f"python3 work/tools/c_cross_validate.py --root . --project {rust_project} --out logs/trace --mode full --attempt-kind confirmation --trigger model-regenerated",
            ]
        elif action == "REPAIR_ABI_LAYOUT":
            profile["allowed_paths"] = list(dict.fromkeys(scoped_paths + VERIFY_TRACE_OUTPUTS))
            profile["verification_commands"] = [
                f"python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project {rust_project} --abi-only",
                f"cargo build --release --manifest-path {rust_project}/Cargo.toml",
                f"python3 work/tools/c_cross_validate.py --root . --project {rust_project} --out logs/trace --scaffold-layout-only",
                f"python3 work/tools/c_cross_validate.py --root . --project {rust_project} --out logs/trace --mode full --attempt-kind confirmation --trigger abi-layout-regenerated",
            ]
        else:
            if scoped_paths:
                profile["allowed_paths"] = list(dict.fromkeys(scoped_paths + VERIFY_TRACE_OUTPUTS))
            profile["verification_commands"] = [
                f"cargo build --release --manifest-path {rust_project}/Cargo.toml",
                (
                    "python3 work/tools/c_cross_validate.py --root . "
                    f"--project {rust_project} --out logs/trace --mode full "
                    "--attempt-kind repair --trigger task-packet-repair "
                    f"--changed-file <{rust_project}/src/changed-file.rs>"
                ),
            ]

    symbols = set(focus["symbols"])
    for requirement in selected_requirements:
        symbols.update(requirement_strings(requirement, "symbols"))
    for scenario in selected_scenarios:
        steps = scenario.get("scenario_ir", [])
        if isinstance(steps, list):
            symbols.update(
                str(step["call"])
                for step in steps
                if isinstance(step, dict) and step.get("call_type") == "public_api" and isinstance(step.get("call"), str)
            )

    return {
        "schema_version": 1,
        "stage": normalized_stage,
        "input_digest": design_digest or test_digest,
        "objective": profile["objective"],
        "allowed_modification_paths": profile["allowed_paths"],
        "requirements": [compact_requirement(item) for item in selected_requirements],
        "symbols": sorted(symbols),
        "scenarios": [compact_scenario(item, max_steps) for item in selected_scenarios],
        "verification_commands": profile["verification_commands"],
        "command_notes": profile.get("command_notes", []),
        "completion_contract": {
            "command": "python3 work/tools/workflowctl.py --root . finish --run-id <RUN_ID> --nonce <NONCE>",
            "owner": "workflowctl",
            "rule": "Do not edit workflow_state, receipts, invocation evidence, or claim gate success manually.",
        },
        "evidence_paths": profile["evidence_paths"],
        "protected_paths": profile["protected_paths"],
        "prohibitions": profile["prohibitions"],
        "repair_focus": focus,
        "repair_evidence": bounded_repair_evidence,
        "selection": {
            "requirements_in_model": len(requirements),
            "requirements_selected": len(selected_requirements),
            "scenarios_in_model": len(scenarios),
            "scenarios_selected": len(selected_scenarios),
            "omitted_requirement_ids": [
                str(item["id"])
                for item in requirements
                if str(item["id"]) not in {str(selected["id"]) for selected in selected_requirements}
            ],
            "omitted_scenario_ids": [
                str(item.get("id", item.get("scenario_id", "")))
                for item in scenarios
                if not any(scenario_identity(item) & scenario_identity(selected) for selected in selected_scenarios)
            ],
            "bounded": True,
        },
    }


def apply_static_rewrite_role(
    packet: dict[str, Any],
    manifest: dict[str, Any],
    role: str,
    rust_project: str,
) -> None:
    """Restrict a REWRITE packet to one generator-owned static worker role."""
    normalized = role.upper()
    if normalized not in {"IMPLEMENT_CORE", "WIRE_FACADE"}:
        raise ValueError(f"unsupported rewrite role: {role}")
    ownership = manifest.get("rewrite_ownership")
    if not isinstance(ownership, dict) or ownership.get("schema_version") != 1:
        raise ValueError("scaffold manifest has no supported rewrite_ownership contract")
    key = "core_owned_paths" if normalized == "IMPLEMENT_CORE" else "facade_owned_paths"
    raw_paths = ownership.get(key)
    if not isinstance(raw_paths, list) or not raw_paths or not all(isinstance(item, str) and item for item in raw_paths):
        raise ValueError(f"rewrite ownership {key} must be a non-empty string list")
    project = rust_project.rstrip("/")
    owner_paths = set(raw_paths)
    packet["rewrite_role"] = normalized
    packet["allowed_modification_paths"] = [f"{project}/{item}" for item in raw_paths]
    packet["read_only_paths"] = [
        f"{project}/{item}"
        for category in [
            "core_owned_paths",
            "facade_owned_paths",
            "frozen_contract_paths",
            "shared_readonly_paths",
        ]
        for item in ownership.get(category, [])
        if isinstance(item, str) and item not in raw_paths
    ]
    # Controller-owned stage evidence is not worker input.  Showing it in a
    # role packet caused workers to run the final audit while facade stubs
    # were intentionally still present.
    packet["evidence_paths"] = []
    packet["verification_commands"] = []
    packet["completion_contract"] = {
        "command": (
            "python3 work/tools/workflowctl.py --root . finish-rewrite-worker "
            "--worker-run-id <WORKER_RUN_ID> --nonce <WORKER_NONCE> --status complete"
        ),
        "owner": "workflowctl",
        "rule": "The worker edits only its owner paths; workflowctl computes diffs and runs bounded checks.",
    }
    packet["command_notes"] = [
        "This is one fixed static REWRITE role, not a dynamic batch. Do not change roles or edit the other owner's files.",
        "A workflowctl error ends this worker attempt. Report its exact text to the orchestrator; never edit work/**, contracts, controller state, or generated evidence to bypass it.",
        "Do not run workflowctl stage finish, regenerate the scaffold, or create source backups.",
    ]
    if normalized == "IMPLEMENT_CORE":
        packet["objective"] = "Implement internal Rust behavior only in generator-declared core-owned files."
        packet["facade_contracts"] = []
        for requirement in packet.get("requirements", []):
            if not isinstance(requirement, dict):
                continue
            suggested = requirement.get("suggested_files")
            if not isinstance(suggested, list):
                continue
            writable = [item for item in suggested if isinstance(item, str) and item in owner_paths]
            readonly = [item for item in suggested if isinstance(item, str) and item not in owner_paths]
            requirement["suggested_files"] = writable
            if readonly:
                requirement["non_writable_dependencies"] = readonly
    else:
        packet["objective"] = "Wire generated external ABI function bodies to the existing internal Rust API."
        packet["requirements"] = []
        packet["scenarios"] = []
        packet["facade_contracts"] = ownership.get("frozen_contract_symbols", [])
        packet["symbols"] = sorted({
            item.get("symbol")
            for item in packet["facade_contracts"]
            if isinstance(item, dict) and isinstance(item.get("symbol"), str)
        })
        packet["command_notes"].append(
            "If the frozen facade cannot be wired because an internal API is missing, finish with "
            "--status missing_core_capability --reason '<brief required capability>'."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a bounded per-stage conversion task packet.")
    parser.add_argument("--root", default=".", help="Conversion workbench root.")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--design", help="rust_api_design.json path (defaults under --root logs/trace)")
    parser.add_argument("--test-model", help="c_test_model.json path (defaults under --root logs/trace)")
    parser.add_argument("--repair-plan", help="Optional repair plan/queue JSON path")
    parser.add_argument("--action", help="Controller-selected machine action for this physical stage")
    parser.add_argument("--trace-dir", default="logs/trace")
    parser.add_argument("--output", help="Override task packet output path")
    parser.add_argument("--rust-project", default="flashDB_rust")
    parser.add_argument("--max-requirements", type=int, help="Defaults to workflow-contract.json")
    parser.add_argument("--max-scenarios", type=int, help="Defaults to workflow-contract.json")
    parser.add_argument("--max-steps", type=int, help="Defaults to workflow-contract.json")
    parser.add_argument(
        "--rewrite-role",
        choices=["IMPLEMENT_CORE", "WIRE_FACADE"],
        help="Generate one static REWRITE worker packet from scaffold ownership.",
    )
    args = parser.parse_args(argv)

    if any(value is not None and value < 1 for value in (args.max_requirements, args.max_scenarios, args.max_steps)):
        parser.error("packet limits must all be positive")
    stage = normalize_stage(args.stage)
    root = Path(args.root).resolve()

    def rooted(value: str | None, default: str) -> Path:
        path = Path(value or default)
        return path if path.is_absolute() else root / path

    design_path = rooted(args.design, "logs/trace/rust_api_design.json")
    test_model_path = rooted(args.test_model, "logs/trace/c_test_model.json")
    if args.repair_plan:
        repair_path: Path | None = rooted(args.repair_plan, args.repair_plan)
    else:
        candidate = root / "logs" / "trace" / "c-cross" / "repair-plan.json"
        repair_path = candidate if candidate.is_file() else None
    design = load_json(design_path) if design_path.is_file() else {}
    test_model = load_json(test_model_path) if test_model_path.is_file() else {}
    repair_plan = load_json(repair_path) if repair_path else None
    if args.action and stage == "VERIFY_RUST_WITH_C_TESTS":
        repair_plan = dict(repair_plan or {})
        repair_plan["next_action"] = normalize_stage(args.action)
    implementation_requirements = design.get("implementation_requirements", [])
    role_requirement_limit = (
        max(1, len(implementation_requirements))
        if args.rewrite_role == "IMPLEMENT_CORE" and isinstance(implementation_requirements, list)
        else args.max_requirements
    )
    packet = build_task_packet(
        stage,
        design,
        test_model,
        repair_plan,
        rust_project=args.rust_project,
        max_requirements=role_requirement_limit,
        max_scenarios=args.max_scenarios,
        max_steps=args.max_steps,
    )
    if args.rewrite_role:
        if stage != "REWRITE_CORE_MODULES":
            parser.error("--rewrite-role is only valid for REWRITE_CORE_MODULES")
        manifest_path = root / "logs" / "trace" / "scaffold-manifest.json"
        if not manifest_path.is_file():
            parser.error("--rewrite-role requires logs/trace/scaffold-manifest.json")
        apply_static_rewrite_role(
            packet,
            load_json(manifest_path),
            args.rewrite_role,
            args.rust_project,
        )
    state_path = root / "logs" / "trace" / "workflow_state.json"
    runtime_context: dict[str, Any] = {}
    if state_path.is_file():
        state = load_json(state_path)
        source_root = state.get("input_source_root")
        if isinstance(source_root, str) and source_root:
            runtime_context["flashdb_source"] = source_root
            if stage == "READ_C_PROJECT":
                packet["verification_commands"] = [
                    command.replace('"$FLASHDB_SOURCE"', shlex.quote(source_root))
                    for command in packet["verification_commands"]
                ]
    packet["runtime_context"] = runtime_context
    if stage == "BUILD_TEST_REPAIR":
        triage = load_last_jsonl_object(root / "logs" / "trace" / "test-failure-triage.jsonl")
        apply_test_triage_scope(packet, triage)
        packet["triage_authorization"] = triage
    if args.rewrite_role:
        packet["controller_inputs"] = {
            "design_sha256": hashlib.sha256(design_path.read_bytes()).hexdigest() if design_path.is_file() else None,
            "test_model_sha256": hashlib.sha256(test_model_path.read_bytes()).hexdigest() if test_model_path.is_file() else None,
            "agent_readable": False,
        }
    else:
        packet["source_artifacts"] = {
            "design": design_path.as_posix() if design_path.is_file() else None,
            "test_model": test_model_path.as_posix() if test_model_path.is_file() else None,
            "repair_plan": repair_path.as_posix() if repair_path else None,
        }
    output = rooted(args.output, str(Path(args.trace_dir) / "task-packets" / f"{stage}.json"))
    write_json(output, packet)
    print("TASK_PACKET: WRITTEN")
    print(f"stage={stage}")
    print(f"requirements={len(packet['requirements'])}")
    print(f"scenarios={len(packet['scenarios'])}")
    print(f"output={output.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
