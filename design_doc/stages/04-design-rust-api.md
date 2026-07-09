# 04 - DESIGN_RUST_API

## 目标

基于 C 工程模型固定 Rust API、模块边界和测试侧调用接口。在写任何 Rust 实现前，先确定 public shape。

本阶段仍然是 FlashDB 专用设计，不追求任意 C 项目通用 API。但它必须兼容真实 FlashDB 输入扩展：`error`、`flash`、`kvdb`、`tsdb` 是核心模块，不能被省略；如果 C 模型中出现新增源码域、扩展符号或未分类文件，Rust 设计必须给出处理去向，不能只输出固定四个模块后忽略其余事实。

## 执行主体

```text
flashdb-orchestrator
flashdb-migration Skill
work/tools/design_rust_api.py
work/tools/gate.py
```

## 输入

```text
logs/trace/c_project_model.json
logs/trace/c_api_model.json
logs/trace/c_test_model.json
work/knowledge/flashdb-rust-architecture.md
work/skills/flashdb-migration/SKILL.md
```

## 输出

```text
logs/trace/rust_api_design.json
logs/trace/04-design-rust-api.md
logs/trace/workflow_state.json
```

## 细节实现

opencode 根据 C 模型和架构知识写出 `rust_api_design.json`，至少包含：

```json
{
  "crate_name": "flashdb_rust",
  "core_modules": ["error", "flash", "kvdb", "tsdb"],
  "support_modules": [],
  "extension_modules": [],
  "modules": ["error", "flash", "kvdb", "tsdb", "optional_support_module"],
  "core_types": [],
  "traits": [],
  "kvdb_api": [],
  "tsdb_api": [],
  "extension_api": [],
  "test_api": {},
  "c_abi_facade": {
    "structs": [],
    "functions": [],
    "c_type_map": {
      "rules": [],
      "resolved": {},
      "unresolved": []
    }
  },
  "error_model": {},
  "storage_model": {},
  "c_to_rust_symbol_map": {},
  "unmapped_symbols": [],
  "excluded_sources": []
}
```

其中 `optional_support_module` 只是示例占位，实际名称必须来自 C 模型和 `support_modules` / `extension_modules` 的设计结果。

核心设计项：

- `FlashStorage`：存储抽象；
- `MemFlash`：测试与内存场景；
- `FileFlash`：文件持久化场景；
- `FdbError`：统一错误类型；
- `KvDb`：KVDB 操作入口；
- `TsDb`：TSDB 操作入口；
- `TslRecord`：时间序列记录。

设计必须明确：

- C 的返回码如何映射为 `Result<T, FdbError>`；
- C 指针/缓冲区如何映射为切片、Vec、String 或 owned 类型；
- KVDB/TSDB 测试侧使用哪些 Rust public API；
- reload、gc、tombstone、append record 的语义保留点。
- `test_api.observables` 必须声明 C 测试需要的 Rust 观察接口，例如 `oldest_addr`、`is_initialized`、`sector_status`；
- `test_api.controls` 必须声明 C control 接口对应的 Rust builder/config/control 能力；
- `storage_constraints` 必须记录后端约束。如果 C 输入启用 POSIX file mode 或包含 file storage 源码，应声明 `backend: "file_sector_mode"`、sector 文件模式和 fd cache 约束。
- `c_abi_facade.structs` 必须完全来自 `c_api_model.json.abi_layouts`，每个结构体记录 `c_name`、`rust_name`、`sizeof`、`alignof`、`fields` 和 `notes`；
- `notes` 必须记录影响布局的 active macros 或条件编译说明，禁止在 Rust API 设计阶段重新猜测字段。
- `c_abi_facade.functions` 必须来自 `c_api_model.json.function_signatures`，覆盖 C runner、scorer case 和 `c_to_rust_symbol_map` 需要的 C symbols。每个函数必须记录 `c_symbol`、`rust_export`、`source_signature`、`return.rust_ffi_type`、`params[].rust_ffi_type`、`safe_target` 和 `required_by`；
- `c_abi_facade.c_type_map` 必须记录中等粒度的 C->Rust FFI 类型映射：primitive、typedef 链、enum/status code、struct value/pointer、`const char *`、`void *`、buffer + length、ownership/nullability。callback/function pointer 必须明确支持或进入 unresolved；
- `c_type_map.unresolved` 不得包含 C runner、scorer case 或 layout checker 依赖的关键路径类型。

