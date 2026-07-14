---
name: flashdb-migration
description: 用于 FlashDB C-to-Rust 分阶段 opencode 工作台中的 C 项目建模与 Rust API 迁移。
---

# FlashDB 迁移

## 运行时编辑与 C-cross 收敛边界

- 运行时代理只允许修改当前职责内的 `flashDB_rust/**`、`logs/trace/**` 和规定的 `result/issues/**`；不得修改 `work/**`，不得修改 `INSTRUCTION.md`，不得修改 `.opencode/**`、设计文档、评测测试或平台 C 输入。
- 工作台脚本或契约问题由主控写入 `logs/trace/c-cross/workbench-issues.jsonl`，运行时不得现场修改工作台。
- C-cross 的 suite 和测试集合必须从模型动态推导，不得硬编码名称、数量或通过比例。
- C-CROSS 必须保留每个 invocation 的 pass、fail、not_run、parse_failed 或 unresolved 证据；失败不会伪装成通过。
- 中间阶段输出 `PASS` 或 `CONTINUE_WITH_FAILURES`；后者必须先消费 machine repair queue，只有收敛或显式耗尽修复预算后才继续测试迁移。最终 final/full/all-suite C-cross 全部通过才可报告 C-cross PASS。
- 所有新运行通过 `workflowctl` 的 task packet、receipt 和 next_action 推进；代理不得手写状态、attempt 或 invocation 证据。

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
- `c_api_model.json.function_signatures`：public header 中关键 C ABI 函数的 return type、参数顺序、参数类型、pointer depth、const 信息和声明来源；
- `c_api_model.json.typedef_map`、`enum_map`、`unresolved_signatures`、`unresolved_types`：记录类型事实和无法安全解析的证据。C runner、scorer case 或 layout checker 依赖的关键路径不得 unresolved；
- pointer typedef 必须展开为有效 pointer depth，function pointer typedef 必须保留参数和返回类型；不得把宏、typedef 名、测试 helper 或 `_fdb_*` 内部函数混入 public API；
- struct、typedef、enum、enum value 和 macro 名称；
- `c_api_model.json.abi_layouts`：由 C probe 确认的 ABI struct `sizeof`、`alignof`、字段 offset、字段大小/对齐和 active macros；每个字段保留 `raw_declarator`、`kind`、`array_extents`、`pointee`、`callback_signature`，不得丢失 array/anonymous aggregate/function pointer 形状；
- 已注册的 KVDB 和 TSDB 测试函数；
- `c_test_model.json.registered_test_invocations`：保留 `TEST_RUN(...)` 的动态注册顺序、来源 runner 和测试函数名；
- 从当前 C 测试注册表推导出的动态 `standard_scenarios`；
- 每个 scenario 的静态语义事实：源文件、C API 调用、helper 调用和断言宏；并生成有序 `scenario_ir`，保留 call/control/assert 及 helper/callback 展开顺序。

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
- `rust_api_design.json.c_abi_facade.structs` 必须来自 `c_api_model.json.abi_layouts`，不得在设计阶段重新猜测 FFI struct 字段；
- `rust_api_design.json.c_abi_facade.functions` 必须来自 `c_api_model.json.function_signatures`，覆盖 C runner、scorer case 和 `c_to_rust_symbol_map` 需要的 C symbols；
- `rust_api_design.json.c_abi_facade.c_type_map` 必须记录 primitive、typedef、enum/status、struct value/pointer、字符串/void 指针、buffer + length、ownership/nullability 等 ABI wrapper 必需映射；关键路径类型不得 unresolved；
- `rust_api_design.json.implementation_requirements` 必须从当前 scorer case 的 semantic obligations 和 observed C symbols 动态推导；每项包含 `symbols`、`acceptance_scenarios`、`suggested_files` 和 `dependency_ids`，实现阶段必须逐项消费，不能只实现能够链接的 facade；
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
- 当 `rust_api_design.json.c_abi_facade` 声明 struct 或 function 时，生成 `flashDB_rust/src/ffi/mod.rs`、`src/ffi/c_types.rs`、`src/ffi/c_abi.rs`、`src/ffi/layout_probe.rs`；
- `logs/trace/05-generate-rust-scaffold.md`.
- `logs/trace/scaffold-manifest.json`，记录文件 hash、FFI body baseline、stub symbols 与 placeholder modules；
- `logs/trace/c-cross/scaffold-layout-check.json`，必须在模型编辑源码前由 compiler-confirmed layout-only 检查写出 PASS。

边界：

