# 05 - GENERATE_RUST_SCAFFOLD

## 目标

根据已固定的 Rust API 设计生成 Rust 项目骨架。这个阶段只建立文件结构、模块声明和可编译的 API 空壳，不实现完整业务语义。

本阶段结束前必须立即运行一次 `cargo check`。05 通过的含义不是“业务已实现”，而是“Rust crate 骨架已经能被 Rust 编译器接受”。这样可以把骨架错误和后续业务实现错误分开，减少 06/08 的混合故障。

## 执行主体

```text
flashdb-orchestrator
flashdb-migration Skill
work/tools/gate.py
```

## 输入

```text
logs/trace/rust_api_design.json
work/knowledge/flashdb-rust-architecture.md
```

## 输出

```text
flashDB_rust/Cargo.toml
flashDB_rust/src/lib.rs
flashDB_rust/src/error.rs
flashDB_rust/src/flash.rs
flashDB_rust/src/kvdb.rs
flashDB_rust/src/tsdb.rs
flashDB_rust/src/<support-or-extension>.rs
flashDB_rust/tests/
logs/trace/05-generate-rust-scaffold.md
logs/trace/cargo-check-scaffold.log
logs/trace/scaffold-check.json
logs/trace/workflow_state.json
result/output.md
result/issues/00-summary.md
```

## 细节实现

opencode 创建：

```text
flashDB_rust/
├── Cargo.toml
├── src/
│   ├── lib.rs
│   ├── error.rs
│   ├── flash.rs
│   ├── kvdb.rs
│   ├── tsdb.rs
│   └── <support-or-extension>.rs
└── tests/
```

`Cargo.toml` 应使用稳定 Rust edition。`src/lib.rs` 公开模块：

```rust
pub mod error;
pub mod flash;
pub mod kvdb;
pub mod tsdb;
// support/extension modules are generated when rust_api_design.json.modules declares them
```

API 空壳必须与 `rust_api_design.json` 一致。`error`、`flash`、`kvdb`、`tsdb` 是必须存在的核心模块；如果 `rust_api_design.json.modules` 包含支持模块或扩展模块，也必须生成对应 `.rs` 文件和 `lib.rs` module 声明。允许使用明确错误返回表示“尚未实现”，但不得长期留下 `todo!()`、`unimplemented!()` 或 panic 作为后续阶段通过条件。

生成骨架后立即执行：

```bash
cd flashDB_rust
cargo check
```

并记录：

```text
logs/trace/cargo-check-scaffold.log
logs/trace/scaffold-check.json
```

`scaffold-check.json` 建议结构：

```json
{
  "stage": "GENERATE_RUST_SCAFFOLD",
  "command": "cargo check",
  "status": "pass",
  "returncode": 0,
  "log": "logs/trace/cargo-check-scaffold.log"
}
```

如果 `cargo check` 失败，不得进入 `REWRITE_CORE_MODULES`。修复范围只允许覆盖：

- `Cargo.toml`；
- `src/lib.rs`；
- 核心模块和支持/扩展模块的 API 空壳；
- 模块声明、类型签名、Result alias、trait 声明等骨架级问题。

此时可以调用 `repairer` 的骨架修复模式，但不得开始实现 KVDB/TSDB 业务语义。

## 执行命令

```bash
python3 work/tools/gate.py --stage DESIGN_RUST_API
# opencode 生成 flashDB_rust 骨架
cd flashDB_rust && cargo check
python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD
```

## Gate 检查

`gate.py --stage GENERATE_RUST_SCAFFOLD` 必须检查：

- `flashDB_rust/Cargo.toml` 存在；
- `flashDB_rust/src/lib.rs` 存在；
- `error.rs`、`flash.rs`、`kvdb.rs`、`tsdb.rs` 存在；
- `flashDB_rust/tests/` 存在；
- public module 声明与 `rust_api_design.json.modules` 一致；
- `rust_api_design.json.modules` 中声明的支持/扩展模块均有对应 Rust 文件；
- `logs/trace/cargo-check-scaffold.log` 存在；
- `logs/trace/scaffold-check.json.status == pass`；
- `workflow_state.json.current_stage == GENERATE_RUST_SCAFFOLD`。

## 约束

- 不实现完整 KVDB/TSDB 或扩展模块语义。
- 不迁移测试。
- 不链接或编译 C 源码。
- 不改变 `rust_api_design.json` 的 public API。
- 本阶段修复仅限骨架编译问题，不实现完整业务语义。

## 下一阶段交接

成功后进入 `REWRITE_CORE_MODULES`。下一阶段在此骨架中实现 storage、KVDB、TSDB 核心逻辑。
