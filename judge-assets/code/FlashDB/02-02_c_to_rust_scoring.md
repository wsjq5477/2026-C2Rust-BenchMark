# C-to-Rust 转换项目评分 Skill

自动化测试 C2Rust（或类似工具）转换后的 Rust 项目，确定最优测试方案，执行测试并输出结构化评分报告。

## 适用场景

- 评估C2Rust重构后Rust代码质量

## 触发关键词

`c2rust 评分`, `c2rust 测试`, `rust 转换测试`, `评分 rust 项目`, `c-to-rust score`

## 工作流程

### Step 1 — 定位 Rust 项目

**输入**：项目根目录路径（默认当前 workspace）

**操作**：

1. 扫描项目目录，查找 Rust 项目标志文件：
   - `flashDB_rust` - c2rust重构后的rust项目目录名
   - `Cargo.toml` — Rust 项目入口。 如果找不到flashDB_rust，将带有Cargo.toml的目录作为rust项目

2. 识别 Rust 项目类型（见 Step 3 的判断依据）

3. 同时定位原始 C 项目的测试目录：
   - `<project>/tests/` — C 单元测试
   - `<project>/tests/benchmark/` — C 基准测试

**输出**：
- `rust_project_path` — Rust 项目绝对路径
- `c_project_path` — 原始 C 项目绝对路径
- `c_tests_path` — C 测试目录绝对路径
- `rust_project_type` — "c2rust_staticlib" | "c2rust_lib" | "manual_rust"

---

### Step 2 — 构建 Rust 项目

**前置条件**：需要 Rust 工具链（rustc, cargo）

**操作**：

1. 检查 `Cargo.toml` 中的 `crate-type`：
   ```toml
   [lib]
   crate-type = ["staticlib"]  # → 输出 librust.a (C ABI)
   crate-type = ["cdylib"]     # → 输出 librust.so (C ABI)
   # 无 [lib] 配置              # → 输出 Rust ABI rlib
   ```

2. 检查 `lib.rs` 中的 feature flag 需求：
   - `#![feature(linkage)]` → 需要 `RUSTC_BOOTSTRAP=1`
   - `#![feature(...)]` → 需要 nightly 或 `RUSTC_BOOTSTRAP=1`

3. 执行构建：
   ```bash
   # staticlib或cdylib 项目
   RUSTC_BOOTSTRAP=1 cargo build --release
   
   # 标准 Rust 项目
   cargo build --release
   ```

4. 构建目标产物：
   - `staticlib` → `target/release/librust.a`
   - `cdylib` → `target/release/librust.so`
   - `rlib` → `target/release/libflashdb.rlib`（仅供 Rust 消费）

5. 验证构建成功：检查产物文件是否存在且非空

**失败处理**：
- 编译错误 → 记录错误数量和类型，尝试修复警告级别问题
- 链接错误 → 检查是否缺少 C 依赖（flash 操作需要 C 实现）
- 构建失败 = 评分 0，报告标注 "build_failed"

**输出**：
- `build_success` — bool
- `build_warnings_count` — int
- `artifact_path` — 构建产物路径（成功时）
- `artifact_type` — "staticlib" | "cdylib" | "rlib" | "none"

---

### Step 3 — 确定自动测试方案

**判断逻辑**（按优先级顺序）：

---


#### 方案 A：C 测试链接 Rust 静态库

**条件**：
1. Rust 项目输出 C ABI（`staticlib` 或 `cdylib`）
2. Rust 函数使用 `#[unsafe(export_name = "xxx")]` 或 `extern "C"` 导出
3. Rust 数据结构使用 `#[repr(C)]` 与 C 内存布局兼容

**检查方式**：
```bash
# 检查 crate-type
grep "crate-type" <rust_project>/Cargo.toml

# 检查 C ABI 导出
grep -r "export_name\|extern \"C\"" <rust_project>/src/lib.rs | head -5

# 检查是否有 C 头文件兼容
ls <rust_project>/src/mod_*/types.h
```

**适用场景**：输出的项目（1:1 映射 C 函数签名）

