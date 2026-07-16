---
name: rust-compile-repair
description: 用于 staged FlashDB migration 中 Rust build 或 test 失败后的最小化、证据驱动修复。
---

# Rust 编译修复

## 适用范围

仅当 orchestrator 进入 `BUILD_TEST_REPAIR` 后使用此 Skill。

## BUILD_TEST_REPAIR 契约

- 从捕获的 cargo 日志 tail 中分类 compiler 或 test 失败；
- 对 `cargo test` 失败，先运行 `python3 work/tools/test_failure_triage.py --root . --out logs/trace` 或读取已生成的 `logs/trace/test-failure-triage.jsonl`；
- 针对观察到的错误做最小补丁；
- triage 逐项列出全部失败及初始检查范围；assertion mismatch 默认是 `insufficient_evidence`，不得把它直接当成 `test_oracle_suspect`；
- 先对照映射的 C test/helper、Rust test、setup、数据、生命周期和同场景 C-Cross。只有证据完成分类后才确定编辑范围；生产源码编辑必须有 C 证据，并在之后重跑最终全量 C-Cross；
- 每个补丁后重新运行失败命令；
- 将每次修复尝试记录到 `result/issues/repair_trace.jsonl`。

必需证据：

- `logs/trace/cargo-build.log`;
- `logs/trace/cargo-test.log`;
- `logs/trace/cargo-results.json`;
- `logs/trace/test-failure-triage.jsonl`，当 `cargo test` 曾失败时必须存在；
- `logs/trace/08-build-test-repair.md`.

## 测试失败分类

`cargo test` 失败必须先归入以下类型之一：

- `test_oracle_suspect`：当前 C test/helper 与同场景、同输入、同生命周期证据证明 Rust 测试预期不等价。只能修 tests、mapping 或测试说明，不得改 `flashDB_rust/src/`。
- `rust_impl_suspect`：C evidence、spec evidence 或 `validated_obligations` 支持期望值，Rust 行为不一致。允许改 `flashDB_rust/src/`，但 repair trace 必须记录证据来源。
- `harness_suspect`：setup、mock flash、C ABI facade、wrapper、状态清理或初始化顺序可疑。优先修 harness/setup/facade，不得大规模重写 core。
- `insufficient_evidence`：断言只证明发生不一致，尚不能确定测试或实现谁错。先补当前 scenario 的局部 C/Rust 证据；补证据和刷新 fingerprint 不消耗修复轮次。

## 禁止事项

不得删除测试、弱化断言、隐藏错误、返回常量成功，或重写无关模块。未经 triage 判定为 `rust_impl_suspect`，不得直接修改 `flashDB_rust/src/` 的核心语义。默认不全文读取 trace 大 JSON、完整 cargo 日志、总设计文档或历史报告。
