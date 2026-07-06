# 01 - INIT_WORKSPACE

## 目标

初始化结果目录、日志目录和阶段状态文件，让后续每一步都有固定证据落点。

## 执行主体

```text
flashdb-orchestrator + work/tools/gate.py
```

## 输入

```text
当前作品根目录
INSTRUCTION.md
work/agents/flashdb-orchestrator.md
```

## 输出

```text
result/
result/issues/
logs/
logs/trace/
logs/interaction.md
logs/trace/workflow_state.json
logs/trace/01-init-workspace.md
result/output.md
result/issues/00-summary.md
```

## 细节实现

opencode 创建或确认目录：

```text
result/
result/issues/
logs/
logs/trace/
```

创建或确认文件：

```text
logs/interaction.md
logs/trace/01-init-workspace.md
logs/trace/workflow_state.json
```

`workflow_state.json` 初始状态：

```json
{
  "current_stage": "INIT_WORKSPACE",
  "completed_stages": ["BOOTSTRAP", "INIT_WORKSPACE"],
  "checkpoint": "INIT_WORKSPACE",
  "rust_project_path": "flashDB_rust",
  "input_path_candidates": [
    "/app/code/judge-assets/02_02_c_to_rust/code/FlashDB",
    "judge-assets/code/FlashDB",
    "../judge-assets/code/FlashDB"
  ],
  "build_status": "not_started",
  "test_status": "not_started",
  "unsafe_ratio": null,
  "repair_rounds": 0,
  "blocked_issues": []
}
```

## 执行命令

```bash
python3 work/tools/gate.py --stage INIT_WORKSPACE
```

## Gate 检查

`gate.py --stage INIT_WORKSPACE` 必须检查：

- `result/issues/` 存在；
- `logs/trace/` 存在；
- `logs/interaction.md` 存在；
- `logs/trace/workflow_state.json` 存在；
- `logs/trace/01-init-workspace.md` 存在；
- `current_stage == INIT_WORKSPACE`；
- `completed_stages` 包含 `BOOTSTRAP` 和 `INIT_WORKSPACE`；
- `flashDB_rust` 不存在。

## 约束

- 不得读取 FlashDB 源码。
- 不得生成 `flashDB_rust`。
- 不得进入 `READ_C_PROJECT` 之外的后续阶段。

## 下一阶段交接

成功后进入 `READ_C_PROJECT`，使用 `workflow_state.json.input_path_candidates` 定位 FlashDB 输入。
