你现在要改造 FlashDB C-to-Rust 转换工程，目标是解决 C ABI 结构体布局被 Rust 转错的问题。

背景：
当前 build_c_model.py 只提取 struct 名字，不提取字段、偏移、sizeof、alignof 和条件编译信息，导致 rust-implementer 只能凭肉眼从 C header 猜 #[repr(C)] 布局。FlashDB 的 fdb_db 等结构体包含 #ifdef FDB_USING_FILE_MODE 条件字段，而当前配置中 FDB_USING_FILE_POSIX_MODE 会触发 FDB_USING_FILE_MODE，因此字段容易被遗漏。c_cross_validate.py 当前只做编译和运行，不做 layout 校验，导致错误只能以运行时 SIGSEGV 暴露。

请按以下要求开发：

新增 tools/abi_layout_extractor.py
输入 project root、include dirs、config headers、struct names。
使用 gcc 预处理或生成 C probe 的方式获取 C 编译器确认的 struct layout。
输出 JSON，包括 struct name、sizeof、alignof、fields、field offset、field sizeof、active macros。
第一版优先使用 C probe + sizeof + _Alignof + offsetof。
改造 tools/build_c_model.py
保留原有 API/符号提取能力。
新增 abi_layouts 字段。
将 abi_layout_extractor.py 的结果合并到 c_api_model.json。
至少覆盖 public API 直接使用的 FlashDB 结构体，例如 fdb_db, fdb_kvdb, fdb_tsdb, fdb_blob, fdb_kv, fdb_tsl。
改造 Rust API 设计生成逻辑
在 rust_api_design.json 中新增 c_abi_facade。
c_abi_facade.structs 必须来自 c_api_model.json.abi_layouts。
每个结构体包含 c_name、rust_name、sizeof、alignof、fields、notes。
notes 中记录条件编译字段。
修改 rust-implementer skill 文档
增加 C ABI Layout Rules。
明确要求所有 FFI struct 使用 #[repr(C)]。
字段顺序、类型宽度、sizeof、alignof、offset 必须匹配 c_abi_facade。
禁止仅凭原始 C header 猜测条件编译字段。
条件编译激活字段不得遗漏。
改造 tools/c_cross_validate.py
在运行 C functional runner 前，先生成并运行 layout checker。
layout checker 必须检查 C/Rust 两侧 struct 的 sizeof、alignof、关键字段 offset。
如果 mismatch，直接失败并输出 [LAYOUT MISMATCH]，不要继续跑功能测试。
输出中必须列出 missing fields、offset mismatch、sizeof mismatch 和可能原因。
Rust 侧新增可选 layout probe
在 src/ffi/layout_probe.rs 中导出 rust_sizeof_xxx、rust_alignof_xxx、rust_offsetof_xxx_field。
C layout checker 可链接 Rust staticlib，直接对比 C/Rust 编译产物。

完成后请提供：

修改文件列表。
新增 JSON schema 示例。
一次 layout checker 的通过日志示例。
一次故意遗漏条件字段时的失败日志示例。
说明如何运行完整验证链路。

---

## 已审核优化方案

采用“ABI layout 成为一等模型事实”的方案，把结构体布局从人工猜测改为可追踪、可 gate 的工程合同。

### 1. BUILD_C_MODEL 生成 ABI layout 事实

新增 `02_02/work/tools/abi_layout_extractor.py`。

输入：

- FlashDB project root；
- include dirs；
- config headers；
- struct names。

实现方式：

- 优先用 C probe 获取 C 编译器确认的 `sizeof`、`_Alignof`、`offsetof`；
- 通过预处理后的 header 解析当前配置下真正激活的字段；
- 记录 active macros，尤其是会影响布局的 `FDB_USING_*` 宏；
- 输出 JSON object，核心字段为 `abi_layouts`。

`build_c_model.py` 保留现有 API、symbol、test model 提取能力，在 `c_api_model.json` 中新增：

```json
{
  "abi_layouts": [
    {
      "name": "fdb_db",
      "header": "inc/flashdb.h",
      "sizeof": 64,
      "alignof": 8,
      "active_macros": ["FDB_USING_FILE_POSIX_MODE", "FDB_USING_FILE_MODE"],
      "fields": [
        {
          "name": "name",
          "ctype": "const char *",
          "offset": 0,
          "sizeof": 8,
          "condition": null
        }
      ]
    }
  ]
}
```

