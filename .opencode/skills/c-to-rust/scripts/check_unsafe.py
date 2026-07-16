#!/usr/bin/env python3
"""Measure unsafe Rust source lines and enforce a maximum ratio."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


UNSAFE_RE = re.compile(r"\bunsafe\b")


def measure(source: Path | str, maximum: float = 0.10) -> dict[str, Any]:
    root = Path(source)
    files = sorted(root.rglob("*.rs")) if root.is_dir() else [root]
    code_lines = 0
    unsafe_lines = 0
    locations: list[str] = []
    in_block_comment = False
    for path in files:
        for number, raw_line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = raw_line
            if in_block_comment:
                if "*/" not in line:
                    continue
                line = line.split("*/", 1)[1]
                in_block_comment = False
            while "/*" in line:
                before, after = line.split("/*", 1)
                if "*/" in after:
                    line = before + after.split("*/", 1)[1]
                else:
                    line = before
                    in_block_comment = True
                    break
            line = line.split("//", 1)[0].strip()
            if not line:
                continue
            code_lines += 1
            if UNSAFE_RE.search(line):
                unsafe_lines += 1
                locations.append(f"{path}:{number}")
    ratio = unsafe_lines / code_lines if code_lines else 0.0
    return {
        "schema_version": 1,
        "code_lines": code_lines,
        "unsafe_lines": unsafe_lines,
        "ratio": ratio,
        "maximum": maximum,
        "passed": ratio < maximum,
        "locations": locations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--maximum", type=float, default=0.10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = measure(args.source, args.maximum)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
