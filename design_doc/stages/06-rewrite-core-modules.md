# 06 - REWRITE_CORE_MODULES

## 目标

实现 FlashDB 核心 Rust 逻辑，包括存储抽象、KVDB、TSDB、reload、gc 和记录语义。若 `rust_api_design.json` 声明了支持模块或扩展模块，本阶段也必须按设计处理其最小可用语义或记录未完成原因，不能只实现 KVDB/TSDB 后忽略扩展输入。

本阶段必须按批次实现，并在每个批次后运行 `cargo check`。不要一次性写完全部核心模块后才构建；越早构建，错误越局部，repairer 越容易做最小修复。

## 执行主体

```text
flashdb-orchestrator
flashdb-migration Skill
work/tools/gate.py
```

不新增固定模块名的 core subagent，避免 public API 和存储语义被多个上下文改散。本阶段仍可由独立的 `rust-implementer` session 执行，但只按 `rust_api_design.json` 当前声明的模块分批推进，不预置固定任务清单。

## 输入

```text
logs/trace/rust_api_design.json 的必要局部片段
logs/trace/c_project_model.json 的必要局部片段
logs/trace/c_api_model.json 的必要局部片段
flashDB_rust/src/
work/knowledge/flashdb-rust-architecture.md
```

## 输出

```text
rust_api_design.json.modules 声明的 Rust 源文件
logs/trace/06-rewrite-core-modules.md
logs/trace/core_rewrite_batches.jsonl
logs/trace/cargo-check-06-<batch>.log
logs/trace/workflow_state.json
```

## 细节实现

必须按 `rust_api_design.json.modules`、`support_modules` 和 `extension_modules` 的当前声明分批实现。批次名称、目标文件和顺序从设计产物推导，不在阶段文档中预置固定函数、固定 case 或固定实现任务清单。

每完成一个批次，主控 Agent 必须运行：

```bash
cd flashDB_rust
cargo check
```

当一个或多个动态 suite 对应的实现批次完成时，可运行定向 C-cross 检查点：

```bash
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --mode full --suite <model-derived-suite> --attempt-kind checkpoint --trigger implementation_batch
```

`<model-derived-suite>` 必须来自当前模型，不预置 suite 名。检查点只提供局部反馈；阶段结束仍需执行 all-suite 中间验证。

失败时先修当前批次，不进入下一批。修复可以由主控完成；如果错误复杂，可以调用 `repairer`，但主控必须复跑 `cargo check` 并归档日志。

每批记录到：

```text
logs/trace/core_rewrite_batches.jsonl
```

每条记录包含：

```json
{
  "stage": "REWRITE_CORE_MODULES",
  "batch": "kvdb",
  "files": ["flashDB_rust/src/kvdb.rs"],
  "command": "cargo check",
  "status": "pass",
  "log": "logs/trace/cargo-check-06-kvdb.log"
}
```

推荐日志命名：

```text
<batch> -> logs/trace/cargo-check-06-<batch>.log
```

## 执行命令

```bash
python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD
# opencode 分批实现 Rust core
# 每个 batch 后执行 cargo check 并记录到 core_rewrite_batches.jsonl
python3 ../work/tools/gate.py --stage REWRITE_CORE_MODULES --root ..
```

## Gate 检查

`gate.py --stage REWRITE_CORE_MODULES` 必须检查：

- core Rust 文件存在且非空；
- `rust_api_design.json.modules` 声明的支持/扩展模块存在且有实现或有明确未完成记录；
- 不存在 `todo!()`、`unimplemented!()`；
- `core_rewrite_batches.jsonl` 存在；
- `core_rewrite_batches.jsonl` 覆盖 `rust_api_design.json.modules` 当前声明的模块；
- 每个批次的 `status == pass`；
- 最近一次 `cargo check` 证据存在且通过；
- 不存在 `.c` 文件被放进 `flashDB_rust/src/`；
- `workflow_state.json.current_stage == REWRITE_CORE_MODULES`。

## 约束

- 不迁移完整测试套件。
- 不删除或弱化后续测试目标。
- 不链接 C 源码。
- unsafe 必须极少且有注释；优先 safe Rust。
- 不改变已固定 public API，除非回退到 `DESIGN_RUST_API` 并记录原因。
- 默认不全文读取 C 源码或 trace 大 JSON。只有模型事实不足以指导实现时，才允许说明缺口后读取 C 源码局部窗口；超过 400 行的 C/Rust 文件禁止全文读取。
- 运行时代理不得修改 `work/**`、`INSTRUCTION.md`、`.opencode/**`、设计文档、评测测试或平台 C 输入；工作台问题只写入 `logs/trace/workbench-issues.jsonl`。

## 下一阶段交接

成功后进入 `VERIFY_RUST_WITH_C_TESTS`。该阶段先用原始 C 测试证据验证 Rust core，再进入 Rust 测试迁移。
