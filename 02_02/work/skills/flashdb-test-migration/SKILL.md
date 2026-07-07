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
- 使用每个 scorer case 的 `semantic_obligations` 和 `semantic_facts` 保留被调用 API、helper 行为和断言意图；
- 在将 `coverage` 设为 `semantic` 前，必须替换每个生成的 `MIGRATION_PENDING` baseline；
- 只有 Rust 测试实际覆盖的 obligations 才能写入 `validated_obligations`；
- 不得把核心实现作为唯一真相来源；
- 不得删除 scenarios，也不得用恒真断言替代语义检查；
- 动态 scorer-facing 覆盖集合之外的新 FlashDB 测试必须作为证据、扩展覆盖或明确的 unmapped context 保留；
- 只要任何 scorer-standard case 缺失、pending、重复、额外、unmapped，或在没有 validated obligations 的情况下标记为 semantic，stage gate 就必须失败。