- 可以创建 `flashDB_rust`；
- 不链接 C 源码；
- 不迁移测试；
- API 形态必须遵循 `rust_api_design.json`。
- `src/ffi/c_types.rs` 必须按 compiler-confirmed size/offset/align 生成 `#[repr(C)]` 布局和必要 padding；数组、匿名 struct/union 或无法可靠分类的聚合使用精确 `[u8; N]` byte region，不得从 ctype 子串猜成标量；
- `src/ffi/c_abi.rs` 必须按 `c_abi_facade.functions` 生成 typed `extern "C"` export，不能退化为统一 `fn() -> *mut c_void`；
- `src/ffi/layout_probe.rs` 必须用真实 Rust struct 计算 `size_of`、`align_of` 和字段 offset，不能返回合同常量伪装通过。

## REWRITE_CORE_MODULES 契约

本阶段不再由单个长 session 完成，也不按具体业务模块硬编码拆分。`workflowctl` 根据 scaffold manifest 固定调度两个角色：

- `IMPLEMENT_CORE` 只读取角色 packet 和必要 core 文件，只写 `core_owned_paths`；
- `WIRE_FACADE` 只读取角色 packet、冻结的 facade contracts 和必要内部 API，只写 `facade_owned_paths`。

`frozen_contract_paths` 与 `shared_readonly_paths` 对两个角色都只读。函数体可写而签名冻结的合同由 `frozen_contract_symbols` 表达。

产出：

- 已实现的 `rust_api_design.json.modules` 声明模块；
- `logs/trace/06-rewrite-core-modules.md`;
- 控制器生成的 `logs/trace/core_rewrite_batches.jsonl`；
- 控制器生成的 `logs/trace/rewrite-state.json`、`rewrite-worker-receipts/` 和 `rewrite-check/`。
- `logs/trace/implementation-audit.json`，且 status 必须为 pass。

实现规则：

- 保留 FlashDB KVDB 和 TSDB 语义；
- record append、tombstone delete、reload scan 和 gc retain-latest 行为必须在设计或实现证据中保持可见；
- 优先使用 safe Rust；
- 不得向 `flashDB_rust/src` 添加 `.c` 文件；
- 不得留下 `todo!()`、`unimplemented!()` 或基于 panic 的占位实现。
- 不得保留 scaffold marker、与 baseline 相同/仅改空白的 FFI body、恒定 neutral return 或 `module_available() -> true` placeholder；REWRITE gate 必须用 manifest 静态审计。
- 默认不全文读取 trace 大 JSON 或 C 源码。确需回看 C 源码时，必须先说明模型缺口或实现疑点，并只读取相关窗口。
- `implementation_requirements` 中的每项要求都必须落实到内部数据模型；禁止只修改 C 可见 struct 而不更新真实存储状态。
- 当要求包含 sector/address fidelity 时，外部地址必须表示配置 geometry 下的字节偏移，禁止用 `Vec`/`HashMap` 下标冒充物理地址。
- get/iterator 返回的对象若会进入 to-blob/read 链路，必须带稳定的 value handle；read 必须真实复制数据并区分“完整保存长度”和“本次 buffer 复制长度”。
- control 修改 sector size、max size、rollover 或模式后，C facade 与内部 allocator/storage 必须同步生效，并能跨 deinit/reinit 恢复。
- GC、scale-up、tombstone、TSL status 与 sector rollover 必须是持久化状态机的一部分，不能只靠内存集合模拟当前值。
- 所有 FFI callback 使用设计中的 typed function pointer；不得用无类型 `void *` 加 `transmute` 代替已解析回调。
- FFI 边界不得泄漏每次 getter 分配的裸字符串，不得让 `unwrap`/panic 穿越 `extern "C"`。
- worker 不得手写 `core_rewrite_batches.jsonl`、implementation audit 或 check 回执；控制器从精确 owner 范围内的真实 diff 生成。
- core check 通过后才释放 facade。facade 缺少 core 能力时返回 `missing_core_capability`，由控制器产生新 core revision 并使旧 facade 回执失效；不存在通用 integration repair。
- 每次失败均启动同角色的新 session，只提供 packet、当前 owner 文件和有界失败 tail；不得把前一 session 的完整对话或全量日志重新注入。
- 修复只向前修改当前源码，不恢复历史源码，不使用 Git、`/tmp` 或 `cp` 备份/回退。

## 全阶段一致性

保持以下内容的一致视图：

- FlashDB 源文件和 public API；
- KVDB 和 TSDB 状态迁移；
- storage 抽象边界；
- Rust 模块归属；
- `logs/trace` 中的 source-to-Rust 证据。

Rust 项目必须从平台 C 输入和阶段产物推导生成。
