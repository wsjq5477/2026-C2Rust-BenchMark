# Q7: GLM vs GPT 执行对比分析

## 背景

用同一份 `02_02/INSTRUCTION.md` 分别由 GLM（CodeAgent/GLM-5.1）和 GPT 运行 FlashDB C-to-Rust 转换流水线。GLM 运行至 VERIFY_RUST_WITH_C_TESTS 停止。以下逐阶段对比关键差异。

---

## 1. INIT_WORKSPACE

| 维度 | GLM | GPT |
|------|-----|-----|
| 阶段日志 | 详细（20 行，含环境确认） | 极简（2 行） |
| gate 通过次数 | 2 次（workflow_state 缺字段） | 1 次 |
| agent-registry.json | 初始写为数组，gate 报错后改为对象 | 一次写对 |
| workflow_state | 缺 `checkpoint`、`completed_stages`、`input_path_candidates` 等 key | 一次含全量 key |

**不足**：对 `gate.py` 的校验规则不熟悉，`agent-registry.json` 应为 `{"subagents": {...}}` 对象而非数组，`workflow_state.json` 需包含 `checkpoint`/`completed_stages`/`input_path_candidates`/`rust_project_path` 等必填字段——这些全靠 gate 报错后才发现。

---

## 2. C_ANALYSIS（READ_C_PROJECT + BUILD_C_MODEL + DESIGN_RUST_API）

| 维度 | GLM | GPT |
|------|-----|-----|
| 执行方式 | 主控直接执行工具 | subagent 执行（c-analyzer, mode=isolated_proxy） |
| c_api_model | 有 abi_layouts（12 个 struct） | 有 abi_layouts |
| subagent 产物 | **丢失**（worktree 隔离，文件未写回主目录） | 正确落回主目录 |
| 主控补救 | 手动重跑 scan_c_project / build_c_model / design_rust_api | 不需要 |

**核心不足**：GLM 派出的 subagent 在 worktree 隔离模式下运行，所有文件写入隔离副本，主工作区无产物。主控不得不自己重新执行全部 C_ANALYSIS 工具。GPT 用 `isolated_proxy` 模式成功写回。

---

## 3. GENERATE_RUST_SCAFFOLD

| 维度 | GLM | GPT |
|------|-----|-----|
| 脚手架结构 | 相同（lib.rs, common.rs, error.rs, storage.rs, kvdb.rs, tsdb.rs, ffi/） | 相同 |
| gate | 1 次通过 | 1 次通过 |
| subagent 产物 | 同样丢失，主控手动验证 gate 已通过 | 无问题 |

此阶段差异不大，脚手架由 `generate_rust_scaffold.py` 自动生成，两者产出一致。

---

## 4. REWRITE_CORE_MODULES — **最大差距**

| 维度 | GLM | GPT |
|------|-----|-----|
| c_abi.rs 行数 | 225 行（**全是空 stub**） | **739 行**（完整实现） |
| storage.rs 行数 | 5 行（空） | **60 行**（KvState/TsState sidecar + Registry） |
| common.rs 行数 | 5 行 | **16 行**（crc32 实现） |
| c_types.rs | 174 行 | 151 行 |
| FFI 函数实现 | **全部返回 null/0/false** | **31 个 FFI 函数全部有真实业务逻辑** |
| cargo build | 通过 | 通过 |
| gate | 通过（只检查 fmt+build） | 通过 |

### GPT 的实现架构

GPT 在 REWRITE 阶段构建了完整的 **sidecar 状态机**：

**storage.rs**（60 行）：
- `KvState`：BTreeMap<String, KvRecord> 存 KV 值，next_addr 地址分配，scratch buffer，writes 计数，oldest_addr
- `TsState`：Vec<TslRecord> 存时序记录，next_addr 地址分配
- `Registry`：HashMap<usize, KvState/TSState> 按 db 指针地址索引
- `with_registry()`：全局 Mutex + OnceLock，poison-safe

