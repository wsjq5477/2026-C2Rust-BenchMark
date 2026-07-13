#!/usr/bin/env python3
"""Compute unsafe usage ratio in the generated Rust project."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


UNSAFE_PATTERN = re.compile(r"\bunsafe\b")


def rust_files(project: Path) -> list[Path]:
    files: list[Path] = []
    for base in [project / "src", project / "tests"]:
        if base.exists():
            files.extend(path for path in base.rglob("*.rs") if path.is_file())
    return sorted(files)


def compute(project: Path) -> dict[str, Any]:
    files = rust_files(project)
    total_lines = 0
    unsafe_lines = 0
    unsafe_occurrences = 0
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            total_lines += 1
            matches = UNSAFE_PATTERN.findall(line)
            if matches:
                unsafe_lines += 1
                unsafe_occurrences += len(matches)
    ratio = (unsafe_lines / total_lines) if total_lines else 0.0
    return {
        "rust_files": len(files),
        "total_lines": total_lines,
        "unsafe_lines": unsafe_lines,
        "unsafe_occurrences": unsafe_occurrences,
        "unsafe_ratio": ratio,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate unsafe ratio for flashDB_rust.")
    parser.add_argument("--project", required=True, help="Path to flashDB_rust.")
    parser.add_argument("--out", required=True, help="Output unsafe-ratio.json path.")
    args = parser.parse_args(argv)

    result = compute(Path(args.project))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("REPORT_AND_VERIFY: UNSAFE_RATIO_WRITTEN")
    print(f"unsafe_ratio={result['unsafe_ratio']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
