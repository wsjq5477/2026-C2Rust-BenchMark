#!/usr/bin/env python3
"""Scan the platform FlashDB C project and write a deterministic input manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


BUILD_FILE_NAMES = {
    "Makefile",
    "makefile",
    "GNUmakefile",
    "CMakeLists.txt",
}


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def sorted_rel_files(root: Path, base: Path, suffixes: set[str] | None = None) -> list[str]:
    if not base.exists():
        return []
    files: list[str] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if suffixes is not None and path.suffix not in suffixes:
            continue
        files.append(rel(path, root))
    return sorted(files)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_project(source: Path | str) -> dict[str, Any]:
    root = Path(source).resolve()
    if not root.exists():
        raise FileNotFoundError(f"FlashDB source root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"FlashDB source root is not a directory: {root}")

    src_dir = root / "src"
    tests_dir = root / "tests"
    if not src_dir.is_dir():
        raise FileNotFoundError(f"missing src directory: {src_dir}")
    if not tests_dir.is_dir():
        raise FileNotFoundError(f"missing tests directory: {tests_dir}")

    core_sources = sorted_rel_files(root, src_dir, {".c"})
    test_sources = sorted_rel_files(root, tests_dir, {".c"})
    headers = sorted(
        sorted_rel_files(root, root / "inc", {".h"})
        + sorted_rel_files(root, src_dir, {".h"})
        + sorted_rel_files(root, tests_dir, {".h"})
    )

    build_files: list[str] = []
    for path in root.rglob("*"):
        if path.is_file() and path.name in BUILD_FILE_NAMES:
            build_files.append(rel(path, root))
    build_files.sort()
    # This is the one immutable input record.  The focused lists above drive
    # modelling; this complete file list prevents other source-tree changes
    # from escaping the input-integrity check.
    evidence_files = sorted(
        rel(path, root)
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )
    file_evidence = {
        name: {
            "sha256": sha256_file(root / name),
            "size": (root / name).stat().st_size,
        }
        for name in evidence_files
    }
    aggregate = hashlib.sha256()
    for name, evidence in file_evidence.items():
        aggregate.update(name.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(evidence["sha256"].encode("ascii"))
        aggregate.update(b"\n")

    manifest: dict[str, Any] = {
        "source_root": str(root),
        "src_dir": "src",
        "tests_dir": "tests",
        "core_sources": core_sources,
        "test_sources": test_sources,
        "headers": headers,
        "build_files": build_files,
        "file_evidence": file_evidence,
        "input_digest": aggregate.hexdigest(),
        "counts": {
            "core_sources": len(core_sources),
            "test_sources": len(test_sources),
            "headers": len(headers),
            "build_files": len(build_files),
        },
    }
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan FlashDB C input and write logs/trace/input_manifest.json.")
    parser.add_argument("--source", required=True, help="FlashDB source root.")
    parser.add_argument("--output", required=True, help="Manifest JSON output path.")
    args = parser.parse_args(argv)

    manifest = scan_project(args.source)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"READ_C_PROJECT: SCANNED {manifest['source_root']}")
    print(f"core_sources={manifest['counts']['core_sources']} test_sources={manifest['counts']['test_sources']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
