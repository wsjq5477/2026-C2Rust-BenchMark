# Q4 - C cross 验证频繁报错

## 现象

`VERIFY_RUST_WITH_C_TESTS` 阶段反复失败。当前最典型表现是 scorer scenario 全体 `fail`，没有部分通过的中间状态。

`c_cross_validate.py` 的真实执行链路已经是：

```text
编译 Rust staticlib -> layout checker -> 编译 C runner -> 运行 C runner
```

这条链路是必要的，但现在任何一层失败都会把后续层全部阻断。失败诊断通常只到 suite 级别，例如 “kvdb runner failed”，没有稳定落到具体 scenario、C 测试函数、C ABI 符号、参数类型或 layout 字段。

有时 `rust-implementer` 写出的 Rust `extern "C"` 函数与原始 C API 不一致：入参结构体类型对不上、参数顺序或个数对不上、返回值语义不一致、指针可空性和 ownership 判断不一致。这类不一致会导致：

- Rust staticlib 编译失败；
- C runner 链接失败；
- layout checker 失败；
- C runner 运行时语义失败；
- repairer 只能看到大范围失败，无法判断该回派 `c-analyzer`、`rust-implementer` 还是只修 harness。

## 判断

这不是单点 bug，而是当前流程的**验证风险累积结构**问题。

真实 harness 已经存在，strict gate 也已经禁止把 `not_supported` 当作通过条件；剩下的核心问题是：上游没有把 C ABI 所需的签名、类型、layout 和 test-to-scenario 映射提前固化成可执行合同，导致 `rust-implementer` 在实现阶段同时承担“猜 C API”“设计 FFI”“写业务逻辑”“修 C cross”的多重风险。

按阶段归属如下。

### BUILD_C_MODEL 阶段

当前 C 模型生成的函数主要是名字级事实，缺少完整 public function signature、参数列表、返回类型、typedef 关系、参数是否指针/数组/function pointer、可空性证据和声明来源。

`rust-implementer` 缺乏函数签名事实，只能回看 C 源码猜测参数类型和结构体对应关系，导致 Rust `extern "C"` 函数入参不一致、结构体类型对不上。

### DESIGN_RUST_API 阶段

当前 API 设计已经有 `c_abi_facade.structs`，但还没有形成完整 C ABI facade 合同：C 函数签名、C 类型到 Rust FFI 类型映射、safe Rust API 映射、返回码映射、ownership/nullability 规则和 unresolved gap 没有作为一个整体产出。

下游骨架和实现阶段缺乏确定性参考，无法稳定把 C 类型翻译成正确的 Rust FFI 类型。

### GENERATE_RUST_SCAFFOLD 阶段

当前骨架仍偏 placeholder：

- struct 以 `_opaque: [u8; N]` 为主；
- C ABI 函数以泛化 `fn() -> *mut c_void` 为主；
- layout probe 初始值来自合同常量，而不是 Rust 实际 struct；
- ABI wrapper 和 safe Rust 实现之间的映射没有在骨架阶段建立。

这会把 struct layout、函数签名和 C ABI wrapper 风险全部推迟到 `REWRITE_CORE_MODULES`，使实现阶段混入过多 ABI 基建问题。

### VERIFY_RUST_WITH_C_TESTS 阶段

当前验证是大爆炸模式。它能证明真实编译/链接/运行链路是否通过，但缺少递进 checkpoint：

- Rust build fail；
- layout fail；
- C runner link fail；
- runner runtime fail；
- 单个 C test fail；
- scenario mapping fail。

这些失败类型没有形成独立产物和稳定 diagnosis，repairer 无法精准定位哪个 scenario、哪个 C test、哪个 ABI 符号或哪个字段出了问题。

## 方案取舍

### 方案 A：只增强 `c_cross_validate.py` 的诊断

做法：保留上游模型不变，只在 `c_cross_validate.py` 里增加 `layout_check` / `link_check` / `full` 模式、逐 scenario 日志和更细 diagnosis。

优点是改动小、见效快。缺点是只能更好地报错，不能减少 `rust-implementer` 猜签名和猜类型导致的错误。C ABI 错误仍然会集中爆发在最后。

### 方案 B：C ABI 合同前移 + 分层 C cross 诊断

做法：在 `BUILD_C_MODEL` 提取函数签名和类型事实；在 `DESIGN_RUST_API` 产出完整 C ABI facade 合同；在 `GENERATE_RUST_SCAFFOLD` 生成 typed FFI scaffold；在 `VERIFY_RUST_WITH_C_TESTS` 增加分层 checkpoint 和逐 case 诊断。

优点是从源头降低 ABI 猜测，失败能回到正确阶段修复。缺点是要同时更新模型 schema、gate、scaffold、validator 和文档。

推荐采用这个方案。

### 方案 C：引入 Clang AST 做完整 C 解析

做法：用 libclang 或 clang JSON AST 统一抽取函数、typedef、struct、macro 条件和调用关系。

准确度高，但依赖重、环境要求高，也容易把工作台变成完整 C 编译器工程。当前比赛工作台更需要稳健、可解释、低依赖的合同链路，不建议作为 Q4 第一阶段方案。

## 推荐优化方案

目标不是让 `c_cross_validate.py` 替上游兜底，而是让 C cross 只做最终验证。ABI 事实必须尽量在前置阶段固化，验证失败必须能指向明确责任边界。

整体路线：

