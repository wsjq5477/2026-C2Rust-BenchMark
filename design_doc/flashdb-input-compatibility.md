# FlashDB 真实输入扩展兼容策略

## 目标边界

本项目不是任意 C 项目到 Rust 的通用转换器。比赛目标始终是读取平台提供的 FlashDB C 工程，并生成 `flashDB_rust`。

但真实评测输入可能比本地样例更完整，可能出现：

- 更多 `.c` / `.h` 文件；
- 更多一级或多级目录；
- 更多 public `fdb_*` 符号；
- 更多测试文件和测试入口；
- 平台适配、存储适配、示例、工具、移植层等辅助目录。

因此系统必须做到：

- FlashDB 核心语义专用；
- FlashDB 输入规模变化可兼容；
- 不因样例较小而把目录、文件或符号写死；
- 不静默忽略新增文件、符号和测试。

一句话：**专用对象是 FlashDB，兼容对象是真实 FlashDB 工程的规模和布局变化。**

## 不做什么

本项目不承诺：

- 支持任意 C 项目；
- 自动理解任意业务领域；
- 把所有 C 语言特性完整建成 Clang AST；
- 用一套 generic 规则替代 FlashDB 的 KVDB/TSDB 语义设计。

这些能力超出比赛目标，也会稀释 FlashDB 迁移的确定性。

## 必须保留的 FlashDB 核心域

无论真实输入如何扩展，以下核心域都必须被识别和设计：

- `kvdb`：KV 数据库；
- `tsdb`：时间序列数据库；
- `flash` / `storage`：Flash 存储抽象；
- `error`：错误模型；
- `tests`：测试语义覆盖。

Rust 侧至少保留：

- `FlashStorage`
- `MemFlash`
- `FileFlash`
- `FdbError`
- `KvDb`
- `TsDb`
- `TslRecord`

这些是 FlashDB profile 的核心，不因扩展兼容而弱化。

## 真实输入扩展的处理规则

### 1. 扫描阶段必须全量覆盖

`READ_C_PROJECT` 必须递归记录 FlashDB 根目录下的相关 `.c/.h` 文件。文件只能进入以下集合之一：

- 核心源码；
- 测试源码；
- 头文件；
- 扩展源码；
- 扩展头文件；
- 明确忽略文件；
- 未分类文件。

不允许存在“扫描到了但 manifest 不记录”的 C/H 文件。

### 2. 建模阶段允许 unknown，但不允许丢失

`BUILD_C_MODEL` 可以无法立刻判断某个文件属于哪个语义域，但必须记录：

- 文件路径；
- include 关系；
- 函数、类型、宏、枚举等可抽取事实；
- 推断出的 `domain_hints`；
- 是否进入 `unknown` / `unclassified_sources`。

`unknown` 是待处理事项，不是失败，也不是忽略。

### 3. API 设计阶段必须给新增项去向

`DESIGN_RUST_API` 必须对新增文件和符号做出三类处理之一：

1. 纳入 `support_modules` 或 `extension_modules`；
2. 纳入 `extension_api` 或 `unmapped_symbols`；
3. 纳入 `excluded_sources`，并写清排除理由。

如果新增 public `fdb_*` 符号没有映射到 Rust API，也必须进入 `unmapped_symbols`，后续实现阶段不得绕过。

### 4. Gate 检查覆盖率，而不是只检查核心名

gate 不应只检查 `kvdb`、`tsdb` 是否存在。更重要的是检查：

- manifest 是否覆盖全部 `.c/.h`；
- C 模型是否覆盖 manifest 中全部相关文件；
- public `fdb_*` 符号是否全部记录；
- 未分类/未映射项是否进入显式清单；
- 真实输入扩展是否在阶段日志中说明处理方式。

核心域存在是下限，全量覆盖是安全网。

## 推荐数据结构

### input_manifest.json

```json
{
  "source_root": "...",
  "all_c_files": [],
  "all_h_files": [],
  "core_sources": [],
  "test_sources": [],
  "headers": [],
  "extra_sources": [],
  "extra_headers": [],
  "ignored_files": [],
  "top_level_dirs": [],
  "counts": {}
}
```

### c_project_model.json

```json
{
  "modules": {
    "common": [],
    "kvdb": [],
    "tsdb": [],
    "storage": [],
    "port": [],
    "utils": [],
    "tests": [],
    "extension": [],
    "unknown": []
  },
  "source_units": [],
  "unclassified_sources": []
}
```

### rust_api_design.json

```json
{
  "core_modules": ["error", "flash", "kvdb", "tsdb"],
  "support_modules": [],
  "extension_modules": [],
  "modules": ["error", "flash", "kvdb", "tsdb", "optional_support_module"],
  "kvdb_api": [],
  "tsdb_api": [],
  "extension_api": [],
  "unmapped_symbols": [],
  "excluded_sources": []
}
```

`optional_support_module` 是占位示例，真实模块名由 `DESIGN_RUST_API` 根据 C 模型决定。

## 阶段日志要求

每个阶段的中文日志必须记录扩展兼容信息：

- 本次输入是否存在样例之外的目录；
- 新增 `.c/.h` 文件数量；
- 未分类文件数量；
- 未映射 public 符号数量；
- 已排除文件及理由；
- 后续阶段需要处理的事项。

这样即使真实 FlashDB 比样例更复杂，也能做到问题可见、边界清楚、后续可修复。
