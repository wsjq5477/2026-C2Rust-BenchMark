# 08 - BUILD_TEST_REPAIR

## 目标

执行最终 Rust 构建和测试，并在失败时先做测试失败归因，再基于证据自动做最小修复，形成编译/测试自愈闭环。

本阶段不是第一次发现所有编译错误的地方。05 已经保证骨架 `cargo check` 通过，06 已经保证核心实现分批 `cargo check` 通过，06.5 已经生成 C 测试交叉验证矩阵，07 已经生成 Rust 测试映射。因此 08 主要处理最终 `cargo build` / `cargo test` 的剩余问题，包括测试断言失败、边界行为不等价、少量类型或集成问题。

## 执行主体

```text
flashdb-orchestrator
repairer subagent
rust-compile-repair Skill
work/tools/cargo_capture.py
work/tools/test_failure_triage.py
work/tools/gate.py
```

## 输入

```text
flashDB_rust/
work/skills/rust-compile-repair/SKILL.md
logs/trace/rust_test_mapping.json
logs/trace/validation-matrix.json 的相关局部片段
logs/trace/c_test_model.json 的相关局部片段
```

## 输出

```text
logs/trace/cargo-build.log
logs/trace/cargo-test.log
logs/trace/cargo-fmt.log
logs/trace/cargo-clippy.log
logs/trace/08-build-test-repair.md
logs/trace/test-failure-triage.jsonl
result/issues/repair_trace.jsonl
logs/trace/workflow_state.json
```

## 细节实现

建议新增工具：

```text
work/tools/cargo_capture.py
```

负责在 `flashDB_rust` 中执行 cargo 命令，并将 stdout/stderr/exit code 写到 `logs/trace`。

基础命令：

```bash
cd flashDB_rust
cargo fmt
cargo build
cargo test
```

失败时先进入 `TEST_FAILURE_TRIAGE`。`repairer` 是 first responder，必须先读取或生成 triage 证据，再决定小修或回派。

- 如果 opencode subagent 可用，主控必须调用 `repairer`；
- 如果原生 subagent 注册异常，主控必须拉起隔离任务代理读取 `work/skills/repairer.md` 后执行；
- 同一 subagent 连续 3 次失败、超时或输出不合格后，主控才允许 fallback 自行执行；
- 用户不参与选择，流程不得等待人工确认。
- 发生 `cargo test` 失败时，主控必须写入 `workflow_state.json.test_failure_triage_required = true`，并追加 `logs/trace/test-failure-triage.jsonl`。
- `cargo test` 失败后必须先运行 `python3 work/tools/test_failure_triage.py --root . --out logs/trace`；`cargo_capture.py` 也会自动生成同一 triage 记录。

fingerprint 至少包含：

```json
{
  "test": "kvdb_test_fdb_create_kv_blob",
  "file": "tests/kvdb_tests.rs",
  "assertion": "value_len == 16",
  "actual": 21,
  "error_kind": "assertion_mismatch"
}
```

归因分类：

- `test_oracle_suspect`：断言期望值可疑，必须先查 C 测试、C 模型、规格或可计算事实，只能先改 tests、mapping 或测试说明；
- `rust_impl_suspect`：C 证据、规格或 `validated_obligations` 支持期望值，Rust 行为不一致，允许改 `flashDB_rust/src/`；
- `harness_suspect`：测试 setup、mock flash、C ABI facade、wrapper、状态清理或初始化顺序可疑，优先修 harness/setup/facade；
- `insufficient_evidence`：证据不足，主控最多补一轮证据，之后按失败类型保守推进，不得无限停住。

fallback 规则：

- 编译错误：修 Rust 编译问题；
- panic/unwrap：优先修 Rust 或 harness 健壮性；
- assertion expected/actual：优先审计或修测试 oracle；
- C evidence 明确支持期望：修 Rust 实现；
- harness 初始化或桥接异常：修 harness。

同一个 fingerprint 连续出现 2 次后，禁止继续盲修 `flashDB_rust/src/`，必须切回 triage/fallback，并把结论追加到 `logs/trace/test-failure-triage.jsonl`。

`repairer` 最多 8 轮。每轮必须：

1. 读取失败日志；
2. 分类错误；
3. 读取或生成本轮 triage 结论；
4. 根据 triage 的 `allowed_edit_scope` 定位最小修复点；
5. 由主控 Agent 重跑失败命令；
6. 写入 `result/issues/repair_trace.jsonl`。

主控 Agent 必须亲自运行 cargo 命令并归档日志。`repairer` subagent 只负责 triage、小修或回派建议，不负责判定阶段通过。

回派规则：

- `c-analyzer`：C 模型、测试语义或 `rust_api_design.json` 源头错误；
- `rust-implementer`：Rust 核心行为与 C 语义不一致，且测试预期有完整 C evidence；
- `test-migrator`：`validation-matrix.json` 已通过但 Rust 测试预期、mapping 或 harness 可疑。

## 执行命令

```bash
python3 work/tools/gate.py --stage MIGRATE_TESTS
python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace
python3 work/tools/test_failure_triage.py --root . --out logs/trace  # only required when cargo test failed
python3 work/tools/gate.py --stage BUILD_TEST_REPAIR
```

## Gate 检查

`gate.py --stage BUILD_TEST_REPAIR` 必须检查：

- `cargo-build.log` 存在且 exit code 为 0；
- `cargo-test.log` 存在且 exit code 为 0；
- `cargo-results.json.build_status == pass`；
- `cargo-results.json.test_status == pass`；
- `workflow_state.json.build_status == pass`；
- `workflow_state.json.test_status == pass`；
- 修复轮次不超过上限；
- `workflow_state.json.test_failure_triage_required == true` 时，`test-failure-triage.jsonl` 必须记录每个修复轮次的 classification、evidence_paths、allowed_edit_scope；
- 测试文件未被删除；
- 不存在恒真测试替换；
- `workflow_state.json.current_stage == BUILD_TEST_REPAIR`。

## 约束

- 不删除测试。
- 不削弱断言。
- 不整体重写项目。
- 不修改平台输入目录。
- 不为了通过而吞掉错误。
- 不把 05/06/07 中已经有局部检查的问题拖到本阶段集中处理。
- 未经 triage 判定为 `rust_impl_suspect`，不得直接修改 `flashDB_rust/src/` 的核心语义。
- `test_oracle_suspect` 只能修改 tests、mapping 或测试说明。
- `VERIFY_RUST_WITH_C_TESTS` 已通过后，Rust 测试失败默认优先怀疑测试迁移或 harness；只有完整 C evidence 支持测试预期时，才允许改 Rust 源码。
- `insufficient_evidence` 只能补一轮证据，不能让流程无限停住。

## 下一阶段交接

成功后进入 `REPORT_AND_VERIFY`。下一阶段只汇总和最终校验，不再做大规模实现。
