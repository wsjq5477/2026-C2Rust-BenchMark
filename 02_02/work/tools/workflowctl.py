#!/usr/bin/env python3
"""Transactional stage coordinator for the C-to-Rust workbench.

The language model is allowed to edit source files, but it is not trusted to
declare that a stage completed.  This tool owns run identities, artifact
receipts, state transitions, repair routing, and subagent invocation evidence.
It is intentionally opt-in so traces produced by older workbench versions stay
readable by ``gate.py``.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable


CONTRACT_VERSION = 1
INPUT_PATH_CANDIDATES = [
    "/app/code/judge-assets/02_02_c_to_rust/code/FlashDB",
    "judge-assets/code/FlashDB",
    "../judge-assets/code/FlashDB",
]
CONTRACT_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "workflow-contract.json"
try:
    WORKFLOW_CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise RuntimeError(f"cannot load workflow contract {CONTRACT_PATH}: {exc}") from exc
if WORKFLOW_CONTRACT.get("schema_version") != CONTRACT_VERSION:
    raise RuntimeError("workflow contract schema_version does not match workflowctl")
STAGES = WORKFLOW_CONTRACT.get("stage_order")
STAGE_CONTRACTS = WORKFLOW_CONTRACT.get("stages")
PROTECTED_PATHS = WORKFLOW_CONTRACT.get("protected_paths")
if (
    not isinstance(STAGES, list)
    or not all(isinstance(item, str) for item in STAGES)
    or not isinstance(STAGE_CONTRACTS, dict)
    or set(STAGES) != set(STAGE_CONTRACTS)
    or not isinstance(PROTECTED_PATHS, list)
):
    raise RuntimeError("workflow contract must define stage_order, stages, and protected_paths")
STAGE_ALLOWED_PATHS: dict[str, list[str]] = {
    stage: list(STAGE_CONTRACTS[stage]["allowed_paths"]) for stage in STAGES
}
STAGE_REQUIRED_OUTPUTS: dict[str, list[str]] = {
    stage: list(STAGE_CONTRACTS[stage]["required_outputs"]) for stage in STAGES
}

DEFAULT_AGENTS = {
    "c-analyzer": {
        "path": "work/skills/c-analyzer.md",
        "mode": "subagent",
        "stages": ["READ_C_PROJECT", "BUILD_C_MODEL", "DESIGN_RUST_API"],
    },
    "rust-implementer": {
        "path": "work/skills/rust-implementer.md",
        "mode": "subagent",
        "stages": ["GENERATE_RUST_SCAFFOLD", "REWRITE_CORE_MODULES", "VERIFY_RUST_WITH_C_TESTS"],
    },
    "test-migrator": {
        "path": "work/skills/test-migrator.md",
        "mode": "subagent",
        "stages": ["MIGRATE_TESTS"],
    },
    "repairer": {
        "path": "work/skills/repairer.md",
        "mode": "subagent",
        "stages": ["BUILD_TEST_REPAIR"],
    },
}

VERIFY_ACTIONS = {
    "REPAIR_RUST_WITH_C_TESTS",
    "REPAIR_RUST",
    "REPAIR_ABI_LAYOUT",
    "REANALYZE_C_MODEL",
    "ISOLATE_SCENARIOS",
    "CONFIRM_C_CROSS",
    "RESTORE_BEST",
}
TERMINAL_ACTIONS = {"DONE", "DONE_WITH_FAILURES"}
CONTROLLER_OWNED_PATTERNS = [
    "logs/trace/workflow_state.json",
    "logs/trace/agent-registry.json",
    "logs/trace/subagent-invocations.jsonl",
    "logs/trace/stage-runs/**",
    "logs/trace/stage-receipts/**",
    "logs/trace/stage-receipts.jsonl",
    "logs/trace/stage-aborts.jsonl",
    "logs/trace/task-packets/**",
    "logs/trace/input-source-baseline.json",
    "logs/trace/test-failure-triage.jsonl",
]


class WorkflowError(RuntimeError):
    pass


def _now_ns() -> int:
    return time.time_ns()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"{path} must contain a JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"invalid {path.name} record {index}: {exc}") from exc
        if not isinstance(row, dict):
            raise WorkflowError(f"invalid {path.name} record {index}: expected object")
        rows.append(row)
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise WorkflowError(f"path escapes workbench root: {path}") from exc


def _matches(path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if path == prefix or path.startswith(prefix + "/"):
                return True
        elif fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def _pattern_within(candidate: str, allowed_patterns: Iterable[str]) -> bool:
    if candidate in {"", "*", "**", "/"} or Path(candidate).is_absolute() or ".." in Path(candidate).parts:
        return False
    probe = candidate[:-3].rstrip("/") + "/__scope_probe__" if candidate.endswith("/**") else candidate
    return _matches(probe, allowed_patterns)


def _iter_files(root: Path, patterns: Iterable[str]) -> Iterable[tuple[str, Path]]:
    seen: set[str] = set()
    for pattern in patterns:
        base = pattern.split("*", 1)[0].rstrip("/")
        start = root / base if base else root
        if start.is_file() or start.is_symlink():
            candidates = [start]
        elif start.is_dir():
            candidates = start.rglob("*")
        else:
            continue
        for path in candidates:
            if path.is_symlink():
                pass
            elif not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in seen or not _matches(rel, [pattern]):
                continue
            framed = f"/{rel}/"
            if (
                "/target/" in framed
                or "/node_modules/" in framed
                or "/__pycache__/" in framed
                or "/.git/" in framed
                or rel.endswith((".pyc", ".pyo"))
            ):
                continue
            seen.add(rel)
            yield rel, path


def _snapshot(root: Path, patterns: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for rel, path in sorted(_iter_files(root, patterns)):
        if path.is_symlink():
            result[rel] = "symlink:" + os.readlink(path)
        else:
            result[rel] = _sha256(path)
    return result


def _snapshot_digest(snapshot: dict[str, str]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _root_identity(root: Path) -> dict[str, Any]:
    stat = root.stat()
    return {
        "canonical": str(root),
        "device": stat.st_dev,
        "inode": stat.st_ino,
    }


def _state_path(root: Path) -> Path:
    return root / "logs" / "trace" / "workflow_state.json"


def _load_state(root: Path) -> dict[str, Any]:
    return _json(_state_path(root))


def _initial_state(root: Path, max_repairs: int, max_test_repairs: int) -> dict[str, Any]:
    return {
        "controller_contract_version": CONTRACT_VERSION,
        "run_root": _root_identity(root),
        "current_stage": "INIT_WORKSPACE",
        "completed_stages": ["BOOTSTRAP", "INIT_WORKSPACE"],
        "checkpoint": "INIT_WORKSPACE",
        "rust_project_path": "flashDB_rust",
        "input_path_candidates": list(INPUT_PATH_CANDIDATES),
        "build_status": "pending",
        "test_status": "pending",
        "unsafe_ratio": None,
        "repair_rounds": 0,
        "c_cross_repair_transactions": 0,
        "non_rust_c_cross_repairs": 0,
        "best_snapshot_restored": False,
        "max_c_cross_repairs": max_repairs,
        "test_repair_rounds": 0,
        "max_test_repairs": max_test_repairs,
        "report_repair_rounds": 0,
        "max_report_repairs": 2,
        "final_status": "pending",
        "blocked_issues": [],
        "next_action": "READ_C_PROJECT",
        "active_stage_run": None,
        "last_gate": None,
    }


def _find_input_source(root: Path, state: dict[str, Any]) -> Path | None:
    candidates = state.get("input_path_candidates")
    values = [item for item in candidates if isinstance(item, str)] if isinstance(candidates, list) else []
    for value in values:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if (candidate / "src").is_dir() and (candidate / "tests").is_dir():
            return candidate
    return None


def _ensure_source_baseline(root: Path, state: dict[str, Any]) -> None:
    """Capture the platform input before any delegated READ work begins."""
    existing = state.get("input_source_baseline")
    existing_hash = state.get("input_source_baseline_sha256")
    if isinstance(existing, str) and isinstance(existing_hash, str) and (root / existing).is_file():
        if _sha256(root / existing) != existing_hash:
            raise WorkflowError("controller-owned input source baseline was modified")
        return
    source = _find_input_source(root, state)
    if source is None:
        return
    baseline_path = root / "logs" / "trace" / "input-source-baseline.json"
    document = {
        "schema_version": 1,
        "source_root": str(source),
        "files": _snapshot(source, ["**"]),
    }
    _atomic_json(baseline_path, document)
    state["input_source_baseline"] = baseline_path.relative_to(root).as_posix()
    state["input_source_baseline_sha256"] = _sha256(baseline_path)
    state["input_source_root"] = str(source)


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    max_test_repairs = int(getattr(args, "max_test_repairs", 8))
    if args.max_c_cross_repairs < 1 or args.max_c_cross_repairs > 32:
        raise WorkflowError("--max-c-cross-repairs must be between 1 and 32")
    if max_test_repairs < 1 or max_test_repairs > 32:
        raise WorkflowError("--max-test-repairs must be between 1 and 32")
    generated_project = root / "flashDB_rust"
    if generated_project.exists() and not args.force:
        raise WorkflowError(
            "flashDB_rust already exists; archive it or pass --force only when intentionally starting a clean run"
        )
    state_path = _state_path(root)
    if state_path.exists() and not args.force:
        raise WorkflowError(f"{state_path} already exists; pass --force only when intentionally starting a new trace")
    # These are controller-owned runtime trees.  Clearing them here prevents
    # stale receipts/attempts from being accepted as evidence for a new run.
    for owned in [root / "result", root / "logs"]:
        if owned.exists():
            shutil.rmtree(owned)
    if generated_project.exists():
        shutil.rmtree(generated_project)
    for path in [root / "result" / "issues", root / "logs" / "trace"]:
        path.mkdir(parents=True, exist_ok=True)
    interaction = root / "logs" / "interaction.md"
    interaction.parent.mkdir(parents=True, exist_ok=True)
    interaction.touch(exist_ok=True)
    state = _initial_state(root, args.max_c_cross_repairs, max_test_repairs)
    _ensure_source_baseline(root, state)
    _atomic_json(state_path, state)
    _atomic_json(root / "logs" / "trace" / "agent-registry.json", {"subagents": DEFAULT_AGENTS})
    (root / "logs" / "trace" / "subagent-invocations.jsonl").touch(exist_ok=True)
    stage_log = root / "logs" / "trace" / "01-init-workspace.md"
    stage_log.write_text("# 初始化工作区\n\n- 状态、目录和代理注册表由 workflowctl 创建。\n", encoding="utf-8")
    gate = root / "work" / "tools" / "gate.py"
    if gate.is_file():
        checked = subprocess.run(
            [sys.executable, str(gate), "--stage", "INIT_WORKSPACE", "--root", str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if checked.returncode != 0:
            raise WorkflowError("INIT_WORKSPACE gate failed:\n" + checked.stdout[-4000:])
        state = _load_state(root)
        state["last_gate"] = {"stage": "INIT_WORKSPACE", "status": "pass", "receipt": None}
        _atomic_json(state_path, state)
    print("WORKFLOWCTL: INITIALIZED")
    print("next_action=READ_C_PROJECT")
    return 0


def _stage_for_action(action: str) -> str | None:
    if action in STAGES:
        return action
    if action in VERIFY_ACTIONS:
        return "VERIFY_RUST_WITH_C_TESTS"
    for prefix in ("REPAIR_", "RETRY_", "COMPLETE_", "RUN_GATE_"):
        if action.startswith(prefix) and action[len(prefix):] in STAGES:
            return action[len(prefix):]
    return None


def _expected_stage(state: dict[str, Any]) -> str | None:
    action = str(state.get("next_action") or "")
    routed = _stage_for_action(action)
    if routed is not None:
        return routed
    if action in TERMINAL_ACTIONS:
        return None
    current = str(state.get("current_stage") or "")
    return current if current in STAGES else None


def _suggested_agent(stage: str, action: str) -> str:
    if action == "REANALYZE_C_MODEL":
        return "c-analyzer"
    if action in {"ISOLATE_SCENARIOS", "CONFIRM_C_CROSS", "RESTORE_BEST", "REPAIR_ABI_LAYOUT"}:
        return "controller"
    for agent, registration in DEFAULT_AGENTS.items():
        stages = registration.get("stages")
        if isinstance(stages, list) and stage in stages:
            return agent
    return "controller"


def _invoke_task_packet(root: Path, stage: str, action: str | None = None) -> str | None:
    tool = root / "work" / "tools" / "task_packet.py"
    if not tool.exists():
        return None
    output = root / "logs" / "trace" / "task-packets" / f"{stage.lower()}.json"
    command = [
        sys.executable,
        str(tool),
        "--root",
        str(root),
        "--stage",
        stage,
        "--output",
        str(output),
    ]
    if action:
        command.extend(["--action", action])
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if completed.returncode != 0:
        raise WorkflowError("task packet generation failed:\n" + completed.stdout[-4000:])
    return output.relative_to(root).as_posix()


def cmd_begin(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    requested_action = args.stage.upper()
    stage = requested_action if requested_action in STAGES else _stage_for_action(requested_action)
    if stage not in STAGES:
        raise WorkflowError(f"unsupported stage/action: {requested_action}")
    state = _load_state(root)
    if int(state.get("controller_contract_version", 0)) != CONTRACT_VERSION:
        raise WorkflowError("workflow state was not initialized by this workflowctl contract")
    if state.get("active_stage_run"):
        raise WorkflowError("another stage run is active; finish or abort it first")
    expected = _expected_stage(state)
    if expected is None:
        raise WorkflowError(f"workflow is terminal: {state.get('next_action')}")
    current = str(state.get("current_stage") or "")
    if stage != expected and not (args.resume and stage == current):
        raise WorkflowError(
            f"expected stage {expected}, got {stage}; --resume can only retry the current stage {current}"
        )

    if stage == "READ_C_PROJECT":
        _ensure_source_baseline(root, state)
        _atomic_json(_state_path(root), state)
    if stage == "BUILD_TEST_REPAIR":
        _refresh_test_triage(root)
    defaults = STAGE_ALLOWED_PATHS[stage]
    raw_requested = list(args.allow_path)
    wildcard_requests = [item for item in raw_requested if any(char in item for char in "*?[]")]
    if wildcard_requests:
        raise WorkflowError("additional allow paths must be exact files, not glob patterns")
    requested = [_relative(root, item) for item in raw_requested]
    if requested:
        raise WorkflowError("dynamic allow-path expansion is disabled; use the versioned workflow contract")
    protected_roots = {"INSTRUCTION.md", "work", ".opencode", "tests", "judge-assets", "design_doc"}
    invalid_requested = [
        item for item in requested
        if item.split("/", 1)[0] in protected_roots
    ]
    if invalid_requested:
        raise WorkflowError("additional allow paths cannot weaken protected scope: " + ", ".join(invalid_requested))
    outside_contract = [item for item in requested if not _pattern_within(item, defaults)]
    if outside_contract:
        raise WorkflowError("additional allow paths must stay within the stage contract: " + ", ".join(outside_contract))
    packet = _invoke_task_packet(root, stage, str(state.get("next_action") or requested_action))
    packet_allowed: list[str] = []
    if packet:
        packet_doc = _json(root / packet)
        raw_packet_allowed = packet_doc.get("allowed_modification_paths")
        if not isinstance(raw_packet_allowed, list) or not raw_packet_allowed:
            raise WorkflowError("task packet must declare allowed_modification_paths")
        packet_allowed = [item for item in raw_packet_allowed if isinstance(item, str)]
        if len(packet_allowed) != len(raw_packet_allowed) or any(
            not _pattern_within(item, defaults) for item in packet_allowed
        ):
            raise WorkflowError("task packet allowed paths exceed the stage contract")
    allowed = list(dict.fromkeys((packet_allowed or defaults) + requested))
    required = list(dict.fromkeys(STAGE_REQUIRED_OUTPUTS[stage] + [_relative(root, item) for item in args.require_output]))
    if packet and packet not in required:
        required.append(packet)
    # Snapshot the whole workbench so a stage cannot hide changes by writing
    # outside both its allow-list and the older explicit protected set.
    monitored = list(dict.fromkeys(["**", *PROTECTED_PATHS]))
    current_snapshot = _snapshot(root, monitored)
    retry_origin = state.get("retry_baseline_run")
    entry_action = str(state.get("next_action") or "")
    # A failed core-rewrite gate may require another implementation pass. Its
    # receipt must still describe the delta from the original scaffold, not
    # from the already-edited tree visible to the repair agent. Other repair
    # stages deliberately retain per-attempt snapshots.
    reuse_rewrite_baseline = (
        stage == "REWRITE_CORE_MODULES"
        and entry_action.startswith(("RETRY_REWRITE_CORE_MODULES", "REPAIR_REWRITE_CORE_MODULES"))
    )
    if (entry_action.startswith("RETRY_") or reuse_rewrite_baseline) and isinstance(retry_origin, dict):
        origin_file = root / str(retry_origin.get("run_file") or "")
        if (
            not origin_file.is_file()
            or origin_file.is_symlink()
            or _sha256(origin_file) != retry_origin.get("run_sha256")
        ):
            raise WorkflowError("retry baseline stage-run record was modified")
        origin_run = _json(origin_file)
        if origin_run.get("stage") != stage or origin_run.get("root") != _root_identity(root):
            raise WorkflowError("retry baseline belongs to a different stage or workbench")
        baseline = origin_run.get("baseline")
        if not isinstance(baseline, dict):
            raise WorkflowError("retry baseline stage-run record is missing its snapshot")
        baseline = {str(key): str(value) for key, value in baseline.items()}
        baseline_origin = dict(retry_origin)
    else:
        baseline = current_snapshot
        baseline_origin = None
    run_id = f"{_now_ns()}-{stage.lower().replace('_', '-')}"
    nonce = secrets.token_hex(16)
    run = {
        "contract_version": CONTRACT_VERSION,
        "run_id": run_id,
        "nonce": nonce,
        "stage": stage,
        "agent": args.agent,
        "root": _root_identity(root),
        "started_at_ns": _now_ns(),
        "allowed_paths": allowed,
        "requested_allow_paths": requested,
        "required_outputs": required,
        "monitored_patterns": monitored,
        "baseline": baseline,
        "baseline_digest": _snapshot_digest(baseline),
        "baseline_origin": baseline_origin,
        "controller_baseline": {
            path: digest
            for path, digest in current_snapshot.items()
            if _matches(path, CONTROLLER_OWNED_PATTERNS)
        },
        "task_packet": packet,
        "task_packet_sha256": _sha256(root / packet) if packet else None,
        "input_source_baseline": state.get("input_source_baseline"),
        "input_source_baseline_sha256": state.get("input_source_baseline_sha256"),
        "repair_run": bool(
            args.resume
            or str(state.get("next_action") or "").startswith(("REPAIR_", "REANALYZE_", "ISOLATE_"))
        ),
        "entry_action": state.get("next_action"),
        "attempt_records_before": len(
            _read_jsonl(root / "logs" / "trace" / "c-cross" / "attempts.jsonl")
        ) if stage == "VERIFY_RUST_WITH_C_TESTS" else 0,
        "isolation_records_before": len(
            _read_jsonl(root / "logs" / "trace" / "c-cross" / "isolation-results.jsonl")
        ) if stage == "VERIFY_RUST_WITH_C_TESTS" else 0,
        "state_before": json.loads(json.dumps(state)),
    }
    run_path = root / "logs" / "trace" / "stage-runs" / stage / f"{run_id}.json"
    _atomic_json(run_path, run)
    run_sha256 = _sha256(run_path)
    state["active_stage_run"] = {
        "run_id": run_id,
        "nonce": nonce,
        "stage": stage,
        "run_file": run_path.relative_to(root).as_posix(),
        "run_sha256": run_sha256,
    }
    state["current_stage"] = stage
    state["checkpoint"] = stage
    state["next_action"] = f"COMPLETE_{stage}"
    _atomic_json(_state_path(root), state)
    print("WORKFLOWCTL: STAGE_BEGUN")
    print(f"stage={stage}")
    print(f"run_id={run_id}")
    print(f"nonce={nonce}")
    if packet:
        print(f"task_packet={packet}")
    return 0


def _diff(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    before_keys = set(before)
    after_keys = set(after)
    return {
        "created": sorted(after_keys - before_keys),
        "deleted": sorted(before_keys - after_keys),
        "modified": sorted(path for path in before_keys & after_keys if before[path] != after[path]),
    }


def _matrix_all_pass(root: Path) -> bool:
    path = root / "logs" / "trace" / "validation-matrix.json"
    if not path.exists():
        return False
    matrix = _json(path)
    scenarios = matrix.get("scenarios")
    rows = [row for row in scenarios if isinstance(row, dict)] if isinstance(scenarios, list) else []
    return bool(rows) and all(row.get("rust_impl_c_test") == "pass" for row in rows)


def _repair_attempt_count(root: Path) -> int:
    path = root / "logs" / "trace" / "c-cross" / "attempts.jsonl"
    if not path.is_file():
        return 0
    count = 0
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"invalid attempts.jsonl record {index}: {exc}") from exc
        if not isinstance(row, dict):
            raise WorkflowError(f"invalid attempts.jsonl record {index}: expected object")
        if row.get("kind") == "repair":
            count += 1
    return count


def _refresh_test_triage(root: Path) -> bool:
    """Regenerate trusted triage from cargo evidence; agents cannot grant their own scope."""
    trace = root / "logs" / "trace"
    results_path = trace / "cargo-results.json"
    triage_path = trace / "test-failure-triage.jsonl"
    before = _sha256(triage_path) if triage_path.is_file() else None
    if not results_path.is_file():
        return False
    results = _json(results_path)
    if results.get("test_status") == "pass":
        if triage_path.exists():
            triage_path.unlink()
        return before is not None
    tool = root / "work" / "tools" / "test_failure_triage.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--root",
            str(root),
            "--out",
            str(trace),
            "--replace",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode != 0 or not triage_path.is_file():
        raise WorkflowError("controller test triage failed:\n" + completed.stdout[-4000:])
    return before != _sha256(triage_path)


def _c_cross_repair_action(root: Path) -> str:
    attempts = _read_jsonl(root / "logs" / "trace" / "c-cross" / "attempts.jsonl")
    latest = attempts[-1] if attempts else {}
    if latest.get("regression") and latest.get("restore_best_available"):
        return "RESTORE_BEST"
    path = root / "logs" / "trace" / "c-cross" / "repair-plan.json"
    if not path.is_file():
        return "REPAIR_RUST"
    plan = _json(path)
    action = str(plan.get("next_action") or "")
    if action == "ISOLATE_SCENARIOS":
        queue = plan.get("isolation_queue")
        pending = [
            item for item in queue
            if isinstance(item, dict) and item.get("status", "pending") == "pending"
        ] if isinstance(queue, list) else []
        if not pending:
            return "CONFIRM_C_CROSS"
    allowed = {
        "REPAIR_ABI_LAYOUT",
        "REANALYZE_C_MODEL",
        "ISOLATE_SCENARIOS",
        "REPAIR_RUST",
        "CONFIRM_C_CROSS",
        "RESTORE_BEST",
    }
    return action if action in allowed else "REPAIR_RUST"


def _report_failure_action(state: dict[str, Any], root: Path) -> str:
    if not _matrix_all_pass(root):
        if state.get("c_cross_functional_status") == "budget_exhausted":
            return "DONE_WITH_FAILURES"
        return "VERIFY_RUST_WITH_C_TESTS"
    if state.get("build_status") != "pass" or state.get("test_status") != "pass":
        rounds = int(state.get("test_repair_rounds", 0) or 0)
        maximum = int(state.get("max_test_repairs", 8) or 8)
        return "DONE_WITH_FAILURES" if rounds >= maximum else "BUILD_TEST_REPAIR"
    ratio_path = root / "logs" / "trace" / "unsafe-ratio.json"
    if ratio_path.is_file():
        ratio = _json(ratio_path).get("unsafe_ratio", 1.0)
        try:
            if float(ratio) > 0.10:
                return "BUILD_TEST_REPAIR"
        except (TypeError, ValueError):
            pass
    rounds = int(state.get("report_repair_rounds", 0) or 0)
    maximum = int(state.get("max_report_repairs", 2) or 2)
    return "DONE_WITH_FAILURES" if rounds >= maximum else "REPAIR_REPORT_AND_VERIFY"


def _budget_exhausted_c_cross_action(state: dict[str, Any], root: Path) -> str:
    best = root / "logs" / "trace" / "c-cross" / "snapshots" / "best.json"
    if best.is_file() and not state.get("best_snapshot_restored"):
        return "RESTORE_BEST"
    return "MIGRATE_TESTS"


def _invalidate_report_candidate(root: Path, gate_output: str) -> None:
    reason = next(
        (line.strip() for line in gate_output.splitlines() if line.strip().startswith("- ")),
        "- final gate rejected the candidate report",
    )
    for path in [
        root / "result" / "output.md",
        root / "result" / "issues" / "00-summary.md",
    ]:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        text = text.replace("STATUS: SUCCESS", "STATUS: FAILED", 1)
        marker = "\n## Controller Final Gate\n"
        if marker not in text:
            text += f"{marker}\n{reason}\n"
        path.write_text(text, encoding="utf-8")


def _next_after(stage: str, state: dict[str, Any], root: Path, gate_ok: bool) -> str:
    if stage == "REPORT_AND_VERIFY":
        return "DONE" if gate_ok else _report_failure_action(state, root)
    if not gate_ok:
        if stage == "VERIFY_RUST_WITH_C_TESTS":
            rounds = int(state.get("repair_rounds", 0) or 0)
            maximum = int(state.get("max_c_cross_repairs", 8) or 8)
            return (
                _c_cross_repair_action(root)
                if rounds < maximum
                else _budget_exhausted_c_cross_action(state, root)
            )
        if stage == "BUILD_TEST_REPAIR":
            rounds = int(state.get("test_repair_rounds", 0) or 0)
            maximum = int(state.get("max_test_repairs", 8) or 8)
            if rounds >= maximum:
                return "REPORT_AND_VERIFY"
        return f"REPAIR_{stage}"
    if stage == "VERIFY_RUST_WITH_C_TESTS" and not _matrix_all_pass(root):
        rounds = int(state.get("repair_rounds", 0) or 0)
        maximum = int(state.get("max_c_cross_repairs", 8) or 8)
        if rounds < maximum:
            return _c_cross_repair_action(root)
        return _budget_exhausted_c_cross_action(state, root)
    return STAGES[STAGES.index(stage) + 1]


def _artifact_hashes(root: Path, required: list[str]) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for rel in required:
        path = root / rel
        if not path.is_file() or path.is_symlink():
            missing.append(rel)
        else:
            hashes[rel] = _sha256(path)
    return hashes, missing


def _verify_input_immutable(root: Path) -> None:
    state = _load_state(root)
    baseline_rel = state.get("input_source_baseline")
    baseline_hash = state.get("input_source_baseline_sha256")
    baseline_source: Path | None = None
    if isinstance(baseline_rel, str) and isinstance(baseline_hash, str):
        baseline_path = root / baseline_rel
        if not baseline_path.is_file() or baseline_path.is_symlink():
            raise WorkflowError("controller-owned input source baseline is missing")
        if _sha256(baseline_path) != baseline_hash:
            raise WorkflowError("controller-owned input source baseline was modified")
        baseline = _json(baseline_path)
        source_root = baseline.get("source_root")
        files = baseline.get("files")
        if not isinstance(source_root, str) or not isinstance(files, dict):
            raise WorkflowError("input source baseline is malformed")
        baseline_source = Path(source_root).resolve()
        current = _snapshot(baseline_source, ["**"])
        if current != files:
            differences = _diff(
                {str(key): str(value) for key, value in files.items()},
                current,
            )
            changed = differences["created"] + differences["modified"] + differences["deleted"]
            raise WorkflowError("platform C input changed during conversion: " + ", ".join(changed[:20]))

    manifest_path = root / "logs" / "trace" / "input_manifest.json"
    if not manifest_path.exists():
        return
    manifest = _json(manifest_path)
    source_root = manifest.get("source_root")
    evidence = manifest.get("file_evidence")
    if not isinstance(source_root, str) or not isinstance(evidence, dict):
        return
    source = Path(source_root).resolve()
    if baseline_source is not None and source != baseline_source:
        raise WorkflowError("input_manifest.json source_root does not match controller-captured platform input")
    changed: list[str] = []
    for rel, expected in evidence.items():
        if not isinstance(rel, str) or not isinstance(expected, dict) or ".." in Path(rel).parts:
            changed.append(str(rel))
            continue
        path = source / rel
        if not path.is_file() or _sha256(path) != expected.get("sha256"):
            changed.append(rel)
    if changed:
        raise WorkflowError("platform C input changed during conversion: " + ", ".join(changed[:20]))


def _update_stage_state(root: Path, state: dict[str, Any], stage: str) -> None:
    """Project verified artifact facts into workflow_state without model edits."""
    trace = root / "logs" / "trace"
    if stage == "READ_C_PROJECT":
        manifest = _json(trace / "input_manifest.json")
        source_root = manifest.get("source_root")
        if not isinstance(source_root, str) or not source_root:
            raise WorkflowError("input_manifest.json must include source_root")
        state["input_path"] = source_root
        state["input_manifest"] = "logs/trace/input_manifest.json"
    elif stage == "BUILD_C_MODEL":
        state.update({
            "c_project_model": "logs/trace/c_project_model.json",
            "c_api_model": "logs/trace/c_api_model.json",
            "c_test_model": "logs/trace/c_test_model.json",
        })
    elif stage == "DESIGN_RUST_API":
        state["rust_api_design"] = "logs/trace/rust_api_design.json"
    elif stage == "MIGRATE_TESTS":
        state["rust_test_mapping"] = "logs/trace/rust_test_mapping.json"
    elif stage == "BUILD_TEST_REPAIR":
        results = _json(trace / "cargo-results.json")
        state["build_status"] = results.get("build_status", "fail")
        state["test_status"] = results.get("test_status", "fail")
        state["test_failure_triage_required"] = bool(
            results.get("test_status") != "pass"
            or (trace / "test-failure-triage.jsonl").is_file()
        )
    elif stage == "REPORT_AND_VERIFY":
        ratio_path = trace / "unsafe-ratio.json"
        if ratio_path.exists():
            ratio = _json(ratio_path)
            state["unsafe_ratio"] = ratio.get("unsafe_ratio", ratio.get("ratio"))


def cmd_finish(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    state = _load_state(root)
    active = state.get("active_stage_run")
    if not isinstance(active, dict):
        raise WorkflowError("no active stage run")
    if active.get("run_id") != args.run_id or active.get("nonce") != args.nonce:
        raise WorkflowError("run_id/nonce do not match the active stage run")
    run_file = root / str(active.get("run_file") or "")
    if not run_file.is_file() or run_file.is_symlink() or _sha256(run_file) != active.get("run_sha256"):
        raise WorkflowError("controller stage-run record was modified")
    run = _json(run_file)
    stage = str(run.get("stage") or "")
    if stage not in STAGES:
        raise WorkflowError(f"active stage run has unsupported stage: {stage}")
    if stage != str(active.get("stage") or ""):
        raise WorkflowError("active state and run receipt disagree on stage")
    if run.get("root") != _root_identity(root):
        raise WorkflowError("stage was begun from a different worktree/root identity")
    if run.get("run_id") != args.run_id or run.get("nonce") != args.nonce:
        raise WorkflowError("stage run file does not match the active run credentials")
    state_before = run.get("state_before")
    if not isinstance(state_before, dict):
        raise WorkflowError("stage run file is missing its controller state baseline")
    expected_state = json.loads(json.dumps(state_before))
    expected_state["active_stage_run"] = active
    expected_state["current_stage"] = stage
    expected_state["checkpoint"] = stage
    expected_state["next_action"] = f"COMPLETE_{stage}"
    if state != expected_state:
        raise WorkflowError("workflow state was modified outside workflowctl during the stage")
    run_allowed = run.get("allowed_paths")
    if (
        not isinstance(run_allowed, list)
        or not run_allowed
        or any(not isinstance(item, str) or not _pattern_within(item, STAGE_ALLOWED_PATHS[stage]) for item in run_allowed)
    ):
        raise WorkflowError("stage run file contains paths outside the stage contract")
    run_required = run.get("required_outputs")
    if not isinstance(run_required, list) or not set(STAGE_REQUIRED_OUTPUTS[stage]).issubset(set(run_required)):
        raise WorkflowError("stage run file removed mandatory required outputs")
    if "**" not in run.get("monitored_patterns", []):
        raise WorkflowError("stage run file removed whole-workbench monitoring")
    for key in ("input_source_baseline", "input_source_baseline_sha256"):
        if run.get(key) != state.get(key):
            raise WorkflowError(f"workflow state changed controller-owned {key}")
    packet_rel = run.get("task_packet")
    packet_hash = run.get("task_packet_sha256")
    if packet_rel:
        packet_path = root / str(packet_rel)
        if (
            not packet_path.is_file()
            or packet_path.is_symlink()
            or not isinstance(packet_hash, str)
            or _sha256(packet_path) != packet_hash
        ):
            raise WorkflowError("controller-generated task packet was modified")
        packet_doc = _json(packet_path)
        packet_allowed = packet_doc.get("allowed_modification_paths")
        requested_allowed = run.get("requested_allow_paths")
        expected_allowed = list(dict.fromkeys(
            ([item for item in packet_allowed if isinstance(item, str)] if isinstance(packet_allowed, list) else [])
            + ([item for item in requested_allowed if isinstance(item, str)] if isinstance(requested_allowed, list) else [])
        ))
        if expected_allowed != run_allowed:
            raise WorkflowError("stage run allowed paths do not match the controller task packet")

    triage_refreshed = _refresh_test_triage(root) if stage == "BUILD_TEST_REPAIR" else False
    monitored = run.get("monitored_patterns")
    patterns = [item for item in monitored if isinstance(item, str)] if isinstance(monitored, list) else []
    before = run.get("baseline") if isinstance(run.get("baseline"), dict) else {}
    after = _snapshot(root, patterns)
    business_before = {
        path: digest for path, digest in before.items()
        if not _matches(path, CONTROLLER_OWNED_PATTERNS)
    }
    business_after = {
        path: digest for path, digest in after.items()
        if not _matches(path, CONTROLLER_OWNED_PATTERNS)
    }
    changes = _diff(business_before, business_after)
    changed = sorted(changes["created"] + changes["modified"] + changes["deleted"])
    allowed = [item for item in run.get("allowed_paths", []) if isinstance(item, str)]
    unexpected = [path for path in changed if not _matches(path, allowed)]
    if unexpected:
        raise WorkflowError("stage modified protected/out-of-scope files: " + ", ".join(unexpected))
    symlink_changes = [path for path in changed if (root / path).is_symlink()]
    if symlink_changes:
        raise WorkflowError("stage created or modified symlink outputs: " + ", ".join(symlink_changes))
    expected_controller_changes = {
        "logs/trace/workflow_state.json",
        run_file.relative_to(root).as_posix(),
    }
    if stage == "BUILD_TEST_REPAIR" and triage_refreshed:
        expected_controller_changes.add("logs/trace/test-failure-triage.jsonl")
    controller_before = run.get("controller_baseline")
    if not isinstance(controller_before, dict):
        raise WorkflowError("stage run file is missing its controller metadata baseline")
    controller_after = {
        path: digest for path, digest in after.items()
        if _matches(path, CONTROLLER_OWNED_PATTERNS)
    }
    controller_diff = _diff(controller_before, controller_after)
    controller_changes = [
        path
        for path in sorted(
            controller_diff["created"] + controller_diff["modified"] + controller_diff["deleted"]
        )
        if path not in expected_controller_changes
    ]
    if controller_changes:
        raise WorkflowError("stage modified controller-owned metadata: " + ", ".join(controller_changes))

    required = [item for item in run.get("required_outputs", []) if isinstance(item, str)]
    artifact_hashes, missing = _artifact_hashes(root, required)
    if missing:
        raise WorkflowError("stage is missing required outputs: " + ", ".join(missing))
    _verify_input_immutable(root)

    completed = state.get("completed_stages")
    completed_list = [item for item in completed if isinstance(item, str)] if isinstance(completed, list) else []
    if stage not in completed_list:
        completed_list.append(stage)
    state["completed_stages"] = completed_list
    state["current_stage"] = stage
    state["checkpoint"] = stage
    _update_stage_state(root, state, stage)
    if stage == "REPORT_AND_VERIFY":
        # The existing final gate deliberately requires DONE while retaining
        # checkpoint=REPORT_AND_VERIFY.  A failed gate is routed back below.
        state["current_stage"] = "DONE"
    if stage == "VERIFY_RUST_WITH_C_TESTS":
        # C-cross attempts are the machine source of truth.  Confirmation and
        # isolation transactions do not consume the finite repair budget.
        # Deterministic ABI regeneration and C-model reanalysis are genuine
        # non-Rust repairs, so count their committed transactions separately.
        entry_action = str(run.get("entry_action") or "")
        non_rust_repairs = int(state.get("non_rust_c_cross_repairs", 0) or 0)
        if entry_action in {"REPAIR_ABI_LAYOUT", "REANALYZE_C_MODEL"}:
            non_rust_repairs += 1
        repair_actions = {
            "REPAIR_RUST_WITH_C_TESTS",
            "REPAIR_RUST",
            "REPAIR_ABI_LAYOUT",
            "REANALYZE_C_MODEL",
        }
        transactions = int(state.get("c_cross_repair_transactions", 0) or 0)
        if entry_action in repair_actions:
            transactions += 1
            state["best_snapshot_restored"] = False
        elif entry_action == "RESTORE_BEST":
            state["best_snapshot_restored"] = True
        state["c_cross_repair_transactions"] = transactions
        state["non_rust_c_cross_repairs"] = non_rust_repairs
        state["repair_rounds"] = max(
            transactions,
            _repair_attempt_count(root) + non_rust_repairs,
        )
    state["active_stage_run"] = None
    state.pop("retry_baseline_run", None)
    state["next_action"] = f"RUN_GATE_{stage}"
    _atomic_json(_state_path(root), state)

    receipt_path = root / "logs" / "trace" / "stage-receipts" / f"{stage}.json"
    immutable_receipt_path = (
        root / "logs" / "trace" / "stage-receipts" / stage / f"{args.run_id}.json"
    )
    receipt = {
        "contract_version": CONTRACT_VERSION,
        "run_id": args.run_id,
        "nonce_sha256": hashlib.sha256(args.nonce.encode("utf-8")).hexdigest(),
        "stage": stage,
        "agent": run.get("agent"),
        "root": _root_identity(root),
        "started_at_ns": run.get("started_at_ns"),
        "finished_at_ns": _now_ns(),
        "status": "ready_for_gate",
        "allowed_paths": allowed,
        "required_outputs": required,
        "artifact_hashes": artifact_hashes,
        "changed_files": changed,
        "changed_file_hashes": {
            rel: _sha256(root / rel)
            for rel in changed
            if (root / rel).is_file()
        },
        "change_set": changes,
        "unexpected_changes": [],
        "baseline_digest": run.get("baseline_digest"),
        "after_digest": _snapshot_digest(after),
        "task_packet": run.get("task_packet"),
        "task_packet_sha256": run.get("task_packet_sha256"),
        "run_file": run_file.relative_to(root).as_posix(),
        "run_file_sha256": _sha256(run_file),
        "receipt_path": immutable_receipt_path.relative_to(root).as_posix(),
    }
    _atomic_json(receipt_path, receipt)

    gate_command = [sys.executable, str(root / "work" / "tools" / "gate.py"), "--stage", stage, "--root", str(root)]
    completed_gate = subprocess.run(gate_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    gate_ok = completed_gate.returncode == 0
    if stage == "BUILD_TEST_REPAIR" and not gate_ok:
        state["test_repair_rounds"] = int(state.get("test_repair_rounds", 0) or 0) + 1
        _atomic_json(_state_path(root), state)
    if stage == "REPORT_AND_VERIFY" and not gate_ok:
        state["report_repair_rounds"] = int(state.get("report_repair_rounds", 0) or 0) + 1
        _atomic_json(_state_path(root), state)
        _invalidate_report_candidate(root, completed_gate.stdout)
        receipt["artifact_hashes"], _ = _artifact_hashes(root, required)
        receipt["changed_file_hashes"] = {
            rel: _sha256(root / rel)
            for rel in changed
            if (root / rel).is_file()
        }
        receipt["after_digest"] = _snapshot_digest(_snapshot(root, patterns))
    next_action = _next_after(stage, state, root, gate_ok)
    if (
        stage == "REWRITE_CORE_MODULES"
        and not gate_ok
        and next_action == "REPAIR_REWRITE_CORE_MODULES"
    ):
        # Retain the original scaffold-era baseline for the repair run. Agents
        # must not reconstruct it with git, /tmp backups, or a second scaffold
        # generation.
        state["retry_baseline_run"] = {
            "run_file": run_file.relative_to(root).as_posix(),
            "run_sha256": _sha256(run_file),
        }
    receipt["status"] = "pass" if gate_ok else "failed"
    receipt["gate_exit_code"] = completed_gate.returncode
    receipt["gate_output_tail"] = "\n".join(completed_gate.stdout.splitlines()[-40:])
    receipt["next_action"] = next_action
    _atomic_json(receipt_path, receipt)
    _atomic_json(immutable_receipt_path, receipt)

    state = _load_state(root)
    state["last_gate"] = {
        "stage": stage,
        "status": "pass" if gate_ok else "fail",
        "receipt": immutable_receipt_path.relative_to(root).as_posix(),
    }
    state["next_action"] = next_action
    if next_action in TERMINAL_ACTIONS:
        state["current_stage"] = "DONE"
        state["final_status"] = "pass" if next_action == "DONE" else "fail"
    elif stage == "REPORT_AND_VERIFY":
        state["current_stage"] = "REPORT_AND_VERIFY"
    if stage == "VERIFY_RUST_WITH_C_TESTS":
        if _matrix_all_pass(root):
            state["c_cross_functional_status"] = "pass"
        elif next_action == "MIGRATE_TESTS":
            state["c_cross_functional_status"] = "budget_exhausted"
        else:
            state["c_cross_functional_status"] = "repair_required"
    _atomic_json(_state_path(root), state)

    _append_jsonl(root / "logs" / "trace" / "stage-receipts.jsonl", receipt)
    print(completed_gate.stdout, end="" if completed_gate.stdout.endswith("\n") else "\n")
    print("WORKFLOWCTL: STAGE_FINISHED")
    print(f"receipt={immutable_receipt_path.relative_to(root).as_posix()}")
    print(f"latest_receipt={receipt_path.relative_to(root).as_posix()}")
    print(f"next_action={next_action}")
    return completed_gate.returncode


def cmd_abort(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    state = _load_state(root)
    active = state.get("active_stage_run")
    if not isinstance(active, dict):
        raise WorkflowError("no active stage run")
    if active.get("run_id") != args.run_id or active.get("nonce") != args.nonce:
        raise WorkflowError("run_id/nonce do not match the active stage run")
    run_file = root / str(active.get("run_file") or "")
    if not run_file.is_file() or run_file.is_symlink() or _sha256(run_file) != active.get("run_sha256"):
        raise WorkflowError("controller stage-run record was modified")
    run = _json(run_file)
    if run.get("run_id") != args.run_id or run.get("nonce") != args.nonce:
        raise WorkflowError("stage run file does not match the active run credentials")
    state_before = run.get("state_before")
    if not isinstance(state_before, dict):
        raise WorkflowError("stage run file is missing its controller state baseline")
    monitored = run.get("monitored_patterns")
    patterns = [item for item in monitored if isinstance(item, str)] if isinstance(monitored, list) else []
    before = run.get("baseline") if isinstance(run.get("baseline"), dict) else {}
    after = _snapshot(root, patterns)
    business_before = {
        path: digest for path, digest in before.items()
        if not _matches(path, CONTROLLER_OWNED_PATTERNS)
    }
    business_after = {
        path: digest for path, digest in after.items()
        if not _matches(path, CONTROLLER_OWNED_PATTERNS)
    }
    changes = _diff(business_before, business_after)
    changed = sorted(changes["created"] + changes["modified"] + changes["deleted"])
    expected_controller_changes = {
        "logs/trace/workflow_state.json",
        run_file.relative_to(root).as_posix(),
    }
    controller_before = run.get("controller_baseline")
    if not isinstance(controller_before, dict):
        raise WorkflowError("stage run file is missing its controller metadata baseline")
    controller_after = {
        path: digest for path, digest in after.items()
        if _matches(path, CONTROLLER_OWNED_PATTERNS)
    }
    controller_diff = _diff(controller_before, controller_after)
    controller_changes = [
        path
        for path in sorted(
            controller_diff["created"] + controller_diff["modified"] + controller_diff["deleted"]
        )
        if path not in expected_controller_changes
    ]
    if controller_changes:
        raise WorkflowError("stage modified controller-owned metadata: " + ", ".join(controller_changes))
    business_changes = changed
    allowed = [item for item in run.get("allowed_paths", []) if isinstance(item, str)]
    unexpected = [path for path in business_changes if not _matches(path, allowed)]
    if unexpected:
        raise WorkflowError(
            "cannot abort while protected/out-of-scope changes exist: " + ", ".join(unexpected)
        )
    symlink_changes = [path for path in business_changes if (root / path).is_symlink()]
    if symlink_changes:
        raise WorkflowError("cannot abort modified symlink outputs: " + ", ".join(symlink_changes))
    _verify_input_immutable(root)
    state_tampered = state != {
        **json.loads(json.dumps(state_before)),
        "active_stage_run": active,
        "current_stage": active.get("stage"),
        "checkpoint": active.get("stage"),
        "next_action": f"COMPLETE_{active.get('stage')}",
    }
    _append_jsonl(root / "logs" / "trace" / "stage-aborts.jsonl", {
        "run_id": args.run_id,
        "stage": active.get("stage"),
        "agent": run.get("agent"),
        "reason": args.reason,
        "state_tampering_restored": state_tampered,
        "aborted_at_ns": _now_ns(),
    })
    restored = json.loads(json.dumps(state_before))
    restored["current_stage"] = active.get("stage")
    restored["checkpoint"] = active.get("stage")
    restored["active_stage_run"] = None
    restored["next_action"] = f"RETRY_{active.get('stage')}"
    if isinstance(state_before.get("retry_baseline_run"), dict):
        restored["retry_baseline_run"] = state_before["retry_baseline_run"]
    else:
        restored["retry_baseline_run"] = {
            "run_file": run_file.relative_to(root).as_posix(),
            "run_sha256": _sha256(run_file),
        }
    _atomic_json(_state_path(root), restored)
    print("WORKFLOWCTL: STAGE_ABORTED")
    print(f"next_action={restored['next_action']}")
    return 0


def cmd_record_agent(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    stage = args.stage.upper()
    if stage not in {*STAGES, "C_ANALYSIS"}:
        raise WorkflowError(f"unsupported invocation stage: {stage}")
    if args.status not in {"pass", "success"}:
        raise WorkflowError("only successful agent invocations may satisfy stage evidence")
    receipt_rel = _relative(root, args.receipt)
    receipt = _json(root / receipt_rel)
    if receipt.get("run_id") != args.run_id or receipt.get("status") != "pass":
        raise WorkflowError("agent evidence must reference a matching, gate-passed stage receipt")
    receipt_stage = receipt.get("stage")
    expected_receipt_stage = "DESIGN_RUST_API" if stage == "C_ANALYSIS" else stage
    expected_receipt_prefix = f"logs/trace/stage-receipts/{expected_receipt_stage}/"
    if (
        receipt_stage != expected_receipt_stage
        or not receipt_rel.startswith(expected_receipt_prefix)
        or receipt_rel != receipt.get("receipt_path")
        or Path(receipt_rel).name != f"{args.run_id}.json"
    ):
        raise WorkflowError(
            f"agent evidence for {stage} must reference its immutable {expected_receipt_prefix}<run_id>.json receipt"
        )
    receipt_agent = receipt.get("agent")
    if receipt_agent not in {args.agent, "controller", None}:
        raise WorkflowError("agent name does not match the stage receipt")
    row = {
        "agent": args.agent,
        "stage": stage,
        "mode": args.mode,
        "status": args.status,
        "run_id": args.run_id,
        "artifact_receipt": receipt_rel,
        "artifact_receipt_sha256": _sha256(root / receipt_rel),
        "recorded_at_ns": _now_ns(),
    }
    if args.mode == "primary_fallback":
        if args.consecutive_failures < 3 or not args.reason:
            raise WorkflowError("primary_fallback requires --consecutive-failures >= 3 and --reason")
        registered_stages = DEFAULT_AGENTS.get(args.agent, {}).get("stages", [])
        failure_stages = (
            set(registered_stages)
            if stage == "C_ANALYSIS" and isinstance(registered_stages, list)
            else {expected_receipt_stage}
        )
        aborts = [
            item
            for item in _read_jsonl(root / "logs" / "trace" / "stage-aborts.jsonl")
            if item.get("agent") == args.agent and item.get("stage") in failure_stages
        ]
        if len(aborts) < args.consecutive_failures:
            raise WorkflowError(
                "primary_fallback consecutive failures are not backed by workflowctl abort records"
            )
        selected_aborts = aborts[-args.consecutive_failures :]
        row["consecutive_failures"] = args.consecutive_failures
        row["fallback_to_primary_reason"] = args.reason
        row["fallback_abort_runs"] = [str(item.get("run_id")) for item in selected_aborts]
    _append_jsonl(root / "logs" / "trace" / "subagent-invocations.jsonl", row)
    print("WORKFLOWCTL: AGENT_INVOCATION_RECORDED")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    state = _load_state(root)
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"current_stage={state.get('current_stage')}")
        print(f"next_action={state.get('next_action')}")
        print(f"repair_rounds={state.get('repair_rounds', 0)}/{state.get('max_c_cross_repairs', 8)}")
        print(f"test_repair_rounds={state.get('test_repair_rounds', 0)}/{state.get('max_test_repairs', 8)}")
        expected = _expected_stage(state)
        print(f"expected_stage={expected or 'none'}")
        active = state.get("active_stage_run")
        if isinstance(active, dict):
            run_id = active.get("run_id")
            nonce = active.get("nonce")
            if isinstance(run_id, str) and isinstance(nonce, str):
                print(
                    "next_command=python3 work/tools/workflowctl.py --root . finish "
                    f"--run-id {run_id} --nonce {nonce}"
                )
        elif expected:
            action = str(state.get("next_action") or "")
            stage_token = action if _stage_for_action(action) == expected else expected
            agent = _suggested_agent(expected, action)
            print(
                "next_command=python3 work/tools/workflowctl.py --root . begin "
                f"--stage {stage_token} --agent {agent}"
            )
        print(f"final_status={state.get('final_status', 'pending')}")
        print(f"active_run={active.get('run_id') if isinstance(active, dict) else 'none'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transactional FlashDB migration workflow coordinator.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Initialize controller-owned workspace state.")
    init.add_argument("--force", action="store_true")
    init.add_argument("--max-c-cross-repairs", type=int, default=8)
    init.add_argument("--max-test-repairs", type=int, default=8)
    init.set_defaults(handler=cmd_init)

    begin = subparsers.add_parser("begin", help="Begin a transactional stage run.")
    begin.add_argument("--stage", required=True)
    begin.add_argument("--agent", default="controller")
    begin.add_argument("--allow-path", action="append", default=[])
    begin.add_argument("--require-output", action="append", default=[])
    begin.add_argument("--resume", action="store_true", help="Retry/resume the current evidence-backed stage.")
    begin.set_defaults(handler=cmd_begin)

    finish = subparsers.add_parser("finish", help="Commit artifacts, run the gate, and route the next action.")
    finish.add_argument("--run-id", required=True)
    finish.add_argument("--nonce", required=True)
    finish.set_defaults(handler=cmd_finish)

    abort = subparsers.add_parser("abort", help="Abort an active stage without declaring completion.")
    abort.add_argument("--run-id", required=True)
    abort.add_argument("--nonce", required=True)
    abort.add_argument("--reason", required=True)
    abort.set_defaults(handler=cmd_abort)

    agent = subparsers.add_parser("record-agent", help="Append controller-owned subagent invocation evidence.")
    agent.add_argument("--agent", required=True)
    agent.add_argument("--stage", required=True)
    agent.add_argument(
        "--mode",
        choices=["native", "generic_subagent", "isolated_proxy", "primary_fallback"],
        required=True,
    )
    agent.add_argument("--status", choices=["pass", "success"], required=True)
    agent.add_argument("--run-id", required=True)
    agent.add_argument("--receipt", required=True)
    agent.add_argument("--consecutive-failures", type=int, default=0)
    agent.add_argument("--reason", default="")
    agent.set_defaults(handler=cmd_record_agent)

    status = subparsers.add_parser("status", help="Print current machine-owned routing state.")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except WorkflowError as exc:
        print(f"WORKFLOWCTL: ERROR\n{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