```text
BUILD_C_MODEL
  -> 提取 public function signatures、typedefs、ABI layouts、test invocation mapping

DESIGN_RUST_API
  -> 产出 c_abi_facade：struct layout + function signatures + c_type_map + symbol wrappers

GENERATE_RUST_SCAFFOLD
  -> 生成 typed #[repr(C)] struct、typed extern "C" wrappers、layout probe、staticlib 配置

REWRITE_CORE_MODULES
  -> 只实现 safe Rust 业务逻辑和 wrapper 调用，不重新设计 C ABI

VERIFY_RUST_WITH_C_TESTS
  -> 分层执行 build/layout/link/full，写逐 scenario 诊断和 repair handoff
```

## 分阶段优化设计

### 1. BUILD_C_MODEL：抽取函数签名和类型事实

#### 问题

当前 `public_functions`、`kvdb_symbols`、`tsdb_symbols` 主要是符号名集合，不足以生成 C ABI facade。缺少这些事实会导致下游猜测：

- return type；
- 参数数量、顺序、名称；
- pointer depth；
- `const` / mutable；
- struct/typedef/enum 对应关系；
- 数组参数、buffer 参数和长度参数关系；
- callback 或 function pointer；
- 哪个测试 runner 调用了哪个 public API。

#### 优化思路

在 `BUILD_C_MODEL` 增加“签名事实层”，仍然坚持轻量和通用：

- 不引入 Clang AST；
- 不把工具扩成完整 C 编译器；
- 不硬编码 FlashDB 固定函数清单；
- 使用当前输入的 public headers、active config 和 C 编译器可接受的预处理环境生成事实；
- 对无法确定的类型显式写入 `unresolved_signatures` / `unresolved_types`，由 gate 阻断被 C tests 或 scorer cases 需要的符号。

需要纠正一个细节：C 预处理能处理 `#include`、条件编译和宏展开，但不会展开 typedef。typedef 必须由 typedef 表、声明解析和小型 compiler probe 共同归一化，不能把“预处理后得到真实类型”作为单一前提。

#### 产物合同

`c_api_model.json` 新增或补强：

```json
{
  "function_signatures": {
    "fdb_xxx": {
      "name": "fdb_xxx",
      "header": "inc/xxx.h",
      "declaration": "fdb_err_t fdb_xxx(struct fdb_db *db, const char *name);",
      "return_type": {
        "raw": "fdb_err_t",
        "canonical": "enum_or_typedef:fdb_err_t",
        "category": "status_code"
      },
      "params": [
        {
          "index": 0,
          "name": "db",
          "raw_type": "struct fdb_db *",
          "canonical": "pointer:struct fdb_db",
          "pointer_depth": 1,
          "const": false,
          "nullable": "unknown",
          "ownership": "borrowed"
        }
      ],
      "varargs": false,
      "source": "public_header",
      "confidence": "compiler_accepted"
    }
  },
  "typedef_map": {},
  "enum_map": {},
  "unresolved_signatures": [],
  "unresolved_types": []
}
```

`c_test_model.json` 补强 C test 到 scenario 的连接：

```json
{
  "registered_test_invocations": [
    {
      "suite": "kvdb",
      "runner": "tests/kvdb_main.c",
      "test_function": "test_xxx",
      "order": 1,
      "scenarios": ["scenario_id_from_current_input"]
    }
  ]
}
```

#### Gate 要求

`BUILD_C_MODEL` gate 应检查：

- `function_signatures` 非空；
- 当前 `public_functions` 中被 `scorer_standard_cases`、registered tests 或 `c_to_rust_symbol_map` 需要的符号必须有签名；
- `function_signatures` 的参数 index 连续、name/type 存在、return_type 存在；
- unresolved 项允许存在，但必须有 `symbol`、`reason`、`source`，且不得覆盖必须迁移的 scorer/test 依赖符号；
- `abi_layouts` 继续由 compiler-backed probe 生成，不能由手写常量代替。

### 2. DESIGN_RUST_API：产出完整 C ABI facade 合同

#### 问题

`c_abi_facade.structs` 已经承接 layout，但函数签名、类型映射、wrapper 名称和 safe API 之间的关系仍不完整。下游知道“有哪些 struct”，但不知道“这些 C 函数应该如何用 Rust FFI 表达”。

#### 优化思路

把 `rust_api_design.json.c_abi_facade` 从 struct-only 合同扩展成完整 FFI 合同。它不是 safe Rust API 的替代品，而是原始 C runner 链接 Rust staticlib 的边界合同。

#### 产物合同

`rust_api_design.json` 中 `c_abi_facade` 建议结构：

```json
{
  "c_abi_facade": {
    "structs": [],
    "functions": [
      {
        "c_symbol": "fdb_xxx",
        "rust_export": "fdb_xxx",
        "source_signature": "c_api_model.function_signatures.fdb_xxx",
        "return": {
          "c_type": "fdb_err_t",
          "rust_ffi_type": "i32",
          "safe_mapping": "FdbError/status code"
        },
        "params": [
          {
            "name": "db",
            "c_type": "struct fdb_db *",
            "rust_ffi_type": "*mut FdbDb",
            "safe_role": "database handle",
            "nullable": false,
            "ownership": "borrowed_mut"
          }
        ],
        "safe_target": "KvDb::xxx",
        "required_by": ["c_runner", "scorer_case"]
      }
    ],
    "c_type_map": {
      "rules": [],
      "resolved": {},
      "unresolved": []
    }
  }
}
```

`c_type_map` 必须区分：

- C primitive 到 Rust FFI primitive；
- typedef 到 canonical type；
- enum/status code 到 Rust repr 类型；
- struct value、struct pointer、opaque handle；
- `const char *`、`void *`、buffer + length；
- nullable pointer 和 borrowed/owned pointer；
- function pointer/callback 如果当前输入出现，必须显式标注支持、暂不支持或回派。

#### Gate 要求

`DESIGN_RUST_API` gate 应检查：

