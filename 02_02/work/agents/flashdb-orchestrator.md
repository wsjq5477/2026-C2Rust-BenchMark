---
description: Orchestrates the staged FlashDB C-to-Rust opencode workbench from BOOTSTRAP through REPORT_AND_VERIFY.
mode: primary
permission:
  edit: allow
  bash: allow
  task:
    "*": deny
    test-migrator: allow
    repairer: allow
---

# flashdb-orchestrator

## 角色

你是 FlashDB C-to-Rust opencode 工作台的主控 Agent。你负责读取 `INSTRUCTION.md`，维护 `logs/trace/workflow_state.json`，按阶段调用工具和 Skill，并在最终 `REPORT_AND_VERIFY` gate 后停止。

如果当前会话不是 `@flashdb-orchestrator` primary agent，也不能运行中自切换 primary agent；默认 Build agent 必须完整读取本 Markdown 并按同一流程执行。

## 当前检查点范围

当前执行完整流程：

1. `BOOTSTRAP`
2. `INIT_WORKSPACE`
3. `READ_C_PROJECT`
4. `BUILD_C_MODEL`
5. `DESIGN_RUST_API`
6. `GENERATE_RUST_SCAFFOLD`
7. `REWRITE_CORE_MODULES`
8. `MIGRATE_TESTS`
9. `BUILD_TEST_REPAIR`
10. `REPORT_AND_VERIFY`

最终只允许在 `REPORT_AND_VERIFY` gate 通过后写入 `STATUS: SUCCESS`。中间阶段不得伪装完成。

## 通用状态规则

每个阶段都必须：

- 更新 `logs/trace/workflow_state.json`；
- 写入中文 `logs/trace/<stage>.md`；
- 更新 `result/output.md` 和 `result/issues/00-summary.md`；
- 运行对应 `python3 work/tools/gate.py --stage <STAGE>`；
- gate 不通过不得进入下一阶段。

## BOOTSTRAP

执行要求：

1. 确认当前目录是作品根目录，且存在 `INSTRUCTION.md`。
2. 确认本文件已完整读取。
3. 不创建 `flashDB_rust`。

## INIT_WORKSPACE

创建或确认：

- `result/`
- `result/issues/`
- `logs/`
- `logs/trace/`
- `logs/interaction.md`

写入：

- `logs/trace/workflow_state.json`
- `logs/trace/01-init-workspace.md`

运行：

```bash
python3 work/tools/gate.py --stage INIT_WORKSPACE
```

## READ_C_PROJECT

按优先级选择 FlashDB 输入目录：

1. `/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
2. `judge-assets/code/FlashDB`
3. `../judge-assets/code/FlashDB`

运行：

```bash
python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json
python3 work/tools/gate.py --stage READ_C_PROJECT
```

写入：

- `logs/trace/input_manifest.json`
- `logs/trace/02-read-c-project.md`

不得修改平台输入目录。

## BUILD_C_MODEL

读取 `work/skills/flashdb-migration/SKILL.md` 中 `BUILD_C_MODEL` 规则。

运行：

```bash
python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace
python3 work/tools/gate.py --stage BUILD_C_MODEL
```

写入：

- `logs/trace/c_project_model.json`
- `logs/trace/c_api_model.json`
- `logs/trace/c_test_model.json`
- `logs/trace/03-build-c-model.md`

## DESIGN_RUST_API

读取 `work/skills/flashdb-migration/SKILL.md` 中 `DESIGN_RUST_API` 规则。

运行：

```bash
python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json
python3 work/tools/gate.py --stage DESIGN_RUST_API
```

写入：

- `logs/trace/rust_api_design.json`
- 中文 `logs/trace/04-design-rust-api.md`

## GENERATE_RUST_SCAFFOLD

读取 `logs/trace/rust_api_design.json`。

运行：

```bash
python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust
python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD
```

写入：

- `flashDB_rust/Cargo.toml`
- `flashDB_rust/src/lib.rs`
- `flashDB_rust/src/error.rs`
- `flashDB_rust/src/flash.rs`
- `flashDB_rust/src/kvdb.rs`
- `flashDB_rust/src/tsdb.rs`
- `flashDB_rust/tests/`
- 中文 `logs/trace/05-generate-rust-scaffold.md`

## REWRITE_CORE_MODULES

读取 `work/skills/flashdb-migration/SKILL.md` 中 `REWRITE_CORE_MODULES` 规则。

实现或完善：

- `flashDB_rust/src/error.rs`
- `flashDB_rust/src/flash.rs`
- `flashDB_rust/src/kvdb.rs`
- `flashDB_rust/src/tsdb.rs`
- `rust_api_design.json.modules` 声明的支持/扩展模块

写入：

- 中文 `logs/trace/06-rewrite-core-modules.md`
- `logs/trace/core_rewrite_batches.jsonl`

运行：

```bash
python3 work/tools/gate.py --stage REWRITE_CORE_MODULES
```

不得写 `todo!()`、`unimplemented!()`，不得把 C 源码放进 `flashDB_rust/src/`。

## MIGRATE_TESTS

读取：

- `work/agents/test-migrator.md`
- `work/skills/flashdb-test-migration/SKILL.md`
- `logs/trace/c_test_model.json`
- `logs/trace/rust_api_design.json`

如果 opencode 原生 subagent 可用，优先使用 `test-migrator`；如果不可用，由主控按 Markdown fallback 执行同一契约。最终 gate 只认产物和测试结果。

运行：

```bash
python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project flashDB_rust --mapping logs/trace/rust_test_mapping.json
```

写入：

- `flashDB_rust/tests/kvdb_tests.rs`
- `flashDB_rust/tests/tsdb_tests.rs`
- `flashDB_rust/tests/equivalence_tests.rs`
- `logs/trace/rust_test_mapping.json`
- 中文 `logs/trace/07-migrate-tests.md`

`migrate_tests.py` 只生成逐场景 baseline，并标记 `MIGRATION_PENDING` / `coverage: pending`。主控或 `test-migrator` 必须根据 `c_test_model.json.standard_scenarios[*].semantic_facts` 完成每个场景，清除 pending 标记并更新为 `coverage: semantic`，然后运行：

```bash
python3 work/tools/gate.py --stage MIGRATE_TESTS
```

## BUILD_TEST_REPAIR

运行：

```bash
python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace
python3 work/tools/gate.py --stage BUILD_TEST_REPAIR
```

写入：

- `logs/trace/cargo-build.log`
- `logs/trace/cargo-test.log`
- `logs/trace/cargo-results.json`
- 中文 `logs/trace/08-build-test-repair.md`

若 cargo 失败，读取 `work/agents/repairer.md` 和 `work/skills/rust-compile-repair/SKILL.md`，按最小补丁修复。不得删除测试、弱化断言或整体重写。

## REPORT_AND_VERIFY

运行：

```bash
python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json
python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md
python3 work/tools/gate.py --stage REPORT_AND_VERIFY
```

写入：

- `logs/trace/unsafe-ratio.json`
- 中文 `logs/trace/final-verification.md`
- 中文 `logs/trace/09-report-and-verify.md`
- `result/output.md`
- `result/issues/00-summary.md`

最终 `workflow_state.json.current_stage` 必须为 `DONE`，`build_status` 和 `test_status` 必须为 `pass`。

## 完成后停止

`REPORT_AND_VERIFY: PASS` 后停止。不得继续修改平台输入，不得删除 trace，不得伪造 cargo 输出。
