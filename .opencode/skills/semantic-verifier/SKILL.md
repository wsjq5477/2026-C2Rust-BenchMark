---
name: semantic-verifier
description: Verify C-to-Rust behavioral equivalence with repeatable evidence.
---

# Semantic Verifier

## 目标

用可重复证据证明 Rust 项目覆盖原 C 工程的行为，而不仅是能够编译。

## 验证顺序

1. 重新运行 C 基线副本，确认基线仍通过。
2. 运行全部 Rust 测试，逐项核对 `migration-state.json` 的 C/Rust 测试映射。
   对 FlashDB 还必须逐项核对 `c-to-rust/references/flashdb-profile.json` 的24个标准场景；实际 C 注册测试与标准场景可以多对一，但每个场景都要有独立的 Rust 断言证据。
3. 对持久化库比较创建、更新、删除、遍历、重启恢复和异常状态行为；可比较逻辑记录，若宣称格式兼容则还要比较磁盘字节。
4. 运行 `check_coverage.py`，任何缺失核心文件、公共函数或 C 测试均失败。
5. 运行 `check_unsafe.py --maximum 0.10`，比例必须严格小于 0.10。
6. 执行 release build、全量测试、fmt 和 clippy，并保存完整输出。
7. 运行 `c-to-rust/scripts/check_no_c_linkage.py`，确认最终项目没有编译、链接或嵌入原 C 核心实现。
8. 按 `c-to-rust/references/verification-rules.md` 生成最终结论。

## 结论规则

只有所有硬门禁均有退出码为零的本轮证据时才允许 `STATUS: SUCCESS`。缺证据与失败同等处理。
