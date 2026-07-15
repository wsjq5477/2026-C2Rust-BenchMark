#!/usr/bin/env python3
"""Verify that migration state covers every discovered C unit, API, and test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def verified(items: list[dict[str, Any]], key: str) -> set[str]:
    return {str(item[key]) for item in items if item.get("status") == "verified" and item.get(key)}


def evaluate(inventory: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    source_files = verified(state.get("source_files", []), "c_file")
    symbols = verified(state.get("symbols", []), "c_symbol")
    tests = verified(state.get("tests", []), "c_test")
    missing_sources = sorted(set(inventory.get("core_sources", [])) - source_files)
    missing_symbols = sorted(set(inventory.get("public_functions", [])) - symbols)
    missing_tests = sorted(set(inventory.get("test_cases", [])) - tests)
    return {
        "schema_version": 1,
        "missing_sources": missing_sources,
        "missing_symbols": missing_symbols,
        "missing_tests": missing_tests,
        "passed": not (missing_sources or missing_symbols or missing_tests),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    state = json.loads(args.state.read_text(encoding="utf-8"))
    result = evaluate(inventory, state)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
