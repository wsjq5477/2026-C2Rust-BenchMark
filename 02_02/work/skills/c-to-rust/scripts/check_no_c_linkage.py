#!/usr/bin/env python3
"""Reject Rust outputs that embed, build, or link migrated C core sources."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FORBIDDEN_RE = re.compile(r"(?:\bcc\s*=|cc::Build|\.file\s*\([^)]*\.c|FlashDB[/\\]src|judge-assets)", re.I)


def inspect(project: Path | str) -> dict[str, Any]:
    root = Path(project).resolve()
    if not (root / "Cargo.toml").is_file():
        raise FileNotFoundError(f"Cargo.toml not found in {root}")
    c_sources = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.c")
        if "target" not in path.relative_to(root).parts
    )
    forbidden_references: list[str] = []
    for relative in ("Cargo.toml", "build.rs"):
        path = root / relative
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if FORBIDDEN_RE.search(line):
                forbidden_references.append(f"{relative}:{number}: {line.strip()}")
    return {
        "schema_version": 1,
        "c_sources": c_sources,
        "forbidden_references": forbidden_references,
        "passed": not c_sources and not forbidden_references,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect(args.project)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
