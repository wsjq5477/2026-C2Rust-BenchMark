#!/usr/bin/env python3
"""Create and restore immutable, Git-independent submission snapshots."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
SNAPSHOT_ROOT = Path("logs/trace/submission-snapshots")
TRACKED_FILES = (
    Path("flashDB_rust/Cargo.toml"),
    Path("flashDB_rust/Cargo.lock"),
    Path("flashDB_rust/build.rs"),
    Path("logs/trace/rust_test_mapping.json"),
)
TRACKED_DIRS = (Path("flashDB_rust/src"), Path("flashDB_rust/tests"))
EVIDENCE_FILES = (
    Path("logs/trace/implementation-audit.json"),
    Path("logs/trace/validation-matrix.json"),
    Path("logs/trace/c-cross/failure-summary.json"),
    Path("logs/trace/cargo-results.json"),
    Path("logs/trace/test-placeholder-check.json"),
    Path("logs/trace/test-semantic-review.json"),
    Path("logs/trace/test-consistency.json"),
    Path("logs/trace/unsafe-ratio.json"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _safe_relative(path: Path) -> Path:
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe snapshot path: {path}")
    allowed = (
        path == Path("flashDB_rust/Cargo.toml")
        or path == Path("flashDB_rust/Cargo.lock")
        or path == Path("flashDB_rust/build.rs")
        or path == Path("logs/trace/rust_test_mapping.json")
        or path.parts[:2] in (("flashDB_rust", "src"), ("flashDB_rust", "tests"))
    )
    if not allowed:
        raise ValueError(f"snapshot path is outside the submission allowlist: {path}")
    return path


def submission_files(root: Path) -> list[Path]:
    root = root.resolve()
    result: set[Path] = set()
    for relative in TRACKED_FILES:
        candidate = root / relative
        if candidate.is_symlink():
            raise ValueError(f"submission file must not be a symlink: {relative}")
        if candidate.is_file():
            result.add(relative)
    for directory in TRACKED_DIRS:
        base = root / directory
        if base.is_symlink():
            raise ValueError(f"submission directory must not be a symlink: {directory}")
        if not base.is_dir():
            continue
        for candidate in base.rglob("*"):
            relative = candidate.relative_to(root)
            if candidate.is_symlink():
                raise ValueError(f"submission tree must not contain symlinks: {relative}")
            if candidate.is_file():
                result.add(relative)
    return sorted(result)


def current_manifest(root: Path) -> dict[str, str]:
    return {path.as_posix(): _sha256(root / path) for path in submission_files(root)}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _scenario_ids_with_status(report: dict[str, Any], status: str) -> set[str]:
    rows = report.get("scenarios")
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("scenario_id"))
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("scenario_id"), str) and row.get("status") == status
    }


def _cargo_pass_ids(mapping: dict[str, Any], cargo: dict[str, Any]) -> set[str]:
    execution = cargo.get("test_execution") if isinstance(cargo.get("test_execution"), dict) else {}
    executed = set(execution.get("executed_tests") or [])
    failed = set(execution.get("failed_expected_tests") or [])
    ignored = set(execution.get("ignored_expected_tests") or [])
    missing = set(execution.get("missing_expected_tests") or [])
    result: set[str] = set()
    rows = mapping.get("scenarios") if isinstance(mapping.get("scenarios"), list) else []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not isinstance(row.get("rust_test"), str):
            continue
        name = row["rust_test"]
        matched = any(item == name or str(item).endswith(f"::{name}") for item in executed)
        if matched and name not in failed and name not in ignored and name not in missing:
            result.add(row["id"])
    return result


def _c_cross_pass_ids(matrix: dict[str, Any]) -> set[str]:
    rows = matrix.get("scenarios") if isinstance(matrix.get("scenarios"), list) else []
    return {
        str(row.get("scenario_id"))
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("scenario_id"), str)
        and row.get("rust_impl_c_test") == "pass"
    }


def compute_score(root: Path) -> dict[str, Any]:
    trace = root / "logs" / "trace"
    cargo = _load_json(trace / "cargo-results.json")
    consistency = _load_json(trace / "test-consistency.json")
    mapping = _load_json(trace / "rust_test_mapping.json")
    matrix = _load_json(trace / "validation-matrix.json")
    layout = _load_json(trace / "c-cross" / "scaffold-layout-check.json")
    build_success = cargo.get("build_status") == "pass" or (
        layout.get("status") == "pass" and layout.get("build_status") == "pass"
    )
    consistency_pass = _scenario_ids_with_status(consistency, "pass")
    cargo_pass = _cargo_pass_ids(mapping, cargo)
    judge_pass = consistency_pass & cargo_pass
    c_cross_pass = _c_cross_pass_ids(matrix)
    expected = {
        str(row.get("id"))
        for row in (mapping.get("scenarios") if isinstance(mapping.get("scenarios"), list) else [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    not_run = expected - cargo_pass
    failed = expected - judge_pass
    vector = [
        1 if build_success else 0,
        len(judge_pass),
        len(consistency_pass),
        len(cargo_pass),
        len(c_cross_pass),
        -len(not_run),
        -len(failed),
    ]
    return {
        "build_success": build_success,
        "judge_case_passed": sorted(judge_pass),
        "consistency_passed": sorted(consistency_pass),
        "cargo_executed_passed": sorted(cargo_pass),
        "c_cross_passed": sorted(c_cross_pass),
        "not_run": sorted(not_run),
        "failed": sorted(failed),
        "score_vector": vector,
    }


def _best(root: Path) -> dict[str, Any]:
    return _load_json(root / SNAPSHOT_ROOT / "best.json")


def _load_local_tool(filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location("snapshot_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _is_validated_current(root: Path, score: dict[str, Any]) -> bool:
    trace = root / "logs" / "trace"
    consistency = _load_json(trace / "test-consistency.json")
    cargo = _load_json(trace / "cargo-results.json")
    mapping = _load_json(trace / "rust_test_mapping.json")
    if not bool(
        score.get("build_success")
        and isinstance(mapping.get("scenarios"), list)
        and mapping.get("scenarios")
        and isinstance(consistency.get("scenarios"), list)
        and consistency.get("total_scenarios") == len(mapping["scenarios"])
        and isinstance(cargo.get("test_execution"), dict)
        and cargo["test_execution"].get("expected_count") == len(mapping["scenarios"])
    ):
        return False
    current = current_manifest(root)
    convergence = cargo.get("repair_convergence") if isinstance(cargo.get("repair_convergence"), dict) else {}
    cargo_manifest = convergence.get("source_manifest") if isinstance(convergence.get("source_manifest"), dict) else {}
    if not cargo_manifest or any(current.get(path) != digest for path, digest in cargo_manifest.items()):
        return False
    try:
        consistency_tool = _load_local_tool("test_consistency_check.py")
        placeholder_tool = _load_local_tool("placeholder_check.py")
        expected_consistency = consistency_tool.build_input_fingerprint(root)
        expected_placeholder = placeholder_tool.analyze_placeholders(
            root,
            root / "flashDB_rust" / "tests",
            trace / "rust_test_mapping.json",
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return False
    placeholder = _load_json(trace / "test-placeholder-check.json")
    return bool(
        consistency.get("input_fingerprint") == expected_consistency
        and placeholder.get("input_fingerprint") == expected_placeholder.get("input_fingerprint")
        and placeholder.get("status") == expected_placeholder.get("status")
        and placeholder.get("issue_count") == expected_placeholder.get("issue_count")
    )


def select_best(root: Path) -> dict[str, Any]:
    pointer = _best(root)
    snapshot_id = pointer.get("snapshot_id")
    if isinstance(snapshot_id, str):
        try:
            verify_snapshot(root, snapshot_id)
            return pointer
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    history = root / SNAPSHOT_ROOT / "history.jsonl"
    candidates: list[dict[str, Any]] = []
    try:
        lines = history.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not isinstance(row.get("snapshot_id"), str):
            continue
        try:
            verify_snapshot(root, row["snapshot_id"])
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        candidates.append(row)
    if not candidates:
        raise ValueError("no valid submission snapshot is available")
    return max(candidates, key=lambda row: (row.get("score_vector") or [], int(row.get("created_at_ns") or 0)))


def capture(root: Path, *, kind: str, run_id: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    if kind not in {"baseline", "provisional", "validated"}:
        raise ValueError("snapshot kind must be baseline, provisional, or validated")
    files = submission_files(root)
    cargo_toml = Path("flashDB_rust/Cargo.toml")
    if cargo_toml not in files:
        raise ValueError("flashDB_rust/Cargo.toml is required for a submission snapshot")
    score = compute_score(root)
    if kind in {"baseline", "validated"} and not score["build_success"]:
        raise ValueError(f"{kind} snapshot requires current cargo build success evidence")
    if kind == "validated" and not _is_validated_current(root, score):
        raise ValueError("validated snapshot requires complete current mapping, Cargo, and consistency evidence")
    if kind == "baseline":
        # A baseline proves only that the submission builds.  Do not let
        # partial/stale downstream evidence make it outrank a validated state.
        score["score_vector"] = [1, 0, 0, 0, 0, 0, 0]

    snapshot_id = f"submission-{time.time_ns()}"
    snapshots = root / SNAPSHOT_ROOT
    temporary = snapshots / f".{snapshot_id}.tmp"
    final = snapshots / snapshot_id
    if temporary.exists() or final.exists():
        raise ValueError("snapshot id collision")
    (temporary / "files").mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    for relative in files:
        _safe_relative(relative)
        source = root / relative
        destination = temporary / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        rows.append({
            "path": relative.as_posix(),
            "sha256": _sha256(destination),
            "mode": stat.S_IMODE(source.stat().st_mode),
        })

    evidence_rows: list[dict[str, str]] = []
    for relative in EVIDENCE_FILES:
        source = root / relative
        if not source.is_file() or source.is_symlink():
            continue
        destination = temporary / "evidence" / relative.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        evidence_rows.append({"path": relative.as_posix(), "snapshot_name": relative.name, "sha256": _sha256(destination)})

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "created_at_ns": time.time_ns(),
        "kind": kind,
        "scope": "submission",
        "files": rows,
        "evidence": evidence_rows,
        "score_vector": score["score_vector"],
        "validation_scope": "full" if kind == "validated" else kind,
    }
    _atomic_json(temporary / "manifest.json", manifest)
    _atomic_json(temporary / "score.json", score)
    snapshots.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, final)
    verify_snapshot(root, snapshot_id)

    best = _best(root)
    best_vector = best.get("score_vector") if isinstance(best.get("score_vector"), list) else None
    eligible_for_best = kind == "validated" or (kind == "baseline" and best.get("kind") != "validated")
    promoted = bool(eligible_for_best and (best_vector is None or score["score_vector"] >= best_vector))
    pointer = {
        "snapshot_id": snapshot_id,
        "kind": kind,
        "score_vector": score["score_vector"],
        "created_at_ns": manifest["created_at_ns"],
        "manifest": f"{SNAPSHOT_ROOT.as_posix()}/{snapshot_id}/manifest.json",
    }
    if promoted:
        _atomic_json(snapshots / "best.json", pointer)
    _append_jsonl(snapshots / "history.jsonl", {**pointer, "promoted": promoted})
    return {**pointer, "promoted": promoted, "score": score}


def verify_snapshot(root: Path, snapshot_id: str) -> dict[str, Any]:
    root = root.resolve()
    snapshot = root / SNAPSHOT_ROOT / snapshot_id
    manifest = _load_json(snapshot / "manifest.json")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("snapshot_id") != snapshot_id:
        raise ValueError("snapshot manifest is missing or inconsistent")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("snapshot manifest contains no files")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not isinstance(row.get("sha256"), str):
            raise ValueError("snapshot manifest has an invalid file row")
        relative = _safe_relative(Path(row["path"]))
        source = snapshot / "files" / relative
        if not source.is_file() or source.is_symlink() or _sha256(source) != row["sha256"]:
            raise ValueError(f"snapshot file is missing or corrupt: {relative}")
    return manifest


def verify_current(root: Path, snapshot_id: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    pointer = select_best(root) if snapshot_id is None else {"snapshot_id": snapshot_id}
    snapshot_id = pointer.get("snapshot_id")
    if not isinstance(snapshot_id, str):
        raise ValueError("no best submission snapshot is available")
    manifest = verify_snapshot(root, snapshot_id)
    expected = {str(row["path"]): str(row["sha256"]) for row in manifest["files"]}
    current = current_manifest(root)
    matches = current == expected
    return {
        "status": "match" if matches else "mismatch",
        "snapshot_id": snapshot_id,
        "matches": matches,
        "missing": sorted(set(expected) - set(current)),
        "extra": sorted(set(current) - set(expected)),
        "changed": sorted(path for path in set(expected) & set(current) if expected[path] != current[path]),
        "source_manifest": current,
    }


def restore_best(
    root: Path,
    *,
    reason: str,
    restore_evidence: bool | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if restore_evidence is None:
        restore_evidence = reason == "contest_deadline"
    pointer = select_best(root)
    snapshot_id = pointer.get("snapshot_id")
    if not isinstance(snapshot_id, str):
        raise ValueError("no best submission snapshot is available")
    manifest = verify_snapshot(root, snapshot_id)
    snapshot = root / SNAPSHOT_ROOT / snapshot_id
    expected = {Path(str(row["path"])): row for row in manifest["files"]}

    # The whole cache is validated before the first workspace mutation.  Each
    # destination is then replaced atomically.
    for relative, row in sorted(expected.items(), key=lambda item: item[0].as_posix()):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.restore.{os.getpid()}.tmp")
        shutil.copy2(snapshot / "files" / relative, temporary)
        os.chmod(temporary, int(row.get("mode", 0o644)))
        os.replace(temporary, destination)

    current_paths = set(submission_files(root))
    for relative in sorted(current_paths - set(expected), reverse=True):
        (root / relative).unlink()
    for directory in reversed(TRACKED_DIRS):
        base = root / directory
        if base.is_dir():
            for candidate in sorted(base.rglob("*"), reverse=True):
                if candidate.is_dir() and not any(candidate.iterdir()):
                    candidate.rmdir()

    evidence_restored: list[str] = []
    for row in manifest.get("evidence", []) if restore_evidence else []:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not isinstance(row.get("snapshot_name"), str):
            continue
        relative = Path(row["path"])
        if relative not in EVIDENCE_FILES:
            continue
        source = snapshot / "evidence" / row["snapshot_name"]
        if not source.is_file() or _sha256(source) != row.get("sha256"):
            raise ValueError(f"snapshot evidence is missing or corrupt: {relative}")
        destination = root / relative
        temporary = destination.with_name(f".{destination.name}.restore.{os.getpid()}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        evidence_restored.append(relative.as_posix())

    verification = verify_current(root, snapshot_id)
    if not verification["matches"]:
        raise ValueError("restored submission does not match its snapshot manifest")
    evidence = {
        "status": "restored",
        "reason": reason,
        "snapshot_id": snapshot_id,
        "score_vector": manifest.get("score_vector"),
        "restored_files": sorted(path.as_posix() for path in expected),
        "restored_evidence": sorted(evidence_restored),
        "evidence_mode": "restored" if restore_evidence else "fresh_confirmation_required",
        "next_action": "finalize_deadline" if restore_evidence else "rerun_cargo_and_consistency",
        "verification": verification,
    }
    _atomic_json(root / "logs" / "trace" / "submission-restore.json", evidence)
    return evidence


def protect_submission(root: Path) -> list[str]:
    protected: list[str] = []
    for relative in submission_files(root.resolve()):
        path = root.resolve() / relative
        mode = stat.S_IMODE(path.stat().st_mode)
        os.chmod(path, mode & ~0o222)
        protected.append(relative.as_posix())
    return protected


def unprotect_submission(root: Path) -> list[str]:
    changed: list[str] = []
    for relative in submission_files(root.resolve()):
        path = root.resolve() / relative
        mode = stat.S_IMODE(path.stat().st_mode)
        if not mode & stat.S_IWUSR:
            os.chmod(path, mode | stat.S_IWUSR)
            changed.append(relative.as_posix())
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage immutable submission snapshots without Git.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "show-best", "restore-best", "verify-current"):
        item = sub.add_parser(name)
        item.add_argument("--root", default=".")
        if name == "capture":
            item.add_argument("--kind", choices=["baseline", "provisional", "validated"], required=True)
            item.add_argument("--run-id")
        if name == "restore-best":
            item.add_argument("--reason", choices=["regression", "contest_deadline"], required=True)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.command == "capture":
            result = capture(root, kind=args.kind, run_id=args.run_id)
        elif args.command == "show-best":
            result = _best(root)
        elif args.command == "restore-best":
            result = restore_best(root, reason=args.reason)
        else:
            result = verify_current(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SUBMISSION_SNAPSHOT: REFUSED: {exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