**c_abi.rs**（739 行）核心逻辑：
- `fdb_kvdb_init`：setup parent 字段 + 初始化 sidecar
- `fdb_kv_set/get/del/blob`：BTreeMap 存取，地址分配，scratch buffer 管理
- `fdb_kv_iterate`：按序遍历 BTreeMap，填充 curr_kv
- `fdb_kvdb_control`：按 cmd 读写 sec_size/max_size/file_mode/not_formatable
- **GC**：检测 4-sector 阈值触发 compaction，relocate live records，更新 oldest_addr
- `fdb_tsdb_init`：setup parent + 注册 get_time callback + 初始化 sidecar
- `fdb_tsl_append/append_with_ts`：分配地址，存储 TslRecord
- `fdb_tsl_iter/iter_by_time/iter_reverse`：时间范围过滤 + 正/反向迭代
- `fdb_tsl_query_count`：按 status 过滤计数
- `fdb_tsl_set_status`：按 index_addr 匹配记录，更新 status
- `fdb_blob_make/read/to_blob`：blob round-trip 完整实现

**GLM 的实现**：所有 FFI 函数体为空（`std::ptr::null_mut()` / `0` / `false`），无任何业务逻辑。

### 根因分析

1. **subagent 隔离问题**：GLM 的 rust-implementer subagent 在 worktree 中运行，大量代码修改写入隔离副本后丢失。主控无法获得 subagent 的实现成果。
2. **调度提示不够明确**：REWRITE 阶段的调度提示未强调"逐函数实现业务逻辑"，subagent 可能认为只需通过 cargo build 即可。
3. **主控未做二次验证**：REWRITE gate 只检查 fmt+build，不检查函数体是否为空。主控应在 gate 通过后抽查 FFI 函数实现质量。

---

## 5. VERIFY_RUST_WITH_C_TESTS

| 维度 | GLM | GPT |
|------|-----|-----|
| Layout check | 初始全失败，**修了 6 个 struct 后全通过** | 初始失败，关键 layout 修复后通过；最终产物复跑一次通过 |
| c-cross 结果 | **9/24 pass, 8 fail, 7 not_run** | **24/24 pass** |
| 修复轮次 | 多轮（layout_probe 导出名、c_types 布局反复修正） | **13 次尝试，其中 9 次 repair** |

> 勘误：旧版上表的“一次通过”只描述 GPT 最终产物再次执行 layout check 的结果，不代表首次生成即正确。按第 7 节原始 attempts 证据，GPT 首次 checkpoint 为 0/24，经历 `layout_symbol_fix` 和关键的 `layout_struct_fix` 后才进入 20/24，最终修到 24/24。

### GLM 的 ABI 布局错误清单

| Struct | 错误 | 修复 |
|--------|------|------|
| FdbBlob | `saved` 写成 `u32`，实际是嵌套 struct `{meta_addr, addr, len}` | 改为 `FdbBlobSaved` |
| FdbDb | `storage` 写成 `*const c_char`，实际是 `union {dir}` | 改为 `FdbDbStorage` union |
| FdbDb | `cur_file_sec`/`cur_file` 写成标量，实际是数组 `[u32;2]`/`[i32;2]` | 改为数组 |
| FdbKv | `addr` 写成 `u32`，实际是嵌套 struct `{start, value}` | 改为 `FdbKvAddr` |
| FdbTsl | `addr` 写成 `u32`，实际是嵌套 struct `{index, log}` | 改为 `FdbTslAddr` |
| KvdbSecInfo | `status` 写成 `u64`，实际是嵌套 struct `{store, dirty}` | 改为 `FdbKvdbSecStatus` |
| TsdbSecInfo | `end_info_stat` 写成 `u64`，实际是 `[u32; 2]` | 改为数组 |
| FdbKvIterator | 多余的显式 `_pad_0` 导致 `iterated_obj_bytes` 偏移错位 | 移除显式 padding |
| layout_probe | `rust_offsetof_fdb_db_type_`（因 `r#type` 自动加下划线） | 改为 `rust_offsetof_fdb_db_type` |

### GPT 的 c_types.rs 策略差异

GPT 最终产物采用了更务实的方式：
- FdbKv/FdbKvdb/FdbTsdb 的内部字段用 `[u8; N]` 不透明字节表示（`curr_kv: [u8; 92]`, `parent: [u8; 88]`），避免逐字段映射的复杂性
- FdbKv 的 `addr` 拆为 `addr: u32` + `value_addr: u32` 两个平面字段，而非嵌套 struct
- KvdbSecInfo.status 用 `[u8; 8]`，TsdbSecInfo.end_info_stat 用 `[u8; 8]`
- FdbKvIterator.curr_kv 用 `[u8; 92]`，避免 FdbKv 的对齐传播问题

