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
- use `c_test_model.json.scorer_standard_cases` as the scoring coverage contract;
- use `c_test_model.json.standard_scenarios` as dynamic C registration evidence;
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
- preserve a one-to-one mapping between scorer-standard cases and Rust tests;
- use each scorer case's `semantic_obligations` and `semantic_facts` to preserve called APIs, helper behavior, and assertion intent;
- replace every generated `MIGRATION_PENDING` baseline before setting `coverage` to `semantic`;
- set `validated_obligations` only for obligations actually covered by the Rust test;
- do not use the core implementation as the only source of truth;
- do not delete scenarios or replace semantic checks with constant truth assertions;
- new FlashDB tests outside the scorer taxonomy must remain available as evidence, extension coverage, or explicit unmapped context.
- the stage gate must fail while any scorer-standard case is missing, pending, duplicated, extra, unmapped, or marked semantic without validated obligations.