**执行方式**：混合构建 — C 测试 runner + Rust 静态库
```bash
# 1. 编译 Rust 静态库
RUSTC_BOOTSTRAP=1 cargo build --release

# 2. 编译 C 测试，链接 librust.a
cd <c_tests_path>

# 编译 C 测试代码（仅编译，不链接原始 C 实现）
gcc -c kvdb_main.c tsdb_main.c -I../src -o kvdb_main.o tsdb_main.o

# 链接：C 测试代码 + Rust 静态库 + 系统库
gcc -o kvdb_test kvdb_main.o \
    -L<rust_project>/target/release \
    -lrust -lpthread -ldl -lm

gcc -o tsdb_test tsdb_main.o \
    -L<rust_project>/target/release \
    -lrust -lpthread -ldl -lm

# 3. 运行测试
./kvdb_test
./tsdb_test
```

**关键注意**：
- 确保输出的 Rust 代码保留了所有 C 函数名（`fdb_kvdb_init`, `fdb_kv_get` 等）
- 弱链接函数（`__attribute__((weak)`）在 Rust 中用 `#![feature(linkage)]` 实现
- Flash 操作的 C 实现需要同时链接（Rust 只转换了核心逻辑，flash 适配层仍是 C）


#### 方案 B：Rust 内置测试

**条件**：Rust 项目包含 `#[test]` 函数或 `tests/` 目录

**检查方式**：
```bash
# 检查 tests 目录
ls <rust_project>/tests/

# 检查 src 中的 #[test]
grep -r "#\[test\]" <rust_project>/src/
```

**适用场景**：Rust 重写项目自带 Rust 测试

**执行命令**：
```bash
cargo test 2>&1
```

Rust 测试用例是 Rust 代码自己写的，可能与 C 测试用例不一致。

额外分析原始项目C测试用例与rust测试用例是否一致，输出测试用例一致性分析报告


---

#### 方案 C：FFI 桥接层 + C 测试

**条件**：方案 A 和 B 都不可行（纯 Rust ABI，无 C 导出，无自带测试）

**操作**：为 Rust 项目创建 C FFI 桥接层

**桥接层模板**：
```rust
// src/ffi.rs — C ABI 桥接层
#![allow(non_camel_case_types)]

use core::ffi::{c_char, c_int, c_void};
use crate::{Kvdb, Tsdb, FdbError, ...};

// 类型映射
pub type fdb_kvdb_t = *mut Kvdb;
pub type fdb_tsdb_t = *mut Tsdb;
pub type fdb_err_t = c_int;
pub type fdb_db_type_t = c_int;

// 函数映射
#[no_mangle]
pub extern "C" fn fdb_kvdb_init(
    db: fdb_kvdb_t,
    name: *const c_char,
    path: *const c_char,
    default_kv: *mut c_void,
    user_data: *mut c_void,
) -> fdb_err_t {
    let name_str = unsafe { CStr::from_ptr(name) }.to_str().unwrap_or("");
    let path_str = unsafe { CStr::from_ptr(path) }.to_str().unwrap_or("");
    let result = unsafe { (*db).init(name_str, path_str) };
    match result {
        FdbError::NoErr => 0,
        _ => -1,
    }
}

// ... 对每个 C API 函数创建对应桥接
```

**修改 Cargo.toml**：
```toml
[lib]
crate-type = ["staticlib"]  # 改为输出 C ABI
```

**工作量评估**：需要桥接约 30-50 个函数 + 类型映射，工作量中等偏大。仅在 A/B 都不可行时使用。

完成桥接后按方案A执行测试

---

#### 方案选择决策表

| Cargo.toml crate-type | 有 Rust 测试? | 有 C ABI 导出? | 选择方案 |
|---|---|---|---|
| `staticlib` | 无 | 有（export_name） | **A** |
| `staticlib` | 有 | 有 | **A** |
| `rlib`（默认） | 有 | 无 | **B** |
| `rlib`（默认） | 无 | 无 | **C** |
| `cdylib` | 无 | 有 | **A** |

---

### Step 4 — 执行测试

**通用流程**：

1. 清理旧测试产物和数据文件：
   ```bash
   rm -rf fdb_kvdb1/ fdb_tsdb1/ storage_*
   ```