这种策略牺牲了类型安全性，但大幅降低了 ABI 布局出错的概率——不透明字节块不会因字段对齐产生偏移错误。它是历史运行中的人工修复策略；本轮工程升级后，优先由 C 模型、编译器 probe 和确定性 scaffold generator 自动选择精确字段、数组、union 或不透明字节块，避免要求弱模型自行猜布局。

---


## 三大核心差距总结

### 差距 1：REWRITE_CORE_MODULES 空实现（致命）

**现象**：GLM 的 FFI 函数全部为空 stub，c-cross 仅 9/24 通过。GPT 实现了完整 sidecar 状态机，c-cross 24/24 通过。

**根因**：
1. Subagent 报告完成但文件实际未写入主工作区（详见差距 3 分析）
2. 调度提示未明确要求"逐函数实现业务逻辑"
3. REWRITE gate 只检查 fmt+build，不检查函数体是否为空

**改进**：
1. 主控应在 REWRITE 阶段直接执行代码编写，而非依赖 subagent
2. 调度提示应明确列出"每个 FFI 函数必须有业务实现，不得返回 null/0/false"
3. gate 通过后主控应抽查 c_abi.rs 的函数体，验证非 stub

### 差距 2：ABI 布局一次性正确率低

**现象**：GLM 对 6 个 struct 的布局理解错误，需多轮修复。GPT 一次做对。

**根因**：
1. `generate_rust_scaffold.py` 生成的 c_types.rs 本身就有错误（saved=u32, addr=u32 等）
2. REWRITE 阶段未先对照 C header 验证 c_types.rs 布局
3. 对 C 嵌套 struct/union/条件编译字段的建模不够细致

**改进**：
1. REWRITE 阶段应先读取 C header（在 120 行窗口限制内）验证每个 struct 的字段定义
2. 考虑采用 GPT 的"不透明字节块"策略：对 FdbKv/FdbKvdb/FdbTsdb 等复杂 struct 用 `[u8; N]` 表示内部字段，只对 C runner 直接访问的字段做 typed mapping
3. 在 c_cross_validate 之前先单独运行 layout check，提前发现布局问题

### 差距 3：Subagent 产物部分丢失

**现象**：GLM 派出的 subagent 报告任务完成，但主控检查时发现部分文件缺失。规律：**脚本生成的文件和 Rust 源码修改有时存在，但 subagent 用 Write/Edit 工具写的文件几乎全部缺失。**

#### 逐 subagent 缺失清单

**c-analyzer（C_ANALYSIS）后：**

| 应存在 | 实际 |
|--------|------|
| `logs/trace/input_manifest.json` | 不存在 |
| `logs/trace/c_project_model.json` | 不存在 |
| `logs/trace/c_api_model.json` | 不存在 |
| `logs/trace/c_test_model.json` | 不存在 |
| `logs/trace/rust_api_design.json` | 不存在 |
| `logs/trace/02-read-c-project.md` | 不存在 |
| `logs/trace/03-build-c-model.md` | 不存在 |
| `logs/trace/04-design-rust-api.md` | 不存在 |
| `logs/trace/workflow_state.json` 更新 | 未更新（仍是 INIT_WORKSPACE） |
| `logs/trace/subagent-invocations.jsonl` 追加 | 空文件（0 字节） |

**rust-implementer（scaffold）后：** 无缺失，gate 一次通过。

**rust-implementer（rewrite）后：**

| 应存在 | 实际 |
|--------|------|
| `logs/trace/06-rewrite-core-modules.md` | 不存在 |
| `logs/trace/core_rewrite_batches.jsonl` | 不存在 |
| `logs/trace/workflow_state.json` 更新 | 未更新 |
| `logs/trace/subagent-invocations.jsonl` 追加 | 未追加 |
| `flashDB_rust/src/` 下 Rust 源码 | **有修改**（c_abi.rs, c_types.rs, layout_probe.rs） |

**rust-implementer（verify）后：**

