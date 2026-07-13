---
name: flashdb-report
description: 用于生成 FlashDB 迁移报告，汇总阶段证据、cargo 结果、unsafe ratio、输出路径和已知问题。
---

# FlashDB 报告

## 适用范围

仅当 orchestrator 进入 `REPORT_AND_VERIFY` 后使用此 Skill。

## REPORT_AND_VERIFY 契约

产出：

- `result/output.md`;
- `result/issues/00-summary.md`;
- `logs/trace/final-verification.md`.

报告必须汇总：

- 输入路径和输出路径；
- C 模型证据；
- Rust API 设计证据；
- extension/unknown/unmapped 覆盖情况；
- cargo build 和 test 状态；
- unsafe ratio；
- 已知问题。

报告必须区分检查点进度和完整迁移成功。只有当每个 final gate 都有新鲜证据且 `python3 work/tools/gate.py --stage REPORT_AND_VERIFY` 通过后，才允许写入 `STATUS: SUCCESS`。
