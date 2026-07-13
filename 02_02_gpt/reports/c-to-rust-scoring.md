# C-to-Rust 评分报告

使用 `.opencode/skills/c-to-rust-scoring/SKILL.md` 对当前 GPT 转换副本评分。

## 结论

- 功能基线：**60.0 / 60.0**
- 最终 C-CROSS：**24 / 24 通过**
- Rust 原生测试：**26 / 26 通过**
- 用例语义一致性：**24 / 24 通过**
- unsafe ratio：**3.08%**（低于 10% 上限）

## 测试方案

项目为 `manual_rust`，但输出 `staticlib` 且提供 typed `extern "C"` ABI，因此按评分 Skill 的优先级选择方案 A。功能结论来自最终 `full/all/final` C-CROSS：原始 C runner 链接 Rust staticlib 并逐场景运行。

构建产物：[libflashdb_rust.a](/home/nv_test/777/flashdb2rust/02_02%20gpt/flashDB_rust/target/release/libflashdb_rust.a)。release 构建成功；仅有 1 条 Rust 命名风格 warning。

## 一致性与性能说明

`logs/trace/test-consistency.json` 显示 24 个动态 C 场景均有 semantic Rust mapping，且没有逻辑不一致。评分 Skill 文档中的静态“23 项”表与当前输入动态发现的 24 个注册调用不一致，因此本报告以运行时模型和最终 C-CROSS 的 24 项为准。

性能未计分：C benchmark 会在平台 C 输入目录写入数据，而本次评分保持不修改 C 输入的边界；项目也未提供可在隔离目录运行的 Rust 等价 benchmark。未生成任何性能比值。

完整机器可读结果见 [c-to-rust-scoring.json](/home/nv_test/777/flashdb2rust/02_02%20gpt/reports/c-to-rust-scoring.json)。
