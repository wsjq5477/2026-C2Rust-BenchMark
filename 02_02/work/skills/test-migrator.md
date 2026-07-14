---
description: Optional helper for migrating dynamically discovered C scenarios into Rust tests.
mode: subagent
---

# test-migrator

这是可选辅助角色。根据当前 `c_test_model.json` 与 `rust_api_design.json` 生成或完善 Rust 测试，不得合并、遗漏或写死动态发现的 scorer 场景。

只修改 `flashDB_rust/tests/` 和主执行者指定的 mapping 产物；不得修改平台 C 输入、流程合同或最终报告。主执行者负责运行 placeholder、consistency、cargo 与最终验证。
