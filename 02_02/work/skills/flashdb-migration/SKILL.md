---
name: flashdb-migration
description: 用于 FlashDB C-to-Rust 分阶段 opencode 工作台中的 C 项目建模与 Rust API 迁移。
---

# FlashDB 迁移

## 适用范围

仅当 orchestrator 进入 `BUILD_C_MODEL`、`DESIGN_RUST_API`、`GENERATE_RUST_SCAFFOLD` 或 `REWRITE_CORE_MODULES` 后使用此 Skill。

完整流程在 `BUILD_C_MODEL`、`DESIGN_RUST_API`、`GENERATE_RUST_SCAFFOLD` 和 `REWRITE_CORE_MODULES` 阶段使用此 Skill。先抽取 C 事实并写入模型产物；再设计安全 Rust API 边界；然后生成 Rust 脚手架；最后实现核心 Rust 模块。

## BUILD_C_MODEL 契约

读取：

- `logs/trace/input_manifest.json`;
- manifest 中列出的 FlashDB `src/`、`inc/` 和 `tests/` 文件。

产出：

- `logs/trace/c_project_model.json`;
- `logs/trace/c_api_model.json`;
- `logs/trace/c_test_model.json`;
- `logs/trace/03-build-c-model.md`.

本阶段只记录事实：

- source/test/header 文件分类；
- include 关系；
- public C 函数；
- struct、typedef、enum、enum value 和 macro 名称；
- `c_api_model.json.abi_layouts`：由 C probe 确认的 ABI struct `sizeof`、`alignof`、字段 offset、字段大小和 active macros；
- 已注册的 KVDB 和 TSDB 测试函数；
- 从当前 C 测试注册表推导出的动态 `standard_scenarios`；
- 每个 scenario 的静态语义事实：源文件、C API 调用、helper 调用和断言宏。

边界：

- 不做 Clang AST；
- 不做宏展开来替代 C 事实建模；ABI layout 允许用受控 C probe 和预处理结果获取编译器确认的 active fields；
- 不做完整调用图；
- 不做完整函数体业务语义解释，但允许抽取测试函数中的调用和断言事实；
- 不做 Rust API 决策。

本阶段不得设计或预置任何 Rust public API、类型名或模块名。

## DESIGN_RUST_API 契约

读取：

- `logs/trace/c_project_model.json`;
- `logs/trace/c_api_model.json`;
- `logs/trace/c_test_model.json`;
- `work/knowledge/flashdb-rust-architecture.md`.

产出：

- `logs/trace/rust_api_design.json`;
- `logs/trace/04-design-rust-api.md`.

本阶段做出 Rust API 决策：

- crate 名称遵循比赛要求；
- 模块、核心类型、trait、错误模型和 storage model 必须从当前 C public API、数据结构事实、错误返回语义和测试事实推导；
- Rust API 表面必须由 `c_api_model.json` 中的 public symbols 和 `c_test_model.json` 中的测试使用方式推导；
- `rust_api_design.json.c_abi_facade` 必须来自 `c_api_model.json.abi_layouts`，不得在设计阶段重新猜测 FFI struct 字段；
- C 测试分组映射到后续 Rust integration test 计划，具体文件名由 `rust_api_design.json` 记录。

边界：

- 不生成 `flashDB_rust`；
- 不写 Rust 源码；
- 不运行 `cargo`；
- 不进入 `GENERATE_RUST_SCAFFOLD`；
- 阶段日志 `logs/trace/04-design-rust-api.md` 必须使用中文。

## GENERATE_RUST_SCAFFOLD 契约

读取：

- `logs/trace/rust_api_design.json` 中生成脚手架所需的局部设计事实;
- `work/knowledge/flashdb-rust-architecture.md`.

产出：

- `flashDB_rust/Cargo.toml`;
- `flashDB_rust/src/lib.rs`;
- `rust_api_design.json.modules` 声明的源码模块；
- `rust_api_design.json.modules` 声明的任何支撑模块或扩展模块；
- `logs/trace/05-generate-rust-scaffold.md`.

边界：

- 可以创建 `flashDB_rust`；
- 不链接 C 源码；
- 不迁移测试；
- API 形态必须遵循 `rust_api_design.json`。

## REWRITE_CORE_MODULES 契约

读取：

- `logs/trace/rust_api_design.json` 的必要局部片段;
- `logs/trace/c_project_model.json` 的必要局部片段;
- `logs/trace/c_api_model.json` 的必要局部片段;
- `flashDB_rust/src/`.

产出：

- 已实现的 `rust_api_design.json.modules` 声明模块；
- `logs/trace/06-rewrite-core-modules.md`;
- `logs/trace/core_rewrite_batches.jsonl`.

实现规则：

- 保留 FlashDB KVDB 和 TSDB 语义；
- record append、tombstone delete、reload scan 和 gc retain-latest 行为必须在设计或实现证据中保持可见；
- 优先使用 safe Rust；
- 不得向 `flashDB_rust/src` 添加 `.c` 文件；
- 不得留下 `todo!()`、`unimplemented!()` 或基于 panic 的占位实现。
- 默认不全文读取 trace 大 JSON 或 C 源码。确需回看 C 源码时，必须先说明模型缺口或实现疑点，并只读取相关窗口。

## 全阶段一致性

保持以下内容的一致视图：

- FlashDB 源文件和 public API；
- KVDB 和 TSDB 状态迁移；
- storage 抽象边界；
- Rust 模块归属；
- `logs/trace` 中的 source-to-Rust 证据。

Rust 项目必须从平台 C 输入和阶段产物推导生成。
