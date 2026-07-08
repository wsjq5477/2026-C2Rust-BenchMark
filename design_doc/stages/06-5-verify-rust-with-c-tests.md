# 06.5 - VERIFY_RUST_WITH_C_TESTS

## 目标

在迁移 Rust 测试之前，用原始 C 测试场景验证已经完成的 Rust core。该阶段输出 2x2 验证矩阵中的 `Rust Impl x C Test` 证据，用于区分“Rust 实现错误”和“Rust 测试迁移错误”。

## 执行主体

```text
flashdb-orchestrator
work/tools/c_cross_validate.py
work/tools/gate.py
```

## 输入

```text
logs/trace/input_manifest.json
logs/trace/c_project_model.json
logs/trace/c_api_model.json
logs/trace/c_test_model.json
logs/trace/rust_api_design.json
flashDB_rust/
```

## 输出

```text
logs/trace/c-cross/cross-compile.log
logs/trace/c-cross/cross-test.log
logs/trace/validation-matrix.json
logs/trace/06-5-verify-rust-with-c-tests.md
logs/trace/workflow_state.json
result/output.md
result/issues/00-summary.md
```

## 细节实现

运行：

```bash
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace
python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS
```

第一版 `c_cross_validate.py` 允许 advisory 模式：暂不支持真实编译的 C harness 场景必须写成 `not_supported`，并为每个 scorer case 写入 `logs/trace/c-cross/*.log`。不得静默丢弃 scorer case，不得把 unsupported 当作 pass。

后续增强版本可以在 `--features c-abi-test` 下编译 Rust `staticlib`，再把原 C 测试链接到 Rust C ABI facade。该临时 harness 只能写入 `logs/trace/c-cross/`。

## validation-matrix.json

矩阵必须覆盖 `c_test_model.json.scorer_standard_cases`：

```json
{
  "stage": "VERIFY_RUST_WITH_C_TESTS",
  "policy": "advisory",
  "total_scenarios": 24,
  "summary": {
    "rust_impl_c_test": {
      "not_supported": 24
    }
  },
  "scenarios": []
}
```

每个 scenario 至少包含：

```text
scenario_id
scorer_case_id
suite
c_impl_c_test
rust_impl_c_test
c_impl_rust_test
rust_impl_rust_test
diagnosis
reason
log
```

## Gate 检查

`gate.py --stage VERIFY_RUST_WITH_C_TESTS` 必须检查：

- `workflow_state.json.current_stage == VERIFY_RUST_WITH_C_TESTS`；
- `workflow_state.json.checkpoint == VERIFY_RUST_WITH_C_TESTS`；
- `completed_stages` 包含从 `BOOTSTRAP` 到 `VERIFY_RUST_WITH_C_TESTS` 的连续阶段；
- `validation-matrix.json` 存在且合法；
- matrix scenario 与 scorer case 一一对应；
- `rust_impl_c_test == fail` 必须阻断后续阶段；
- `not_supported` 必须包含 reason 和 `logs/trace/c-cross/` 下的 log；
- `flashDB_rust/src/` 下递归不存在 `.c` 文件。

## 失败归因

- 本阶段 `fail`：优先修 Rust 实现或 C ABI 测试 facade。
- 本阶段通过但 `MIGRATE_TESTS` 失败：优先修 Rust 测试迁移和 `rust_test_mapping.json`。
- 本阶段和 `MIGRATE_TESTS` 都通过但 `BUILD_TEST_REPAIR` 失败：优先修 Rust 测试 harness、Cargo 配置或集成边界。

## 约束

- 不把 C 源码复制进 `flashDB_rust/src/`。
- 不让最终 Rust 项目依赖 FlashDB C 实现。
- 不把 `not_supported` 当作 `pass`。
- 不替代 `MIGRATE_TESTS`，只在 Rust 测试迁移前提供 C 基线证据。

## 下一阶段交接

成功后进入 `MIGRATE_TESTS`。
