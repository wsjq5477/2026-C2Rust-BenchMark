# 03 - BUILD_C_MODEL

## 目标

基于 C 源码、头文件和测试建立结构化 C 工程模型。这个阶段只抽取事实，不做 Rust API 设计。

本阶段面向真实 FlashDB 输入扩展：`kvdb` 和 `tsdb` 是必须识别的核心域，但不是唯一可能出现的源码域。真实工程如果新增目录或文件，本阶段必须把它们纳入模型、分类或显式标记为未知，不能因为本地样例较小就漏掉。

## 执行主体

```text
flashdb-orchestrator
flashdb-migration Skill
work/tools/build_c_model.py
work/tools/gate.py
```

## 输入

```text
logs/trace/input_manifest.json
FlashDB/src/
FlashDB/inc/
FlashDB/tests/
FlashDB 根目录下递归发现的其他 .c/.h 文件
work/skills/flashdb-migration/SKILL.md
```

`FlashDB` 根目录来自：

```text
logs/trace/input_manifest.json.source_root
```

## 输出

```text
logs/trace/c_project_model.json
logs/trace/c_api_model.json
logs/trace/c_test_model.json
logs/trace/03-build-c-model.md
logs/trace/workflow_state.json
result/output.md
result/issues/00-summary.md
```

## 细节实现

新增确定性工具：

```text
work/tools/build_c_model.py
```

建议命令：

```bash
python3 work/tools/build_c_model.py \
  --manifest logs/trace/input_manifest.json \
  --output-dir logs/trace
```

### c_project_model.json

记录工程事实：

```json
{
  "source_root": "...",
  "all_c_files": [],
  "all_h_files": [],
  "modules": {
    "common": [],
    "kvdb": [],
    "tsdb": [],
    "file": [],
    "storage": [],
    "port": [],
    "utils": [],
    "tests": [],
    "extension": [],
    "unknown": []
  },
  "source_units": [],
  "source_files": [],
  "headers": [],
  "test_files": [],
  "unclassified_sources": [],
  "ignored_files": [],
  "include_graph": {},
  "build_files": []
}
```

模块分类先按文件名、路径和符号线索确定，例如：

- `fdb_kvdb.c` -> `kvdb`
- `fdb_tsdb.c` -> `tsdb`
- `fdb_file.c` -> `file`
- `fal`、`port`、`platform` 路径 -> `port` 或 `storage`
- `fdb_utils.c` -> `utils`
- `tests/*.c` -> `tests`

真实输入扩展时，必须遵守：

- 新增 `.c/.h` 文件必须出现在 `all_c_files` / `all_h_files`；
- 能分类的文件放入对应 `modules.<domain>`；
- 不能可靠分类但可能属于 FlashDB 的文件放入 `modules.unknown` 和 `unclassified_sources`；
- 明确不参与核心迁移的样例、工具或演示文件可以进入 `ignored_files`，但必须在 `03-build-c-model.md` 说明原因；
- `unknown` 不是本阶段失败条件，但不能被静默忽略。后续 `DESIGN_RUST_API` 必须决定它是扩展模块、支持模块、测试输入还是明确排除项。

`source_units` 用于记录单文件事实，建议结构：

```json
{
  "path": "ports/fal/fdb_port.c",
  "kind": "source",
  "role": "port",
  "domain_hints": ["storage", "platform"],
  "public_symbols": [],
  "includes": []
}
```

### c_api_model.json

记录 C API 事实：

```json
{
  "public_headers": [],
  "public_functions": [],
  "all_functions": [],
  "structs": [],
  "typedefs": [],
  "macros": [],
  "enums": [],
  "kvdb_symbols": [],
  "tsdb_symbols": [],
  "extension_symbols": [],
  "unmapped_public_symbols": []
}
```

提取范围：

- `inc/*.h`
- `src/**/*.c`
- manifest 中记录的其他 `.c/.h`
- 必要时读取 `tests/*.c` 中调用到的 public API

边界：

