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
    "logs/trace/rewrite-state.json",
    "logs/trace/rewrite-worker-runs/**",
    "logs/trace/rewrite-worker-receipts/**",
    "logs/trace/rewrite-check/**",
    "logs/trace/core_rewrite_batches.jsonl",
    "logs/trace/implementation-audit.json",
    "logs/trace/06-rewrite-core-modules.md",
]
REWRITE_SETTINGS = WORKFLOW_CONTRACT.get("rewrite_static", {})
REWRITE_ROLES = {"CORE": "IMPLEMENT_CORE", "FACADE": "WIRE_FACADE"}


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
    baseline_rel = state.get("input_source_baseline")
    baseline_path = root / baseline_rel if isinstance(baseline_rel, str) else None
    baseline = _json(baseline_path) if baseline_path is not None and baseline_path.is_file() else {}
    baseline_files = baseline.get("files") if isinstance(baseline.get("files"), dict) else {}
    stage_log.write_text(
        "# INIT_WORKSPACE 阶段日志\n\n"
        "- 生成者：workflowctl\n"
        "- workflow_state.json：已生成\n"
        "- agent-registry.json：已生成（4 个 subagent）\n"
        f"- 输入基线文件：{len(baseline_files)}\n"
        f"- 输入基线 SHA256：`{state.get('input_source_baseline_sha256')}`\n"
        "- flashDB_rust：未生成\n"
        "- 下一阶段：READ_C_PROJECT\n",
        encoding="utf-8",
    )
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
        with stage_log.open("a", encoding="utf-8") as handle:
            handle.write("- INIT_WORKSPACE gate：PASS\n")
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


def _invoke_task_packet(
    root: Path,
    stage: str,
    action: str | None = None,
    rewrite_role: str | None = None,
) -> str | None:
    tool = root / "work" / "tools" / "task_packet.py"
    if not tool.exists():
        return None
    suffix = f"-{rewrite_role.lower().replace('_', '-')}" if rewrite_role else ""
    output = root / "logs" / "trace" / "task-packets" / f"{stage.lower()}{suffix}.json"
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
    if rewrite_role:
        command.extend(["--rewrite-role", rewrite_role])
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if completed.returncode != 0:
        raise WorkflowError("task packet generation failed:\n" + completed.stdout[-4000:])
    return output.relative_to(root).as_posix()


def _rewrite_state_path(root: Path) -> Path:
    return root / "logs" / "trace" / "rewrite-state.json"


def _load_rewrite_state(root: Path) -> dict[str, Any]:
    return _json(_rewrite_state_path(root))