扩展兼容项必须明确：

- `core_modules` 固定包含 `error`、`flash`、`kvdb`、`tsdb`；
- `support_modules` 用于承接真实 FlashDB 中的工具、格式、平台适配、存储辅助等支持逻辑；
- `extension_modules` 用于承接不能归入 KVDB/TSDB、但属于 FlashDB 核心迁移范围的新增源码域；
- `modules` 是最终 Rust 模块全集，应等于核心模块、支持模块和扩展模块的合并结果；
- `extension_api` 记录新增 public C API 的 Rust 设计；
- `unmapped_symbols` 记录当前阶段无法安全设计的 public C 符号，后续实现前必须处理；
- `excluded_sources` 记录明确不迁移的样例、演示、工具文件及排除理由。

禁止行为：

- 不得因为 `rust_api_design.json` 已经包含 KVDB/TSDB 就丢弃其他 `fdb_*` public 符号；
- 不得把新增 C 文件默认塞进 `kvdb` 或 `tsdb`；
- 不得在未记录理由的情况下排除真实 FlashDB 源文件。

## 执行命令

```bash
python3 work/tools/gate.py --stage BUILD_C_MODEL
python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json
python3 work/tools/gate.py --stage DESIGN_RUST_API
```

## Gate 检查

`gate.py --stage DESIGN_RUST_API` 必须检查：

- `rust_api_design.json` 存在；
- `04-design-rust-api.md` 存在且使用中文；
- `core_modules` 或 `modules` 包含 `error`、`flash`、`kvdb`、`tsdb`；
- 如果 C 模型存在扩展域、unknown 源文件或未映射 public 符号，`rust_api_design.json` 必须通过 `support_modules`、`extension_modules`、`extension_api`、`unmapped_symbols` 或 `excluded_sources` 给出处理去向；
- `core_types` 包含 `FlashStorage`、`MemFlash`、`FileFlash`、`FdbError`、`KvDb`、`TsDb`、`TslRecord`；
- `kvdb_api` 非空；
- `tsdb_api` 非空；
- `test_api` 已声明；
- 如果 C 测试义务包含 `verify_addr_alignment`，`test_api.observables` 必须包含 `oldest_addr`；
- 如果 C 测试义务包含 `verify_init_state`，`test_api.observables` 必须包含 `is_initialized`；
- 如果 C 测试义务包含 `use_control_interface`，`test_api.controls` 必须包含 control 等价接口；
- 如果 C 测试义务包含跨 sector 数据规模，`storage_constraints.backend` 必须为 `file_sector_mode`；
- 如果 `c_api_model.json.abi_layouts` 非空，`rust_api_design.json.c_abi_facade.structs` 必须一一覆盖并保留布局字段；
- `rust_api_design.json.c_abi_facade.functions` 必须覆盖 `c_to_rust_symbol_map`、KVDB/TSDB 关键路径和当前 scorer/test 需要的 C symbols；
- 每个 facade function 必须绑定 `source_signature`，且 return/params 必须声明 `rust_ffi_type`；
- `rust_api_design.json.c_abi_facade.c_type_map` 必须包含 `rules`、`resolved` 和 `unresolved`，关键路径类型不得 unresolved；
- `workflow_state.json.current_stage == DESIGN_RUST_API`；
- `flashDB_rust` 不存在或只允许在后续阶段创建。

## 约束

- 不写 Rust 源码。
- 不创建 `flashDB_rust`。
- 不运行 cargo。
- 不改变 C 模型事实。
- 不把 C API 机械照搬成裸指针 public API。
- 不把 `modules` 固定理解为只有四个文件；四个核心模块是下限，不是上限。
- 对新增真实 FlashDB 文件，只允许“设计为支持/扩展模块”“加入未映射清单”“明确排除并说明理由”三种处理方式。

## 下一阶段交接

成功后进入 `GENERATE_RUST_SCAFFOLD`。后续 Rust 文件必须按 `rust_api_design.json` 生成，不得临时改 public API。
