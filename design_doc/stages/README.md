# FlashDB C-to-Rust 分层执行设计索引

本目录把整体迁移流程拆成可独立验收的阶段文档。每一层都只做自己的事，输出明确产物，再由 `gate.py` 做硬检查，防止 opencode 跳阶段或口头完成。

真实评测输入仍然是 FlashDB，但可能比本地样例包含更多目录、源码、头文件、测试和 public 符号。扩展兼容策略见：[FlashDB 真实输入扩展兼容策略](../flashdb-input-compatibility.md)。

## 阶段列表

| 顺序 | 阶段 | 文档 | 核心产物 |
|---:|---|---|---|
| 0 | BOOTSTRAP | [00-bootstrap.md](00-bootstrap.md) | 主控流程接管 |
| 1 | INIT_WORKSPACE | [01-init-workspace.md](01-init-workspace.md) | `workflow_state.json` |
| 2 | READ_C_PROJECT | [02-read-c-project.md](02-read-c-project.md) | `input_manifest.json` |
| 3 | BUILD_C_MODEL | [03-build-c-model.md](03-build-c-model.md) | `c_project_model.json` / `c_api_model.json` / `c_test_model.json` |
| 4 | DESIGN_RUST_API | [04-design-rust-api.md](04-design-rust-api.md) | `rust_api_design.json` |
| 5 | GENERATE_RUST_SCAFFOLD | [05-generate-rust-scaffold.md](05-generate-rust-scaffold.md) | `flashDB_rust/Cargo.toml` / `src/` / scaffold `cargo check` |
| 6 | REWRITE_CORE_MODULES | [06-rewrite-core-modules.md](06-rewrite-core-modules.md) | Rust core modules / per-batch `cargo check` |
| 6.5 | VERIFY_RUST_WITH_C_TESTS | [06-5-verify-rust-with-c-tests.md](06-5-verify-rust-with-c-tests.md) | `validation-matrix.json` / C tests on Rust evidence |
| 7 | MIGRATE_TESTS | [07-migrate-tests.md](07-migrate-tests.md) | Rust integration tests / `rust_test_mapping.json` |
| 8 | BUILD_TEST_REPAIR | [08-build-test-repair.md](08-build-test-repair.md) | cargo logs / repair trace |
| 9 | REPORT_AND_VERIFY | [09-report-and-verify.md](09-report-and-verify.md) | `result/output.md` / final verification |

## 分层原则

1. **C 事实与 API 设计同一上下文**：`READ_C_PROJECT`、`BUILD_C_MODEL`、`DESIGN_RUST_API` 是 `C_ANALYSIS` 阶段族，由一次 `c-analyzer` subagent 任务串行执行，避免重复拉起 subagent 和重复读取 C 工程。
2. **代码生成与语义实现分离**：`GENERATE_RUST_SCAFFOLD` 只生成项目骨架，`REWRITE_CORE_MODULES` 才实现业务逻辑。
3. **C 测试基线属于实现完成条件**：`VERIFY_RUST_WITH_C_TESTS` 由 `rust-implementer` 执行，在测试迁移前用原始 C 测试证据验证 Rust core，失败优先修实现或 C ABI facade。
4. **测试迁移独立验收**：`MIGRATE_TESTS` 只负责测试语义覆盖，不大规模修改 core。
5. **修复闭环独立**：`BUILD_TEST_REPAIR` 用 cargo 错误栈最小修复，禁止删除测试或弱化断言。
6. **报告只收口**：`REPORT_AND_VERIFY` 汇总证据，不补写缺失实现。
7. **核心域是下限，不是上限**：KVDB/TSDB/FlashStorage 必须覆盖，但真实 FlashDB 新增文件、目录和符号也必须被记录、分类、映射或显式排除。
8. **构建检查前移**：`GENERATE_RUST_SCAFFOLD` 后立即 `cargo check`，`REWRITE_CORE_MODULES` 每个实现批次后 `cargo check`，避免把骨架错误和核心实现错误堆到 `BUILD_TEST_REPAIR`。
9. **主控判定、subagent 执行**：重阶段优先由 `c-analyzer`、`rust-implementer`、`test-migrator`、`repairer` 执行；主控只做调度、状态推进、gate 和最终报告。原生 subagent 不可用时用通用 subagent 读取 `work/skills/{subagent}.md` 执行，连续 3 次 subagent 失败后才允许主控 fallback。

## 统一产物约定

所有阶段都应更新：

```text
logs/trace/workflow_state.json
logs/trace/<stage-log>.md
result/output.md
result/issues/00-summary.md
logs/trace/agent-registry.json
logs/trace/subagent-invocations.jsonl
```

每个阶段成功后，`workflow_state.json.current_stage` 应等于当前阶段名，`completed_stages` 应包含从 `BOOTSTRAP` 到当前阶段的连续阶段。

完整成功状态只能在 `REPORT_AND_VERIFY` 写入。中间阶段只能写检查点状态，不能写完整 `STATUS: SUCCESS`。