- `c_abi_facade.structs` 仍完全覆盖 `c_api_model.abi_layouts`；
- `c_abi_facade.functions` 覆盖被 C tests、scorer cases 和 `public_functions` 迁移范围需要的 C symbols；
- 每个 facade function 必须绑定 `source_signature`；
- 每个参数和返回值必须有 `rust_ffi_type`；
- `c_type_map.unresolved` 不得包含必需 C runner 或 scorer case 依赖类型；
- safe API 和 C ABI facade 可以分层，但 symbol mapping 不能丢。

### 3. GENERATE_RUST_SCAFFOLD：生成 typed FFI 骨架

#### 问题

当前 scaffold 只是让符号存在，不能提前暴露签名和 layout 问题。`REWRITE_CORE_MODULES` 被迫重建 struct、函数签名和 layout probe，风险过晚暴露。

#### 优化思路

骨架阶段就生成可以被 Rust 编译器检查的 typed FFI 层。业务函数体仍可返回中性默认值，但 ABI shape 必须尽早固定。

#### 生成内容

`generate_rust_scaffold.py` 后续应按 `c_abi_facade` 生成：

```text
flashDB_rust/src/ffi/mod.rs
flashDB_rust/src/ffi/c_types.rs
flashDB_rust/src/ffi/c_abi.rs
flashDB_rust/src/ffi/layout_probe.rs
```

生成规则：

- `Cargo.toml` 固定包含 `crate-type = ["rlib", "staticlib"]`；
- `#[repr(C)]` struct 从 `c_abi_facade.structs` 生成；
- 能安全映射字段的 struct 必须生成真实字段；
- offset 间隙用显式 padding 字段填充，padding 命名必须稳定，例如 `_pad_0`；
- 只有完全不被 C runner 构造、不被 layout checker 检查字段、只作为 opaque handle 传递的类型，才允许 `_opaque`，并必须在合同中标记 `layout_mode: "opaque_handle"`；
- `extern "C"` 函数签名必须来自 `c_abi_facade.functions`，不能统一退化成 `fn() -> *mut c_void`；
- 默认函数体只允许返回类型正确的中性值，例如 status code、null pointer、false、0；不得 `todo!()`、`unimplemented!()` 或 panic；
- `layout_probe.rs` 必须用实际 Rust struct 计算 `size_of` / `align_of` / field offset，不能长期使用合同常量伪装通过。

#### Gate 要求

`GENERATE_RUST_SCAFFOLD` gate 除现有 `cargo check` 外，应检查：

- `src/ffi/mod.rs`、`c_types.rs`、`c_abi.rs`、`layout_probe.rs` 存在；
- `c_abi_facade.functions` 中每个 `rust_export` 都能在 `c_abi.rs` 找到；
- 生成的 C ABI 函数签名不能全部退化为 `fn() -> *mut c_void`；
- `layout_probe.rs` 不能只返回 `rust_api_design.json` 中的静态常量；
- 如果存在 `_opaque`，必须能从 `c_abi_facade.structs[].layout_mode` 解释，且不得用于 C runner 需要字段 offset 的 struct。

### 4. REWRITE_CORE_MODULES：只实现业务，不重写 ABI 合同

#### 问题

如果实现阶段继续自行改 struct 和 extern 签名，前面合同就失效，C cross 仍会变成最后大爆炸。

#### 优化思路

`rust-implementer` 在该阶段只允许：

- 实现 safe Rust core；
- 实现 C ABI wrapper 到 safe API 的调用；
- 在 `src/ffi/c_types.rs` 的既有 struct 中补业务需要的内部 helper，但不能破坏 `#[repr(C)]` 字段顺序和 layout；
- 发现合同缺口时写 `logs/trace/design-gaps.jsonl`，回派 `c-analyzer` 或要求重新运行前置阶段。

#### 约束

- 不得修改 `c_api_model.json`、`c_test_model.json`、`rust_api_design.json`；
- 不得通过临时改 C runner、删除 C test 或弱化 matrix 通过；
- 不得系统性重读 C 工程；需要 C 事实时只读取局部窗口；
- 修改 C ABI signature 必须来自更新后的 `c_abi_facade`，不能在 Rust 源码里私改。

### 5. VERIFY_RUST_WITH_C_TESTS：分层 checkpoint + 逐 case 诊断

#### 问题

真实 harness 已有，但失败类别混在一起，matrix 只按 suite 映射，repairer 很难定位。

#### 优化思路

`c_cross_validate.py` 保持一个正式阶段，但内部支持递进模式：

```text
--mode build       只编译 Rust staticlib
--mode layout      build + layout checker
--mode link        build + layout + C runner compile/link
--mode full        build + layout + link + run
```

不建议新增全局 `VERIFY_RUST_ABI` 阶段，避免流程继续变复杂。上述模式作为 `VERIFY_RUST_WITH_C_TESTS` 的内部 checkpoint 和 repair loop 工具即可。

#### 诊断产物

`logs/trace/c-cross/` 下新增分层产物：

```text
build-check.json
layout-check.json
link-check.json
case-results.jsonl
diagnostics.jsonl
```

`validation-matrix.json.scenarios[]` 保持现有字段，同时增强 reason/diagnosis：

```json
{
  "scenario_id": "dynamic_scenario_id",
  "scorer_case_id": "dynamic_case_id",
  "suite": "kvdb",
  "source_test": "test_xxx",
  "source_runner": "tests/kvdb_main.c",
  "c_symbol": "fdb_xxx",
  "rust_impl_c_test": "fail",
  "diagnosis": "c_abi_signature_mismatch",
  "failure_layer": "link",
  "reason": "undefined reference or incompatible symbol signature",
  "log": "logs/trace/c-cross/scenario.log",
  "handoff": "rust-implementer"
}
```

