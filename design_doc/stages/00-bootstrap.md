# 00 - BOOTSTRAP

## 目标

让 opencode 从 `INSTRUCTION.md` 进入固定执行流程，明确主控 Agent、阶段边界和禁止事项。

## 执行主体

```text
opencode 默认 Build agent 或启动前选中的 flashdb-orchestrator primary agent
```

如果 opencode 启动时已经选择 `flashdb-orchestrator`，由该 primary agent 执行。若已经由默认 Build agent 启动，不要求运行中自切换 primary agent；默认 agent 完整读取主控 Agent 文档后执行也合规。

## 输入

```text
02_02/INSTRUCTION.md
02_02/work/agents/flashdb-orchestrator.md
```

可选运行镜像：

```text
02_02/.opencode/agents/flashdb-orchestrator.md
02_02/.opencode/skills/
```

`work/` 目录始终是权威源，`.opencode/` 只是在启动前复制出的 opencode 原生发现镜像。

## 输出

本阶段不写业务产物。它只建立执行上下文：

```text
后续流程由 flashdb-orchestrator.md 中的阶段契约控制
```

## 细节实现

opencode 必须：

1. 从作品根目录读取 `INSTRUCTION.md`。
2. 读取 `work/agents/flashdb-orchestrator.md`。
3. 识别当前允许执行到哪个检查点。
4. 识别最终输出目录是 `flashDB_rust`，但不得提前生成。
5. 识别平台输入优先路径：
   - `/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
   - `judge-assets/code/FlashDB`
   - `../judge-assets/code/FlashDB`

## 约束

- 不得修改 `judge-assets`。
- 不得生成 `flashDB_rust`。
- 不得伪造完整转换成功。
- 不得跳过主控 Agent 文档。

## 检查方式

本阶段由后续 `INIT_WORKSPACE` 的状态文件间接证明。`workflow_state.json.completed_stages` 必须包含：

```json
["BOOTSTRAP", "INIT_WORKSPACE"]
```

## 失败处理

如果 `INSTRUCTION.md` 或主控 Agent 缺失，立即停止，写入 `result/issues/00-summary.md`，不得继续。