2. 执行选定方案的测试命令

3. 捕获完整输出（stdout + stderr）

4. 记录每个测试用例的执行结果

**方案 A 执行细节**：
```bash
cd <rust_project>
cargo test --test kvdb_tests 2>&1 | tee kvdb_test_output.txt
cargo test --test tsdb_tests 2>&1 | tee tsdb_test_output.txt
```

**方案 B 执行细节**：

1. 执行 Rust 内置测试：
```bash
cd <rust_project>
cargo test 2>&1 | tee rust_test_output.txt
```

2. **Rust 测试用例与 C 测试用例对比校验**（必选步骤）：

> **目的**：Rust 项目的测试用例是手工编写的，可能遗漏、新增或变更了 C 原项目的测试场景。必须逐一对应用例确保覆盖一致。若 Rust 测试用例与 C 原测试用例不一致，也判断为测试失败。

**对比流程**：

a. 提取 C 测试用例及其测试逻辑：
```bash
# KVDB 测试用例（C）— 提取函数名
grep -oP '(?<=void )test_\w+' <c_tests_path>/kvdb_main.c | sort
# TSDB 测试用例（C）— 提取函数名
grep -oP '(?<=void )test_\w+' <c_tests_path>/tsdb_main.c | sort
```

对每个 C 测试函数，提取以下**测试逻辑要素**（用于后续语义对比）：
- **目标 API**：测试调用了哪些 FlashDB C API（如 `fdb_kv_set`、`fdb_kv_get`、`fdb_kv_del` 等）
- **测试数据**：构造了哪些 KV key/value、TSL blob 数据、初始化参数
- **断言条件**：使用了哪些断言（如 `assert(result == FDB_NO_ERR)`、`assert(strcmp(...))` 等）及期望值

b. 提取 Rust 测试用例及其测试逻辑：
```bash
# Rust tests/ 目录下所有 .rs 文件中的 #[test] 函数
# 文件名不限制 — 允许 Rust 测试文件名与 C 测试文件名不同（如 kvdb_test.rs、db_tests.rs 等均可）
grep -r -oP '(?<=fn )\w+' <rust_project>/tests/ | grep -v '^Binary' | sort
```

对每个 Rust `#[test]` 函数，提取同样的**测试逻辑要素**：
- **目标 API**：测试调用了哪些 Rust API（如 `db.set()`、`db.get()`、`db.del()` 等，对应 C API 的语义等价调用）
- **测试数据**：构造了哪些 KV key/value、TSL blob 数据、初始化参数
- **断言条件**：使用了哪些断言（如 `assert_eq!()`、`assert!()`、`unwrap()` 等）及期望值

c. 对比规则（按 24 个标准测试用例逐一校验，**基于语义而非名称**）：

| 校验维度 | 判断逻辑 | 不一致时结论 |
|---|---|---|
| **C 有、Rust 缺失** | C 测试场景（如「KV 初始化」「创建 KV」）在 Rust 中找不到语义等价的测试 | `passed: false`，reason: `测试用例与C原测试用例不一致 — Rust缺少用例: {case_name}` |
| **C 无、Rust 新增** | Rust 测试场景无对应 C 测试场景（如 Rust 额外补充的边界测试） | `warn` 级别记录，不计入失败（允许 Rust 额外测试） |
| **测试逻辑不一致** | 目标 API 不匹配、测试数据构造不同、断言条件/期望值不一致 | `passed: false`，reason: `测试用例与C原测试用例不一致 — 测试逻辑不一致: {具体差异}` |

> **语义匹配规则**：不要求 C 与 Rust 测试函数名完全一致。通过**测试场景描述**（Step 6 的「描述」列，如「KVDB 初始化」「创建 KV」「设置 KV」）进行语义映射。匹配依据按优先级：
> 1. 测试场景语义（做什么）→ 优先匹配
> 2. 目标 API 调用链（调什么）→ 辅助确认
> 3. 函数名相似度（叫什么）→ 最低优先级，仅作参考

**测试逻辑一致性判断标准**：

