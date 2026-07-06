---
name: flashdb-migration
description: Use when FlashDB C project modeling and Rust API migration are required during the staged opencode C-to-Rust workbench.
---

# FlashDB Migration

## Scope

Use this Skill only after the orchestrator enters `BUILD_C_MODEL`, `DESIGN_RUST_API`, `GENERATE_RUST_SCAFFOLD`, or `REWRITE_CORE_MODULES`.

The full workflow uses this Skill for `BUILD_C_MODEL`, `DESIGN_RUST_API`, `GENERATE_RUST_SCAFFOLD`, and `REWRITE_CORE_MODULES`. First extract C facts and write model artifacts; then design the safe Rust API boundary; then generate the Rust scaffold; finally implement the core Rust modules.

## BUILD_C_MODEL contract

Read:

- `logs/trace/input_manifest.json`;
- FlashDB `src/`, `inc/`, and `tests/` files listed in the manifest.

Produce:

- `logs/trace/c_project_model.json`;
- `logs/trace/c_api_model.json`;
- `logs/trace/c_test_model.json`;
- `logs/trace/03-build-c-model.md`.

This stage records facts only:

- source/test/header file classification;
- include relationships;
- public C functions;
- struct, typedef, enum, enum value, and macro names;
- registered KVDB and TSDB test functions.

Boundary:

- 不做 Clang AST；
- 不做宏展开；
- 不做完整调用图；
- 不解析函数体业务语义；
- 不做 Rust API 决策。

Do not design `FlashStorage`, `KvDb`, `TsDb`, or any Rust public API in this stage.

## DESIGN_RUST_API contract

Read:

- `logs/trace/c_project_model.json`;
- `logs/trace/c_api_model.json`;
- `logs/trace/c_test_model.json`;
- `work/knowledge/flashdb-rust-architecture.md`.

Produce:

- `logs/trace/rust_api_design.json`;
- `logs/trace/04-design-rust-api.md`.

This stage makes Rust API decisions:

- crate name: `flashdb_rust`;
- modules: `error`, `flash`, `kvdb`, `tsdb`;
- core types: `FlashStorage`, `MemFlash`, `FileFlash`, `FdbError`, `KvDb`, `TsDb`, `TslRecord`;
- error model: `Result<T, FdbError>`;
- KVDB API surface derived from `fdb_kvdb_init`, `fdb_kv_set`, `fdb_kv_get`, `fdb_kv_del`, iterator and GC-related symbols;
- TSDB API surface derived from `fdb_tsdb_init`, `fdb_tsl_append`, `fdb_tsl_iter`, `fdb_tsl_iter_by_time`, `fdb_tsl_set_status`, and `fdb_tsl_clean`;
- C test groups mapped to future Rust integration test files.

Boundary:

- 不生成 `flashDB_rust`；
- 不写 Rust 源码；
- 不运行 `cargo`；
- 不进入 `GENERATE_RUST_SCAFFOLD`；
- 阶段日志 `logs/trace/04-design-rust-api.md` 必须使用中文。

## GENERATE_RUST_SCAFFOLD contract

Read:

- `logs/trace/rust_api_design.json`;
- `work/knowledge/flashdb-rust-architecture.md`.

Produce:

- `flashDB_rust/Cargo.toml`;
- `flashDB_rust/src/lib.rs`;
- `flashDB_rust/src/error.rs`;
- `flashDB_rust/src/flash.rs`;
- `flashDB_rust/src/kvdb.rs`;
- `flashDB_rust/src/tsdb.rs`;
- any support or extension modules declared by `rust_api_design.json.modules`;
- `logs/trace/05-generate-rust-scaffold.md`.

Boundary:

- 可以创建 `flashDB_rust`；
- 不链接 C 源码；
- 不迁移测试；
- API shape must follow `rust_api_design.json`.

## REWRITE_CORE_MODULES contract

Read:

- `logs/trace/rust_api_design.json`;
- `logs/trace/c_project_model.json`;
- `logs/trace/c_api_model.json`;
- `flashDB_rust/src/`.

Produce:

- implemented `error`, `flash`, `kvdb`, `tsdb`, and support/extension modules;
- `logs/trace/06-rewrite-core-modules.md`;
- `logs/trace/core_rewrite_batches.jsonl`.

Implementation rules:

- preserve FlashDB KVDB and TSDB semantics;
- record append, tombstone delete, reload scan, and gc retain-latest behavior must remain visible in design or implementation evidence;
- use safe Rust first;
- do not add `.c` files to `flashDB_rust/src`;
- do not leave `todo!()`, `unimplemented!()`, or panic-based placeholders.

## Full-stage coherence

Preserve one coherent view of:

- FlashDB source files and public API;
- KVDB and TSDB state transitions;
- storage abstraction boundaries;
- Rust module ownership;
- source-to-Rust evidence in `logs/trace`.

Derive the Rust project from the platform C input and the stage artifacts.