| 应存在 | 实际 |
|--------|------|
| `logs/trace/c-cross/` 整个目录 | 不存在 |
| `logs/trace/validation-matrix.json` | 不存在 |
| `logs/trace/06-5-verify-rust-with-c-tests.md` | 不存在 |
| `logs/trace/workflow_state.json` 更新 | 未更新 |
| `logs/trace/subagent-invocations.jsonl` 追加 | 未追加 |

**规律总结**：脚本产物（`input_manifest.json` 等）和 Rust 源码修改有时存在，但 subagent 用 Write/Edit 工具写入的文件（阶段日志、workflow_state 更新、invocations 追加）几乎全部缺失。

**根因**：Agent tool 启动的 subagent 可能因以下原因导致部分产物丢失：
1. **工作目录不一致**：subagent 的 CWD 可能不是 `02_02/`，导致文件写到了错误路径
2. **subagent 虚报完成**：subagent 在回复中声称写入了文件，但实际未执行写入操作（LLM 幻觉）
3. **文件系统上下文隔离**：Agent tool 的 subagent 进程可能存在某种沙箱机制，使 Write/Edit 的变更对主控不可见

注意：这不是 `isolation: "worktree"` 导致的——GLM 派 subagent 时并未使用该参数。

**改进**：
1. 主控直接执行关键阶段（尤其 REWRITE_CORE_MODULES），不依赖 subagent 写入代码
2. 如果使用 subagent，主控应在 subagent 返回后立即验证文件是否真正存在
3. 对于必须由 subagent 完成的工作，主控应自己补写缺失的产物（阶段日志、workflow_state 更新等）

---

## 6. C-Cross 逐测试对比（2026-07-13 补充）

### 6.1 总览

| 指标 | GLM | GPT |
|------|-----|-----|
| 总通过率 | 9/24 (37.5%) | 24/24 (100%) |
| KVDB 通过 | 2/13 (15.4%) | 13/13 (100%) |
| TSDB 通过 | 7/11 (63.6%) | 11/11 (100%) |
| KVDB runner 退出码 | -11 (SIGSEGV) | 0 |
| TSDB runner 退出码 | 1 | 0 |

### 6.2 KVDB 逐测试明细

| 测试 | GPT | GLM | GLM 失败原因 |
|------|-----|-----|------------|
| kvdb_init | ✅ | ✅ | — |
| kvdb_init_check | ✅ | ✅ | — |
| create_kv_blob | ✅ | ❌ | `blob.saved.len=1625937464`（stub 返回 null，内存垃圾） |
| change_kv_blob | ✅ | ❌ | `blob->saved.len=-1851114752`（同上） |
| del_kv_blob | ✅ | ❌ | `blob.saved.len=-1851114752`（同上） |
| create_kv | ✅ | ❌ | `fdb_kv_get` 返回 NULL |
| change_kv | ✅ | ⬜ not_run | runner 已 SIGSEGV，后续全未运行 |
| del_kv | ✅ | ⬜ not_run | 同上 |
| gc | ✅ | ⬜ not_run | 同上 |
| gc2 | ✅ | ⬜ not_run | 同上 |
| scale_up | ✅ | ⬜ not_run | 同上 |
| set_default | ✅ | ⬜ not_run | 同上 |
| deinit | ✅ | ⬜ not_run | 同上 |

**关键**：KVDB runner 在 `test_fdb_create_kv` 处 SIGSEGV 崩溃，导致后续 7 个测试全部 not_run。根因是 `fdb_kv_get` stub 返回 NULL，C 测试解引用空指针。

### 6.3 TSDB 逐测试明细

| 测试 | GPT | GLM | GLM 失败原因 |
|------|-----|-----|------------|
| tsdb_init_ex | ✅ | ✅ | — |
| tsl_clean | ✅ | ✅ | — |
| tsl_append | ✅ | ✅ | — |
| tsl_iter | ✅ | ✅ | — |
| tsl_iter_by_time | ✅ | ✅ | — |
| query_count | ✅ | ❌ | stub 返回 0，期望 256 |
| set_status | ✅ | ❌ | stub 返回 0 |
| clean__2 | ✅ | ✅ | — |
| iter_by_time_1 | ✅ | ❌ | `test_secs_info[2].start_time=0x7FFFFFFF`（sentinel 未更新） |
| deinit | ✅ | ✅ | — |
| issue_249 | ✅ | ❌ | `fdb_tsl_query_count` 返回错误值 |

