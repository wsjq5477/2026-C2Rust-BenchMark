---
name: flashdb-migration
description: Dynamic facts and implementation guidance for the simplified FlashDB C-to-Rust workflow.
---

# FlashDB Migration

## 事实优先

先由 `scan_c_project.py`、`build_c_model.py`、`abi_layout_extractor.py` 与 `design_rust_api.py` 生成当前输入的事实。模型、脚本和人工实现均不得预置固定文件、函数、类型、测试数量或标准答案。

## 实现优先级

1. 先保持 C ABI 的类型、签名和 layout 可验证。
2. 再实现原 C runner 实际可观察的行为。
3. C-Cross 失败时按 failure summary 定位最小语义缺口，修复后立即复跑。
4. 不为没有事实或失败证据支撑的内部细节扩展复杂度。

## 验收

成功必须同时由 ABI layout、真实 C compile/link/run、Rust 测试映射与 cargo 结果支撑。构建成功、Agent 回复完成或日志存在都不是行为通过证据。