- 不做 Clang AST；
- 不做宏展开；
- 不做完整调用图；
- 不解析函数体业务语义；
- 不做 Rust API 决策。

如果后续阶段遇到宏或类型疑问，由 opencode 定点读取对应 C 文件；不要在本阶段把工具扩展成 C 编译器。

必须识别关键符号：

```text
fdb_kvdb_init
fdb_tsdb_init
```

同时要记录新增 public 符号：

- 任何 `fdb_*` 函数都必须进入 `public_functions`；
- 如果符号无法归入 KVDB/TSDB，也不能丢弃，应进入 `extension_symbols` 或 `unmapped_public_symbols`；
- `unmapped_public_symbols` 不代表失败，而是给下一阶段做 Rust API 设计时显式处理。

### c_test_model.json

记录测试事实：

```json
{
  "test_files": [],
  "test_functions": [],
  "kvdb_tests": [],
  "tsdb_tests": [],
  "extension_tests": [],
  "unclassified_tests": [],
  "scenario_tags": {}
}
```

测试函数可通过 `test_` 前缀、测试注册表、文件名和 main 调用关系识别。新增测试文件如果不属于 KVDB/TSDB，必须进入 `extension_tests` 或 `unclassified_tests`，并在阶段日志中说明后续处理策略。

`semantic_facts` 不得只记录“调用了什么函数”和“有几个 assert”。每个 scorer case 在可提取时必须保留深语义事实：

- `assertion_details` / `assertion_targets`：assert 宏验证的表达式和目标字段，例如 `oldest_addr`、`init_ok`、状态计数；
- `control_usage`：`fdb_kvdb_control` / `fdb_tsdb_control` 的控制命令；
- `data_shape`：KV 写入数量、blob 大小/sector 倍数、TSL append 数量；
- `scenario_features`：反向迭代、按时间迭代、多状态过滤、大 blob、跨 sector、GC 压力等子场景；
- `semantic_markers`：由事实推导出的 `verify_addr_alignment`、`use_control_interface`、`verify_persistence_after_reboot` 等义务。

`semantic_obligations` 必须优先使用这些具体义务；`assertion_intent` 只能作为兜底事实，不能单独证明深语义覆盖。

## 执行命令

```bash
python3 work/tools/gate.py --stage READ_C_PROJECT
python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace
python3 work/tools/gate.py --stage BUILD_C_MODEL
```

## Gate 检查

`gate.py --stage BUILD_C_MODEL` 必须检查：

- `c_project_model.json` 存在；
- `c_api_model.json` 存在；
- `c_test_model.json` 存在；
- `03-build-c-model.md` 存在；
- `c_project_model.json` 识别到 `kvdb`、`tsdb`、`tests`；
- manifest 中递归发现的 `.c/.h` 都被模型覆盖、分类、标记 unknown 或显式忽略；
- `c_api_model.json.public_functions` 非空；
- `c_api_model.json` 包含 `fdb_kvdb_init` 和 `fdb_tsdb_init`；
- 新增 `fdb_*` public 符号不能静默丢弃，必须进入 `public_functions`，并按情况进入核心域、扩展域或未映射清单；
- `c_test_model.json.test_functions` 非空；
- 高风险 scorer case 的 `semantic_obligations` 应包含可验证的 `verify_*`、`data_shape:*` 或 `scenario:*` 义务，而不是只停留在 `assertion_intent`；
- `workflow_state.json.current_stage == BUILD_C_MODEL`；
- `flashDB_rust` 不存在。

## 约束

- 不设计 Rust API。
- 不生成 Rust 项目。
- 不运行 cargo。
- 不修改 FlashDB C 输入。
- 不把测试语义简化成结论，只记录事实和粗标签。

## 下一阶段交接

成功后进入 `DESIGN_RUST_API`。下一阶段主要读取 C 模型和 Rust 架构知识；只有当 `unknown`、`unclassified_sources` 或 `unmapped_public_symbols` 需要人工/模型判断时，才定点回读对应 C 文件，不重新做无记录的隐式扫描。
