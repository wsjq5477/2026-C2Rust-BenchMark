---
name: rust-compile-repair
description: 用于 staged FlashDB migration 中 Rust build 或 test 失败后的最小化、证据驱动修复。
---

# Rust 编译修复

## 适用范围

仅当 orchestrator 进入 `BUILD_TEST_REPAIR` 后使用此 Skill。

## BUILD_TEST_REPAIR 契约

- 从捕获的 cargo 日志中分类 compiler 或 test 失败；
- 针对观察到的错误做最小补丁；
- 每个补丁后重新运行失败命令；
- 将每次修复尝试记录到 `result/issues/repair_trace.jsonl`。

必需证据：

- `logs/trace/cargo-build.log`;
- `logs/trace/cargo-test.log`;
- `logs/trace/cargo-results.json`;
- `logs/trace/08-build-test-repair.md`.

不得删除测试、弱化断言、隐藏错误、返回常量成功，或重写无关模块。
