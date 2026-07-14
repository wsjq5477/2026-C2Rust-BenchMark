#!/usr/bin/env python3
"""Run cargo verification commands and capture logs for staged gates."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import test_failure_triage


def run_command(project: Path, command: list[str], log_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=project,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {"command": command, "returncode": completed.returncode, "log": log_path.name}


def capture(project: Path, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    results = {
        "build": run_command(project, ["cargo", "build"], out / "cargo-build.log"),
        "test": run_command(project, ["cargo", "test"], out / "cargo-test.log"),
        "fmt": run_command(project, ["cargo", "fmt", "--check"], out / "cargo-fmt.log"),
    }
    results["build_status"] = "pass" if results["build"]["returncode"] == 0 else "fail"
    results["test_status"] = "pass" if results["test"]["returncode"] == 0 else "fail"
    results["fmt_status"] = "pass" if results["fmt"]["returncode"] == 0 else "fail"
    if results["test_status"] == "fail":
        root = out.parent.parent if out.name == "trace" and out.parent.name == "logs" else out.parent
        triage_record = test_failure_triage.write_triage(root, out)
        results["test_failure_triage"] = {
            "status": "written",
            "log": "test-failure-triage.jsonl",
            "classification": triage_record["classification"],
            "allow_src_edit": triage_record["allow_src_edit"],
        }
    (out / "cargo-results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run cargo build/test/fmt and capture logs.")
    parser.add_argument("--project", required=True, help="Path to flashDB_rust.")
    parser.add_argument("--out", required=True, help="Output logs/trace directory.")
    args = parser.parse_args(argv)

    results = capture(Path(args.project), Path(args.out))
    print("BUILD_TEST_REPAIR: CARGO_CAPTURED")
    print(f"build_status={results['build_status']}")
    print(f"test_status={results['test_status']}")
    if "test_failure_triage" in results:
        triage = results["test_failure_triage"]
        if triage.get("status") == "written":
            print("TEST_FAILURE_TRIAGE: WRITTEN")
            print(f"classification={triage['classification']}")
            print(f"allow_src_edit={str(triage['allow_src_edit']).lower()}")
    return 0 if results["build_status"] == "pass" and results["test_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
