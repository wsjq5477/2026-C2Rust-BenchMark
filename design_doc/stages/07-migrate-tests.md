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
logs/trace/c_test_model.json 的相关局部片段
logs/trace/rust_api_design.json 的相关局部片段
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
```

## 细节实现

`test-migrator` 只负责测试侧文件和测试映射：

```text
flashDB_rust/tests/
logs/trace/rust_test_mapping.json
```

`MIGRATE_TESTS` 阶段不强制 `cargo test` 通过；它强制测试被生成、映射被记录、语义义务被验证。最终 cargo build/test 由 `BUILD_TEST_REPAIR` 归档并修复。

本阶段默认不全文读取 trace 大 JSON、C 源码、总设计文档或历史报告；需要 C 测试事实时只读取相关场景或测试函数窗口。

`rust_test_mapping.json` 建议结构：

```json
{
  "kvdb": [],
  "tsdb": [],
  "extension": [],
  "unmapped": [],
  "total_scenarios": "从 scorer_standard_cases 动态推导",
  "source_to_rust": {},
  "assertion_evidence": []
}
```

每个关键断言必须能追溯期望值来源。`assertion_evidence` 至少记录：

```json
{
  "rust_test": "kvdb_test_fdb_create_kv_blob",
  "assertion": "value_len == 21",
  "expected": 21,
  "source": "c_test_model.scorer_standard_cases[kvdb_create_kv_blob]",
  "evidence": "input blob bytes are derived from hello_world_blob_data",
  "validated_obligation": "blob read returns the bytes written by blob create"
}
```

没有 C 测试、C 模型、规格或可计算事实支撑的期望值，不得标记为 `coverage: semantic`。这类测试必须保持 `coverage: pending` 或写入待补证据记录，不能把拍脑袋的 Rust 断言作为后续修实现的依据。

覆盖分级：

- L1/API 调用覆盖：Rust 测试调用了 C scenario 对应 API，但不能标记为 `coverage: semantic`；
- L2/断言意图覆盖：Rust 断言验证了 C assert 的同类属性，可作为普通 semantic；
- L3/数据规模和布局覆盖：Rust 测试保留 C 的 KV/TSL 数量、blob 大小、sector 边界、状态组合和重启恢复，高风险 `data_shape:*` / `scenario:*` case 必须达到此级别。

目标覆盖：

- KVDB、TSDB 及其他 suite 的场景数量均从当前输入动态推导；
- 扩展测试：来自真实 FlashDB 新增测试文件或新增注册项；
- 每个测试必须有实际断言；
- 测试命名能追溯 C 测试或标准场景。

## 执行命令

```bash
python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS
# opencode 调用 test-migrator subagent 生成 Rust tests
python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project flashDB_rust --mapping logs/trace/rust_test_mapping.json
python3 work/tools/placeholder_check.py --root . --tests flashDB_rust/tests --mapping logs/trace/rust_test_mapping.json --output logs/trace/test-placeholder-check.json
python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json
python3 work/tools/gate.py --stage MIGRATE_TESTS
```

## Gate 检查

`gate.py --stage MIGRATE_TESTS` 必须检查：

- `kvdb_tests.rs` 存在；
- `tsdb_tests.rs` 存在；
- `equivalence_tests.rs` 存在；
- `rust_test_mapping.json` 存在；
- 映射与当前 `scorer_standard_cases` 动态推导的全部场景一一对应；
- 新增 C 测试不能静默丢弃，必须进入 `extension`、`unmapped` 或带理由的排除记录；
- Rust 测试文件包含非恒真断言；
- `test-placeholder-check.json` 必须通过，不存在占位宏、占位标记、恒真断言、忽略测试、缺失测试函数或缺失断言；
- `coverage: semantic` 的测试必须有对应 `assertion_evidence` 或等价的 `validated_obligations`；
- 关键 expected value 必须能追溯到 C 测试、C 模型、规格或可计算事实；
- `test-consistency.json` 必须通过；若发现 `missing_assertion_evidence`、`rust_assertion_count_below_threshold`、`missing_direct_verify_obligation` 或 `shallow_assertion_dominance`，本阶段失败并回到测试迁移；
- 不删除 core 文件；
- `workflow_state.json.current_stage == MIGRATE_TESTS`。

## 约束

- 不大规模修改 `flashDB_rust/src/`。
- 不删除测试。
- 不弱化断言。
- 不把测试改成恒真。
- 不跳过 C 测试主干语义。
- 不要求本阶段自行修复所有测试失败；失败必须进入 08，由主控和 repairer 处理。
- `migrate_tests.py` 只生成任务映射，不创建或覆盖测试文件；真实测试由 `test-migrator` 编写。
- `gate.py` 只校验事实，不承担路由。

## 下一阶段交接

成功后进入 `BUILD_TEST_REPAIR`。下一阶段运行并归档最终 cargo build/test，并允许根据错误栈做最小修复。