建议 diagnosis 分类：

```text
rust_staticlib_build_failed
c_abi_layout_mismatch
c_runner_link_failed
c_runner_runtime_failed
c_test_case_failed
c_cross_result_parse_failed
c_model_signature_gap
rust_implementation_matches_c_baseline_for_scenario
```

#### 逐 case 方案

第一步不强求每个 C assert 都独立通过，但必须从 suite-only 提升到 C test function 级别：

- 从 `c_test_model.registered_test_invocations` 获取 runner、`TEST_RUN` 顺序和 scenario 映射；
- 编译 runner 时生成 c-cross owned 的 instrumentation wrapper，记录每个 `TEST_RUN` 的 start/end/status；
- 如果原 C test framework 在首个 assert fail 后 abort，则当前 test 记为 `fail`，后续未执行 test 记为 `not_run` 并整体阻断 gate；
- `not_run` 只能作为失败后的诊断状态，不得让 strict gate 通过；
- scenario 数量来自 `c_test_model.scorer_standard_cases`，不得固定写死 24。

#### Gate 要求

`VERIFY_RUST_WITH_C_TESTS` gate 应检查：

- matrix 与 `c_test_model.scorer_standard_cases` 一一对应；
- `policy == "strict"`；
- `not_supported` 不允许通过；
- `fail` 不允许通过；
- `not_run` 只允许出现在前置失败后的诊断中，不允许通过；
- 每个阻断 scenario 必须有 `failure_layer`、`diagnosis`、`reason`、`log`、`handoff`；
- `log` 必须位于 `logs/trace/c-cross/`；
- `cross-compile.log`、`layout-check.log`、`cross-test.log` 继续保留，兼容现有报告链路；
- 新增 JSON/JSONL 产物用于机器诊断，短 markdown 日志用于人读。

## Repair / 回派规则

失败不应该都交给同一个修复者。`validation-matrix.json` 和 `diagnostics.jsonl` 必须给出建议 handoff：

| failure_layer | 典型 diagnosis | 归属 |
| --- | --- | --- |
| model | `c_model_signature_gap` / unresolved type | 回派 `c-analyzer` |
| scaffold | 缺 ffi 文件、签名退化、layout probe 仍是常量 | `rust-implementer` 的 scaffold 修复 |
| rust_build | `rust_staticlib_build_failed` | `rust-implementer` |
| layout | `c_abi_layout_mismatch` | 先看 `c_abi_facade`，模型错回派 `c-analyzer`，实现错回派 `rust-implementer` |
| link | `c_runner_link_failed` / symbol mismatch | 通常 `rust-implementer` 修 C ABI wrapper；若签名事实缺失，回派 `c-analyzer` |
| runtime | `c_runner_runtime_failed` / `c_test_case_failed` | `rust-implementer` 修业务或 wrapper |
| parse | `c_cross_result_parse_failed` | 修 `c_cross_validate.py` harness 解析 |

repairer 读取默认只读：

```text
validation-matrix.json 的失败 scenario 局部
logs/trace/c-cross/diagnostics.jsonl
对应 scenario log tail
必要的 c_abi_facade function/struct 局部
```

不得因为 C cross 失败就全文读取 trace 大 JSON 或系统性重读 C 源码。

## 后续落地顺序

如果按本方案执行，建议分 5 个小步落地，每步都能独立验证。

### Step 1：模型签名事实

修改范围：

```text
02_02/work/tools/build_c_model.py
02_02/work/tools/gate.py
design_doc/stages/03-build-c-model.md
02_02/work/skills/c-analyzer.md
相关测试
```

验收：

- `c_api_model.json.function_signatures` 动态生成；
- 必需 public/test/scorer 符号都有签名；
- unresolved 必须带 reason；
- 不固定函数名、case 数或 runner 名。

### Step 2：C ABI facade 合同

修改范围：

```text
02_02/work/tools/design_rust_api.py
02_02/work/tools/gate.py
design_doc/stages/04-design-rust-api.md
02_02/work/skills/c-analyzer.md
相关测试
```

验收：

- `rust_api_design.json.c_abi_facade.functions` 覆盖必需 C symbols；
- `c_type_map` 能解释每个参数和返回值；
- unresolved 必需类型阻断 gate。

### Step 3：typed scaffold

修改范围：

```text
02_02/work/tools/generate_rust_scaffold.py
02_02/work/tools/gate.py
design_doc/stages/05-generate-rust-scaffold.md
02_02/work/skills/rust-implementer.md
相关测试
```

验收：

- 生成 `src/ffi/*`；
- C ABI exports 是 typed signature；
- layout probe 使用真实 Rust layout 计算；
- `cargo check` 和 scaffold gate 通过；
- 不出现全量退化 `fn() -> *mut c_void`。

### Step 4：分层 C cross 诊断

修改范围：

```text
02_02/work/tools/c_cross_validate.py
02_02/work/tools/gate.py
design_doc/stages/06-5-verify-rust-with-c-tests.md
02_02/work/skills/rust-implementer.md
02_02/work/skills/repairer.md
相关测试
```

验收：

- 支持 `--mode build|layout|link|full`；
- 产出 `build-check.json`、`layout-check.json`、`link-check.json`、`case-results.jsonl`、`diagnostics.jsonl`；
- matrix 逐 scenario 带 `failure_layer` 和 `handoff`；
- strict gate 继续拒绝 `fail`、`not_supported`，并拒绝未解释的 `not_run`。

### Step 5：合同同步和报告

修改范围：

