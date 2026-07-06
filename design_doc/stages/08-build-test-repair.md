# 08 - BUILD_TEST_REPAIR

## 目标

执行最终 Rust 构建和测试，并在失败时基于错误栈自动做最小修复，形成编译/测试自愈闭环。

本阶段不是第一次发现所有编译错误的地方。05 已经保证骨架 `cargo check` 通过，06 已经保证核心实现分批 `cargo check` 通过，07 已经生成测试并归档一次 `cargo test` 结果。因此 08 主要处理最终 `cargo build` / `cargo test` 的剩余问题，包括测试断言失败、边界行为不等价、少量类型或集成问题。

## 执行主体

```text
flashdb-orchestrator
repairer subagent
rust-compile-repair Skill
work/tools/cargo_capture.py
work/tools/gate.py
```

## 输入

```text
flashDB_rust/
work/skills/rust-compile-repair/SKILL.md
logs/trace/rust_test_mapping.json
```

## 输出

```text
logs/trace/cargo-build.log
logs/trace/cargo-test.log
logs/trace/cargo-fmt.log
logs/trace/cargo-clippy.log
logs/trace/08-build-test-repair.md
result/issues/repair_trace.jsonl
logs/trace/workflow_state.json
result/output.md
result/issues/00-summary.md
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

失败时调用 `repairer`，最多 8 轮。每轮必须：

1. 读取失败日志；
2. 分类错误；
3. 定位最小修复点；
4. 修改最少文件；
5. 由主控 Agent 重跑失败命令；
6. 写入 `result/issues/repair_trace.jsonl`。

主控 Agent 必须亲自运行 cargo 命令并归档日志。`repairer` subagent 只负责提出和应用最小修复，不负责判定阶段通过。

## 执行命令

```bash
python3 work/tools/gate.py --stage MIGRATE_TESTS
python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace
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

## 下一阶段交接

成功后进入 `REPORT_AND_VERIFY`。下一阶段只汇总和最终校验，不再做大规模实现。
