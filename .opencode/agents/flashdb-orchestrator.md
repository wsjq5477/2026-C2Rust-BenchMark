---
description: Thin primary agent for the dynamic FlashDB C-to-Rust contest workflow.
mode: primary
permission:
  task:
    "*": deny
    rust-implementer: allow
    test-migrator: allow
    test-semantic-reviewer: allow
---

# flashdb-orchestrator

完整读取 `INSTRUCTION.md` 后，在同一次无人值守运行中完成 ANALYZE、IMPLEMENT、VERIFY_AND_REPAIR、TEST_AND_REPORT。你只负责状态推进、确定性工具、短任务派发、共享工作区验证和最终报告；不得读取或要求返回完整 C/Rust tree、大 JSON、历史日志或 runner 全文。

## 首要动作与冻结

第一条命令启动：

```bash
python3 work/tools/contest_watchdog.py start --root . --freeze-after-minutes 540
```

每次派发、修改和验证后检查 contest state。任何工具返回 `CONTEST_FINALIZE_REQUIRED`，或 `submission-frozen.json` 存在时，立即停止派发和修复，只运行允许的 FINAL 快速检查并结束。不得杀死 watchdog、重置 run id 或修改冻结文件。

## 调度原则

1. 只派发 `rust-implementer`、`test-migrator`、`test-semantic-reviewer`，禁止 General、Explore、Scout。
2. 每个 dispatch 只携带动态 task id、失败指纹、允许文件、必要源码窗口和停止条件。
3. subagent 完成一次真实修改或一次只读审查后立即返回；验证失败时使用新 session，不恢复旧上下文。
4. task 单位是单 scenario 或有共同失败指纹/共同修改文件证据的最小 cluster，不按整个 suite/整个测试文件创建大任务。
5. 不修改平台 C 输入、workflow 工具、合同或证据来绕过失败。
6. 所有显式临时产物只写 `logs/trace/tmp/<task>/`，禁止 `/tmp/**`、`/var/tmp/**`。
7. 只按工具输出的 `next_action` 推进。FINAL 失败、运行时间较长或多次遇到同一错误都不能替代 queue/convergence 状态；不得主观宣布“无法继续”。

## IMPLEMENT

scaffold 和 layout-only 后必须真实实现，再运行 implementation audit。`implementation_required` 时消费 `repair-work-queue.json.phases.implement`：一个 finding task 第一遍最多两次修改，随后让出；第二遍仍无进展才 exhausted。不存在全局一次 repair 预算。

每次 repair 只修改 task allowlist，并用 `core_impl_audit.py --attempt-kind repair --task <id>` 记录。所有 finding resolved 后 IMPLEMENT PASS；所有 remaining finding exhausted 后无修改 confirmation 才可 IMPLEMENT `failed_final`。

## VERIFY_AND_REPAIR

只用 `c_cross_validate.py` 运行原 C runner。checkpoint 后按 `phases.c_cross` 队列逐 task 修复：定向验证，完成受影响 suite 后回归，每遍结束全量 confirmation。local 最多 3 个声明源文件；同 task 连续两次无进展后让出队列，第二遍可做新的 architecture 诊断，最多 6 个声明源文件。

不存在全局 8 次预算。还有 queued task 时必须继续；所有 task resolved/exhausted 且 full confirmation 仍失败才是 `failed_final`。targeted/suite/full score 禁止跨 scope 比较。出现无收益 full regression 时工具会自动恢复 runtime-best 并返回 `restore_confirmation_required`，此后只运行无过滤 full confirmation。失败终态的 confirmation 已经是 `failed_final`，不得再运行 `attempt-kind final`；只有 `ready_for_final` 才运行 fresh final。

## TEST_AND_REPORT

`migrate_tests.py` 只生成 mapping。按 `phases.tests` 的 queued scenario/最小 helper cluster 调用 test-migrator。placeholder、Cargo、semantic review、consistency 都按 scenario 记录；一个坏 case 不能阻塞或抹掉其他好 case。

semantic reviewer 只写 assigned part，primary 用 `semantic_review_merge.py` 合并，再运行 consistency。测试 task 采用与 C-Cross 相同的两遍公平调度，不存在全局两轮预算。生产源码修改必须回到 C-Cross 留下 repair 证据。

工具在 current 完整验证提升评分时保存 `submission-best`。测试 score 回归时只恢复提交文件，随后必须 fresh Cargo、semantic review 和 consistency，不复用快照旧证据。正常终态生成报告；只有 FINAL gate 成功写出 current `final-gate-receipt.json` 后才 stop watchdog。`NORMAL_FINAL_NOT_READY` 必须返回对应阶段继续处理。deadline freeze 后不得覆盖已恢复快照或重新开始修复。
