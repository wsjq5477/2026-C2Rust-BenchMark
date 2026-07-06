# 07 - MIGRATE_TESTS

## 目标

把 C 测试语义迁移为 Rust 测试，覆盖 KVDB 和 TSDB 主干场景。若真实 FlashDB 输入包含额外测试文件或扩展场景，本阶段必须记录并迁移、归入扩展测试，或明确说明排除原因。

本阶段必须在 `REWRITE_CORE_MODULES` gate 通过后执行，因为测试需要依赖已经 `cargo check` 通过的真实 Rust API。`test-migrator` 可以使用 subagent，但只负责生成测试和映射；主控 Agent 负责运行并归档 `cargo test`。

## 执行主体

```text
flashdb-orchestrator
test-migrator subagent
flashdb-test-migration Skill
work/tools/gate.py
```

## 输入

```text
logs/trace/c_test_model.json
logs/trace/rust_api_design.json
flashDB_rust/src/
work/knowledge/flashdb-test-map.md
work/skills/flashdb-test-migration/SKILL.md
```

## 输出

```text
flashDB_rust/tests/kvdb_tests.rs
flashDB_rust/tests/tsdb_tests.rs
flashDB_rust/tests/equivalence_tests.rs
logs/trace/rust_test_mapping.json
logs/trace/cargo-test-after-migrate.log
logs/trace/test-after-migrate.json
logs/trace/07-migrate-tests.md
logs/trace/workflow_state.json
result/output.md
result/issues/00-summary.md
```

## 细节实现

`test-migrator` 只负责测试侧文件和测试映射：

```text
flashDB_rust/tests/
logs/trace/rust_test_mapping.json
```

主控 Agent 在 test-migrator 完成后必须运行：

```bash
cd flashDB_rust
cargo test
```

并记录：

```text
logs/trace/cargo-test-after-migrate.log
logs/trace/test-after-migrate.json
```

`MIGRATE_TESTS` 阶段不强制 `cargo test` 通过；它强制测试被生成、映射被记录、测试命令被执行并归档。若测试失败，进入 `BUILD_TEST_REPAIR` 做最终修复闭环。

`rust_test_mapping.json` 建议结构：

```json
{
  "kvdb": [],
  "tsdb": [],
  "extension": [],
  "unmapped": [],
  "total_scenarios": 24,
  "source_to_rust": {}
}
```

目标覆盖：

- KVDB：13 个标准场景；
- TSDB：11 个标准场景；
- 扩展测试：来自真实 FlashDB 新增测试文件或新增注册项；
- 每个测试必须有实际断言；
- 测试命名能追溯 C 测试或标准场景。

## 执行命令

```bash
python3 work/tools/gate.py --stage REWRITE_CORE_MODULES
# opencode 调用 test-migrator subagent 生成 Rust tests
cd flashDB_rust && cargo test
python3 ../work/tools/gate.py --stage MIGRATE_TESTS --root ..
```

## Gate 检查

`gate.py --stage MIGRATE_TESTS` 必须检查：

- `kvdb_tests.rs` 存在；
- `tsdb_tests.rs` 存在；
- `equivalence_tests.rs` 存在；
- `rust_test_mapping.json` 存在；
- `cargo-test-after-migrate.log` 存在；
- `test-after-migrate.json` 存在，记录 `cargo test` exit code；
- 映射覆盖 24 个标准场景；
- 新增 C 测试不能静默丢弃，必须进入 `extension`、`unmapped` 或带理由的排除记录；
- Rust 测试文件包含非恒真断言；
- 不删除 core 文件；
- `workflow_state.json.current_stage == MIGRATE_TESTS`。

## 约束

- 不大规模修改 `flashDB_rust/src/`。
- 不删除测试。
- 不弱化断言。
- 不把测试改成恒真。
- 不跳过 C 测试主干语义。
- 不要求本阶段自行修复所有测试失败；失败必须进入 08，由主控和 repairer 处理。

## 下一阶段交接

成功后进入 `BUILD_TEST_REPAIR`。下一阶段允许根据 cargo 错误栈做最小修复。
