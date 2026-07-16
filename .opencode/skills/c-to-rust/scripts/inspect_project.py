#!/usr/bin/env python3
"""Create a deterministic inventory for a C project without modifying it."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FUNCTION_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
TEST_RUN_RE = re.compile(r"\b(?:TEST_RUN|UTEST_UNIT_RUN)\s*\(\s*([A-Za-z_]\w*)")
TEST_DEF_RE = re.compile(r"\b(?:static\s+)?void\s+(test_[A-Za-z0-9_]+)\s*\(")


def relative_files(root: Path, pattern: str) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob(pattern) if path.is_file())


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def strip_preprocessor(text: str) -> str:
    return re.sub(r"^[ \t]*#(?:.*\\\n)*.*$", " ", text, flags=re.M)


def is_test_source(name: str) -> bool:
    path = Path(name)
    parts = {part.lower() for part in path.parts[:-1]}
    stem = path.stem.lower()
    return bool(parts & {"test", "tests", "spec", "specs"}) or stem.startswith("test_") or stem.endswith(("_test", "_tests"))


def extract_public_functions(root: Path, headers: list[str]) -> list[str]:
    preferred = [name for name in headers if name.endswith("/flashdb.h") or name == "flashdb.h"]
    selected = preferred or headers
    names: set[str] = set()
    for name in selected:
        text = strip_preprocessor(strip_c_comments((root / name).read_text(encoding="utf-8", errors="replace")))
        text = re.sub(r'extern\s+"C"\s*\{', " ", text)
        text = re.sub(r"^\s*}\s*$", " ", text, flags=re.M)
        for statement in text.split(";"):
            statement = statement.strip()
            if not statement or "typedef" in statement or "{" in statement or "}" in statement:
                continue
            matches = list(FUNCTION_RE.finditer(statement))
            if not matches:
                continue
            candidate = matches[0].group(1)
            if not candidate.isupper() and candidate not in {"if", "while", "for", "switch", "sizeof"}:
                names.add(candidate)
    return sorted(names)


def extract_tests(root: Path, test_sources: list[str]) -> list[str]:
    registered: set[str] = set()
    defined: set[str] = set()
    for name in test_sources:
        text = strip_c_comments((root / name).read_text(encoding="utf-8", errors="replace"))
        registered.update(TEST_RUN_RE.findall(text))
        defined.update(TEST_DEF_RE.findall(text))
    return sorted(registered or defined)


def inspect_project(source: Path | str) -> dict[str, Any]:
    root = Path(source).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"C project does not exist: {root}")

    all_c = relative_files(root, "*.c")
    headers = relative_files(root, "*.h")
    test_sources = [name for name in all_c if is_test_source(name)]
    if (root / "src").is_dir():
        core_sources = [name for name in all_c if name.startswith("src/") and name not in test_sources]
    else:
        core_sources = [name for name in all_c if name not in test_sources]

    test_makefile = root / "tests" / "Makefile"
    root_makefile = root / "Makefile"
    if test_makefile.is_file() or root_makefile.is_file():
        build = {
            "kind": "make",
            "configure_command": None,
            "build_command": "make -C tests all" if test_makefile.is_file() else "make all",
            "test_command": "make -C tests test" if test_makefile.is_file() else "make test",
        }
    elif (root / "CMakeLists.txt").is_file():
        build = {
            "kind": "cmake",
            "configure_command": "cmake -S . -B build",
            "build_command": "cmake --build build",
            "test_command": "ctest --test-dir build --output-on-failure",
        }
    else:
        build = {"kind": "unknown", "configure_command": None, "build_command": None, "test_command": None}
    return {
        "schema_version": 1,
        "source_root": str(root),
        "core_sources": core_sources,
        "headers": headers,
        "test_sources": test_sources,
        "public_functions": extract_public_functions(root, headers),
        "test_cases": extract_tests(root, test_sources),
        "build": build,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    inventory = inspect_project(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"inventory: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