```text
02_02/INSTRUCTION.md
02_02/work/skills/*.md
02_02/work/knowledge/*.md
.opencode/skills/*
design_doc/stages/*.md
design_doc/参赛工程设计文档.md
02_02/work/tools/report_writer.py
相关测试
```

验收：

- 主控 prompt 仍只传动态上下文，不复制业务规则；
- subagent 文档是权威合同；
- 报告展示 C cross 分层结果；
- mirrors 与 `work/skills` 保持一致；
- 机器字段名保持英文稳定，中文只用于人读说明。

## 最终验收标准

本 Q4 优化完成后，应满足：

- Rust C ABI 函数签名来自 `c_api_model.function_signatures`，不是实现阶段猜测；
- struct layout 来自 compiler-backed `abi_layouts` 和 `c_abi_facade`，Rust 用真实 `#[repr(C)]` layout probe 验证；
- scaffold 阶段已经暴露 ABI shape 问题，不把全部风险压到 06.5；
- C cross 失败时可以定位到 build/layout/link/runtime/case/model gap；
- `validation-matrix.json` 动态覆盖当前输入的 scorer cases，不固定 24；
- `not_supported` 不作为通过条件；
- `repairer` 能根据 `failure_layer` 和 `handoff` 做小修或回派，不扩大读取边界；
- 不把 FlashDB C 源码复制进 `flashDB_rust/src/`；
- 不让最终 Rust 项目链接或编译 FlashDB C 实现；
- 不引入 Clang/libclang 作为必需依赖。

## 已确认决策

以下决策已完成对齐，后续实现应按这些结论执行：

1. 采用“方案 B：C ABI 合同前移 + 分层 C cross 诊断”作为主路线。不只增强 `c_cross_validate.py` 日志，而是在 `BUILD_C_MODEL`、`DESIGN_RUST_API`、`GENERATE_RUST_SCAFFOLD` 和 `VERIFY_RUST_WITH_C_TESTS` 串起完整 ABI 合同。
2. 不新增全局 `VERIFY_RUST_ABI` 阶段。ABI 验证作为 `VERIFY_RUST_WITH_C_TESTS` 的内部 checkpoint，通过 `--mode build|layout|link|full` 支持分层执行和 repair loop。
3. 不允许用 `_opaque` 偷懒。需要暴露给 C runner 或 layout checker 的 struct，Rust 必须生成真实 `#[repr(C)]` 字段布局，字段顺序、类型宽度、`sizeof`、`alignof` 和 offset 必须与 C 一致；必要 padding 必须显式生成。工具无法推导布局时应作为模型缺口 fail。
4. 函数签名和类型事实采用轻量 parser + C compiler probe。parser 提取声明和候选事实；`cc`/`gcc`/`clang` probe 确认 `sizeof`、`alignof`、`offsetof` 和类型可编译性。不引入 `libclang` / Clang AST 作为必需依赖。
5. unresolved 类型/签名采用关键路径严格 fail。C runner 调用、scorer case 覆盖、layout checker 检查的函数和类型如果 unresolved，必须阻断 gate；当前测试和评分不用的扩展 API 可记录为 unresolved，但必须带 `reason`、`source`、`owner` 和后续去向。
6. `c_type_map` 采用中等粒度，覆盖生成正确 C ABI wrapper 必需的信息：primitive、typedef 链、enum/status code、struct value/pointer、`const char *`、`void *`、buffer + length、ownership/nullability。callback/function pointer 必须明确支持或 unresolved，不允许猜。
7. scaffold 必须生成 typed FFI。`src/ffi/c_types.rs`、`src/ffi/c_abi.rs`、`src/ffi/layout_probe.rs` 在 `GENERATE_RUST_SCAFFOLD` 阶段就要固定 ABI shape；业务函数体可返回中性默认值，但签名和布局必须真实，不能退化成 `fn() -> *mut c_void` 或返回合同常量伪装通过。
8. C cross 诊断第一阶段的目标是做到 C test function 级。suite 级结果继续保留，但 matrix 和 `case-results.jsonl` 必须根据 runner 的真实执行输出分别判定每个 `source_test`；仅关联 `source_runner` 与 `source_test`、再把 suite 状态复制给全部 scenario，不算完成逐 test 判定。assert 级结构化诊断暂不强制，失败细节先保留在原始 runner 输出和 log tail。
9. repairer 回派策略进入 gate 和 report，但只做字段和枚举校验，不扩展成复杂自动调度系统。失败 scenario 必须包含 `failure_layer`、`diagnosis`、`reason`、`log`、`handoff`；`handoff` 使用有限枚举，并约束 repairer 默认只读失败局部、diagnostics、log tail 和必要 ABI 局部。

## 运行失败复盘与二次优化方案

本节基于 2026-07-09 的一次完整转换记录，对前述方案做二次复审。前述 ABI 合同前移、真实 layout checker、原始 C runner 和 strict final gate 继续保留；本节重点修正逐 test 判定、阶段阻断、修复收敛和运行写权限问题。

### 1. 本次失败的实际结论

本次真实执行链路不是环境或 C harness 启动失败：

- Rust `staticlib` 构建成功；
- C/Rust `sizeof`、`alignof` 和字段 offset 检查成功；
- KVDB、TSDB 原始 C runner 编译和链接成功；
- 两个 runner 都真实启动并执行测试；
- 原始 FlashDB C 实现在隔离临时目录中运行相同 KVDB、TSDB 测试均通过。

Rust 实现链接原始 C runner 后，实际明确失败的是 5 个 C test：

```text
test_fdb_gc
test_fdb_gc2
test_fdb_scale_up
test_fdb_tsl_set_status
test_fdb_tsl_iter_by_time_1
```

因此，本次失败属于 Rust 业务语义尚未完全匹配 C 基线，不属于 C 编译器缺失、layout checker 不可靠或 runner 无法链接。