def _rewrite_manifest(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _json(root / "logs" / "trace" / "scaffold-manifest.json")
    ownership = manifest.get("rewrite_ownership")
    if not isinstance(ownership, dict) or ownership.get("schema_version") != 1:
        raise WorkflowError("scaffold manifest has no supported rewrite_ownership contract")
    categories: dict[str, set[str]] = {}
    names = [
        "core_owned_paths",
        "facade_owned_paths",
        "frozen_contract_paths",
        "shared_readonly_paths",
    ]
    generated = manifest.get("files")
    generated_paths = set(generated) if isinstance(generated, dict) else set()
    for name in names:
        values = ownership.get(name)
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            raise WorkflowError(f"rewrite ownership {name} must be a string list")
        if any(Path(item).is_absolute() or ".." in Path(item).parts for item in values):
            raise WorkflowError(f"rewrite ownership {name} contains unsafe paths")
        categories[name] = set(values)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            overlap = categories[left] & categories[right]
            if overlap:
                raise WorkflowError(f"rewrite ownership {left}/{right} overlap: {', '.join(sorted(overlap))}")
    classified = set().union(*(categories[name] for name in names))
    if classified != generated_paths:
        missing = sorted(generated_paths - classified)
        unknown = sorted(classified - generated_paths)
        raise WorkflowError(
            "rewrite ownership must classify every generated file"
            + (f"; missing={','.join(missing)}" if missing else "")
            + (f"; unknown={','.join(unknown)}" if unknown else "")
        )
    placeholders = manifest.get("placeholder_modules")
    placeholder_paths = {
        entry.get("path") for entry in placeholders.values()
        if isinstance(placeholders, dict) and isinstance(entry, dict) and isinstance(entry.get("path"), str)
    } if isinstance(placeholders, dict) else set()
    if not placeholder_paths.issubset(categories["core_owned_paths"]):
        raise WorkflowError("rewrite ownership must assign every placeholder module to IMPLEMENT_CORE")
    ffi_functions = manifest.get("ffi_functions")
    ffi_paths = {
        entry.get("path") for entry in ffi_functions.values()
        if isinstance(ffi_functions, dict) and isinstance(entry, dict) and isinstance(entry.get("path"), str)
    } if isinstance(ffi_functions, dict) else set()
    if not ffi_paths.issubset(categories["facade_owned_paths"]):
        raise WorkflowError("rewrite ownership must assign every generated FFI body to WIRE_FACADE")
    return manifest, ownership


def _prepare_static_rewrite(root: Path, parent_run_id: str) -> None:
    manifest, _ = _rewrite_manifest(root)
    path = _rewrite_state_path(root)
    previous: dict[str, Any] | None = None
    if path.is_file():
        previous = _json(path)
        if previous.get("parent_run_id") == parent_run_id:
            return
        if previous.get("manifest_sha256") != _sha256(
            root / "logs" / "trace" / "scaffold-manifest.json"
        ):
            raise WorkflowError("scaffold ownership manifest changed between REWRITE parent runs")
    generated = manifest.get("files")
    if not isinstance(generated, dict):
        raise WorkflowError("scaffold manifest generated-file hashes are malformed")
    rust_project = str(_load_state(root).get("rust_project_path") or "flashDB_rust")
    if previous is None:
        changed_scaffold = [
            relative
            for relative, evidence in generated.items()
            if not isinstance(relative, str)
            or not isinstance(evidence, dict)
            or not isinstance(evidence.get("sha256"), str)
            or not (root / rust_project / relative).is_file()
            or _sha256(root / rust_project / relative) != evidence.get("sha256")
        ]
        if changed_scaffold:
            raise WorkflowError(
                "REWRITE must start from the controller-verified scaffold: "
                + ", ".join(str(item) for item in changed_scaffold[:20])
            )
    document = {
        "schema_version": 1,
        "parent_run_id": parent_run_id,
        "manifest_sha256": _sha256(root / "logs" / "trace" / "scaffold-manifest.json"),
        "scaffold_digest": _snapshot_digest({
            f"flashDB_rust/{key}": value.get("sha256")
            for key, value in manifest.get("files", {}).items()
            if isinstance(key, str) and isinstance(value, dict) and isinstance(value.get("sha256"), str)
        }),
        "phase": "CORE",
        "core_revision": 0,
        "facade_revision": 0,
        "facade_based_on_core_revision": None,
        "active_worker": None,
        "failed_checks": {"IMPLEMENT_CORE": 0, "WIRE_FACADE": 0},
        "attempts": {"IMPLEMENT_CORE": 0, "WIRE_FACADE": 0},
        "latest_receipts": {"IMPLEMENT_CORE": None, "WIRE_FACADE": None},
        "invalidated_receipts": [],
        "status": "running",
    }
    _atomic_json(path, document)


def _active_rewrite_parent(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    state = _load_state(root)
    active = state.get("active_stage_run")
    if not isinstance(active, dict) or active.get("stage") != "REWRITE_CORE_MODULES":
        raise WorkflowError("static rewrite worker requires an active REWRITE_CORE_MODULES parent run")
    run_path = root / str(active.get("run_file") or "")
    if not run_path.is_file() or _sha256(run_path) != active.get("run_sha256"):
        raise WorkflowError("active REWRITE parent run record was modified")
    return state, active


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
    # REWRITE's parent run is controller-only.  Giving it the generic broad
    # packet would invite a weak agent to bypass the two exact-owner workers.
    packet = (
        None
        if stage == "REWRITE_CORE_MODULES"
        else _invoke_task_packet(root, stage, str(state.get("next_action") or requested_action))
    )
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
    if stage == "REWRITE_CORE_MODULES":
        _prepare_static_rewrite(root, run_id)
    _atomic_json(_state_path(root), state)
    print("WORKFLOWCTL: STAGE_BEGUN")
    print(f"stage={stage}")
    print(f"run_id={run_id}")
    print(f"nonce={nonce}")
    if packet:
        print(f"task_packet={packet}")
    if stage == "REWRITE_CORE_MODULES":
        print("next_command=python3 work/tools/workflowctl.py --root . next-rewrite-worker")
    return 0


def _diff(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    before_keys = set(before)
    after_keys = set(after)
    return {
        "created": sorted(after_keys - before_keys),
        "deleted": sorted(before_keys - after_keys),
        "modified": sorted(path for path in before_keys & after_keys if before[path] != after[path]),
    }


def cmd_next_rewrite_worker(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    _, parent = _active_rewrite_parent(root)
    rewrite = _load_rewrite_state(root)
    if rewrite.get("parent_run_id") != parent.get("run_id"):
        raise WorkflowError("rewrite state belongs to a different parent run")
    if rewrite.get("active_worker"):
        raise WorkflowError("a static rewrite worker is already active")
    phase = str(rewrite.get("phase") or "")
    role = REWRITE_ROLES.get(phase)
    if role is None:
        raise WorkflowError(f"no rewrite worker is available in phase {phase}")
    attempts = rewrite.get("attempts")
    if not isinstance(attempts, dict):
        raise WorkflowError("rewrite state attempts are malformed")
    attempt = int(attempts.get(role, 0) or 0) + 1
    max_retries = int(REWRITE_SETTINGS.get("max_worker_retries", 3))
    if attempt > max_retries:
        raise WorkflowError(f"rewrite worker retry budget exhausted for {role}")
    packet = _invoke_task_packet(root, "REWRITE_CORE_MODULES", rewrite_role=role)
    if packet is None:
        raise WorkflowError("static rewrite packet generation is unavailable")
    packet_path = root / packet
    packet_doc = _json(packet_path)
    allowed = packet_doc.get("allowed_modification_paths")
    if not isinstance(allowed, list) or not allowed or not all(isinstance(item, str) for item in allowed):
        raise WorkflowError("static rewrite packet has no exact owner paths")
    nonce = secrets.token_hex(16)
    worker_run_id = f"{_now_ns()}-{role.lower().replace('_', '-')}"
    completion = packet_doc.get("completion_contract")
    if not isinstance(completion, dict) or not isinstance(completion.get("command"), str):
        raise WorkflowError("static rewrite packet has no completion command")
    completion["command"] = (
        completion["command"]
        .replace("<WORKER_RUN_ID>", worker_run_id)
        .replace("<WORKER_NONCE>", nonce)
    )

    retry_context: list[dict[str, Any]] = []
    latest = rewrite.get("latest_receipts")
    candidate_roles = [role]
    if role == "IMPLEMENT_CORE":
        candidate_roles.append("WIRE_FACADE")
    for prior_role in candidate_roles:
        receipt_rel = latest.get(prior_role) if isinstance(latest, dict) else None
        if not isinstance(receipt_rel, str) or not (root / receipt_rel).is_file():
            continue
        receipt = _json(root / receipt_rel)
        if receipt.get("status") not in {"retry_required", "blocked"}:
            continue
        context: dict[str, Any] = {
            "role": prior_role,
            "status": receipt.get("status"),
            "reason": receipt.get("reason"),
            "receipt": receipt_rel,
        }
        check_rel = receipt.get("check_receipt")
        if isinstance(check_rel, str) and (root / check_rel).is_file():
            check = _json(root / check_rel)
            phases = check.get("phases")
            context["failed_checks"] = [
                {
                    "phase": item.get("phase"),
                    "status": item.get("status"),
                    "exit_code": item.get("exit_code"),
                    "log_path": item.get("log_path"),
                    "tail": str(item.get("tail") or "")[
                        -int(REWRITE_SETTINGS.get("max_command_output_bytes", 8192)):
                    ],
                }
                for item in phases
                if isinstance(item, dict) and item.get("status") != "pass"
            ] if isinstance(phases, list) else []
        retry_context.append(context)
    packet_doc["retry_context"] = retry_context
    _atomic_json(packet_path, packet_doc)
    record = {
        "schema_version": 1,
        "worker_run_id": worker_run_id,
        "parent_run_id": parent.get("run_id"),
        "role": role,
        "attempt": attempt,
        "core_revision_before": int(rewrite.get("core_revision", 0) or 0),
        "facade_revision_before": int(rewrite.get("facade_revision", 0) or 0),
        "packet": packet,
        "packet_sha256": _sha256(packet_path),
        "allowed_paths": allowed,
        "baseline": _snapshot(root, ["**"]),
        "started_at_ns": _now_ns(),
    }
    run_path = root / "logs" / "trace" / "rewrite-worker-runs" / role.lower() / f"{worker_run_id}.json"
    _atomic_json(run_path, record)
    attempts[role] = attempt
    rewrite["attempts"] = attempts
    rewrite["active_worker"] = {
        "worker_run_id": worker_run_id,
        "nonce": nonce,
        "role": role,
        "run_file": run_path.relative_to(root).as_posix(),
        "run_sha256": _sha256(run_path),
    }
    _atomic_json(_rewrite_state_path(root), rewrite)
    print("WORKFLOWCTL: REWRITE_WORKER_BEGUN")
    print(f"role={role}")
    print(f"worker_run_id={worker_run_id}")
    print(f"nonce={nonce}")
    print(f"task_packet={packet}")
    return 0


def _append_rewrite_batch(
    root: Path,
    *,
    role: str,
    revision: int,
    changed: list[str],
    receipt_path: str,
) -> None:
    design = _json(root / "logs" / "trace" / "rust_api_design.json")
    if role == "IMPLEMENT_CORE":
        raw = design.get("implementation_requirements", [])
        obligations = [
            item.get("id") for item in raw
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        ] if isinstance(raw, list) else []
    else:
        manifest = _json(root / "logs" / "trace" / "scaffold-manifest.json")
        functions = manifest.get("ffi_functions", {})
        obligations = [f"ffi:{item}" for item in sorted(functions)] if isinstance(functions, dict) else []
    _append_jsonl(root / "logs" / "trace" / "core_rewrite_batches.jsonl", {
        "schema_version": 2,
        "stage": "REWRITE_CORE_MODULES",
        "worker_role": role,
        "revision": revision,
        "status": "complete",
        "changed_files": changed,
        "obligations": obligations or [role.lower()],
        "receipt": receipt_path,
    })


def _write_rewrite_stage_log(root: Path, rewrite: dict[str, Any]) -> None:
    path = root / "logs" / "trace" / "06-rewrite-core-modules.md"
    path.write_text(
        "# REWRITE_CORE_MODULES\n\n"
        "- 静态职责：IMPLEMENT_CORE → WIRE_FACADE。\n"
        f"- core revision：{rewrite.get('core_revision', 0)}\n"
        f"- facade revision：{rewrite.get('facade_revision', 0)}\n"
        "- 修复方式：原地向前修复，不恢复旧源码。\n"
        "- 验证证据：logs/trace/rewrite-check/ 与 rewrite-worker-receipts/。\n",
        encoding="utf-8",
    )


def cmd_finish_rewrite_worker(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    _, parent = _active_rewrite_parent(root)
    rewrite = _load_rewrite_state(root)
    active = rewrite.get("active_worker")
    if not isinstance(active, dict):
        raise WorkflowError("no active static rewrite worker")
    if active.get("worker_run_id") != args.worker_run_id or active.get("nonce") != args.nonce:
        raise WorkflowError("worker_run_id/nonce do not match active rewrite worker")
    run_path = root / str(active.get("run_file") or "")
    if not run_path.is_file() or _sha256(run_path) != active.get("run_sha256"):
        raise WorkflowError("rewrite worker run record was modified")
    run = _json(run_path)
    role = str(run.get("role") or "")
    if run.get("parent_run_id") != parent.get("run_id"):
        raise WorkflowError("rewrite worker belongs to another parent run")
    packet_path = root / str(run.get("packet") or "")
    if not packet_path.is_file() or _sha256(packet_path) != run.get("packet_sha256"):
        raise WorkflowError("rewrite worker packet was modified")

    before = run.get("baseline") if isinstance(run.get("baseline"), dict) else {}
    after = _snapshot(root, ["**"])
    business_before = {key: value for key, value in before.items() if not _matches(key, CONTROLLER_OWNED_PATTERNS)}
    business_after = {key: value for key, value in after.items() if not _matches(key, CONTROLLER_OWNED_PATTERNS)}
    changes = _diff(business_before, business_after)
    changed = sorted(changes["created"] + changes["modified"] + changes["deleted"])
    allowed = [item for item in run.get("allowed_paths", []) if isinstance(item, str)]
    unexpected = [item for item in changed if not _matches(item, allowed)]
    if unexpected:
        raise WorkflowError("rewrite worker modified another owner/frozen path: " + ", ".join(unexpected))
    if any((root / item).is_symlink() for item in changed):
        raise WorkflowError("rewrite worker created or modified a symlink")
    parent_run_path = root / str(parent.get("run_file") or "")
    parent_run = _json(parent_run_path)
    parent_baseline = (
        parent_run.get("baseline") if isinstance(parent_run.get("baseline"), dict) else {}
    )
    owner_before = {
        key: value for key, value in parent_baseline.items()
        if isinstance(key, str) and isinstance(value, str) and _matches(key, allowed)
    }
    owner_after = {
        key: value for key, value in after.items()
        if _matches(key, allowed)
    }
    owner_changes = _diff(owner_before, owner_after)
    cumulative_changed = sorted(
        owner_changes["created"] + owner_changes["modified"] + owner_changes["deleted"]
    )

    attempt = int(run.get("attempt", 0) or 0)
    status = args.status
    reason = str(getattr(args, "reason", None) or "").strip()
    if len(reason.encode("utf-8")) > 1000:
        raise WorkflowError("rewrite worker reason exceeds 1000 bytes")
    if status == "missing_core_capability" and not reason:
        raise WorkflowError("missing_core_capability requires a brief --reason")
    check_receipt: str | None = None
    next_phase = str(rewrite.get("phase") or "")
    receipt_status = status
    if status == "complete":
        check_tool = root / "work" / "tools" / "rewrite_check.py"
        completed = subprocess.run(
            [
                sys.executable,
                str(check_tool),
                "--root",
                str(root),
                "--project",
                str(_load_state(root).get("rust_project_path") or "flashDB_rust"),
                "--role",
                role,
                "--revision",
                str(attempt),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        check_path = root / "logs" / "trace" / "rewrite-check" / role.lower() / str(attempt) / "result.json"
        check_receipt = check_path.relative_to(root).as_posix() if check_path.is_file() else None
        check_result = _json(check_path) if check_path.is_file() else {}
        check_ok = (
            completed.returncode == 0
            and check_result.get("status") == "pass"
            and check_result.get("role") == role
            and check_result.get("revision") == attempt
        )
        if not check_ok:
            failed = rewrite.get("failed_checks")
            if not isinstance(failed, dict):
                failed = {}
            failed[role] = int(failed.get(role, 0) or 0) + 1
            rewrite["failed_checks"] = failed
            maximum = int(REWRITE_SETTINGS.get("max_worker_failed_checks", 2))
            receipt_status = "blocked" if failed[role] >= maximum else "retry_required"
            if receipt_status == "blocked":
                rewrite["phase"] = "BLOCKED"
                rewrite["status"] = "blocked"
            next_phase = str(rewrite.get("phase") or "")
        elif role == "IMPLEMENT_CORE":
            previous_facade = rewrite.get("latest_receipts", {}).get("WIRE_FACADE")
            if previous_facade:
                rewrite.setdefault("invalidated_receipts", []).append(previous_facade)
            rewrite["core_revision"] = int(rewrite.get("core_revision", 0) or 0) + 1
            rewrite["facade_based_on_core_revision"] = None
            rewrite["phase"] = "FACADE"
            next_phase = "FACADE"
        elif role == "WIRE_FACADE":
            rewrite["facade_revision"] = int(rewrite.get("facade_revision", 0) or 0) + 1
            rewrite["facade_based_on_core_revision"] = int(rewrite.get("core_revision", 0) or 0)
            rewrite["phase"] = "READY"
            rewrite["status"] = "ready_for_finish"
            next_phase = "READY"
    elif status == "missing_core_capability":
        if role != "WIRE_FACADE":
            raise WorkflowError("missing_core_capability is only valid for WIRE_FACADE")
        previous_facade = rewrite.get("latest_receipts", {}).get("WIRE_FACADE")
        if previous_facade:
            rewrite.setdefault("invalidated_receipts", []).append(previous_facade)
        rewrite["facade_based_on_core_revision"] = None
        rewrite["phase"] = "CORE"
        next_phase = "CORE"
        receipt_status = "retry_required"
    elif status == "blocked":
        rewrite["phase"] = "BLOCKED"
        rewrite["status"] = "blocked"
        next_phase = "BLOCKED"

    revision = (
        int(rewrite.get("core_revision", 0) or 0)
        if role == "IMPLEMENT_CORE"
        else int(rewrite.get("facade_revision", 0) or 0)
    )
    receipt_path = root / "logs" / "trace" / "rewrite-worker-receipts" / role.lower() / f"{args.worker_run_id}.json"
    receipt = {
        "schema_version": 1,
        "worker_run_id": args.worker_run_id,
        "parent_run_id": parent.get("run_id"),
        "role": role,
        "attempt": attempt,
        "revision": revision,
        "status": receipt_status,
        "based_on_scaffold_digest": rewrite.get("scaffold_digest"),
        "based_on_core_revision": run.get("core_revision_before") if role == "WIRE_FACADE" else None,
        "attempt_changed_files": changed,
        "changed_files": cumulative_changed,
        "changed_file_hashes": {
            item: _sha256(root / item) for item in cumulative_changed if (root / item).is_file()
        },
        "check_receipt": check_receipt,
        "reason": reason or None,
        "finished_at_ns": _now_ns(),
        "next_phase": next_phase,
        "supersedes": rewrite.get("latest_receipts", {}).get(role),
    }
    _atomic_json(receipt_path, receipt)
    latest = rewrite.get("latest_receipts")
    if not isinstance(latest, dict):
        latest = {}
    latest[role] = receipt_path.relative_to(root).as_posix()
    rewrite["latest_receipts"] = latest
    rewrite["active_worker"] = None
    _atomic_json(_rewrite_state_path(root), rewrite)
    if receipt_status == "complete":
        _append_rewrite_batch(
            root,
            role=role,
            revision=revision,
            changed=cumulative_changed,
            receipt_path=receipt_path.relative_to(root).as_posix(),
        )
        if next_phase == "READY":
            _write_rewrite_stage_log(root, rewrite)
    print("WORKFLOWCTL: REWRITE_WORKER_FINISHED")
    print(f"role={role}")
    print(f"status={receipt_status}")
    print(f"receipt={receipt_path.relative_to(root).as_posix()}")
    if next_phase in REWRITE_ROLES:
        print("next_command=python3 work/tools/workflowctl.py --root . next-rewrite-worker")
    elif next_phase == "READY":
        print(
            "next_command=python3 work/tools/workflowctl.py --root . finish "
            f"--run-id {parent.get('run_id')} --nonce {parent.get('nonce')}"
        )
    return 1 if receipt_status == "blocked" else 0


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


def _write_stage_summary(root: Path, stage: str) -> None:
    """Write deterministic human-readable summaries from machine artifacts."""
    trace = root / "logs" / "trace"
    if stage == "READ_C_PROJECT":
        manifest = _json(trace / "input_manifest.json")
        counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
        text = (
            "# READ_C_PROJECT 阶段日志\n\n"
            "- 生成者：workflowctl（根据 input_manifest.json 自动汇总）\n"
            f"- input_digest：`{manifest.get('input_digest')}`\n"
            f"- 核心源码：{counts.get('core_sources', 0)}\n"
            f"- 头文件：{counts.get('headers', 0)}\n"
            f"- 测试源码：{counts.get('test_sources', 0)}\n"
            f"- 构建文件：{counts.get('build_files', 0)}\n"
            "- 输入模式：只读；完整性由输入基线和 stage receipt 校验。\n"
        )
        (trace / "02-read-c-project.md").write_text(text, encoding="utf-8")
    elif stage == "BUILD_C_MODEL":
        api = _json(trace / "c_api_model.json")
        tests = _json(trace / "c_test_model.json")
        scenarios = tests.get("standard_scenarios") if isinstance(tests.get("standard_scenarios"), list) else []
        invoke_only = sorted(
            str(item.get("id") or "<unknown>")
            for item in scenarios if isinstance(item, dict)
            and isinstance(item.get("scenario_ir"), list)
            and len(item["scenario_ir"]) == 1
            and isinstance(item["scenario_ir"][0], dict)
            and item["scenario_ir"][0].get("kind") == "invoke_test"
        )
        unresolved = tests.get("unresolved_registered_tests")
        unresolved_count = len(unresolved) if isinstance(unresolved, list) else -1
        text = (
            "# BUILD_C_MODEL 阶段日志\n\n"
            "- 生成者：workflowctl（根据 C 模型自动汇总）\n"
            f"- input_digest：`{tests.get('input_digest')}`\n"
            f"- 公共函数签名：{len(api.get('function_signatures', {}))}\n"
            f"- ABI 布局：{len(api.get('abi_layouts', []))}\n"
            f"- 唯一注册测试：{len(tests.get('registered_tests', []))}\n"
            f"- 注册调用：{len(tests.get('registered_test_invocations', []))}\n"
            f"- 标准场景：{len(scenarios)}\n"
            f"- unresolved_registered_tests：{unresolved_count}\n"
            f"- invoke-only 场景：{', '.join(invoke_only) if invoke_only else '无'}\n"
        )
        (trace / "03-build-c-model.md").write_text(text, encoding="utf-8")
    elif stage == "DESIGN_RUST_API":
        design = _json(trace / "rust_api_design.json")
        facade = design.get("c_abi_facade") if isinstance(design.get("c_abi_facade"), dict) else {}
        type_map = facade.get("c_type_map") if isinstance(facade.get("c_type_map"), dict) else {}
        text = (
            "# DESIGN_RUST_API 阶段日志\n\n"
            "- 生成者：workflowctl（根据 rust_api_design.json 自动汇总）\n"
            f"- input_digest：`{design.get('input_digest')}`\n"
            f"- crate：`{design.get('crate_name')}`\n"
            f"- 模块：{len(design.get('modules', []))}\n"
            f"- C ABI facade 函数：{len(facade.get('functions', []))}\n"
            f"- C ABI facade 结构体：{len(facade.get('structs', []))}\n"
            f"- unresolved C 类型：{len(type_map.get('unresolved', []))}\n"
            f"- implementation requirements：{len(design.get('implementation_requirements', []))}\n"
            "- Rust 源码：本阶段不生成。\n"
        )
        (trace / "04-design-rust-api.md").write_text(text, encoding="utf-8")


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
    if stage == "REWRITE_CORE_MODULES":
        rewrite = _load_rewrite_state(root)
        if rewrite.get("parent_run_id") != args.run_id or rewrite.get("phase") != "READY":
            raise WorkflowError("REWRITE_CORE_MODULES cannot finish before static CORE/FACADE workers pass")
        if rewrite.get("active_worker"):
            raise WorkflowError("REWRITE_CORE_MODULES cannot finish while a static worker is active")
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
        if stage in {"BUILD_C_MODEL", "DESIGN_RUST_API"}:
            manifest_path = root / "logs" / "trace" / "input_manifest.json"
            if not manifest_path.is_file() or manifest_path.is_symlink():
                raise WorkflowError("controller task packet requires input_manifest.json")
            manifest_digest = _json(manifest_path).get("input_digest")
            if not isinstance(manifest_digest, str) or not manifest_digest:
                raise WorkflowError("input_manifest.json has no usable input_digest")
            if packet_doc.get("input_digest") != manifest_digest:
                raise WorkflowError("task packet input_digest does not match input_manifest.json")
            source_artifacts = packet_doc.get("source_artifacts")
            manifest_artifact = source_artifacts.get("input_manifest") if isinstance(source_artifacts, dict) else None
            if (
                not isinstance(manifest_artifact, dict)
                or manifest_artifact.get("path") != "logs/trace/input_manifest.json"
                or manifest_artifact.get("sha256") != _sha256(manifest_path)
            ):
                raise WorkflowError("task packet input manifest identity is missing or stale")
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
    if stage == "REWRITE_CORE_MODULES":
        rewrite_outputs = [
            "logs/trace/rewrite-state.json",
            "logs/trace/rewrite-worker-runs/**",
            "logs/trace/rewrite-worker-receipts/**",
            "logs/trace/rewrite-check/**",
            "logs/trace/core_rewrite_batches.jsonl",
            "logs/trace/implementation-audit.json",
            "logs/trace/06-rewrite-core-modules.md",
            "logs/trace/task-packets/rewrite_core_modules-*.json",
        ]
        controller_changes = [path for path in controller_changes if not _matches(path, rewrite_outputs)]
    if controller_changes:
        raise WorkflowError("stage modified controller-owned metadata: " + ", ".join(controller_changes))

    required = [item for item in run.get("required_outputs", []) if isinstance(item, str)]
    automatic_log = {
        "READ_C_PROJECT": "logs/trace/02-read-c-project.md",
        "BUILD_C_MODEL": "logs/trace/03-build-c-model.md",
        "DESIGN_RUST_API": "logs/trace/04-design-rust-api.md",
    }.get(stage)
    prerequisites = [item for item in required if item != automatic_log]
    _, prerequisite_missing = _artifact_hashes(root, prerequisites)
    if prerequisite_missing:
        raise WorkflowError("stage is missing required outputs: " + ", ".join(prerequisite_missing))
    if automatic_log is not None:
        _write_stage_summary(root, stage)
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
    rewrite_ready_for_recheck = (
        stage == "REWRITE_CORE_MODULES"
        and rewrite.get("phase") == "READY"
        and rewrite.get("status") == "ready_for_finish"
        and not rewrite.get("active_worker")
    ) if stage == "REWRITE_CORE_MODULES" else False
    next_action = (
        "RECHECK_REWRITE_CORE_MODULES"
        if (
            not gate_ok
            and rewrite_ready_for_recheck
            and "stage receipt must reference a bounded task packet" in completed_gate.stdout
        )
        else _next_after(stage, state, root, gate_ok)
    )
    rewrite_retry_origin: dict[str, Any] | None = None
    if (
        stage == "REWRITE_CORE_MODULES"
        and not gate_ok
        and next_action == "REPAIR_REWRITE_CORE_MODULES"
    ):
        # Retain the original scaffold-era baseline for the repair run. Agents
        # must not reconstruct it with git, /tmp backups, or a second scaffold
        # generation.
        # Keep the first scaffold-era transaction as the origin across every
        # repair.  Replacing it with the latest failed repair run makes the
        # already-implemented owner files appear unchanged and invalidates
        # their cumulative worker receipts.
        origin = run.get("baseline_origin")
        rewrite_retry_origin = (
            dict(origin)
            if isinstance(origin, dict)
            else {
                "run_file": run_file.relative_to(root).as_posix(),
                "run_sha256": _sha256(run_file),
            }
        )
    receipt["status"] = "pass" if gate_ok else "failed"
    receipt["gate_exit_code"] = completed_gate.returncode
    receipt["gate_output_tail"] = "\n".join(completed_gate.stdout.splitlines()[-40:])
    receipt["next_action"] = next_action
    _atomic_json(receipt_path, receipt)
    _atomic_json(immutable_receipt_path, receipt)

    state = _load_state(root)
    if rewrite_retry_origin is not None:
        state["retry_baseline_run"] = rewrite_retry_origin
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


def cmd_recheck_rewrite(args: argparse.Namespace) -> int:
    """Re-run a controller-only REWRITE gate without dispatching workers."""
    root = Path(args.root).resolve()
    state = _load_state(root)
    if state.get("active_stage_run"):
        raise WorkflowError("RECHECK_REWRITE_CORE_MODULES requires no active stage run")
    if state.get("next_action") != "RECHECK_REWRITE_CORE_MODULES":
        raise WorkflowError("RECHECK_REWRITE_CORE_MODULES is not the current controller action")

    receipt_path = root / "logs" / "trace" / "stage-receipts" / "REWRITE_CORE_MODULES.json"
    receipt = _json(receipt_path)
    if receipt.get("stage") != "REWRITE_CORE_MODULES" or receipt.get("status") != "failed":
        raise WorkflowError("RECHECK_REWRITE_CORE_MODULES requires the latest failed REWRITE receipt")
    rewrite = _load_rewrite_state(root)
    if (
        rewrite.get("phase") != "READY"
        or rewrite.get("status") != "ready_for_finish"
        or rewrite.get("active_worker")
        or rewrite.get("parent_run_id") != receipt.get("run_id")
    ):
        raise WorkflowError("RECHECK_REWRITE_CORE_MODULES requires completed workers from the failed parent")

    # The canonical receipt is the active gate candidate.  The immutable
    # per-run receipt remains failed, preserving the original audit trail.
    receipt["status"] = "ready_for_gate"
    receipt["recheck_count"] = int(receipt.get("recheck_count", 0) or 0) + 1
    _atomic_json(receipt_path, receipt)
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "work" / "tools" / "gate.py"),
            "--stage",
            "REWRITE_CORE_MODULES",
            "--root",
            str(root),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    gate_ok = completed.returncode == 0
    next_action = _next_after("REWRITE_CORE_MODULES", state, root, gate_ok)
    receipt["status"] = "pass" if gate_ok else "failed"
    receipt["gate_exit_code"] = completed.returncode
    receipt["gate_output_tail"] = "\n".join(completed.stdout.splitlines()[-40:])
    receipt["next_action"] = next_action
    _atomic_json(receipt_path, receipt)

    record = {
        "schema_version": 1,
        "stage": "REWRITE_CORE_MODULES",
        "receipt": receipt_path.relative_to(root).as_posix(),
        "recheck_count": receipt["recheck_count"],
        "status": "pass" if gate_ok else "failed",
        "gate_exit_code": completed.returncode,
        "gate_output_tail": receipt["gate_output_tail"],
    }
    record_path = (
        root / "logs" / "trace" / "rewrite-gate-rechecks"
        / f"{_now_ns()}-recheck.json"
    )
    _atomic_json(record_path, record)
    state["last_gate"] = {
        "stage": "REWRITE_CORE_MODULES",
        "status": "pass" if gate_ok else "fail",
        "receipt": receipt_path.relative_to(root).as_posix(),
    }
    state["next_action"] = next_action
    _atomic_json(_state_path(root), state)
    print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    print("WORKFLOWCTL: REWRITE_GATE_RECHECKED")
    print(f"record={record_path.relative_to(root).as_posix()}")
    print(f"next_action={next_action}")
    return completed.returncode


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
    if active.get("stage") == "REWRITE_CORE_MODULES" and _rewrite_state_path(root).is_file():
        rewrite = _load_rewrite_state(root)
        if rewrite.get("active_worker"):
            raise WorkflowError("finish the active static rewrite worker before aborting its parent stage")
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
    if active.get("stage") == "REWRITE_CORE_MODULES":
        controller_changes = [
            path for path in controller_changes
            if not _matches(path, [
                "logs/trace/rewrite-state.json",
                "logs/trace/rewrite-worker-runs/**",
                "logs/trace/rewrite-worker-receipts/**",
                "logs/trace/rewrite-check/**",
                "logs/trace/core_rewrite_batches.jsonl",
                "logs/trace/implementation-audit.json",
                "logs/trace/06-rewrite-core-modules.md",
                "logs/trace/task-packets/rewrite_core_modules-*.json",
            ])
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
            if active.get("stage") == "REWRITE_CORE_MODULES" and _rewrite_state_path(root).is_file():
                rewrite = _load_rewrite_state(root)
                print(f"rewrite_phase={rewrite.get('phase')}")
                worker = rewrite.get("active_worker")
                if isinstance(worker, dict):
                    print(f"rewrite_worker={worker.get('role')}")
                    print(
                        "next_command=python3 work/tools/workflowctl.py --root . finish-rewrite-worker "
                        f"--worker-run-id {worker.get('worker_run_id')} --nonce {worker.get('nonce')} "
                        "--status complete"
                    )
                elif rewrite.get("phase") in REWRITE_ROLES:
                    print("next_command=python3 work/tools/workflowctl.py --root . next-rewrite-worker")
                elif rewrite.get("phase") == "READY" and isinstance(run_id, str) and isinstance(nonce, str):
                    print(
                        "next_command=python3 work/tools/workflowctl.py --root . finish "
                        f"--run-id {run_id} --nonce {nonce}"
                    )
            elif isinstance(run_id, str) and isinstance(nonce, str):
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

    rewrite_next = subparsers.add_parser(
        "next-rewrite-worker",
        help="Begin the next fixed static REWRITE worker from scaffold ownership.",
    )
    rewrite_next.set_defaults(handler=cmd_next_rewrite_worker)

    rewrite_finish = subparsers.add_parser(
        "finish-rewrite-worker",
        help="Validate and commit one static REWRITE worker attempt.",
    )
    rewrite_finish.add_argument("--worker-run-id", required=True)
    rewrite_finish.add_argument("--nonce", required=True)
    rewrite_finish.add_argument(
        "--status",
        choices=["complete", "missing_core_capability", "blocked"],
        required=True,
    )
    rewrite_finish.add_argument(
        "--reason",
        help="Brief bounded handoff reason, required for missing_core_capability.",
    )
    rewrite_finish.set_defaults(handler=cmd_finish_rewrite_worker)

    rewrite_recheck = subparsers.add_parser(
        "recheck-rewrite",
        help="Re-run a failed controller-only REWRITE gate without new workers.",
    )
    rewrite_recheck.set_defaults(handler=cmd_recheck_rewrite)

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
