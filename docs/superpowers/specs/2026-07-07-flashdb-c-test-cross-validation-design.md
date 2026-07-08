# FlashDB C Test Cross Validation Design

## Goal

Add a fixed validation stage between `REWRITE_CORE_MODULES` and `MIGRATE_TESTS` so the workbench can run original C test scenarios against the migrated Rust implementation before Rust test migration begins.

This stage is named `VERIFY_RUST_WITH_C_TESTS`.

## Problem

The current workbench verifies two important things:

- `MIGRATE_TESTS` checks that Rust tests map one-to-one to `c_test_model.json.scorer_standard_cases`.
- `BUILD_TEST_REPAIR` checks that the Rust project builds and `cargo test` passes.

That still leaves one diagnostic gap. If a migrated Rust test fails, the workbench cannot immediately tell whether the Rust implementation is wrong, the Rust test migration is wrong, or the Rust test harness is wrong. Original C tests are the best baseline for implementation behavior because they encode the source project's expected behavior before test translation.

## Stage Placement

The stage order becomes:

```text
BOOTSTRAP
INIT_WORKSPACE
READ_C_PROJECT
BUILD_C_MODEL
DESIGN_RUST_API
GENERATE_RUST_SCAFFOLD
REWRITE_CORE_MODULES
VERIFY_RUST_WITH_C_TESTS
MIGRATE_TESTS
BUILD_TEST_REPAIR
REPORT_AND_VERIFY
```

`VERIFY_RUST_WITH_C_TESTS` runs after core Rust modules exist and before Rust tests are migrated.

## Stage Contract

Inputs:

```text
logs/trace/input_manifest.json
logs/trace/c_project_model.json
logs/trace/c_api_model.json
logs/trace/c_test_model.json
logs/trace/rust_api_design.json
flashDB_rust/
```

Outputs:

```text
logs/trace/c-cross/cross-compile.log
logs/trace/c-cross/cross-test.log
logs/trace/validation-matrix.json
logs/trace/06-5-verify-rust-with-c-tests.md
logs/trace/workflow_state.json
```

Tool entrypoint:

```bash
python3 work/tools/c_cross_validate.py \
  --root . \
  --project flashDB_rust \
  --out logs/trace
python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS
```

The stage is a workbench-only validation step. It may compile temporary C harness code under `logs/trace/c-cross/` or another trace-owned temporary directory, but it must not copy C source files into `flashDB_rust/src/` or make the final Rust project depend on the C implementation.

## Rust ABI Strategy

The Rust implementation must expose the C API needed by the original tests through a gated facade:

```rust
#[cfg(feature = "c-abi-test")]
pub mod c_abi;
```

The facade should export only test-validation symbols:

```rust
#[no_mangle]
pub extern "C" fn fdb_kv_set(...) -> i32 {
    ...
}
```

`Cargo.toml` should include a feature and library type suitable for temporary C linkage:

```toml
[features]
c-abi-test = []

[lib]
crate-type = ["rlib", "staticlib"]
```

The default final path remains Rust-native. C ABI exposure is for workbench validation and should be compiled only when the validation tool enables `--features c-abi-test`.

## C Test Harness Strategy

`c_cross_validate.py` should:

1. Build the Rust project as a static library with `c-abi-test` enabled.
2. Prepare a temporary harness directory under `logs/trace/c-cross/`.
3. Compile original C test files from the input manifest, replacing the linked FlashDB implementation with the Rust static library.
4. Run the C test executable or per-scenario executables.
5. Map results back to `c_test_model.json.scorer_standard_cases`.
6. Write `validation-matrix.json`.

The first implementation may support a limited but explicit subset of C test patterns. Unsupported cases must be reported as `not_supported`, not silently treated as pass.

## Validation Matrix

`validation-matrix.json` records scenario-level evidence:

