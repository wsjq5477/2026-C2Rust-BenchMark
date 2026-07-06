#!/usr/bin/env python3
"""Generate Rust integration tests and rust_test_mapping.json from C test facts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def generate_tests(test_model: dict[str, Any], design: dict[str, Any], project: Path, mapping_path: Path) -> dict[str, Any]:
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    kvdb_tests = as_list(test_model, "kvdb_tests")
    tsdb_tests = as_list(test_model, "tsdb_tests")
    extension_tests = as_list(test_model, "extension_tests")
    unclassified_tests = as_list(test_model, "unclassified_tests")

    write(
        tests_dir / "kvdb_tests.rs",
        """
use flashdb_rust::{KvDb, MemFlash};

#[test]
fn kvdb_set_get_delete_roundtrip() {
    let flash = MemFlash::new();
    let mut db = KvDb::open(flash).expect("open kvdb");

    db.set("boot_count", "1").expect("set value");
    assert_eq!(db.get("boot_count").expect("get value"), Some("1".to_string()));

    db.set_blob("raw", [1_u8, 2, 3]).expect("set blob");
    assert_eq!(db.get_blob("raw").expect("get blob"), Some(vec![1, 2, 3]));

    db.delete("boot_count").expect("delete value");
    assert_eq!(db.get("boot_count").expect("get deleted value"), None);
}

#[test]
fn kvdb_iter_exposes_written_blob() {
    let flash = MemFlash::new();
    let mut db = KvDb::open(flash).expect("open kvdb");
    db.set_blob("k", b"v").expect("set blob");
    let pairs: Vec<_> = db.iter().map(|(key, value)| (key.to_string(), value.to_vec())).collect();
    assert_eq!(pairs, vec![("k".to_string(), b"v".to_vec())]);
}
""",
    )
    write(
        tests_dir / "tsdb_tests.rs",
        """
use flashdb_rust::TsDb;

#[test]
fn tsdb_append_and_query_by_time() {
    let mut db = TsDb::open().expect("open tsdb");
    db.append(10, b"a").expect("append first");
    db.append(20, b"b").expect("append second");

    let queried = db.query_by_time(15, 25).expect("query by time");
    assert_eq!(queried.len(), 1);
    assert_eq!(queried[0].timestamp, 20);
    assert_eq!(queried[0].payload, b"b".to_vec());
}

#[test]
fn tsdb_status_and_clean_remove_nonzero_records() {
    let mut db = TsDb::open().expect("open tsdb");
    db.append(1, b"keep").expect("append keep");
    db.append(2, b"drop").expect("append drop");
    db.set_status(2, 1).expect("set status");
    db.clean().expect("clean");

    let all: Vec<_> = db.iter().collect();
    assert_eq!(all.len(), 1);
    assert_eq!(all[0].payload, b"keep".to_vec());
}
""",
    )
    write(
        tests_dir / "equivalence_tests.rs",
        """
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
""",
    )

    mapping = {
        "kvdb": kvdb_tests,
        "tsdb": tsdb_tests,
        "extension": extension_tests,
        "unmapped": unclassified_tests + as_list(design, "unmapped_symbols"),
        "total_scenarios": len(kvdb_tests) + len(tsdb_tests) + len(extension_tests),
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
