# FlashDB C-to-Rust opencode 工作台执行说明

本文件是自动评测系统加载参赛作品的唯一入口。参赛作品的目标是让 opencode 在运行时读取平台提供的 FlashDB C 工程，逐阶段生成 `flashDB_rust/`，而不是提交预置 Rust 实现。

## 固定路径

- 作品根目录：本文件所在目录，评测环境通常为 `/app/code/02_02`
- 平台 C 输入：`/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
- 最终 Rust 输出：作品根目录下的 `flashDB_rust`
- 主控 Agent：`work/agents/flashdb-orchestrator.md`
- opencode 原生 Agent 镜像：`.opencode/agents/flashdb-orchestrator.md`
- opencode 原生 Skill 镜像：`.opencode/skills`
- 状态与证据：`logs/trace`
- 最终报告：`result/output.md` 和 `result/issues/00-summary.md`

## opencode 原生执行入口

work 目录仍为权威源。若评测环境或本地环境在启动 opencode 前已经把 `work/agents` 与 `work/skills` 复制到 `.opencode/agents` 与 `.opencode/skills`，并且如果启动前已经选择 flashdb-orchestrator 作为 primary agent，则由该 primary agent 执行本文件。

opencode 不能在会话中把当前 primary agent 自切换为另一个 primary agent。因此，如果当前会话已经由默认 Build agent 启动，不要求它运行中切换到 `@flashdb-orchestrator`，也不要为了形式条件调用 subagent。默认 Build agent 按普通 Markdown fallback 执行也满足本检查点：完整读取 `work/agents/flashdb-orchestrator.md` 并按其中要求执行。两种方式的阶段边界和禁止事项完全一致。

## 当前开发检查点

当前实现并验证完整检查点：`BOOTSTRAP + INIT_WORKSPACE + READ_C_PROJECT + BUILD_C_MODEL + DESIGN_RUST_API + GENERATE_RUST_SCAFFOLD + REWRITE_CORE_MODULES + MIGRATE_TESTS + BUILD_TEST_REPAIR + REPORT_AND_VERIFY`。

opencode 必须执行主控 Agent 文档中的完整流程。若会话启动时已经选中 `@flashdb-orchestrator` primary agent，则由它执行；否则由默认 Build agent 完整读取 `work/agents/flashdb-orchestrator.md` 后执行。

完成前不得写入 `STATUS: SUCCESS`。只有 `REPORT_AND_VERIFY` gate 通过后，才允许最终报告写入 `STATUS: SUCCESS`。

## 环境准备

1. 确认 `python3`、`cargo`、`rustfmt` 可执行。
2. 不依赖网络、API Key、Docker 或人工输入。
3. 不得修改平台提供的源码或测试。
4. 不得预置、复制或冒充 `flashDB_rust`；`flashDB_rust` 必须在 `GENERATE_RUST_SCAFFOLD` 阶段由 opencode 生成。
5. 如果进入 `INIT_WORKSPACE` 时作品根目录下已经存在 `flashDB_rust`，必须停止并报告异常。

## 自动执行命令总览

从作品根目录执行：

```bash
python3 work/tools/gate.py --stage INIT_WORKSPACE
python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json
python3 work/tools/gate.py --stage READ_C_PROJECT
python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace
python3 work/tools/gate.py --stage BUILD_C_MODEL
python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json
python3 work/tools/gate.py --stage DESIGN_RUST_API
python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust
python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD
python3 work/tools/gate.py --stage REWRITE_CORE_MODULES
python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project flashDB_rust --mapping logs/trace/rust_test_mapping.json
python3 work/tools/gate.py --stage MIGRATE_TESTS
python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace
python3 work/tools/gate.py --stage BUILD_TEST_REPAIR
python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json
python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md
python3 work/tools/gate.py --stage REPORT_AND_VERIFY
```

其中 `$FLASHDB_SOURCE` 必须按以下优先级选择第一个存在的目录：

1. `/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
2. `judge-assets/code/FlashDB`
3. `../judge-assets/code/FlashDB`

## 阶段执行要求

### INIT_WORKSPACE

1. 创建或确认 `result/`、`result/issues/`、`logs/`、`logs/trace/`、`logs/interaction.md`。
2. 写入 `logs/trace/workflow_state.json`，`current_stage` 为 `INIT_WORKSPACE`。
3. 写入中文 `logs/trace/01-init-workspace.md`。
4. 运行 `python3 work/tools/gate.py --stage INIT_WORKSPACE`。

### READ_C_PROJECT

1. 选择 `$FLASHDB_SOURCE`，只读取目录结构和文件清单，不修改平台输入。
2. 运行 `python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json`。
3. 写入中文 `logs/trace/02-read-c-project.md`。
4. 更新 `workflow_state.json`，记录 `input_path` 和 `input_manifest`。
5. 运行 `python3 work/tools/gate.py --stage READ_C_PROJECT`。

### BUILD_C_MODEL

1. 读取 `work/skills/flashdb-migration/SKILL.md` 中 `BUILD_C_MODEL` 规则。
2. 运行 `python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace`。
3. 生成 `logs/trace/c_project_model.json`、`logs/trace/c_api_model.json`、`logs/trace/c_test_model.json`。
4. 写入中文 `logs/trace/03-build-c-model.md`。
5. 更新 `workflow_state.json`。
6. 运行 `python3 work/tools/gate.py --stage BUILD_C_MODEL`。