**关键**：TSDB 失败的 4 个全是查询/状态类操作，stub 无逻辑自然失败，但不会崩溃（返回 0 比 NULL 安全）。

---

## 7. GPT 修复轮次详细进展（2026-07-13 补充）

GPT 从 0/24 到 24/24 经历了 13 次尝试（9 轮 repair + 3 次 checkpoint + 1 次 final verification）：

| # | 类型 | 触发名 | 改动文件 | 结果 | 说明 |
|---|------|--------|---------|------|------|
| 1 | checkpoint | core_complete | — | 0/24 | 初始基线 |
| 2 | repair | layout_symbol_fix | layout_probe.rs | 0→0 | 探索性修复，无效 |
| 3 | repair | **layout_struct_fix** | c_types.rs, c_abi.rs | **0→20** | **关键突破**：修 FFI struct ABI 布局 |
| 4 | repair | sector_and_reverse_iteration | c_abi.rs | 20→18+2 not_run | 反向迭代实验，略回退 |
| 5 | repair | stabilize_iterator_contract | c_abi.rs | 18→18+2 not_run | 迭代器契约修复，未改善 |
| 6 | repair | revert_unstable_sector_experiment | c_abi.rs | 18→20 | 回退实验，恢复到 20 |
| 7 | final | final_verification | — | 20/24 | 确认 20 为基线 |
| 8 | repair | **sector_allocator_and_tsl_geometry** | c_abi.rs | 20→22 | 修 scale_up + 跨 sector 迭代 |
| 9 | repair | track_oldest_sector_after_gc_pressure | storage.rs, c_abi.rs | 22→22 | GC oldest 追踪，未改善 |
| 10 | repair | restore_oldest_on_reinit | c_abi.rs | 22→22 | 重新初始化时恢复 oldest，未改善 |
| 11 | repair | **compact_live_kv_at_gc_threshold** | c_abi.rs | 22→23 | 修 gc2：live KV 压缩 |
| 12 | repair | **persist_gc_oldest_cursor** | storage.rs, c_abi.rs | 22→**24** | 修 gc：持久化 GC oldest cursor |
| 13 | final | final_verification | — | 24/24 | 确认全部通过 |

**GLM 对比**：4 次 checkpoint，0 轮 repair，9/24 后停止。c-cross 框架未触发任何代码修复循环。

---

## 8. Runner 级差异分析（2026-07-13 补充）

### KVDB Runner

**GPT**：exit 0，13/13 全部通过，输出干净无错误。

**GLM**：exit -11 (SIGSEGV)，仅在 init 类测试通过后崩溃：
```
Running: test_fdb_kvdb_init ...           ✅
Running: test_fdb_kvdb_init_check ...     ✅
Running: test_fdb_create_kv_blob ...      → blob.saved.len==1625937464 (垃圾值)
Running: test_fdb_change_kv_blob ...      → blob->saved.len==-1851114752
Running: test_fdb_del_kv_blob ...         → blob.saved.len==-1851114752
Running: test_fdb_create_kv ...           → read_value is NULL → SIGSEGV
runner exited with -11
```

崩溃级联效应：一旦 SIGSEGV，后续 7 个测试全部 not_run。

### TSDB Runner

**GPT**：exit 0，11/11 全部通过。

**GLM**：exit 1，4 个查询/状态测试失败但不崩溃：
```
Running: test_fdb_tsdb_init_ex ...       ✅
Running: test_fdb_tsl_clean ...          ✅
Running: test_fdb_tsl_append ...         ✅
Running: test_fdb_tsl_iter ...           ✅
Running: test_fdb_tsl_iter_by_time ...   ✅
Running: test_fdb_tsl_query_count ...    → count=0, expected=256
Running: test_fdb_tsl_set_status ...     → query_count mismatch
Running: test_fdb_tsl_clean ...          ✅
Running: test_fdb_tsl_iter_by_time_1 ... → start_time=0x7FFFFFFF (sentinel)
Running: test_fdb_tsdb_deinit ...        ✅
Running: test_fdb_github_issue_249 ...   → query_count returns wrong value
=== TSDB Test: FAILED ===
runner exited with 1
```