### 2. 当前实现存在的工程问题

#### 2.1 suite 失败被错误放大为全部 scenario 失败

当前实现先得到 KVDB 或 TSDB runner 的整体退出码，再把同一个 suite 状态复制给 suite 下全部 scenario。结果是 5 个明确失败被写成全量 scenario 失败。

这会产生三个后果：

- 通过率失真，无法判断实现已经覆盖了哪些语义；
- repair agent 收到过大的错误范围，容易重复分析和大范围修改；
- 同一轮修复前后的进展无法比较。

`case-results.jsonl` 中出现 `source_test` 字段不等于已经完成逐 test 判定。只有每个 test 的状态来自该 test 的真实执行证据，才能标记为 `pass`、`fail` 或 `not_run`。

#### 2.2 阶段日志与实际修改时间不一致

本次 `REWRITE_CORE_MODULES` 阶段日志较早声明完成，但之后 Rust FFI、storage、KVDB 和 TSDB 文件仍持续修改，并且中间穿插运行 C cross。说明当前阶段状态只能表示“写过阶段日志”，不能证明实现和验证已经稳定结束。

后续不能再用一份提前写出的阶段 markdown 代替真实批次记录。每次实现和复测必须进入机器可读的 attempt 记录，最终 gate 以最后一次有效记录为准。

#### 2.3 C cross 命令不慢，未受控的修复过程才是风险

本次完整 build/layout/link/run 命令约数秒完成，未发现 `c_cross_validate.py` 自身存在无界循环。其外部命令已经有超时保护。

主要风险来自：

- 验证失败后没有统一的修复轮次定义；
- 没有判断本轮是否产生进展；
- 没有稳定失败指纹，代理可能重复修同一个问题；
- 运行代理曾修改工作台脚本，混淆了“修 Rust 实现”和“改验证规则”；
- 中间 C cross strict fail 直接阻断后续 Rust 测试，失去后续证据和统一修复机会。

### 3. 二次优化原则

二次优化不删除 C cross，也不降低最终质量要求。采用以下原则：

1. C cross 是原始 C 行为基线验证器，不负责现场修工作台；
2. 中间 C cross 是可继续的诊断 checkpoint，最终 C cross 是 strict gate；
3. 不依赖固定 wall-clock 时长控制循环，按失败指纹和结果是否收敛控制；
4. 不用固定通过比例作为放行条件，通过比例只用于安排修复优先级；
5. 增量验证按当前输入动态发现的 suite 和依赖执行，不固定 KVDB、TSDB 名称或 case 数；
6. 运行任务只修改迁移产物和证据，不修改工作台、设计文档或平台输入；
7. 最终仍要求原始 C tests 对 Rust 实现全部通过，`deferred` 不是最终豁免。

### 4. 调整后的执行流程

```text
GENERATE_RUST_SCAFFOLD
  -> cargo check
  -> c-cross build/layout/link checkpoint

REWRITE_CORE_MODULES
  -> 按动态模块批次实现
  -> 每批 cargo check
  -> 当前 suite 的依赖满足后，只运行该 suite
  -> 解析逐 C test 结果
  -> 有进展则继续定向修复
  -> 同一失败指纹连续 3 次无进展则 deferred

MIGRATE_TESTS + BUILD_TEST_REPAIR
  -> 即使中间存在 deferred C tests 也继续
  -> 利用 Rust tests 和新实现证据修复
  -> 相关实现变化后重新激活 deferred tests

REPORT_AND_VERIFY 前
  -> full C cross
  -> cargo build/test
  -> 全部严格通过后才允许 STATUS: SUCCESS
```

不强制为了执行 C cross 更换 agent。当前 `rust-implementer` 可以直接运行确定性命令并继续修复 Rust；主控负责检查 attempt 记录、推进 checkpoint 和执行最终 gate。是否切换 session 不是验收条件，产物和结果才是验收条件。

### 5. 增量 C cross 设计

#### 5.1 scaffold checkpoint

typed FFI scaffold 生成并通过 `cargo check` 后，立即执行：

```text
build -> layout -> link
```

此时不要求业务 runtime tests 通过，目标是提前确认：

- Rust `staticlib` 可以生成；
- C/Rust struct layout 一致；
- 当前输入需要的 C symbols 可以链接；
- typed function signature 没有把错误继续推迟到业务实现末尾。

build/layout/link 的中间失败写入诊断，但不伪装成 runtime test 失败。`cargo check` 或 Rust build 失败必须在继续实现前修复；layout/link 缺口进入当前实现批次的待修列表。

#### 5.2 suite checkpoint

suite 列表、suite 到 C test 的关系以及所需 symbols 必须从当前输入动态产生：

```text
c_test_model.registered_test_invocations
c_test_model.scorer_standard_cases
rust_api_design.c_abi_facade.functions[].required_by
core_rewrite_batches.jsonl
```

当某个 suite 依赖的 wrapper 和 owner module 已标记实现完成后，运行该 suite。修复后只重跑受影响 suite，不重复执行与本轮修改无关的 suite。

如果现有模型无法可靠证明某 suite 的依赖已经满足，则不猜依赖关系；该 suite 延迟到 core 全部完成后的 full checkpoint。

#### 5.3 full checkpoint

所有 core batch 完成后运行一次 full C cross。该次结果用于建立进入 Rust test migration 前的 C evidence baseline，但中间 runtime case 失败不再直接阻断 `MIGRATE_TESTS`。失败项进入 deferred/repair 流程，最终报告前必须再次 full 验证。

### 6. 原始 runner 的逐 test 判定