结构体候选从当前输入动态推导：优先 public API 参数、public header 中的 `fdb_*` struct 和 typedef，不把固定样例答案写死为唯一合同。FlashDB 已知 public ABI 结构体如 `fdb_db`、`fdb_kvdb`、`fdb_tsdb`、`fdb_blob`、`fdb_kv`、`fdb_tsl` 必须被覆盖，只要当前输入中存在且可由 C 编译器探测。

### 2. DESIGN_RUST_API 传递 ABI facade 合同

`design_rust_api.py` 在 `rust_api_design.json` 中新增：

```json
{
  "c_abi_facade": {
    "structs": [
      {
        "c_name": "fdb_db",
        "rust_name": "FdbDb",
        "sizeof": 64,
        "alignof": 8,
        "fields": [],
        "notes": [
          "Fields reflect active C preprocessor configuration from c_api_model.abi_layouts."
        ]
      }
    ]
  }
}
```

`c_abi_facade.structs` 必须来自 `c_api_model.json.abi_layouts`，不得由 Rust 设计阶段重新猜测字段。notes 记录条件编译字段和 active macros。

### 3. rust-implementer 遵守 C ABI Layout Rules

`rust-implementer` 增加明确规则：

- 所有 FFI struct 必须使用 `#[repr(C)]`；
- 字段顺序、类型宽度、`sizeof`、`alignof`、offset 必须匹配 `rust_api_design.json.c_abi_facade`；
- 禁止仅凭原始 C header 猜测条件编译字段；
- active macros 激活的字段不得遗漏；
- 如果 layout 合同不足，必须回派 `c-analyzer` 补充 `c_api_model.json.abi_layouts`，不能在实现阶段私自改 C 事实。

### 4. VERIFY_RUST_WITH_C_TESTS 先做 layout checker

`c_cross_validate.py` 在编译/运行 C functional runner 前先生成并运行 layout checker：

- 生成 `logs/trace/c-cross/layout_checker.c`；
- 链接 Rust staticlib；
- 比较 C/Rust 两侧 struct 的 `sizeof`、`alignof` 和关键字段 offset；
- mismatch 时输出 `[LAYOUT MISMATCH]`，写入 `layout-check.log`；
- mismatch 后不继续跑 KVDB/TSDB functional runner；
- `validation-matrix.json` 将相关 scorer cases 标为 `fail`，reason 中包含 layout mismatch 摘要。

通过日志示例：

```text
[LAYOUT CHECK] start
[LAYOUT OK] struct=fdb_db sizeof=64 alignof=8
[LAYOUT OK] struct=fdb_db field=name offset=0
[LAYOUT OK] struct=fdb_kvdb sizeof=120 alignof=8
[LAYOUT CHECK] pass
```

故意遗漏条件字段时的失败日志示例：

```text
[LAYOUT CHECK] start
[LAYOUT MISMATCH] struct=fdb_db sizeof c=64 rust=56
[LAYOUT MISMATCH] struct=fdb_db field=storage offset c=40 rust=missing
possible_reason=active macro FDB_USING_FILE_MODE added a C field that Rust omitted
[LAYOUT CHECK] fail
```

### 5. Rust 侧 layout probe

`generate_rust_scaffold.py` 生成可维护的 `src/ffi/layout_probe.rs` 或等价模块，导出：

- `rust_sizeof_xxx()`;
- `rust_alignof_xxx()`;
- `rust_offsetof_xxx_field()`;
- 字段缺失时可导出 sentinel 值，让 C checker 报出 missing field。

第一版允许 scaffold 提供 probe 框架，最终字段和类型由 `rust-implementer` 根据 `c_abi_facade` 补齐。

### 6. 完整验证链路

```bash
python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace
python3 work/tools/gate.py --stage BUILD_C_MODEL
python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json
python3 work/tools/gate.py --stage DESIGN_RUST_API
python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace
python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS
```

开发验证命令：

```bash
python3 -m py_compile \
  02_02/work/tools/abi_layout_extractor.py \
  02_02/work/tools/build_c_model.py \
  02_02/work/tools/design_rust_api.py \
  02_02/work/tools/generate_rust_scaffold.py \
  02_02/work/tools/c_cross_validate.py \
  02_02/work/tools/gate.py
python3 -m unittest 02_02.tests.test_conversion_system
git diff --check
```
