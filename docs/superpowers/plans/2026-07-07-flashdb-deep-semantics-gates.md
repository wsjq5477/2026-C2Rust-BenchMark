# FlashDB Deep Semantics Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the FlashDB migration workbench so C test semantics, Rust API design, test migration gates, and internal pre-scoring all catch shallow semantic migrations before final scoring.

**Architecture:** `build_c_model.py` becomes the source of deep test facts and obligations. `design_rust_api.py` consumes those facts to declare storage and test-observable API contracts. `gate.py` and a new `test_consistency_check.py` enforce those contracts against `rust_test_mapping.json` and Rust test source.

**Tech Stack:** Python 3 stdlib, `unittest`, existing FlashDB workbench JSON artifacts.

## Global Constraints

- Do not hardcode a fixed C test count; derive cases from current C evidence.
- Keep `standard_scenarios` as dynamic C evidence and `scorer_standard_cases` as scorer-facing contract.
- Test-first for behavior changes: add failing `02_02/tests/test_conversion_system.py` tests before production edits.
- Do not rewrite unrelated workflow structure or revert user files.

---

### Task 1: Deep C Test Fact Extraction

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/build_c_model.py`

**Interfaces:**
- Produces: `extract_test_semantics(body: str) -> dict` with `assertion_details`, `assertion_targets`, `control_usage`, `data_shape`, `scenario_features`.
- Produces: `semantic_obligations_from_facts(tags: list[str], facts: dict) -> list[str]` with concrete `verify_*`, `data_shape:*`, and scenario obligations.

- [ ] Add failing tests for assert expression, control usage, reboot persistence, multi-KV, large blob, reverse iteration, multi-status, and cross-sector TSL facts.
- [ ] Run `python3 -m unittest 02_02.tests.test_conversion_system.FrameworkCheckpointTests.test_build_c_model_extracts_deep_semantic_obligations -v` and confirm it fails on missing fields.
- [ ] Implement regex-based fact extraction in `build_c_model.py` using stdlib only.
- [ ] Run the targeted test and confirm it passes.

### Task 2: Rust API Design Contracts

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/design_rust_api.py`
- Modify: `02_02/work/tools/gate.py`

**Interfaces:**
- Consumes: deep obligations from Task 1.
- Produces: `rust_api_design.json.test_api.observables`, `test_api.controls`, and `storage_constraints`.
- Gate requires observables when obligations reference internal state, control, sector, or persistence behavior.

- [ ] Add failing tests proving API design emits `oldest_addr`, `is_initialized`, `sector_status`, control interface, and file-sector storage constraints from model facts.
- [ ] Run targeted tests and confirm failure.
- [ ] Implement design extraction and gate validation.
- [ ] Run targeted tests and confirm pass.

### Task 3: Test Consistency Checker and MIGRATE_TESTS Gate

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Create: `02_02/work/tools/test_consistency_check.py`
- Modify: `02_02/work/tools/gate.py`
- Modify: `02_02/work/tools/migrate_tests.py`

**Interfaces:**
- Produces: `analyze_consistency(root: Path) -> dict` with `issues`.
- CLI: `python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json`.
- Gate rejects semantic mappings with missing assertion evidence, shallow assertions, missing direct `verify_*` evidence, or assertion counts below the C threshold.

- [ ] Add failing tests where `coverage: semantic` plus `validated_obligations` is rejected because Rust test code only contains `assert!(x.is_ok())` or `assert!(true)`.
- [ ] Run targeted tests and confirm failure.
- [ ] Implement Rust test parser and issue classification.
- [ ] Integrate it into `gate.py --stage MIGRATE_TESTS` and `REPORT_AND_VERIFY`.
- [ ] Run targeted tests and confirm pass.

### Task 4: Documentation and Verification

**Files:**
- Modify: `02_02/work/skills/test-migrator.md`
- Modify: `02_02/work/skills/flashdb-test-migration/SKILL.md`
- Modify: `02_02/work/knowledge/flashdb-test-map.md`
- Modify: `design_doc/stages/03-build-c-model.md`
- Modify: `design_doc/stages/04-design-rust-api.md`
- Modify: `design_doc/stages/07-migrate-tests.md`
- Modify: `design_doc/stages/09-report-and-verify.md`

**Interfaces:**
- Documents L1/L2/L3 coverage and pre-scoring command.

- [ ] Update docs and agent instructions to consume the new fields and forbid API-only semantic claims.
- [ ] Run `python3 -m py_compile 02_02/work/tools/*.py`.
- [ ] Run `python3 -m unittest 02_02.tests.test_conversion_system`.
- [ ] Inspect failures, fix only aligned issues, and rerun until green.
