# 07 - MIGRATE_TESTS

## 目标

把 C 测试语义迁移为 Rust 测试，覆盖 KVDB 和 TSDB 主干场景。若真实 FlashDB 输入包含额外测试文件或扩展场景，本阶段必须记录并迁移、归入扩展测试，或明确说明排除原因。

本阶段必须在 `VERIFY_RUST_WITH_C_TESTS` gate 通过后执行。此时 Rust 核心实现已经用原始 C 测试证据做过基线验证，本阶段只负责把 C 测试语义迁移为 Rust 测试并维护 `rust_test_mapping.json`。

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

`MIGRATE_TESTS` 阶段不强制 `cargo test` 通过；它强制测试被生成、映射被记录、语义义务被验证。最终 cargo build/test 由 `BUILD_TEST_REPAIR` 归档并修复。

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
python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS
# opencode 调用 test-migrator subagent 生成 Rust tests
python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project flashDB_rust --mapping logs/trace/rust_test_mapping.json
python3 work/tools/gate.py --stage MIGRATE_TESTS
```

## Gate 检查

`gate.py --stage MIGRATE_TESTS` 必须检查：

- `kvdb_tests.rs` 存在；
- `tsdb_tests.rs` 存在；
- `equivalence_tests.rs` 存在；
- `rust_test_mapping.json` 存在；
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

成功后进入 `BUILD_TEST_REPAIR`。下一阶段运行并归档最终 cargo build/test，并允许根据错误栈做最小修复。
