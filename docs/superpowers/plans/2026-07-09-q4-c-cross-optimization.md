# Q4 C Cross Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Q4 plan so C ABI facts are modeled before Rust implementation and C cross failures become layered, scenario-level diagnostics.

**Architecture:** Move ABI knowledge forward through the workbench: BUILD_C_MODEL emits function signatures and unresolved evidence, DESIGN_RUST_API turns those facts into a complete `c_abi_facade`, GENERATE_RUST_SCAFFOLD emits typed FFI, and VERIFY_RUST_WITH_C_TESTS reports build/layout/link/full diagnostics. Each task updates gates, docs, and tests for its contract before moving to the next layer.

**Tech Stack:** Python stdlib tools under `02_02/work/tools`, `unittest` guardrails under `02_02/tests`, C compiler probe via `cc`/`gcc`/`clang`, Rust scaffold generation, Markdown workflow docs.

## Global Constraints

- Adopt “方案 B：C ABI 合同前移 + 分层 C cross 诊断”.
- Do not add a global `VERIFY_RUST_ABI` stage; use `VERIFY_RUST_WITH_C_TESTS --mode build|layout|link|full`.
- Do not use `_opaque` for structs observed by C runner or layout checker; generate real `#[repr(C)]` fields and explicit padding.
- Use lightweight parser + C compiler probe, not mandatory libclang/Clang AST.
- Fail gates for unresolved signatures/types on C runner, scorer, or layout-checker critical paths.
- Keep `c_type_map` at ABI-wrapper granularity: primitive, typedef, enum/status, struct value/pointer, string/pointer/buffer, ownership/nullability, callback support/unresolved.
- Scaffold must generate typed FFI files and real ABI signatures before core rewrite.
- C cross diagnostics target C test function granularity first; assert-level structure is not required in the first pass.
- Failed matrix scenarios must include `failure_layer`, `diagnosis`, `reason`, `log`, and `handoff`.
- Machine identifiers stay English and stable; Chinese human-facing prose is allowed.
- Do not hardcode fixed function names, runner names, or case counts.

---

### Task 1: BUILD_C_MODEL Signature Facts

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/build_c_model.py`
- Modify: `02_02/work/tools/gate.py`
- Modify: `design_doc/stages/03-build-c-model.md`
- Modify: `02_02/work/skills/c-analyzer.md`

**Interfaces:**
- Produces: `c_api_model.json.function_signatures`, `typedef_map`, `enum_map`, `unresolved_signatures`, `unresolved_types`.
- Produces: `c_test_model.json.registered_test_invocations`.
- Gate: `BUILD_C_MODEL` rejects missing required signatures and malformed unresolved records.

- [x] Write failing tests that require dynamic function signatures, typed params/returns, and strict gate rejection for missing critical signatures.
- [x] Implement lightweight declaration parsing and canonical signature emission in `build_c_model.py`.
- [x] Add `registered_test_invocations` to the test model using current registered tests and dynamically derived scenarios.
- [x] Harden `gate.py --stage BUILD_C_MODEL` for required signatures and unresolved records.
- [x] Update stage and c-analyzer docs for the signature contract.
- [x] Verify with targeted unittest, `py_compile`, and `git diff --check`.

### Task 2: DESIGN_RUST_API C ABI Facade Contract

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/design_rust_api.py`
- Modify: `02_02/work/tools/gate.py`
- Modify: `design_doc/stages/04-design-rust-api.md`
- Modify: `02_02/work/skills/c-analyzer.md`

**Interfaces:**
- Consumes: `c_api_model.json.function_signatures`, `typedef_map`, `enum_map`, `abi_layouts`.
- Produces: `rust_api_design.json.c_abi_facade.functions`.
- Produces: `rust_api_design.json.c_abi_facade.c_type_map`.

- [x] Write failing tests for facade functions, `source_signature`, `rust_ffi_type`, and critical unresolved type rejection.
- [x] Implement C type mapping at ABI-wrapper granularity.
- [x] Generate facade functions from required C symbols and function signatures.
- [x] Harden `DESIGN_RUST_API` gate for facade functions and type map.
- [x] Update docs and verify targeted tests.

### Task 3: Typed FFI Scaffold

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/generate_rust_scaffold.py`
- Modify: `02_02/work/tools/gate.py`
- Modify: `design_doc/stages/05-generate-rust-scaffold.md`
- Modify: `02_02/work/skills/rust-implementer.md`

**Interfaces:**
- Consumes: `rust_api_design.json.c_abi_facade.structs`, `functions`, and `c_type_map`.
- Produces: `flashDB_rust/src/ffi/mod.rs`, `c_types.rs`, `c_abi.rs`, `layout_probe.rs`.

- [x] Write failing tests that reject all-`c_void` placeholder ABI and constant-only layout probes.
- [x] Generate typed `#[repr(C)]` structs with explicit padding where enough layout evidence exists.
- [x] Generate typed `extern "C"` exports with neutral default return bodies.
- [x] Generate real Rust layout probes from actual Rust types.
- [x] Harden scaffold gate and update docs.
- [x] Verify targeted tests and scaffold py_compile.

### Task 4: Layered C Cross Diagnostics

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/c_cross_validate.py`
- Modify: `02_02/work/tools/gate.py`
- Modify: `02_02/work/tools/report_writer.py`
- Modify: `design_doc/stages/06-5-verify-rust-with-c-tests.md`
- Modify: `02_02/work/skills/rust-implementer.md`
- Modify: `02_02/work/skills/repairer.md`

**Interfaces:**
- Produces: `build-check.json`, `layout-check.json`, `link-check.json`, `case-results.jsonl`, `diagnostics.jsonl`.
- Extends: `validation-matrix.json.scenarios[]` with `failure_layer`, `source_runner`, `source_test`, and `handoff`.

- [x] Write failing tests for `--mode build|layout|link|full` and required failed-scenario diagnostics.
- [x] Implement mode handling without adding a global stage.
- [x] Map registered `TEST_RUN` evidence to source tests and scenarios.
- [x] Emit layered diagnostics and report summaries.
- [x] Harden gate for failed scenario diagnostic fields and allowed handoff values.
- [x] Verify targeted tests and py_compile.

### Task 5: Contract Synchronization

**Files:**
- Modify: `02_02/INSTRUCTION.md`
- Modify: `02_02/work/skills/*.md`
- Modify: `02_02/work/knowledge/*.md`
- Modify: `.opencode/skills/*`
- Modify: `design_doc/stages/*.md`
- Modify: `design_doc/参赛工程设计文档.md`
- Modify: `02_02/tests/test_conversion_system.py`

**Interfaces:**
- Aligns human docs, primary/subagent contracts, stage docs, mirrors, and final report expectations.

- [x] Add tests or assertions for the new documented contracts where they are part of the workbench guardrail.
- [x] Update docs without embedding fixed case/function lists.
- [x] Check mirror parity where mirrors exist.
- [x] Run broad contract tests and diff checks.