| 逻辑维度 | 一致条件 | 不一致示例 |
|---|---|---|
| **目标 API** | Rust 测试调用的 API 与 C 测试调用的 API 语义等价（如 `fdb_kv_set` ≈ `db.set()`） | C 调用 `fdb_kv_set` 但 Rust 调用 `db.get()` |
| **测试数据** | 构造的 key/value、blob 内容、初始化参数与 C 测试数据含义一致（值可不同但等价） | C 用 key="temp" 但 Rust 用完全不同类型/结构的 key |
| **断言条件** | 断言类型和期望行为等价（如 C 的 `assert(result == 0)` ≈ Rust 的 `assert!(result.is_ok())`） | C 期望 FDB_NO_ERR 但 Rust 期望返回错误 |

d. 输出一致性分析结果：
```json
{
  "test_case_consistency": {
    "consistent": false,
    "c_only": ["test_fdb_gc", "test_fdb_gc2"],
    "rust_only": ["test_extra_boundary_case"],
    "logic_mismatch": [
      {
        "case_id": "12",
        "c_func": "test_fdb_scale_up",
        "rust_func": "test_kv_expansion",
        "dimension": "assertion",
        "detail": "C 期望扩容后 sector 数=4，Rust 期望=2"
      }
    ],
    "total_c_standard": 24,
    "rust_matched_count": 20,
    "rust_file_count": 3
  }
}
```

**关键规则**：
- 若任意标准 C 测试场景在 Rust 中缺失 → 该用例对应的 `case_id` 直接标记 `passed: false`，reason: `测试用例与C原测试用例不一致 — Rust缺少用例: {case_name}`
- 若测试逻辑不一致（目标 API/数据/断言任一项不匹配）→ `passed: false`，reason: `测试用例与C原测试用例不一致 — 测试逻辑不一致: {dimension}`
- 测试文件名称允许不同，用例函数名称允许不同，**仅按语义+逻辑匹配**
- 用例一致性校验是 `cargo test` 运行结果的**前置门禁**：先校验用例一致性，再结合运行结果综合判定
- 即使 `cargo test` 全部通过，若用例不一致（缺失/错配/逻辑不同），仍判定为测试失败

**方案 C 执行细节**：
1. 创建桥接层代码
2. 修改 Cargo.toml 为 `staticlib`
3. `cargo build --release`
4. 编译 C 测试 + 链接 Rust 静态库
5. 运行 C 测试

**超时保护**：单个测试用例超过 60 秒视为阻塞/死循环，标记为 `passed: false`，reason: "timeout"

---

### Step 5 — 执行性能基线测试

在原项目 C 测试（`<c_project>/tests/benchmark/`）和 Rust 项目中分别运行性能基线测试，生成性能对比报告。

#### 5.1 执行 C 基准测试

```bash
cd <c_tests_path>/benchmark
# 编译 C 基准测试
gcc -o kvdb_benchmark kvdb_benchmark.c -I../../src -lm
gcc -o tsdb_benchmark tsdb_benchmark.c -I../../src -lm

# 运行并捕获输出
./kvdb_benchmark 2>&1 | tee c_kvdb_benchmark_output.txt
./tsdb_benchmark 2>&1 | tee c_tsdb_benchmark_output.txt
```

提取以下指标：
| 指标 | 提取方式 | 说明 |
|---|---|---|
| KV set 吞吐 (ops/s) | 解析 `kvdb_benchmark` 输出 | 每秒 KV 写入次数 |
| KV get 吞吐 (ops/s) | 解析 `kvdb_benchmark` 输出 | 每秒 KV 读取次数 |
| KV del 吞吐 (ops/s) | 解析 `kvdb_benchmark` 输出 | 每秒 KV 删除次数 |
| TSL append 延迟 (μs) | 解析 `tsdb_benchmark` 输出 | 单次 TSL 追加平均耗时 |
| 内存占用 (KB) | `ps -o rss=` 记录进程峰值 | 运行期最大 RSS |

#### 5.2 执行 Rust 基准测试（按方案分支）

**方案 A（C 测试 + Rust 静态库）**：

使用 C 基准测试程序链接 Rust 静态库，与功能测试方式相同：

