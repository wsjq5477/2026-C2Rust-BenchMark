---
name: flashdb-test-migration
description: 用于迁移 FlashDB C 测试，生成具备等价 KVDB 和 TSDB 覆盖的 Rust 测试。
---

# FlashDB 测试迁移

## 适用范围

仅当 orchestrator 进入 `TEST_AND_REPORT` 的测试迁移部分后使用此 Skill。

## MIGRATE_TESTS 契约

- 读取 `logs/trace/c_test_model.json` 的相关局部片段；
- 读取 `logs/trace/rust_api_design.json` 的相关局部片段；
- 遵循 `work/knowledge/flashdb-test-map.md`；
- 使用 `c_test_model.json.scorer_standard_cases` 作为评分覆盖契约；
- 在 `flashDB_rust/tests/` 下生成 Rust 测试；
- 保持断言有实际语义；
- 写入 `logs/trace/rust_test_mapping.json`。
- `migrate_tests.py` 只生成动态任务映射，不创建或覆盖测试文件；测试体必须从证据直接重写；
- mapping 生成后 orchestrator 必须按动态 `rust_file` 分组调用 `test-migrator`，不得跳过测试体实现直接进入验证；
- 场景数量必须从当前 `scorer_standard_cases` 推导，不得预置固定总数；

必需产出：

- `rust_test_mapping.json` 中声明的 Rust 测试文件；
- `logs/trace/07-migrate-tests.md`.

准确性规则：

- 测试必须从 C 测试事实和已固定的 Rust API 推导；
- 保持 scorer-standard cases 与 Rust 测试之间的一对一映射；
- 使用每个 scorer case 的 `semantic_obligations` 和 `semantic_facts` 作为阅读导航，保留被调用 API、helper 行为、断言目标、测试数据规模和场景特征；
- 评分一致性预检动态输出 `c_only`、`logic_mismatch`、`rust_only`：前两者失败，`rust_only` 仅 warning；不预置 case 名或数量；
- 必须写入真实测试；`implementation_status` 只保留为任务提示，不能替代源码、Cargo 或 semantic review 证据；
- 不生成 `MIGRATION_PENDING`、`todo!()`、恒真断言等占位 baseline；不得通过机械修改 `implementation_status` 宣称完成；
- `validated_obligations`、`api_evidence`、`data_evidence` 和 `assertion_evidence` 仅用于帮助 reviewer 定位，不能作为最终 semantic pass 的依据；
- 不得把核心实现作为唯一真相来源；
- 不得删除 scenarios，也不得用恒真断言替代语义检查；
- 不得用浅层 `is_ok()`、`is_some()`、`is_none()` 断言证明深语义 obligation；
- 动态 scorer-facing 覆盖集合之外的新 FlashDB 测试必须作为证据、扩展覆盖或明确的 unmapped context 保留；
- 只要任何 scorer-standard case 缺失、pending、重复、额外或 unmapped，stage gate 就必须失败。
- `work/subagent/test-semantic-reviewer.md` 是独立只读的预评分审查合同。它必须逐 case 阅读 C/Rust 源码并比较场景、API、数据、配置、生命周期、顺序和断言；Reviewer 不得修改 tests 或 mapping。
- `work/tools/test_consistency_check.py` 校验 reviewer 的动态覆盖、源码 evidence、文件指纹和 JSON 合同；发现 logic_mismatch、unresolved 或证据失效时必须回到测试迁移修复。
- `work/tools/placeholder_check.py` 是确定性占位检查；其失败与一致性检查失败一样必须回到测试迁移修复。
- placeholder 为 `repair_required` 时不得运行 Cargo、unsafe 或报告；placeholder 通过，或修复预算耗尽后为了保留最终诊断，才运行 Cargo。
- Cargo 必须从真实输出确认每个动态映射测试实际执行；0 tests、missing 或 ignored 映射测试都不是通过。
- Cargo 通过后才生成 fresh semantic review。测试或 mapping 每次修改后必须从 placeholder、Cargo、Reviewer、consistency 完整重跑，并在 unsafe/report 前通过 `gate.py --stage TEST_AND_REPORT`。
- 默认不全文读取 trace 大 JSON、C 源码、总设计文档或历史报告；需要 C 测试事实时只读取相关场景或测试函数窗口。
