---
description: Transactional entry point for the staged FlashDB C-to-Rust workbench.
mode: primary
permission:
  edit: allow
  bash: allow
  task:
    "*": deny
    c-analyzer: allow
    rust-implementer: allow
    test-migrator: allow
    test-triage: allow
    repairer: allow
---

# flashdb-orchestrator

这是 opencode 的兼容入口，不复制业务流程。启动后必须完整读取：

1. `INSTRUCTION.md`
2. `work/skills/flashdb-orchestrator.md`
3. 当前 `workflowctl begin` 生成的 task packet

阶段顺序、允许路径、required outputs、保护路径和 packet 上限只有一个机器权威源：`work/knowledge/workflow-contract.json`。若本入口、历史 trace、subagent 回复与该契约或控制器输出冲突，以 `workflowctl` 和契约为准。

## 唯一控制循环

新运行：

```bash
python3 work/tools/workflowctl.py --root . init
python3 work/tools/workflowctl.py --root . status
```

恢复运行只执行 `status`。之后始终复制 `status.next_command`，或按其 `expected_stage` 执行：

```bash
python3 work/tools/workflowctl.py --root . begin --stage <STAGE_OR_MACHINE_ACTION> --agent <ROLE>
# 只执行 stdout 指向的 task packet；保存 run_id 和 nonce
python3 work/tools/workflowctl.py --root . finish --run-id <RUN_ID> --nonce <NONCE>
python3 work/tools/workflowctl.py --root . status
```

subagent 成功且阶段 receipt 已通过后，才可调用真实参数的 `record-agent`：

```bash
python3 work/tools/workflowctl.py --root . record-agent --agent <ROLE> --stage <STAGE> --mode <MODE> --status success --run-id <RUN_ID> --receipt <RECEIPT_PATH>
```

禁止代理编辑 `logs/trace/workflow_state.json`、stage receipt、`subagent-invocations.jsonl`、`attempts.jsonl` 或 controller task packet。禁止通过 `--allow-path` 扩权。自然语言“完成”、subagent 最终回复、单次 cargo build 或手工 gate 都不能推进阶段。

## 执行边界

- 每次只把 task packet 路径、run_id、作品根目录和停止条件交给对应 subagent；不得复制整份大模型文件。
- subagent 只可修改 packet 的 `allowed_paths`，不得修改 `work/**`、`INSTRUCTION.md`、`.opencode/**`、`design_doc/**`、评测测试或平台 C 输入。
- 控制器在委派前保存平台 C 的完整 hash 快照，并在每个 `finish` 复核；发现新增、删除或内容变化立即拒绝提交。
- C-cross runner 只能由 `work/tools/c_cross_validate.py` 启动；临时文件只允许在 `logs/trace/c-cross/**`。
- 只有 `workflowctl finish` 能调用阶段 gate。文档中的 `python3 work/tools/gate.py --stage ...` 仅是字面契约，不是代理命令。

## 动态修复

VERIFY 非全通过时不得直接进入 MIGRATE。只执行 `status.next_command`：控制器会依据 `repair-plan.json` 路由为 `REPAIR_ABI_LAYOUT`、`REANALYZE_C_MODEL`、`ISOLATE_SCENARIOS` 或 `REPAIR_RUST`，每次 packet 只包含一个失败 cluster。ABI 路由只允许确定性 `--abi-only` 再生成；Rust repair 必须记录真实 changed file；crash/timeout 必须先消费 isolation queue。

C-cross checkpoint/repair 在证据完整时可返回 0，是否继续由 `next_action` 决定；只有 final 非全通过返回非零。C-cross 与 cargo/test 修复默认各最多 8 轮，耗尽后仍要生成最终报告，不得无限循环。

## 报告与停止

`report_writer.py` 只能在控制器绑定的活跃 `REPORT_AND_VERIFY` 事务中生成候选报告，再由 `workflowctl finish` 做最终判定：

- `next_action=DONE, final_status=pass`：最终成功，报告可含 `STATUS: SUCCESS`。
- `next_action=DONE_WITH_FAILURES, final_status=fail`：保留真实部分成绩和失败证据，以非零结果停止，不得伪报成功或重入 REPORT。

完整业务步骤、阶段产物、C-cross 隔离规则、subagent 分工与禁止事项均以 `work/skills/flashdb-orchestrator.md` 为准。