第一版不生成、不改写 C instrumentation runner，也不修改平台 C tests。直接运行原始 runner，结合模型中的注册顺序解析原始输出。

当前 FlashDB runner 的关键证据形如：

```text
Running: test_xxx ...
FAIL test_xxx: assertion text
```

判定规则：

- 出现 start/running 证据，且没有该 test 的 fail 证据：`pass`；
- 出现明确的 `FAIL test_name`：`fail`；
- runner 提前退出，模型中预期但没有 start 证据：`not_run`；
- runner 自身异常退出且无法归属到 test：suite 级 `runtime_error`，不能复制成全部 test fail；
- 输出中的 test 名必须映射到 `registered_test_invocations`；
- expected、started、failed、not_run 集合必须可闭合校验；
- 出现未知 test、重复歧义或集合无法闭合时：`c_cross_result_parse_failed`。

无法解析时必须 fail closed，不能猜测通过，也不能把 suite 状态批量复制给所有 scenario。中间 parse failure 可以记录后继续后续阶段；最终 full C cross 必须得到完整可解析结果。

#### 采用原始输出解析的原因

- 验证的仍是平台原始 runner；
- 不改测试宏，不引入临时测试语义变化；
- 一次 suite 运行即可得到多个 test 的结果；
- 当前输入已经输出稳定的 test 名和 fail 行；
- 比为每个 static C test 重新生成 runner 更轻量，也避免破坏共享 setup、teardown 和持久化状态。

其限制是依赖 runner 提供可关联的 test 名。该限制通过严格集合校验和 `c_cross_result_parse_failed` 显式暴露，不通过猜测兜底。

### 7. 修复轮次与进展判定

#### 7.1 失败指纹

每个失败至少形成以下稳定指纹：

```text
failure_layer
suite
source_test
normalized assertion/error
```

编译、layout、link、timeout 和 result parse 失败也必须有自己的指纹，不能全部归入 `c_runner_runtime_failed`。

#### 7.2 一次有效修复尝试

一次 attempt 必须同时包含：

1. 基于一个或一组相关失败指纹，对允许范围内文件做定向修改；
2. 清理对应 c-cross run directory；
3. 使用同一输入、配置和 runner 重跑受影响 suite；
4. 记录修改前后的 test 集合和失败指纹。

只重复命令但没有定向修改，不算一次修复 attempt。用于确认偶发错误的同条件重跑必须单独标记为 `confirmation_run`。

#### 7.3 有进展

以下任一情况视为有进展：

- 至少一个失败 test 变成 pass；
- 失败层次向后推进，例如 build -> link -> runtime；
- 同一个 test 原断言通过，失败移动到后续新断言；
- 一个公共修复消除了多个失败指纹；
- 通过集合严格增加，且没有引入更严重的回归。

有进展时，相关失败指纹的连续无进展计数清零。

#### 7.4 无进展

以下情况记为一次无进展：

- 同一 test 仍在同一断言或同一 normalized error 上失败；
- 通过集合没有增加，失败集合也没有向更后层次移动；
- 修改导致 build 回退或让原本通过的 tests 失败；
- 失败在近期指纹之间循环，例如 A -> B -> A。

超时、runner 崩溃或环境异常造成不可比较结果时，先自动做一次 confirmation run，不直接计入业务修复无进展。连续出现相同异常后，形成独立异常指纹并进入正常计数。

#### 7.5 deferred 规则

同一失败指纹连续 3 次无进展后：

- 标记 `status: deferred`；
- 停止在中间阶段继续消耗修复轮次；
- 进入后续 Rust test migration 和统一 repair；
- 只有相关 Rust 实现发生变化、Rust tests 提供新证据或失败指纹变化后，才重新激活；
- 最终 full C cross 不接受 deferred，必须转为 pass，否则最终 gate 失败。

### 8. 通过比例的用途

不设置 `80%`、`90%` 等固定中间放行比例。固定比例无法表达关键性：一个公共状态机错误可能造成大量失败，一个孤立的 reload/GC 失败也可能是评分关键语义。

通过比例和通过集合只用于：

- 判断修复是否收敛；
- 优先处理能消除多个失败的公共根因；
- 在少量孤立失败时缩小读取和修改范围；
- 在报告中展示迁移进展。

中间流程是否继续由 deferred 和进展规则决定；最终是否成功仍由完整 C baseline、Rust build/test 和 final gate 共同决定。

### 9. 运行期写权限边界

比赛运行不等待人工审批，也不新增哈希清单或文件完整性工具。通过主控和各 subagent 的权威提示词明确写权限。

允许范围：

| agent | 允许运行时修改 |
| --- | --- |
| `flashdb-orchestrator` | `logs/**`、`result/**`，以及正常调度生成的状态证据 |
| `c-analyzer` | `logs/**` 中的 C 模型、API 设计和阶段证据 |
| `rust-implementer` | `flashDB_rust/**`、`logs/**` 中的实现与 C-cross 证据 |
| `test-migrator` | `flashDB_rust/tests/**`、测试所需 Rust 文件、`logs/**` 中的 mapping/证据 |
| `repairer` | triage 明确授权的 `flashDB_rust/**`、`logs/**`、`result/issues/**` |

所有运行 agent 禁止修改：

```text
INSTRUCTION.md
work/**
.opencode/**
tests/**
design_doc/**
平台提供的 C 源码和 C tests
```

C cross 失败不能作为修改验证脚本、gate、skill 或设计文档的理由。如果运行中发现工作台缺陷，只写入：

```text
logs/trace/workbench-issues.jsonl
```

并包含 `tool`、`symptom`、`evidence`、`impact` 和建议维护动作。比赛运行继续使用赛前固定的工作台，不现场修工具。

