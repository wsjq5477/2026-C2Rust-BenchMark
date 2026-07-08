---
name: flashdb-test-migration
description: 用于迁移 FlashDB C 测试，生成具备等价 KVDB 和 TSDB 覆盖的 Rust 测试。
---

# FlashDB 测试迁移

## 适用范围

仅当 orchestrator 进入 `MIGRATE_TESTS` 后使用此 Skill。

## MIGRATE_TESTS 契约

- 读取 `logs/trace/c_test_model.json`；
- 读取 `logs/trace/rust_api_design.json`；
- 遵循 `work/knowledge/flashdb-test-map.md`；
- 使用 `c_test_model.json.scorer_standard_cases` 作为评分覆盖契约；
- 使用 `c_test_model.json.standard_scenarios` 作为动态 C 注册证据；
- 在 `flashDB_rust/tests/` 下生成 Rust 测试；
- 保持断言有实际语义；
- 写入 `logs/trace/rust_test_mapping.json`。

必需产出：

- `rust_test_mapping.json` 中声明的 Rust 测试文件；
- `logs/trace/07-migrate-tests.md`.

准确性规则：

- 测试必须从 C 测试事实和已固定的 Rust API 推导；
- 保持 scorer-standard cases 与 Rust 测试之间的一对一映射；
- 使用每个 scorer case 的 `semantic_obligations` 和 `semantic_facts` 保留被调用 API、helper 行为、断言目标、测试数据规模和场景特征；
- 在将 `coverage` 设为 `semantic` 前，必须替换每个生成的 `MIGRATION_PENDING` baseline；
- 只有 Rust 测试实际覆盖的 obligations 才能写入 `validated_obligations`；
- `verify_*`、`data_shape:*`、`scenario:*` obligations 必须有 `assertion_evidence`，且 evidence 要能追溯到 C 测试、C 模型、规格或可计算事实；
- 覆盖分级必须区分：L1/API 调用覆盖、L2/断言意图覆盖、L3/数据规模和布局覆盖。`coverage: semantic` 至少达到 L2；高风险 `data_shape:*` 和 `scenario:*` case 必须达到 L3 或保持 pending；
- 不得把核心实现作为唯一真相来源；
- 不得删除 scenarios，也不得用恒真断言替代语义检查；
- 不得用浅层 `is_ok()`、`is_some()`、`is_none()` 断言证明深语义 obligation；
- 动态 scorer-facing 覆盖集合之外的新 FlashDB 测试必须作为证据、扩展覆盖或明确的 unmapped context 保留；
- 只要任何 scorer-standard case 缺失、pending、重复、额外、unmapped，或在没有 validated obligations 的情况下标记为 semantic，stage gate 就必须失败。
- `work/tools/test_consistency_check.py` 是 MIGRATE_TESTS 和 REPORT_AND_VERIFY 的预评分检查，发现 logic_mismatch、shallow_assertion 或 assertion evidence 缺口时必须回到测试迁移修复。
