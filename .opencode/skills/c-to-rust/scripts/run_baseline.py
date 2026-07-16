#!/usr/bin/env python3
"""Build and test a copied C project, preserving platform-provided input."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence


def run(command: Sequence[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {"command": list(command), "exit_code": completed.returncode, "output": completed.stdout}


def run_baseline(
    source: Path | str,
    scratch: Path | str,
    build_command: Sequence[str],
    test_command: Sequence[str],
) -> dict[str, Any]:
    source_path = Path(source).resolve()
    scratch_path = Path(scratch).resolve()
    if not source_path.is_dir():
        raise FileNotFoundError(f"C project does not exist: {source_path}")
    if scratch_path.exists():
        shutil.rmtree(scratch_path)
    shutil.copytree(source_path, scratch_path, symlinks=True)

    build = run(build_command, scratch_path)
    test = run(test_command, scratch_path) if build["exit_code"] == 0 else {
        "command": list(test_command),
        "exit_code": None,
        "output": "skipped because build failed",
    }
    return {
        "schema_version": 1,
        "source_root": str(source_path),
        "scratch_root": str(scratch_path),
        "build": build,
        "test": test,
        "passed": build["exit_code"] == 0 and test["exit_code"] == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--build-command", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_baseline(
        args.source,
        args.scratch,
        shlex.split(args.build_command),
        shlex.split(args.test_command),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(result["build"]["output"], end="")
    print(result["test"]["output"], end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
