# 02 - READ_C_PROJECT

## 目标

定位平台提供的 FlashDB C 工程，只读取文件清单并生成输入 manifest。这个阶段不分析语义、不设计 Rust API。

本阶段的兼容目标是 **真实 FlashDB 输入扩展兼容**，不是任意 C 项目通用转换。评测平台提供的工程仍然是 FlashDB，但真实工程可能比本地样例包含更多目录、更多 `.c/.h` 文件、更多构建文件或更多测试入口。因此本阶段不得把 `src/`、`inc/`、`tests/` 之外的内容静默忽略。

## 执行主体

```text
flashdb-orchestrator + work/tools/scan_c_project.py + work/tools/gate.py
```

## 输入

```text
logs/trace/workflow_state.json
平台 FlashDB 工程目录
```

路径优先级：

```text
/app/code/judge-assets/02_02_c_to_rust/code/FlashDB
judge-assets/code/FlashDB
../judge-assets/code/FlashDB
```

## 输出

```text
logs/trace/input_manifest.json
logs/trace/02-read-c-project.md
logs/trace/workflow_state.json
result/output.md
result/issues/00-summary.md
```

## 细节实现

opencode 选择第一个存在且包含 FlashDB 源码特征的目录，记为 `$FLASHDB_SOURCE`。优先确认 `src/` 和 `tests/`，但扫描范围必须覆盖 FlashDB 根目录下的全部相关 C 文件。

运行扫描：

```bash
python3 work/tools/scan_c_project.py \
  --source "$FLASHDB_SOURCE" \
  --output logs/trace/input_manifest.json
```

`input_manifest.json` 至少包含：

```json
{
  "source_root": "...",
  "src_dir": "src",
  "tests_dir": "tests",
  "all_c_files": [],
  "all_h_files": [],
  "core_sources": [],
  "test_sources": [],
  "headers": [],
  "extra_sources": [],
  "extra_headers": [],
  "top_level_dirs": [],
  "build_files": [],
  "ignored_files": [],
  "counts": {}
}
```

字段含义：

- `all_c_files`：FlashDB 根目录下递归发现的全部 `.c` 文件；
- `all_h_files`：FlashDB 根目录下递归发现的全部 `.h` 文件；
- `core_sources`：明确属于核心源码的 `.c` 文件，通常来自 `src/`，但不局限于一层目录；
- `test_sources`：明确属于测试的 `.c` 文件，通常来自 `tests/`；
- `headers`：全部可读头文件，包括 `inc/`、`src/`、`tests/` 及扩展目录；
- `extra_sources`：不在典型 `src/`/`tests/` 分类中、但仍属于 FlashDB 输入的 `.c` 文件；
- `extra_headers`：不在典型 `inc/`/`src/`/`tests/` 分类中、但仍属于 FlashDB 输入的 `.h` 文件；
- `top_level_dirs`：FlashDB 根目录下的一级目录清单，用于后续识别真实输入是否比样例更多；
- `ignored_files`：明确因后缀、目录或规则被跳过的文件清单。跳过必须可解释，不得静默丢弃。

兼容策略：

- 样例工程只有 `src/`、`inc/`、`tests/` 时，manifest 仍可保持简洁；
- 真实工程新增 `ports/`、`samples/`、`tools/`、`examples/`、`demo/`、`platform/`、`plugins/` 等目录时，扫描阶段必须记录；
- 只有后续阶段确认某目录与核心迁移无关时，才能把它列为 `ignored_files`，并在阶段日志说明原因；
- 任何 `.c/.h` 如果没有进入 `core_sources`、`test_sources`、`headers`、`extra_sources`、`extra_headers` 或 `ignored_files` 中任一集合，视为 manifest 覆盖缺口。

更新 `workflow_state.json`：

```json
{
  "current_stage": "READ_C_PROJECT",
  "completed_stages": ["BOOTSTRAP", "INIT_WORKSPACE", "READ_C_PROJECT"],
  "checkpoint": "READ_C_PROJECT",
  "input_path": "$FLASHDB_SOURCE",
  "input_manifest": "logs/trace/input_manifest.json"
}
```

## 执行命令

```bash
python3 work/tools/gate.py --stage INIT_WORKSPACE
python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json
python3 work/tools/gate.py --stage READ_C_PROJECT
```

## Gate 检查

`gate.py --stage READ_C_PROJECT` 必须检查：

- `input_manifest.json` 存在；
- manifest 包含 `source_root`、`src_dir`、`tests_dir`、`core_sources`、`test_sources`、`headers`、`build_files`、`counts`；
- manifest 应覆盖递归发现的全部 `.c/.h` 文件；如果存在扩展目录文件，必须进入 `extra_sources`、`extra_headers` 或 `ignored_files`；
- `core_sources` 非空；
- `test_sources` 非空；
- `02-read-c-project.md` 存在；
- `workflow_state.json.current_stage == READ_C_PROJECT`；
- `completed_stages` 连续包含前三阶段；
- `flashDB_rust` 不存在。

## 约束

- 只读 FlashDB 文件系统信息。
- 不修改 `judge-assets`。
- 不进入 `BUILD_C_MODEL`。
- 不生成 Rust 项目。

## 下一阶段交接

成功后进入 `BUILD_C_MODEL`。下一阶段以 `input_manifest.json.source_root` 作为源码根。
