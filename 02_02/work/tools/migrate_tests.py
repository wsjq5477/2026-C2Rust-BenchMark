#!/usr/bin/env python3
"""Build a Rust test migration task map from C test facts.

This tool deliberately does not generate Rust test bodies.  Semantic test code is
written by the test-migrator from the task map and the referenced C/Rust evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import re


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def as_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def scenario_suite(name: str, tags: list[str]) -> str:
    if "kvdb" in tags:
        return "kvdb"
    if "tsdb" in tags:
        return "tsdb"
    lower = name.lower()
    if "kv" in lower or "gc" in lower or "scale" in lower:
        return "kvdb"
    if "tsl" in lower or "tsdb" in lower:
        return "tsdb"
    return "extension"


def infer_tags(name: str) -> list[str]:
    lower = name.lower()
    tags: list[str] = []
    if "kv" in lower or "kvdb" in lower or "gc" in lower or "scale" in lower:
        tags.append("kvdb")
    if "tsl" in lower or "tsdb" in lower or "github_issue" in lower:
        tags.append("tsdb")
    for keyword in ["init", "deinit", "append", "iter", "query", "status", "clean", "gc", "del", "change", "set", "create", "get"]:
        if keyword in lower:
            tags.append(keyword)
    return sorted(dict.fromkeys(tags))


def safe_rust_ident(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not ident:
        ident = "scenario"
    if ident[0].isdigit():
        ident = f"scenario_{ident}"
    return ident


def standard_scenarios(test_model: dict[str, Any]) -> list[dict[str, Any]]:
    scorer_cases = test_model.get("scorer_standard_cases")
    if isinstance(scorer_cases, list) and scorer_cases:
        source_scenarios = test_model.get("standard_scenarios")
        source_by_id: dict[str, dict[str, Any]] = {}
        if isinstance(source_scenarios, list):
            source_by_id = {
                item["id"]: item
                for item in source_scenarios
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
        scenarios: list[dict[str, Any]] = []
        for index, case in enumerate(scorer_cases, start=1):
            if not isinstance(case, dict):
                continue
            scenario_id = case.get("scenario_id") if isinstance(case.get("scenario_id"), str) else case.get("id")
            if not isinstance(scenario_id, str) or not scenario_id:
                continue
            source = source_by_id.get(scenario_id, {})
            tags = case.get("tags") if isinstance(case.get("tags"), list) else source.get("tags")
            if not isinstance(tags, list):
                tags = infer_tags(scenario_id)
            tags = [tag for tag in tags if isinstance(tag, str)]
            suite = case.get("suite") if isinstance(case.get("suite"), str) else source.get("suite")
            if not isinstance(suite, str):
                suite = scenario_suite(scenario_id, tags)
            semantic_facts = case.get("semantic_facts")
            if not isinstance(semantic_facts, dict):
                semantic_facts = source.get("semantic_facts") if isinstance(source.get("semantic_facts"), dict) else {}
            scenarios.append(
                {
                    "id": scenario_id,
                    "name": scenario_id,
                    "parent_test": scenario_id,
                    "suite": suite,
                    "source": "scorer_cases",
                    "source_file": source.get("source_file") if isinstance(source, dict) else None,
                    "order": case.get("order") if isinstance(case.get("order"), int) else index,
                    "tags": tags,
                    "semantic_facts": semantic_facts,
                    "scorer_case_id": case.get("case_id"),
                    "scorer_case_name": case.get("case_name"),
                    "required_c_tests": case.get("required_c_tests") if isinstance(case.get("required_c_tests"), list) else [scenario_id],
                    "present_c_tests": case.get("present_c_tests") if isinstance(case.get("present_c_tests"), list) else [],
                    "missing_c_tests": case.get("missing_c_tests") if isinstance(case.get("missing_c_tests"), list) else [],
                    "semantic_obligations": case.get("semantic_obligations") if isinstance(case.get("semantic_obligations"), list) else [],
                }
            )
        if scenarios:
            return scenarios

    raw = test_model.get("standard_scenarios")
    scenarios: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            name = item.get("name") if isinstance(item.get("name"), str) else item.get("id")
            if not isinstance(name, str) or not name:
                continue
            tags = item.get("tags") if isinstance(item.get("tags"), list) else infer_tags(name)
            tags = [tag for tag in tags if isinstance(tag, str)]
            suite = item.get("suite") if isinstance(item.get("suite"), str) else scenario_suite(name, tags)
            scenarios.append(
                {
                    "id": item.get("id") if isinstance(item.get("id"), str) else name,
                    "name": name,
                    "parent_test": item.get("parent_test") if isinstance(item.get("parent_test"), str) else name,
                    "suite": suite,
                    "source": item.get("source") if isinstance(item.get("source"), str) else "registered",
                    "source_file": item.get("source_file") if isinstance(item.get("source_file"), str) else None,
                    "order": item.get("order") if isinstance(item.get("order"), int) else index,
                    "tags": tags,
                    "semantic_facts": item.get("semantic_facts") if isinstance(item.get("semantic_facts"), dict) else {},
                    "scorer_case_id": item.get("scorer_case_id") if isinstance(item.get("scorer_case_id"), str) else item.get("id") if isinstance(item.get("id"), str) else name,
                    "scorer_case_name": item.get("scorer_case_name") if isinstance(item.get("scorer_case_name"), str) else name,
                    "semantic_obligations": item.get("semantic_obligations") if isinstance(item.get("semantic_obligations"), list) else [],
                }
            )
    if scenarios:
        return scenarios

    names = as_list(test_model, "kvdb_tests") + as_list(test_model, "tsdb_tests") + as_list(test_model, "extension_tests")
    seen: set[str] = set()
    for index, name in enumerate([item for item in names if item not in seen and not seen.add(item)], start=1):
        tags = infer_tags(name)
        scenarios.append(
            {
                "id": name,
                "name": name,
                "parent_test": name,
                "suite": scenario_suite(name, tags),
                "source": "legacy",
                "source_file": None,
                "order": index,
                "tags": tags,
                "semantic_facts": {},
                "scorer_case_id": name,
                "scorer_case_name": name,
                "semantic_obligations": [],
            }
        )
    return scenarios


def generate_tests(test_model: dict[str, Any], design: dict[str, Any], project: Path, mapping_path: Path) -> dict[str, Any]:
    scenarios = standard_scenarios(test_model)
    scenarios_by_suite: dict[str, list[dict[str, Any]]] = {}
    for scenario in scenarios:
        suite = str(scenario.get("suite", "extension"))
        scenarios_by_suite.setdefault(suite, []).append(scenario)
    kvdb_scenarios = scenarios_by_suite.get("kvdb", [])
    tsdb_scenarios = scenarios_by_suite.get("tsdb", [])
    extension_scenarios = [scenario for suite, items in scenarios_by_suite.items() if suite not in {"kvdb", "tsdb"} for scenario in items]
    kvdb_tests = [str(scenario["id"]) for scenario in kvdb_scenarios]
    tsdb_tests = [str(scenario["id"]) for scenario in tsdb_scenarios]
    extension_tests = as_list(test_model, "extension_tests")
    unclassified_tests = as_list(test_model, "unclassified_tests")

    source_to_rust: dict[str, str] = {}
    for suite, suite_scenarios in sorted(scenarios_by_suite.items()):
        filename = f"{safe_rust_ident(suite)}_tests.rs"
        source_to_rust[suite] = f"flashDB_rust/tests/{filename}"

    mapped_scenarios = []
    for scenario in scenarios:
        suite = str(scenario.get("suite", "extension"))
        rust_file = source_to_rust.get(suite, f"flashDB_rust/tests/{safe_rust_ident(suite)}_tests.rs")
        rust_prefix = safe_rust_ident(suite)
        mapped_scenarios.append(
            {
                "id": scenario["id"],
                "name": scenario["name"],
                "parent_test": scenario.get("parent_test", scenario["name"]),
                "suite": suite,
                "source": scenario.get("source", "registered"),
                "source_file": scenario.get("source_file"),
                "tags": scenario.get("tags", []),
                "semantic_facts": scenario.get("semantic_facts", {}),
                "scorer_case_id": scenario.get("scorer_case_id", scenario.get("id")),
                "scorer_case_name": scenario.get("scorer_case_name", scenario.get("name")),
                "required_c_tests": scenario.get("required_c_tests", [scenario.get("id")]),
                "present_c_tests": scenario.get("present_c_tests", []),
                "missing_c_tests": scenario.get("missing_c_tests", []),
                "semantic_obligations": scenario.get("semantic_obligations", []),
                "validated_obligations": [],
                "assertion_evidence": [],
                "rust_file": rust_file,
                "rust_test": f"{rust_prefix}_{safe_rust_ident(str(scenario['id']))}",
                "implementation_status": "pending",
                "compile_status": "unknown",
                "execution_status": "unknown",
                "placeholder_status": "unknown",
                "consistency_status": "unknown",
                "repair_attempts": 0,
                "unresolved_issues": [],
                "coverage": "pending",
            }
        )

    unmapped = unclassified_tests + as_list(design, "unmapped_symbols")
    unmapped.extend(str(scenario["id"]) for scenario in extension_scenarios)

    mapping = {
        "kvdb": kvdb_tests,
        "tsdb": tsdb_tests,
        "extension": extension_tests,
        "unmapped": sorted(dict.fromkeys(unmapped)),
        "scenarios": mapped_scenarios,
        "total_scenarios": len(mapped_scenarios),
        "total_scorer_cases": len(mapped_scenarios),
        "source_to_rust": source_to_rust,
        "implementation_status": "pending",
    }
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Rust test migration tasks from FlashDB C test facts.")
    parser.add_argument("--test-model", required=True, help="Path to c_test_model.json.")
    parser.add_argument("--design", required=True, help="Path to rust_api_design.json.")
    parser.add_argument("--project", required=True, help="Path to flashDB_rust project.")
    parser.add_argument("--mapping", required=True, help="Path to write rust_test_mapping.json.")
    args = parser.parse_args(argv)

    mapping = generate_tests(load_json(Path(args.test_model)), load_json(Path(args.design)), Path(args.project), Path(args.mapping))
    print("MIGRATE_TESTS: TASK_MAP_WRITTEN")
    print(f"mapped_scenarios={mapping['total_scenarios']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
