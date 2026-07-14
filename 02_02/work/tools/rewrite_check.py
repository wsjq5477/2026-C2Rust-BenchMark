#!/usr/bin/env python3
"""Run bounded, controller-owned checks for one static REWRITE worker role."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "workflow-contract.json"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def bounded_text(value: str, limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value, False
    suffix = encoded[-limit:].decode("utf-8", errors="replace")
    return suffix, True


def run_check(
    *,
    root: Path,
    project: str,
    role: str,
    revision: int,
    max_output_bytes: int,
) -> dict[str, Any]:
    normalized = role.upper()
    cargo = f"{project}/Cargo.toml"
    commands: list[tuple[str, list[str]]] = [
        ("fmt", ["cargo", "fmt", "--manifest-path", cargo, "--", "--check"]),
    ]
    if normalized == "IMPLEMENT_CORE":
        commands.append(("check", ["cargo", "check", "--all-targets", "--manifest-path", cargo]))
    elif normalized == "WIRE_FACADE":
        commands.extend([
            ("build", ["cargo", "build", "--release", "--manifest-path", cargo]),
            (
                "audit",
                [
                    sys.executable,
                    "work/tools/core_impl_audit.py",
                    "--root",
                    ".",
                    "--project",
                    project,
                    "--manifest",
                    "logs/trace/scaffold-manifest.json",
                    "--design",
                    "logs/trace/rust_api_design.json",
                    "--output",
                    "logs/trace/implementation-audit.json",
                ],
            ),
        ])
    else:
        raise ValueError(f"unsupported rewrite role: {role}")

    output_dir = root / "logs" / "trace" / "rewrite-check" / normalized.lower() / str(revision)
    output_dir.mkdir(parents=True, exist_ok=True)
    phases: list[dict[str, Any]] = []
    status = "pass"
    for phase, command in commands:
        started = time.time_ns()
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=300,
            )
            output = completed.stdout
            exit_code = completed.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            output = str(exc)
            exit_code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 127
        log_path = output_dir / f"{phase}.log"
        log_path.write_text(output, encoding="utf-8")
        tail, truncated = bounded_text(output, max_output_bytes)
        phase_result = {
            "phase": phase,
            "status": "pass" if exit_code == 0 else "fail",
            "exit_code": exit_code,
            "duration_ns": time.time_ns() - started,
            "log_path": log_path.relative_to(root).as_posix(),
            "output_bytes": len(output.encode("utf-8", errors="replace")),
            "truncated": truncated,
            "tail": tail,
        }
        phases.append(phase_result)
        if exit_code != 0:
            status = "fail"
            break
    result = {
        "schema_version": 1,
        "role": normalized,
        "revision": revision,
        "status": status,
        "max_output_bytes": max_output_bytes,
        "phases": phases,
    }
    receipt = output_dir / "result.json"
    receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["receipt_path"] = receipt.relative_to(root).as_posix()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--project", default="flashDB_rust")
    parser.add_argument("--role", choices=["IMPLEMENT_CORE", "WIRE_FACADE"], required=True)
    parser.add_argument("--revision", type=int, required=True)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    contract = load_json(CONTRACT_PATH)
    settings = contract.get("rewrite_static", {})
    limit = int(settings.get("max_command_output_bytes", 8192))
    result = run_check(
        root=root,
        project=args.project,
        role=args.role,
        revision=args.revision,
        max_output_bytes=limit,
    )
    rendered, _ = bounded_text(json.dumps(result, ensure_ascii=False), limit)
    print(rendered)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