```bash
cd <c_tests_path>/benchmark
gcc -o kvdb_benchmark_rust kvdb_benchmark.c \
    -I../../src -L<rust_project>/target/release -lrust -lpthread -ldl -lm
./kvdb_benchmark_rust 2>&1 | tee rust_kvdb_benchmark_output.txt
```

**方案 B（Rust 内置测试）**：

```bash
cd <rust_project>
# Rust 内置 benchmark（若存在 benches/ 目录）
cargo bench 2>&1 | tee rust_benchmark_output.txt

# 若无 benches/，使用 criterion 或手工计时循环替代
# 将 C 基准测试逻辑翻译为 Rust #[bench] 或 criterion benchmark
```

**方案 C（FFI 桥接层 + C 测试）**：

与方案 A 相同——编译 C 基准测试链接 Rust 静态库。

#### 5.3 生成性能对比报告

将 C 和 Rust 的基准数据汇入对比表：

| 指标 | C 项目 | Rust 项目 | 比值 (Rust/C) | 结论 |
|---|---|---|---|---|
| KV set 吞吐 (ops/s) | `c_ops` | `rust_ops` | `ratio` | >1.0 更快 / <1.0 更慢 |
| KV get 吞吐 (ops/s) | ... | ... | ... | ... |
| KV del 吞吐 (ops/s) | ... | ... | ... | ... |
| TSL append 延迟 (μs) | ... | ... | ... | <1.0 更快 / >1.0 更慢 |
| 内存占用 (KB) | ... | ... | ... | <1.0 更省 / >1.0 更多 |

**性能评级**：
- `ratio >= 1.0` → 性能达标或优于 C
- `0.7 <= ratio < 1.0` → 性能轻微下降（可接受）
- `ratio < 0.7` → 性能显著下降（需关注）

#### 5.4 性能报告输出与 summary 汇总

将性能对比结果浓缩为一句话写入 `summary.benchmark` 字段。同时生成完整性能对比报告（JSON 对象，字段 `benchmark` 与 summary 同级）。

**`summary.benchmark` 一句话模板**：

> "性能基线测试：Rust KV set/get/del 吞吐分别为 C 的 {x}%/{%y}%/{%z}%，TSL append 延迟为 C 的 {w}%"

示例：
- `"性能基线测试：Rust KV set/get/del 吞吐分别为 C 的 95%/102%/88%，TSL append 延迟为 C 的 110%"`

---

### Step 6 — 分析结果并输出评分报告

**测试用例映射**（FlashDB 标准 24 个测试场景）：

**KVDB 测试（13 个）**：
| case_id | C 测试函数 | 描述 |
|---|---|---|
| 1 | test_fdb_kvdb_init | KVDB 初始化 |
| 2 | test_fdb_create_kv | 创建 KV |
| 3 | test_fdb_set_kv | 设置 KV (string) |
| 4 | test_fdb_get_kv | 获取 KV (string) |
| 5 | test_fdb_set_kv_blob | 设置 KV (blob) |
| 6 | test_fdb_get_kv_blob | 获取 KV (blob) |
| 7 | test_fdb_del_kv | 删除 KV |
| 8 | test_fdb_del_kv_blob | 删除 KV blob |
| 9 | test_fdb_change_kv | 修改 KV |
| 10 | test_fdb_gc | GC 回收 |
| 11 | test_fdb_gc2 | GC 回收 (多 sector) |
| 12 | test_fdb_scale_up | 扩容 |
| 13 | test_fdb_kvdb_deinit | KVDB 去初始化 |

**TSDB 测试（11 个）**：
| case_id | C 测试函数 | 描述 |
|---|---|---|
| 14 | test_fdb_tsdb_init | TSDB 初始化 |
| 15 | test_fdb_tsl_append | 追加 TSL |
| 16 | test_fdb_tsl_append_by_time | 按时间追加 |
| 17 | test_fdb_tsl_iter | 正向迭代 |
| 18 | test_fdb_tsl_iter_reverse | 反向迭代 |
| 19 | test_fdb_tsl_iter_by_time | 按时间迭代 |
| 20 | test_fdb_tsl_query_count | 查询计数 |
| 21 | test_fdb_tsl_clean | 清理 TSL |
| 22 | test_fdb_tsl_set_status | 设置状态 |
| 23 | test_fdb_tsdb_control | TSDB 控制 |
| 24 | test_fdb_tsdb_deinit | TSDB 去初始化 |