TSDB stub 返回 0 而非 NULL，所以不会 SIGSEGV，但数值全错。

---

## 9. 诊断文件差异（2026-07-13 补充）

| 维度 | GLM | GPT |
|------|-----|-----|
| diagnostics.jsonl | 17 条（10 条测试级 + 2 条 runner 级 + 5 条布局） | **0 条**（空文件） |
| workbench-issues.jsonl | 0 条 | 0 条 |

GPT 的 diagnostics 为空是因为所有问题都被 repair 消化了。GLM 的 17 条诊断全部指向 stub 实现（handoff target = rust-implementer），但从未被消费——因为没有触发 repair 循环。

---

## 10. 工程优化落地（2026-07-13）

本节是对照当前转换工程后的最终设计结论。总体设计成立，但实现时做了四个关键收口：状态只能由控制器投影；阶段契约只能有一个 JSON 权威源；checkpoint 的“证据完整”和最终“语义全通过”必须分开；REPORT 必须采用候选报告再提交的两阶段协议。以下修改只作用于转换工作台、提示契约和测试，不修改平台 C，也不直接修改任何参赛 Rust 实现。

### 10.1 事务式工作流与唯一契约

- 新增 `work/tools/workflowctl.py`，统一执行 `init/begin/finish/abort/record-agent/status`。每个阶段绑定 root、run_id、nonce、task packet、输入基线、真实 diff、required outputs 和内容 hash。
- 新增 `work/knowledge/workflow-contract.json`，作为阶段顺序、允许路径、required outputs、保护路径和 packet 上限的唯一权威源；controller、packet generator 和 gate 共同读取，禁止 `--allow-path` 动态扩权。
- `workflow_state.json`、receipt 和 subagent invocation 由控制器独占维护。subagent 的自然语言完成声明不再能推进状态，隔离 worktree 中“声称写入但主目录没有产物”的情况会在 `finish` 被直接拒绝。
- READ 委派前记录平台 C 完整文件清单与 hash，后续每个阶段都复核新增、删除和内容变化，从工程上落实“不得修改 C 输入”。

### 10.2 弱模型最小上下文与可执行路由

- 新增 `work/tools/task_packet.py`。每个 packet 最多 12 条 requirements、3 个 scenarios、16 个步骤；repair 每次只给一个 active cluster、依赖、symbols、evidence tail 和准确编辑范围。
- `workflowctl status` 同时输出 `next_action`、`expected_stage` 和可直接复制的 `next_command`。`REPAIR_ABI_LAYOUT`、`REANALYZE_C_MODEL`、`ISOLATE_SCENARIOS`、`REPAIR_RUST` 都能直接作为 `begin --stage` 参数，不再让弱模型把自然语言诊断自行翻译成流程动作。
- `.opencode/skills/flashdb-orchestrator.md` 收敛为兼容薄入口，完整业务规则只维护在 `work/skills/flashdb-orchestrator.md` 和机器契约中，消除两份 orchestrator 漂移。

### 10.3 防空实现与确定性 ABI

- scaffold manifest 保存生成文件 hash、函数体基线和 marker；新增 `core_impl_audit.py` 检测未改写基线、marker-only 模块、恒定 null/0/false neutral return 和 placeholder module。REWRITE gate 会重新执行审计，不再以 `cargo build` 代替语义实现。
- ABI 模型保留原始 declarator、数组维度、pointee、callback signature、匿名 aggregate 和字段 align；编译器 probe 提供 `sizeof/alignof/offset` 真值。
- scaffold generator 确定性生成数组、union/匿名 aggregate、callback、bitfield 字节块与 padding，并输出独立 scaffold layout 证据。ABI repair 使用 `--abi-only`，只允许重生成 `ffi/c_types.rs` 与 `layout_probe.rs`，不会覆盖已完成的核心 Rust 逻辑。

### 10.4 语义 IR、实现义务与 gate

