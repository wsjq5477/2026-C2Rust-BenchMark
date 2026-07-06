# 09 - REPORT_AND_VERIFY

## 目标

执行最终验证，统计 unsafe 比例，确认没有 C 链接或预置结果，并生成最终报告。

## 执行主体

```text
flashdb-orchestrator
flashdb-report Skill
work/tools/unsafe_ratio.py
work/tools/report_writer.py
work/tools/gate.py
```

## 输入

```text
flashDB_rust/
logs/trace/workflow_state.json
logs/trace/c_project_model.json
logs/trace/rust_api_design.json
logs/trace/rust_test_mapping.json
logs/trace/cargo-build.log
logs/trace/cargo-test.log
```

## 输出

```text
logs/trace/unsafe-ratio.json
logs/trace/no-c-linkage.json
logs/trace/final-verification.md
logs/trace/09-report-and-verify.md
result/output.md
result/issues/00-summary.md
```

## 细节实现

最终验证命令：

```bash
cd flashDB_rust
cargo build --release
cargo test
cargo fmt --check
cargo clippy -- -D warnings
```

unsafe 统计：

```bash
python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json
```

报告生成：

```bash
python3 work/tools/report_writer.py --out result/output.md --issues result/issues/00-summary.md
```

报告必须包含：

- 输入路径；
- Rust 输出路径；
- C 模型摘要；
- Rust API 摘要；
- FlashDB 真实输入扩展覆盖摘要，包括新增目录、新增 `.c/.h`、unknown/unmapped/excluded 数量；
- 测试覆盖摘要；
- cargo build/test/fmt/clippy 结果；
- unsafe 比例；
- 已知问题；
- 未映射 public 符号和明确排除源码的理由；
- 最终状态。

## Gate 检查

`gate.py --stage REPORT_AND_VERIFY` 必须检查：

- `flashDB_rust/Cargo.toml` 存在；
- `cargo build --release` 通过；
- `cargo test` 通过；
- `cargo fmt --check` 通过；
- `cargo clippy -- -D warnings` 通过；
- unsafe 比例低于 10%；
- 最终项目不编译或链接 FlashDB C 源码；
- `result/output.md` 存在；
- `result/issues/00-summary.md` 存在；
- `workflow_state.json.current_stage == DONE`。

## 约束

- 不补写缺失核心实现。
- 不删除测试。
- 不伪造 cargo 输出。
- 不把中间检查点写成最终成功。
- 任一最终 gate 失败，必须写 `STATUS: FAILED`。

## 完成状态

只有本阶段全部通过，才允许在 `result/output.md` 写入：

```text
STATUS: SUCCESS
```

否则写入：

```text
STATUS: FAILED
```