**输出格式**：

```json
{
  "project": "项目名称",
  "rust_project_path": "绝对路径",
  "project_type": "c2rust_staticlib | manual_rust | other",
  "test_strategy": "A | B | C",
  "build": {
    "success": true,
    "warnings": 25,
    "artifact_type": "staticlib"
  },
  "results": [
    {"case_id": "1",  "name": "kvdb_init",       "passed": true},
    {"case_id": "2",  "name": "create_kv",       "passed": true},
    {"case_id": "3",  "name": "set_kv",          "passed": true},
    {"case_id": "4",  "name": "get_kv",          "passed": true},
    {"case_id": "5",  "name": "set_kv_blob",     "passed": true},
    {"case_id": "6",  "name": "get_kv_blob",     "passed": true},
    {"case_id": "7",  "name": "del_kv",          "passed": false, "reason": "assertion failed: KvNameErr != NoErr"},
    {"case_id": "8",  "name": "del_kv_blob",     "passed": false, "reason": "assertion failed"},
    {"case_id": "9",  "name": "change_kv",       "passed": true},
    {"case_id": "10", "name": "gc",              "passed": false, "reason": "expected 4096, got 0"},
    {"case_id": "11", "name": "gc2",             "passed": false, "reason": "expected 8192, got 0"},
    {"case_id": "12", "name": "scale_up",        "passed": false, "reason": "测试用例与C原测试用例不一致 — 测试逻辑不一致: C 期望扩容后 sector 数=4，Rust 期望=2"},
    {"case_id": "13", "name": "kvdb_deinit",     "passed": true},
    {"case_id": "14", "name": "tsdb_init",       "passed": true},
    {"case_id": "15", "name": "tsl_append",      "passed": true},
    {"case_id": "16", "name": "tsl_append_by_time", "passed": true},
    {"case_id": "17", "name": "tsl_iter",        "passed": false, "reason": "timeout 60s"},
    {"case_id": "18", "name": "tsl_iter_reverse", "passed": false, "reason": "timeout 60s"},
    {"case_id": "19", "name": "tsl_iter_by_time",  "passed": false, "reason": "timeout 60s"},
    {"case_id": "20", "name": "tsl_query_count",   "passed": false, "reason": "timeout 60s"},
    {"case_id": "21", "name": "tsl_clean",          "passed": false, "reason": "incorrect count"},
    {"case_id": "22", "name": "tsl_set_status",     "passed": false, "reason": "incorrect status"},
    {"case_id": "23", "name": "tsdb_control",       "passed": true},
    {"case_id": "24", "name": "tsdb_deinit",        "passed": true}
  ],
  "benchmark": {
    "kv_set_ops":     {"c": 12345, "rust": 11728, "ratio": 0.95},
    "kv_get_ops":     {"c": 45678, "rust": 46592, "ratio": 1.02},
    "kv_del_ops":     {"c": 9876,  "rust": 8691,  "ratio": 0.88},
    "tsl_append_us":  {"c": 12.3,  "rust": 13.5,  "ratio": 1.10},
    "memory_kb":      {"c": 2048,  "rust": 1856,  "ratio": 0.91}
  },
  "summary": {
    "total": 24,
    "passed": 11,
    "failed": 13,
    "pass_rate": 0.458,
    "kvdb_passed": 6,
    "kvdb_total": 13,
    "tsdb_passed": 5,
    "tsdb_total": 11,
    "build_passed": true,
    "benchmark": "性能基线测试：Rust KV set/get/del 吞吐分别为 C 的 95%/102%/88%，TSL append 延迟为 C 的 110%"
  }
}
```