```json
{
  "stage": "VERIFY_RUST_WITH_C_TESTS",
  "total_scenarios": 24,
  "summary": {
    "rust_impl_c_test": {
      "pass": 20,
      "fail": 2,
      "not_supported": 2
    }
  },
  "scenarios": [
    {
      "scenario_id": "test_fdb_kv_set",
      "scorer_case_id": "1",
      "suite": "kvdb",
      "c_impl_c_test": "baseline",
      "rust_impl_c_test": "pass",
      "c_impl_rust_test": "not_run",
      "rust_impl_rust_test": "pending",
      "diagnosis": "rust_implementation_matches_c_baseline_for_scenario",
      "log": "logs/trace/c-cross/test_fdb_kv_set.log"
    }
  ]
}
```

Allowed cell values:

```text
baseline
pass
fail
not_run
not_supported
pending
```

Allowed diagnosis values:

```text
rust_implementation_matches_c_baseline_for_scenario
rust_implementation_failed_c_baseline
c_cross_harness_not_supported
blocked_before_rust_test_migration
rust_test_migration_pending
```

## Gate Behavior

`gate.py --stage VERIFY_RUST_WITH_C_TESTS` must check:

- `workflow_state.json.current_stage == VERIFY_RUST_WITH_C_TESTS`.
- `workflow_state.json.checkpoint == VERIFY_RUST_WITH_C_TESTS`.
- `completed_stages` includes every previous stage through `VERIFY_RUST_WITH_C_TESTS`.
- `logs/trace/validation-matrix.json` exists and is valid JSON.
- Matrix scenario IDs exactly match `c_test_model.json.scorer_standard_cases[*].scenario_id`.
- Matrix scorer case IDs exactly match `c_test_model.json.scorer_standard_cases[*].case_id`.
- Every scenario has a valid `rust_impl_c_test` value.
- `fail` blocks progression to `MIGRATE_TESTS`.
- `not_supported` is allowed only when a scenario includes an explicit reason and log path.
- No C source files exist under `flashDB_rust/src/`.

The first implementation should allow a configurable policy for `not_supported`:

```text
strict: not_supported blocks progression
advisory: not_supported is reported but does not block progression
```

The default for this competition workbench should be `advisory` while the harness is incomplete, then move to `strict` when the supported scenario coverage is mature.

## Failure Routing

Failure interpretation:

```text
VERIFY_RUST_WITH_C_TESTS fails:
  Fix Rust implementation or c-abi-test facade before migrating Rust tests.

VERIFY_RUST_WITH_C_TESTS passes, MIGRATE_TESTS fails:
  Fix Rust test migration, rust_test_mapping.json, or semantic obligations.

VERIFY_RUST_WITH_C_TESTS passes, MIGRATE_TESTS passes, BUILD_TEST_REPAIR fails:
  Fix Rust test harness, Cargo configuration, visibility, or final behavior mismatch.
```

This is the main value of the matrix: it prevents the repair loop from changing Rust tests when the Rust implementation is the actual failing component.

## Documentation Updates

The implementation must update:

- `02_02/work/skills/flashdb-orchestrator.md`
- `design_doc/stages/README.md`
- `design_doc/stages/06-rewrite-core-modules.md`
- `design_doc/stages/07-migrate-tests.md`
- `design_doc/stages/08-build-test-repair.md`
- `design_doc/stages/09-report-and-verify.md`
- `design_doc/参赛工程设计文档.md`

The existing `07-migrate-tests` docs currently mention `cargo-test-after-migrate.log` and `test-after-migrate.json`, while the current `gate.py` no longer checks those files. The implementation should resolve that mismatch by making `MIGRATE_TESTS` responsible for Rust test semantic mapping only and keeping cargo pass/fail evidence in `BUILD_TEST_REPAIR`.

## Non-Goals

- Do not make the final submitted Rust project depend on FlashDB C implementation files.
- Do not copy C sources into `flashDB_rust/src/`.
- Do not require all C test framework patterns to be supported in the first implementation.
- Do not replace `MIGRATE_TESTS`; this stage validates Rust source behavior before Rust tests are migrated.
- Do not treat `validation-matrix.json` as a scoring replacement. It is diagnostic evidence for the workbench.
