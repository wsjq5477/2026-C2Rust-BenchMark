# 06 - REWRITE_CORE_MODULES

## 目标

在不改变生成期合同的前提下按 `implementation_requirements` 完成 Rust 内部实现和 facade 接线，并在每批结束时立即用对应原始 C 场景验证，避免全部实现完成后才暴露架构和生命周期错误。

## 执行结构

外部仍是一个 `REWRITE_CORE_MODULES` 阶段。控制器按 requirement 依赖顺序每批最多选择 3 项：

```text
workflowctl parent run
  -> batch 1: IMPLEMENT_CORE -> bounded check
  -> batch 1: WIRE_FACADE -> build -> targeted C-Cross
  -> pass: batch 2
  -> fail: 同批 CORE/FACADE 修复，最多 2 次
  -> 预算耗尽: failed_final，继续其他批次
  -> final batch: wire remaining facade + implementation audit
  -> parent gate
```

不存在第三种 `INTEGRATION_REPAIR` agent。失败按照文件所有权返回原角色；每次重试启动新 session，只注入角色 packet、当前 owner 文件和有界失败 tail。

## 所有权合同

`generate_rust_scaffold.py` 在 `logs/trace/scaffold-manifest.json.rewrite_ownership` 中生成四类互斥路径：

| 类型 | 可写者 | 规则 |
|---|---|---|
| `core_owned_paths` | `IMPLEMENT_CORE` | 内部 placeholder、状态和行为实现 |
| `facade_owned_paths` | `WIRE_FACADE` | 外部函数体及内部 API 接线 |
| `frozen_contract_paths` | 无 | 生成期 ABI、布局和构建合同 |
| `shared_readonly_paths` | 无 | 两个角色均可读取的共享文件 |

函数体可写但签名不可改的 facade 函数由 `frozen_contract_symbols` 单独记录签名和 hash。四类路径必须覆盖 manifest 中全部生成文件且彼此无交集；worker packet 的写路径必须是其中一个 owner 集合的精确展开，不能使用通配符或临时扩权。

## 角色职责

### IMPLEMENT_CORE

- 只消费 task packet 中的 requirements 和必要内部文件；
- 只修改 `core_owned_paths`；
- 实现内部模型、状态、行为和供 facade 调用的 Rust API；
- 不修改 facade、ABI/layout 合同或共享文件；
- 只有 packet 事实不足时才可按规则局部读取 C 源码。

### WIRE_FACADE

- 只消费 packet 中的 `facade_contracts`、冻结签名和必要内部 API；
- 只修改 `facade_owned_paths`；
- 完成参数/返回值转换、边界检查、panic 隔离和内部 API 调用；
- 不修改 core，不重新设计外部接口，不系统性读取 C 工程；
- 若现有 core 缺少必要能力，以 `missing_core_capability` 返回控制器。

## 控制器状态与前向修订

`logs/trace/rewrite-state.json` 额外记录 `requirement_batches`、`current_batch_index`、每批 C-Cross 次数和回执。

- core check 通过后，`core_revision += 1`，阶段进入 `FACADE`；
- facade build 通过后，`facade_revision += 1`，并绑定当前 `core_revision`，随后运行当前批次 targeted C-Cross；
- C-Cross 通过才推进下一批；失败回到同批 CORE，2 次耗尽后记录 `failed_final` 并继续；
- facade 报告缺 core 能力时，阶段回到 `CORE`；
- 新 core revision 会使旧 facade 回执失效，随后必须重新执行 facade；
- 不恢复历史源码，不创建源码备份，所有修复都基于当前工作树向前修改。

这里的“回到 CORE”只改变下一责任人和 revision，不做 `git reset`、文件复制、`/tmp` 备份或 scaffold 再生成。

## 执行命令

父阶段开始：

```bash
python3 work/tools/workflowctl.py --root . begin --stage REWRITE_CORE_MODULES --agent rust-implementer
python3 work/tools/workflowctl.py --root . next-rewrite-worker
```