- C 模型新增有稳定 ID、顺序、源码锚点、调用路径和 helper/callback 展开的 `scenario_ir`。
- Rust API 设计为每项实现义务补充 symbols、acceptance scenarios、suggested files 和依赖 ID；gate 校验引用完整性和依赖无环。
- GENERATE 必须同时通过 scaffold manifest 与 scaffold layout；REWRITE 的 batch claimed files 必须等于 receipt 真实 diff；MIGRATE 必须覆盖动态 scorer cases、语义义务和有效 assertion evidence。

### 10.5 C-cross 收敛、崩溃隔离与安全回退

- 新增 `repair_planner.py` 和 `c_cross_converge.py`。attempts 记录 fingerprint、progress、regression、stalled、diagnostics history 和 best-known；repair plan 按 ABI、C model、isolation、Rust implementation 分类并生成机器 route。
- crash/timeout 导致的 `not_run` 会进入 isolation queue，通过 `--scenario` 单例重跑区分首个致崩用例和级联未运行，不再把 7 个级联 `not_run` 当成 7 个独立实现缺陷。
- checkpoint/repair 在全量 invocation 都有结果、诊断、handoff 和日志时返回 0，表示“证据事务完成”；只有 final 非全通过返回非零。是否继续修复由 `next_action` 决定，避免把 0 误判成 24/24。
- best-known 快照只包含工具拥有的 `flashDB_rust/src/**`，回退前生成备份并校验 manifest/hash；禁止 Git reset、全局删除或恢复 C/测试/用户文件。

### 10.6 有界终止、报告协议与证据可信度

- C-cross repair 与 cargo/test repair 分别有独立默认 8 轮预算。未耗尽继续定向修复；耗尽后强制进入 REPORT，最终状态为 `DONE_WITH_FAILURES`，保留真实部分成绩并以非零结果停止，不会卡死。
- `report_writer.py` 允许在控制器绑定的活跃 REPORT 事务中先写候选报告；随后 `workflowctl finish` 执行最终 gate 并提交 `DONE`。这解决了“报告要求 DONE、但 DONE 又要求报告已存在”的循环依赖。
- gate 校验 controller receipt、run hash、nonce、task packet hash、actual changed-file hash、source baseline 和成功 subagent receipt。失败、错误 stage 或不匹配 run 的调用记录不再能充当完成证据。
- `test_failure_triage.py` 只生成归因证据，`test_failure_triage_required` 由控制器根据 cargo/triage 产物投影，避免业务工具越权修改 controller state。

### 10.7 预期效果

弱模型不再需要记住 gate 内部字段、手写状态、猜修复角色、整库读取 trace 或靠 `cargo build` 判断实现完成。它只需执行 `status.next_command`、完成一个有界 packet，再由控制器用真实文件和机器证据提交。预期直接改善 GLM 历史运行中的四类问题：阶段产物丢失、空 stub 通过 gate、ABI 反复试错、诊断生成后无人消费。

### 10.8 实现验证

- `python3 -B -m unittest 02_02/tests/test_workflow_optimizations.py -v`：26/26 通过，覆盖事务边界、root/nonce/state 防篡改、required outputs、repair route、预算终态、REPORT 候选事务、scenario IR、packet 上限、ABI/scaffold audit、progress/regression 和 crash isolation。
- `python3 -B -m unittest discover -s 02_02/tests -p 'test*.py' -v`：95 项通过，1 项按平台生成 `.opencode` 镜像契约跳过。
- 在隔离临时工作台上使用真实 `judge-assets/code/FlashDB` 完成 `workflowctl init → begin READ_C_PROJECT → scan_c_project → finish → status`：INIT 与 READ gate 均通过，receipt 成功落盘，下一动作准确为 `BUILD_C_MODEL`。
- 变更范围检查未发现平台 C 或既有生成 Rust 项目被修改；本轮只修改 `02_02` 下的转换工具、契约、技能说明、回归测试和本分析文档。

## 附录：关键数据对比

```
                    GLM              GPT
总代码行数          996 行           2109 行
c_abi.rs           225 行(stub)     739 行(完整)
storage.rs          5 行(空)        60 行(sidecar)
c-cross pass       9/24             24/24
layout 修复轮次    3+               2 次尝试（1 次关键修复）
Rust 测试          无               573 行, 26 tests
unsafe ratio       未计算            3.08%
最终状态           VERIFY 停止      STATUS: SUCCESS
```