**评分计算**：
- `pass_rate` = passed / total（0.0 ~ 1.0）
- 若 `build_success = false` → pass_rate = 0.0
- 超时测试 = `passed: false`（不计入 passed）
- **方案 B 特有规则**：用例一致性校验结果直接反映在 `results` 中 — 缺失/错配/逻辑不一致的标准 C 用例对应 `case_id` 直接标记 `passed: false`，reason: `测试用例与C原测试用例不一致 — {具体原因}`。此规则优先级高于 `cargo test` 运行结果。
- **性能基线评分**：基于 `benchmark` 各指标 ratio 计算综合性能分 `perf_score`（0.0~1.0），取所有指标 ratio 的几何平均值（memory 取倒数，越低越好）。`summary.benchmark` 字段为一句自然语言总结。

---

## 完整执行示例

### 示例 1：C2RustXW-CLI 输出（方案 A）

```bash
# Step 1: 定位项目
RUST_PROJECT=/workspace/ai_match/FlashDB/.c2rust/default/rust
C_PROJECT=/workspace/ai_match/FlashDB
C_TESTS=/workspace/ai_match/FlashDB/tests

# Step 2: 构建
cd $RUST_PROJECT
RUSTC_BOOTSTRAP=1 cargo build --release
# → target/release/librust.a (C ABI 静态库)

# Step 3: 判断方案
# crate-type = staticlib → C ABI
# 无 tests/ 目录 → 无 Rust 测试
# 有 #[unsafe(export_name)] → C ABI 导出
# → 选择方案 B

# Step 4: 执行方案 A
cd $C_TESTS
gcc -c kvdb_main.c -I../src -o kvdb_main.o
gcc -c tsdb_main.c -I../src -o tsdb_main.o

gcc -o kvdb_test kvdb_main.o \
    -L$RUST_PROJECT/target/release -lrust -lpthread -ldl -lm
gcc -o tsdb_test tsdb_main.o \
    -L$RUST_PROJECT/target/release -lrust -lpthread -ldl -lm

./kvdb_test && ./tsdb_test

# Step 5: 执行性能基线测试
cd $C_TESTS/benchmark
gcc -o kvdb_benchmark kvdb_benchmark.c -I../../src -lm
gcc -o tsdb_benchmark tsdb_benchmark.c -I../../src -lm
./kvdb_benchmark
./tsdb_benchmark
#（方案 A：Rust 基准复用 C 测试链接 librust.a）

# Step 6: 输出报告
# 预期结果: 24/24 pass (C2RustXW 是 1:1 映射，功能正确性保证)
```

### 示例 2： Rust Skill重写（方案 B）

```bash
# Step 1: 定位项目
RUST_PROJECT=/workspace/ai_match/flashdb-rust-manual
C_PROJECT=/workspace/ai_match/FlashDB

# Step 2: 构建
cd $RUST_PROJECT
cargo build --release
# → rlib (Rust ABI)

# Step 3: 判断方案
# crate-type = rlib (默认) → 无 C ABI
# 有 tests/ 目录 → 有 Rust 测试
# → 选择方案 B

# Step 4: 执行方案 B
cargo test --test kvdb_tests
cargo test --test tsdb_tests

# Step 5: 执行性能基线测试
cd $C_PROJECT/tests/benchmark
gcc -o kvdb_benchmark kvdb_benchmark.c -I../../src -lm
./kvdb_benchmark
#（方案 B：Rust 基准用 cargo bench 或翻译 C 基准逻辑后运行）

# Step 6: 输出报告
# 预期结果: 部分测试失败 (手动重写可能有逻辑 bug)
```

---

## 关键注意事项

1. **C/Rust 混合构建**：C 测试 runner + Rust 静态库需要同时链接 flash 适配层的 C 实现。纯 Rust 无法独立运行，因为 `fdb_flash_read/write/erase` 等底层操作在 C 测试环境中由 C 实现
2. **测试环境一致性**：所有方案必须在相同环境执行，确保文件系统行为一致
3. **数据清理**：每次测试前必须清理 `fdb_kvdb1/` 和 `fdb_tsdb1/` 目录，避免上次测试残留数据影响
4. **超时保护**：单个测试用例 >60s 视为死循环，强制终止并标记失败
5. **方案 A 的弱链接**：项目输出使用 `#![feature(linkage)]` 实现弱符号，需要 `RUSTC_BOOTSTRAP=1` 编译
