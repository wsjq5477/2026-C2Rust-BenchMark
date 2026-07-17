#!/usr/bin/env python3
"""Create and verify a current normal-FINAL receipt.

The deadline watchdog has its own frozen evidence path.  This receipt protects
only an ordinary early completion and makes stopping the watchdog conditional
on the exact submission, validation evidence, queue, and report that passed
the FINAL gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import submission_snapshot


SCHEMA_VERSION = 1
RECEIPT_PATH = Path("logs/trace/final-gate-receipt.json")
EVIDENCE_PATHS = (
    Path("logs/trace/implementation-audit.json"),
    Path("logs/trace/implementation-attempts.jsonl"),
    Path("logs/trace/validation-matrix.json"),
    Path("logs/trace/c-cross/attempts.jsonl"),
    Path("logs/trace/c-cross/failure-summary.json"),
    Path("logs/trace/repair-work-queue.json"),
    Path("logs/trace/cargo-results.json"),
    Path("logs/trace/test-repair-attempts.jsonl"),
    Path("logs/trace/test-placeholder-check.json"),
    Path("logs/trace/test-semantic-review.json"),
    Path("logs/trace/test-consistency.json"),
    Path("logs/trace/unsafe-ratio.json"),
    Path("logs/trace/final-verification.md"),
    Path("logs/trace/09-report-and-verify.md"),
    Path("result/output.md"),
    Path("result/issues/00-summary.md"),
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


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def evidence_manifest(root: Path) -> dict[str, str | None]:
    root = root.resolve()
    return {
        relative.as_posix(): _sha256(root / relative) if (root / relative).is_file() else None
        for relative in EVIDENCE_PATHS
    }


def invalidate(root: Path) -> None:
    try:
        (root.resolve() / RECEIPT_PATH).unlink()
    except FileNotFoundError:
        pass


def create(root: Path, *, terminal_status: str) -> dict[str, Any]:
    root = root.resolve()
    if terminal_status not in {"success", "failed_final"}:
        raise ValueError("normal FINAL receipt requires success or failed_final")
    output = root / "result" / "output.md"
    marker = "STATUS: SUCCESS" if terminal_status == "success" else "STATUS: FAILED"
    if not output.is_file() or marker not in output.read_text(encoding="utf-8", errors="ignore"):
        raise ValueError(f"normal FINAL report does not contain {marker}")
    matrix = _load(root / "logs" / "trace" / "validation-matrix.json")
    cargo = _load(root / "logs" / "trace" / "cargo-results.json")
    consistency = _load(root / "logs" / "trace" / "test-consistency.json")
    queue = _load(root / "logs" / "trace" / "repair-work-queue.json")
    contest_run = _load(root / "logs" / "trace" / "contest-control" / "run.json")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_kind": "normal_final",
        "terminal_status": terminal_status,
        "finalized_at_ns": time.time_ns(),
        "contest_run_id": contest_run.get("run_id"),
        "submission_manifest": submission_snapshot.current_manifest(root),
        "evidence_manifest": evidence_manifest(root),
        "c_cross_attempt_id": matrix.get("execution_id"),
        "c_cross_scope_fingerprint": matrix.get("scope_fingerprint"),
        "cargo_attempt_id": (
            cargo.get("repair_convergence", {}).get("attempt_id")
            if isinstance(cargo.get("repair_convergence"), dict) else None
        ),
        "consistency_fingerprint": consistency.get("input_fingerprint"),
        "repair_queue_sha256": hashlib.sha256(
            json.dumps(queue, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    _atomic_json(root / RECEIPT_PATH, receipt)
    return receipt


def verify(root: Path, *, expected_run_id: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    receipt = _load(root / RECEIPT_PATH)
    errors: list[str] = []
    if receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("receipt_kind") != "normal_final":
        errors.append("missing or unsupported normal FINAL receipt")
    terminal = receipt.get("terminal_status")
    if terminal not in {"success", "failed_final"}:
        errors.append("normal FINAL receipt has an invalid terminal status")
    if expected_run_id is not None and receipt.get("contest_run_id") != expected_run_id:
        errors.append("normal FINAL receipt belongs to a different contest run")
    try:
        current_submission = submission_snapshot.current_manifest(root)
    except (OSError, ValueError) as exc:
        current_submission = {}
        errors.append(f"cannot verify current submission manifest: {exc}")
    if receipt.get("submission_manifest") != current_submission:
        errors.append("submission files changed after FINAL")
    if receipt.get("evidence_manifest") != evidence_manifest(root):
        errors.append("validation evidence or final report changed after FINAL")
    output = root / "result" / "output.md"
    expected_marker = "STATUS: SUCCESS" if terminal == "success" else "STATUS: FAILED"
    if terminal in {"success", "failed_final"} and (
        not output.is_file() or expected_marker not in output.read_text(encoding="utf-8", errors="ignore")
    ):
        errors.append("final report status no longer matches the receipt")
    return {
        "status": "valid" if not errors else "invalid",
        "valid": not errors,
        "errors": errors,
        "receipt": receipt,
    }