worker 完成后执行其 task packet 中带 nonce 的命令：

```bash
python3 work/tools/workflowctl.py --root . finish-rewrite-worker \
  --worker-run-id <WORKER_RUN_ID> --nonce <WORKER_NONCE> --status complete
```

facade 确认缺少内部能力时：

```bash
python3 work/tools/workflowctl.py --root . finish-rewrite-worker \
  --worker-run-id <WORKER_RUN_ID> --nonce <WORKER_NONCE> \
  --status missing_core_capability --reason '<缺失的内部能力>'
```

按 `workflowctl status` 或命令输出继续 `next-rewrite-worker`。状态进入 `READY` 后，执行输出中的父阶段 `finish --run-id ... --nonce ...`。

## 控制器检查

`IMPLEMENT_CORE` 完成时，控制器运行：

```text
cargo fmt --check
cargo check --all-targets
```

`WIRE_FACADE` 完成时，控制器运行：

```text
cargo fmt --check
cargo build --release
targeted C-Cross（当前 acceptance scenarios）
```

只有最后一批追加 `core_impl_audit.py`，并要求连接全部剩余 facade stub。

完整 stdout/stderr 写入 `logs/trace/rewrite-check/<role>/<attempt>/`；反馈给 worker 的内容受 `workflow-contract.json.rewrite_static.max_command_output_bytes` 限制，避免把重复构建日志重新注入上下文。

任务 packet 文件本身不设字节数门槛：它是 worker 启动后按需读取的工作说明，不是启动 prompt 的全量注入。控制器只限制会反复回传的命令失败 tail；若 `workflowctl` 返回错误，worker 必须停止本次尝试并原样报告，不得修改工作台合同、状态或证据绕过检查。

## 机器证据

控制器生成并维护：

```text
logs/trace/rewrite-state.json
logs/trace/rewrite-worker-runs/
logs/trace/rewrite-worker-receipts/
logs/trace/rewrite-check/
logs/trace/rewrite-c-cross/<batch>/attempt-*.json
logs/trace/core_rewrite_batches.jsonl
logs/trace/implementation-audit.json
logs/trace/06-rewrite-core-modules.md
```

worker 不手写这些证据。`changed_files` 来自控制器对 worker 前后快照的真实 diff，且必须全部属于该 worker 的精确 owner 路径。

## Gate 检查

父阶段 gate 至少验证：

- ownership schema 有效、四类路径互斥并完整覆盖生成文件；
- placeholder 文件属于 core，FFI function 文件属于 facade；
- frozen symbol 签名与生成期合同一致；
- rewrite 状态为 `READY`；
- 全部 requirement batch 为 `pass` 或 `failed_final`，有场景的批次必须绑定真实 targeted C-Cross receipt；
- 最新 core/facade 回执均为 `complete`；
- facade 回执绑定最新 core revision；
- worker 真实 diff 没有越权文件；
- controller check 回执均通过；
- 最终 implementation audit 通过，源码无 scaffold placeholder、FFI stub、`todo!()` 或 `unimplemented!()`；
- Rust release build 通过，且没有 C 源码进入 Rust 项目。

## 约束

- 不按具体业务模块、测试 suite 或固定用例硬编码拆分。
- 不让弱模型识别内外接口；生成工具依据 scaffold 的生成来源写 ownership。
- 不允许 worker 修改 workflow state、回执、检查结果、工作台工具、说明文档、评测测试或平台 C 输入。
- 不使用 Git、`/tmp`、`cp` 或重新生成 scaffold 来备份、回退或覆盖当前 Rust 源码。
- 不迁移测试，不链接 C 实现，不以“能编译”代替语义完成。

## 下一阶段交接

父 gate 通过后进入 `VERIFY_RUST_WITH_C_TESTS`，使用原始 C 测试证据验证完整 Rust 实现。REWRITE 内部 worker 的对话历史不传递到下一阶段。