### 10. 新增或调整的机器证据

在现有分层产物基础上，增加 attempt 和 deferred 证据：

```text
logs/trace/c-cross/attempts.jsonl
logs/trace/c-cross/deferred.jsonl
logs/trace/workbench-issues.jsonl
```

`attempts.jsonl` 每条至少包含：

```json
{
  "attempt_id": "dynamic-id",
  "kind": "repair",
  "trigger": "suite_checkpoint",
  "suite": "dynamic-suite",
  "changed_files": ["flashDB_rust/src/example.rs"],
  "before": {
    "passed": ["test_a"],
    "failed": ["test_b"],
    "not_run": []
  },
  "after": {
    "passed": ["test_a", "test_b"],
    "failed": [],
    "not_run": []
  },
  "fingerprints_before": ["runtime|suite|test_b|assertion"],
  "fingerprints_after": [],
  "progress": true,
  "no_progress_count": 0,
  "next_action": "continue"
}
```

`deferred.jsonl` 必须记录：

- failure fingerprint；
- 连续无进展次数；
- 三次 attempt 的 evidence path；
- 当前允许继续的后续阶段；
- 重新激活条件；
- 最终仍需通过的声明。

### 11. Gate 语义调整

#### 中间 checkpoint

中间 C cross 允许以下状态进入后续阶段：

```text
pass
fail_with_progress
deferred
parse_failed_recorded
```

但必须满足：

- 真实命令已执行，不允许 `not_supported` 冒充执行；
- 逐 test 集合可解释，或已明确记录 parse failure；
- 每个失败都有 fingerprint、evidence 和 next action；
- deferred 满足连续三次无进展证据；
- 没有修改禁止范围文件的自报记录；
- Rust 项目至少可以完成当前阶段要求的 `cargo check`。

这里的“允许进入后续阶段”不是宣告 C baseline 已通过，只是避免中间证据不足时永久阻断后续 Rust 测试和统一 repair。

#### 最终 checkpoint

最终 `REPORT_AND_VERIFY` 前的 full C cross 必须满足：

- build/layout/link 全部 pass；
- expected C tests 全部有可解析执行证据；
- 每个 scorer scenario 一一映射到真实 C test 结果；
- 所有 `rust_impl_c_test == pass`；
- 不存在 `fail`、`not_run`、`deferred`、`not_supported` 或未处理 parse failure；
- final full run 使用当前最终 Rust staticlib，不复用旧结果；
- cargo build/test 和其他最终 gate 条件继续满足。

只有最终 checkpoint 满足后，才允许输出 `STATUS: SUCCESS`。

### 12. 落地范围

后续实现应最小化修改并保持合同同步，重点范围为：

```text
02_02/work/tools/c_cross_validate.py
02_02/work/tools/gate.py
02_02/work/tools/report_writer.py
02_02/work/skills/flashdb-orchestrator.md
02_02/work/skills/rust-implementer.md
02_02/work/skills/test-migrator.md
02_02/work/skills/repairer.md
02_02/work/skills/flashdb-migration/SKILL.md
02_02/.opencode/skills 对应镜像
02_02/INSTRUCTION.md
design_doc/stages/05-generate-rust-scaffold.md
design_doc/stages/06-rewrite-core-modules.md
design_doc/stages/06-5-verify-rust-with-c-tests.md
design_doc/stages/08-build-test-repair.md
02_02/tests/test_conversion_system.py
```

不得把本次本地 Rust 实现中的固定函数、固定 test 名或固定 suite 数写入工作台逻辑。文档中的 5 个失败 test 只作为本次复盘证据，不作为 validator 的固定清单。

### 13. 二次优化验收标准

完成实现后必须验证：

- 本次 runner 输出能够得到真实的部分通过和 5 个明确失败，而不是全量失败；
- 未在 runner 中启动的 test 能标记为 `not_run`；
- 未知或歧义输出能得到 `c_cross_result_parse_failed`，不会猜测；
- suite checkpoint 只运行当前输入动态选择的 suite；
- 相关 suite 修复后通过集合增加会被判定为 progress；
- 同一指纹连续三次不变会进入 deferred；
- 新证据或相关实现变化能重新激活 deferred；
- 中间 deferred 不阻断 `MIGRATE_TESTS` 和 `BUILD_TEST_REPAIR`；
- final full C cross 仍拒绝任何非 pass 状态；
- 运行 agent 的文档明确禁止修改工作台和平台输入；
- `workbench_issue` 只记录证据，不触发比赛运行中修改工具；
- 所有 case、suite、symbol 和依赖关系来自当前输入模型，不固定数量或名称。

## 二次复审后的已确认决策

1. 保留真实 C cross；它已证明能发现 Rust 编译和普通 Rust tests 未必能发现的 C 行为差异。
2. 中间 C cross 改为可继续的诊断 checkpoint，最终 full C cross 保持 strict。
3. 不使用固定五小时或其他 wall-clock 作为工作台内部控制条件。
4. 同一失败指纹连续 3 次无进展后 deferred；有进展时相关计数清零。
5. 不设置固定通过比例作为中间放行条件，通过集合仅用于进展判定和修复排序。
6. 第一版解析原始 runner 的 start/fail 输出，不生成或改写 C instrumentation runner。
7. C cross 按实现批次和动态 suite 增量执行，全部 core 完成及最终报告前各执行一次 full。
8. 不强制为验证切换 agent；当前实现 agent 可以运行 C cross 并继续定向修 Rust。
9. 比赛运行只通过权威提示词约束写范围，不新增哈希清单或人工审批。
10. 运行中发现工作台问题只写 `workbench-issues.jsonl`，不得修改 `work/**`、gate、validator、skills 或设计文档。
