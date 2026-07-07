---
name: flashdb-test-migration
description: Use when FlashDB C test migration is required to create Rust tests with equivalent KVDB and TSDB coverage.
---

# FlashDB Test Migration

## Scope

Use this Skill only after the orchestrator enters `MIGRATE_TESTS`.

## MIGRATE_TESTS contract

- read `logs/trace/c_test_model.json`;
- read `logs/trace/rust_api_design.json`;
- follow `work/knowledge/flashdb-test-map.md`;
- use `c_test_model.json.standard_scenarios` as the dynamic source of truth;
- generate Rust tests under `flashDB_rust/tests/`;
- keep assertions meaningful;
- write `logs/trace/rust_test_mapping.json`.

Required outputs:

- `flashDB_rust/tests/kvdb_tests.rs`;
- `flashDB_rust/tests/tsdb_tests.rs`;
- `flashDB_rust/tests/equivalence_tests.rs`;
- `logs/trace/07-migrate-tests.md`.

Accuracy rules:

- derive tests from C test facts and the fixed Rust API;
- preserve a one-to-one scenario ID mapping between C and Rust;
- use each scenario's `semantic_facts` to preserve called APIs, helper behavior, and assertion intent;
- replace every generated `MIGRATION_PENDING` baseline before setting `coverage` to `semantic`;
- do not use the core implementation as the only source of truth;
- do not delete scenarios or replace semantic checks with constant truth assertions;
- new FlashDB tests must be migrated, mapped to `extension`, or placed in `unmapped` with a reason.
- the stage gate must fail while any extracted C scenario is missing, pending, duplicated, extra, or unmapped.
