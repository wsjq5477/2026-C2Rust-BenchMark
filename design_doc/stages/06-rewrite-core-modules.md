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

不拆 KVDB/TSDB core subagent，避免 public API 和存储语义被多个上下文改散。

## 输入

```text
logs/trace/rust_api_design.json
logs/trace/c_project_model.json
logs/trace/c_api_model.json
flashDB_rust/src/
work/knowledge/flashdb-rust-architecture.md
```

## 输出

```text
flashDB_rust/src/error.rs
flashDB_rust/src/flash.rs
flashDB_rust/src/kvdb.rs
flashDB_rust/src/tsdb.rs
flashDB_rust/src/<support-or-extension>.rs
logs/trace/06-rewrite-core-modules.md
logs/trace/core_rewrite_batches.jsonl
logs/trace/cargo-check-06-error.log
logs/trace/cargo-check-06-flash.log
logs/trace/cargo-check-06-kvdb.log
logs/trace/cargo-check-06-tsdb.log
logs/trace/workflow_state.json
result/output.md
result/issues/00-summary.md
```

## 细节实现

必须按批次实现：

1. `error.rs`：`FdbError`、`Result` alias、错误转换。
2. `flash.rs`：`FlashStorage` trait、`MemFlash`、`FileFlash` 基本读写擦除。
3. `kvdb.rs`：record append、set/get/delete/update、reload、gc。
4. `tsdb.rs`：append、iter、query、status、clean、reload。
5. 支持/扩展模块：按照 `rust_api_design.json.support_modules` 和 `rust_api_design.json.extension_modules` 逐项实现，或在 `unmapped_symbols` / `result/issues` 中记录不能实现的原因。

每完成一个批次，主控 Agent 必须运行：

```bash
cd flashDB_rust
cargo check
```

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

推荐批次和日志：

```text
error      -> logs/trace/cargo-check-06-error.log
flash      -> logs/trace/cargo-check-06-flash.log
kvdb       -> logs/trace/cargo-check-06-kvdb.log
tsdb       -> logs/trace/cargo-check-06-tsdb.log
extension  -> logs/trace/cargo-check-06-extension.log（仅在存在扩展模块时）
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
- `core_rewrite_batches.jsonl` 至少包含 `error`、`flash`、`kvdb`、`tsdb` 四个批次；
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

## 下一阶段交接

成功后进入 `VERIFY_RUST_WITH_C_TESTS`。该阶段先用原始 C 测试证据验证 Rust core，再进入 Rust 测试迁移。
