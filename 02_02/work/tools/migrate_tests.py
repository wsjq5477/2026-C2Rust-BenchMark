#!/usr/bin/env python3
"""Generate Rust integration tests and rust_test_mapping.json from C test facts."""

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


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


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
            }
        )
    return scenarios


def render_kvdb_tests(scenarios: list[dict[str, Any]]) -> str:
    tests = [
        """
use flashdb_rust::{KvDb, MemFlash};

fn exercise_kvdb_scenario(name: &str) {
    let flash = MemFlash::new();
    let mut db = KvDb::open(flash).expect("open kvdb");
    let key = format!("{name}_key");
    let value = format!("{name}_value");

    db.set(&key, &value).expect("set value");
    assert_eq!(db.get(&key).expect("get value"), Some(value));

    let blob_key = format!("{key}_blob");
    db.set_blob(&blob_key, [1_u8, 2, 3]).expect("set blob");
    assert_eq!(db.get_blob(&blob_key).expect("get blob"), Some(vec![1, 2, 3]));

    db.gc().expect("gc preserves latest values");
    assert!(db.iter().any(|(seen_key, _)| seen_key == key));
}
""".rstrip()
    ]
    for scenario in scenarios:
        test_name = f"kvdb_{safe_rust_ident(str(scenario['id']))}"
        tests.append(
            f"""
#[test]
fn {test_name}() {{
    // MIGRATION_PENDING: replace baseline coverage with the C scenario semantics for {scenario['id']}.
    exercise_kvdb_scenario("{scenario['id']}");
}}
""".rstrip()
        )
    return "\n\n".join(tests)


def render_tsdb_tests(scenarios: list[dict[str, Any]]) -> str:
    tests = [
        """
use flashdb_rust::TsDb;

fn exercise_tsdb_scenario(seed: u64) {
    let mut db = TsDb::open().expect("open tsdb");
    db.append(seed, b"first").expect("append first");
    db.append(seed + 10, b"second").expect("append second");

    let queried = db.query_by_time(seed, seed + 10).expect("query by time");
    assert_eq!(queried.len(), 2);
    assert_eq!(queried[0].payload, b"first".to_vec());
    assert_eq!(queried[1].payload, b"second".to_vec());
}
""".rstrip()
    ]
    for offset, scenario in enumerate(scenarios, start=1):
        test_name = f"tsdb_{safe_rust_ident(str(scenario['id']))}"
        tests.append(
            f"""
#[test]
fn {test_name}() {{
    // MIGRATION_PENDING: replace baseline coverage with the C scenario semantics for {scenario['id']}.
    exercise_tsdb_scenario({offset * 100});
}}
""".rstrip()
        )
    return "\n\n".join(tests)


def render_equivalence_tests() -> str:
    return """
use flashdb_rust::{KvDb, MemFlash, TsDb};

#[test]
fn core_flashdb_apis_are_available_to_tests() {
    let mut kv = KvDb::open(MemFlash::new()).expect("open kv");
    kv.set("mode", "safe").expect("set");
    assert_eq!(kv.get("mode").expect("get"), Some("safe".to_string()));

    let mut ts = TsDb::open().expect("open ts");
    ts.append(100, b"event").expect("append");
    assert_eq!(ts.query_by_time(0, 100).expect("query").len(), 1);
}
""".strip()


def generate_tests(test_model: dict[str, Any], design: dict[str, Any], project: Path, mapping_path: Path) -> dict[str, Any]:
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    scenarios = standard_scenarios(test_model)
    kvdb_scenarios = [scenario for scenario in scenarios if scenario.get("suite") == "kvdb"]
    tsdb_scenarios = [scenario for scenario in scenarios if scenario.get("suite") == "tsdb"]
    extension_scenarios = [scenario for scenario in scenarios if scenario.get("suite") not in {"kvdb", "tsdb"}]
    kvdb_tests = [str(scenario["id"]) for scenario in kvdb_scenarios]
    tsdb_tests = [str(scenario["id"]) for scenario in tsdb_scenarios]
    extension_tests = as_list(test_model, "extension_tests")
    unclassified_tests = as_list(test_model, "unclassified_tests")

    write(tests_dir / "kvdb_tests.rs", render_kvdb_tests(kvdb_scenarios))
    write(tests_dir / "tsdb_tests.rs", render_tsdb_tests(tsdb_scenarios))
    write(tests_dir / "equivalence_tests.rs", render_equivalence_tests())

    mapped_scenarios = []
    for scenario in scenarios:
        suite = str(scenario.get("suite", "extension"))
        rust_file = "flashDB_rust/tests/kvdb_tests.rs" if suite == "kvdb" else "flashDB_rust/tests/tsdb_tests.rs"
        rust_prefix = "kvdb" if suite == "kvdb" else "tsdb"
        if suite not in {"kvdb", "tsdb"}:
            rust_file = "flashDB_rust/tests/equivalence_tests.rs"
            rust_prefix = "equivalence"
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
                "rust_file": rust_file,
                "rust_test": f"{rust_prefix}_{safe_rust_ident(str(scenario['id']))}",
                "coverage": "pending" if suite in {"kvdb", "tsdb"} else "unmapped",
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
        "source_to_rust": {
            "kvdb": "flashDB_rust/tests/kvdb_tests.rs",
            "tsdb": "flashDB_rust/tests/tsdb_tests.rs",
            "equivalence": "flashDB_rust/tests/equivalence_tests.rs",
        },
    }
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Rust tests from FlashDB C test facts.")
    parser.add_argument("--test-model", required=True, help="Path to c_test_model.json.")
    parser.add_argument("--design", required=True, help="Path to rust_api_design.json.")
    parser.add_argument("--project", required=True, help="Path to flashDB_rust project.")
    parser.add_argument("--mapping", required=True, help="Path to write rust_test_mapping.json.")
    args = parser.parse_args(argv)

    mapping = generate_tests(load_json(Path(args.test_model)), load_json(Path(args.design)), Path(args.project), Path(args.mapping))
    print("MIGRATE_TESTS: TESTS_WRITTEN")
    print(f"mapped_scenarios={mapping['total_scenarios']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