### DESIGN_RUST_API

1. 读取 `work/skills/flashdb-migration/SKILL.md` 中 `DESIGN_RUST_API` 规则。
2. 运行 `python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json`。
3. 写入中文 `logs/trace/04-design-rust-api.md`，记录核心 API、扩展兼容、未映射符号和未生成源码边界。
4. 更新 `workflow_state.json`。
5. 运行 `python3 work/tools/gate.py --stage DESIGN_RUST_API`。

### GENERATE_RUST_SCAFFOLD

1. 读取 `logs/trace/rust_api_design.json`。
2. 运行 `python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust`。
3. 写入中文 `logs/trace/05-generate-rust-scaffold.md`。
4. 更新 `workflow_state.json`，`current_stage` 为 `GENERATE_RUST_SCAFFOLD`。
5. 运行 `python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD`。

### REWRITE_CORE_MODULES

1. 读取 `work/skills/flashdb-migration/SKILL.md` 中 `REWRITE_CORE_MODULES` 规则。
2. 基于 `rust_api_design.json` 和 C 模型完善 `flashDB_rust/src/` 中 `error`、`flash`、`kvdb`、`tsdb` 以及支持/扩展模块。
3. 不链接 C 源码，不写 `todo!()`、`unimplemented!()`。
4. 写入中文 `logs/trace/06-rewrite-core-modules.md` 和必要的 `logs/trace/core_rewrite_batches.jsonl`。
5. 更新 `workflow_state.json`，`current_stage` 为 `REWRITE_CORE_MODULES`。
6. 运行 `python3 work/tools/gate.py --stage REWRITE_CORE_MODULES`。

### MIGRATE_TESTS

1. 读取 `work/agents/test-migrator.md` 和 `work/skills/flashdb-test-migration/SKILL.md`。
2. 如果 opencode 原生 subagent 可用，优先用 `test-migrator`；如果不可用，主控按 Markdown fallback 执行同一契约。
3. 运行 `python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project flashDB_rust --mapping logs/trace/rust_test_mapping.json`。
4. 生成 `flashDB_rust/tests/kvdb_tests.rs`、`flashDB_rust/tests/tsdb_tests.rs`、`flashDB_rust/tests/equivalence_tests.rs`。
5. 写入中文 `logs/trace/07-migrate-tests.md`。
6. 更新 `workflow_state.json`，记录 `rust_test_mapping`。
7. 运行 `python3 work/tools/gate.py --stage MIGRATE_TESTS`。

### BUILD_TEST_REPAIR

1. 运行 `python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace`。
2. 如果 cargo 失败，读取 `work/agents/repairer.md` 和 `work/skills/rust-compile-repair/SKILL.md`，按最小补丁修复，最多 8 轮。
3. 写入中文 `logs/trace/08-build-test-repair.md`。
4. 更新 `workflow_state.json`，`build_status` 和 `test_status` 必须为 `pass`。
5. 运行 `python3 work/tools/gate.py --stage BUILD_TEST_REPAIR`。

### REPORT_AND_VERIFY

1. 运行 `python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json`。
2. 写入中文 `logs/trace/final-verification.md` 和 `logs/trace/09-report-and-verify.md`。
3. 更新 `workflow_state.json`，`current_stage` 为 `DONE`，`checkpoint` 为 `REPORT_AND_VERIFY`。
4. 运行 `python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md`。
5. 运行 `python3 work/tools/gate.py --stage REPORT_AND_VERIFY`。
6. gate 通过后，`result/output.md` 可保留 `STATUS: SUCCESS`。

## 完成判定

完整任务只在以下条件全部满足时通过：

- `logs/trace/workflow_state.json` 存在且 `current_stage == DONE`；
- 01 到 09 的中文阶段日志都存在；
- `logs/trace/input_manifest.json`、`c_project_model.json`、`c_api_model.json`、`c_test_model.json` 存在；
- `logs/trace/rust_api_design.json` 存在；
- `flashDB_rust/Cargo.toml`、`flashDB_rust/src/`、`flashDB_rust/tests/` 存在；
- `logs/trace/rust_test_mapping.json` 存在；
- `logs/trace/cargo-build.log`、`logs/trace/cargo-test.log` 存在且对应状态通过；
- `logs/trace/unsafe-ratio.json` 存在且 unsafe 比例低于 10%；
- `logs/trace/final-verification.md` 存在；
- `logs/trace/09-report-and-verify.md` 存在；
- `result/output.md` 包含 `STATUS: SUCCESS`；
- `result/issues/00-summary.md` 存在；
- `python3 work/tools/gate.py --stage REPORT_AND_VERIFY` 退出码为 0。

## 禁止事项

- 不得修改平台 FlashDB 输入目录。
- 不得把中间检查点写成最终成功。
- 不得删除测试或弱化断言。
- 不得把测试改成恒真。
- 不得在最终 Rust 项目中链接或编译 C 源码。
- 不得超过 unsafe 比例限制。
