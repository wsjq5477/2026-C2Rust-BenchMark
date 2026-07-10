# FlashDB C-to-Rust opencode 工作台执行说明

本文件是自动评测系统加载参赛作品的唯一入口。参赛作品的目标是让 opencode 在运行时读取平台提供的 FlashDB C 工程，逐阶段生成 `flashDB_rust/`，而不是提交预置 Rust 实现。

## 固定路径

- 作品根目录：本文件所在目录，评测环境通常为 `/app/code/02_02`
- 平台 C 输入：`/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
- 最终 Rust 输出：作品根目录下的 `flashDB_rust`
- 主控 Agent：`work/skills/flashdb-orchestrator.md`
- subagent Markdown：`work/skills/c-analyzer.md`、`work/skills/rust-implementer.md`、`work/skills/test-migrator.md`、`work/skills/repairer.md`
- opencode 原生目录：由评分平台按赛题规则从 `work/skills` 自动复制，参赛工程只维护 `work/skills` 权威源
- 状态与证据：`logs/trace`
- subagent 注册证据：`logs/trace/agent-registry.json`
- subagent 调用证据：`logs/trace/subagent-invocations.jsonl`
- 最终报告：`result/output.md` 和 `result/issues/00-summary.md`

## opencode 原生执行入口

work 目录仍为权威源。主控和 subagent Markdown 都按赛题约定保存到 `work/skills/`，subagent 路径形如 `work/skills/{subagent}.md`。若评测环境在启动 opencode 前已经把这些 Markdown 复制到 opencode 原生目录，并且如果启动前已经选择 flashdb-orchestrator 作为 primary agent，则由该 primary agent 执行本文件。

opencode 不能在会话中把当前 primary agent 自切换为另一个 primary agent。因此，如果当前会话已经由默认 Build agent 启动，不要求它运行中切换到 `@flashdb-orchestrator`。默认 Build agent 按普通 Markdown fallback 执行也满足本检查点：完整读取 `work/skills/flashdb-orchestrator.md` 并按其中要求执行。但主控执行重阶段时必须优先拉起对应 subagent；如果平台原生 subagent 注册异常，主控仍必须拉起一个通用 subagent 作为隔离任务代理，让该代理先读取 `work/skills/{subagent}.md` 后执行。只有同一 subagent 连续 3 次失败并写入 `subagent-invocations.jsonl` 后，主控才允许 fallback 自行执行。

主控传给 subagent 的提示词必须是短调度单，只允许包含动态上下文：作品根目录、当前 checkpoint、目标阶段族、`$FLASHDB_SOURCE`、必须先读取 `work/skills/{subagent}.md`、需要读取的 trace/state 文件、停止条件和回写证据路径。如果调度提示与 subagent Markdown 冲突，以 subagent Markdown 为准。禁止在调度提示中复制或改写 subagent 的业务细节，禁止写入固定 API 清单、固定源码文件清单或实现策略。

所有运行时代理的调度提示必须明确编辑边界：只允许修改当前职责内的 `flashDB_rust/**`、`logs/trace/**` 和规定的 `result/issues/**` 运行产物；不得修改 `work/**`，不得修改 `INSTRUCTION.md`，不得修改 `.opencode/**`、`design_doc/**`、评测测试或平台 C 输入。发现工作台脚本或契约问题时由主控追加一条结构化记录到 `logs/trace/c-cross/workbench-issues.jsonl`，并继续可执行比赛流程。

`logs/trace` 是机器证据仓库，不是默认上下文输入。除 `workflow_state.json`、短阶段日志和必要错误 tail 外，subagent 默认不得全文读取 `c_api_model.json`、`c_test_model.json`、`rust_api_design.json`、`validation-matrix.json`、总设计文档或历史报告；需要模型事实时只能读取与当前阶段直接相关的局部片段。

`READ_C_PROJECT + BUILD_C_MODEL + DESIGN_RUST_API` 是 `C_ANALYSIS 阶段族`。主控必须一次拉起 `c-analyzer`，让它从当前 checkpoint 继续执行剩余 C 分析阶段；不得为 READ_C_PROJECT、BUILD_C_MODEL、DESIGN_RUST_API 分别新起 subagent。

## 当前开发检查点

当前实现并验证完整检查点：`BOOTSTRAP + INIT_WORKSPACE + READ_C_PROJECT + BUILD_C_MODEL + DESIGN_RUST_API + GENERATE_RUST_SCAFFOLD + REWRITE_CORE_MODULES + VERIFY_RUST_WITH_C_TESTS + MIGRATE_TESTS + BUILD_TEST_REPAIR + REPORT_AND_VERIFY`。

opencode 必须执行主控 Agent 文档中的完整流程。若会话启动时已经选中 `@flashdb-orchestrator` primary agent，则由它执行；否则由默认 Build agent 完整读取 `work/skills/flashdb-orchestrator.md` 后执行。

完成前不得写入 `STATUS: SUCCESS`。只有 `REPORT_AND_VERIFY` gate 通过后，才允许最终报告写入 `STATUS: SUCCESS`。

## 环境准备

1. 确认 `python3`、`cargo`、`rustfmt` 可执行。
2. 不依赖网络、API Key、Docker 或人工输入。
3. 不得修改平台提供的源码或测试。
4. 不得预置、复制或冒充 `flashDB_rust`；`flashDB_rust` 必须在 `GENERATE_RUST_SCAFFOLD` 阶段由 opencode 生成。 如果进入 `INIT_WORKSPACE` 时作品根目录下已经存在 `flashDB_rust`，需要删除该目录

## subagent 分工

- `c-analyzer`：执行 `READ_C_PROJECT + BUILD_C_MODEL + DESIGN_RUST_API`，拥有 C 事实建模和 Rust API 设计解释权，不写 Rust 源码。
- `rust-implementer`：执行 `GENERATE_RUST_SCAFFOLD`、`REWRITE_CORE_MODULES`、`VERIFY_RUST_WITH_C_TESTS`，三个阶段可分别拉起独立 session，按文件系统产物恢复上下文；仅 `REWRITE_CORE_MODULES` 可在说明缺口后局部回看 C 源码，不得重写 C 模型或 API 设计。
- `test-migrator`：执行 `MIGRATE_TESTS`，只负责 Rust 测试和 `rust_test_mapping.json`。`VERIFY_RUST_WITH_C_TESTS` 已通过后，Rust 测试失败默认先怀疑测试迁移或 harness。
- `repairer`：执行 `BUILD_TEST_REPAIR` 的 triage 和最小修复。小修自行完成；系统性 C 模型、Rust 实现或测试迁移问题必须回派 `c-analyzer`、`rust-implementer` 或 `test-migrator`。

## 自动执行命令总览

从作品根目录执行：

```bash
python3 work/tools/gate.py --stage INIT_WORKSPACE
python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json
python3 work/tools/gate.py --stage READ_C_PROJECT
python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace
python3 work/tools/gate.py --stage BUILD_C_MODEL
python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json
python3 work/tools/gate.py --stage DESIGN_RUST_API
python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust
python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD
python3 work/tools/gate.py --stage REWRITE_CORE_MODULES
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace
python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS
python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project flashDB_rust --mapping logs/trace/rust_test_mapping.json
python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json
python3 work/tools/gate.py --stage MIGRATE_TESTS
python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace
python3 work/tools/test_failure_triage.py --root . --out logs/trace  # only required when cargo test failed
python3 work/tools/gate.py --stage BUILD_TEST_REPAIR
python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json
python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json
python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md
python3 work/tools/gate.py --stage REPORT_AND_VERIFY
```

其中 `$FLASHDB_SOURCE` 必须按以下优先级选择第一个存在的目录：

1. `/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
2. `judge-assets/code/FlashDB`
3. `../judge-assets/code/FlashDB`

## 阶段执行要求

### INIT_WORKSPACE

1. 删除旧的 `result/` 和 `logs/` 目录后重新创建 `result/`、`result/issues/`、`logs/`、`logs/trace/`。
2. 只生成空文件 `logs/interaction.md`，不得写入标题、模板、阶段记录或自动执行内容。
3. 写入 `logs/trace/workflow_state.json`，`current_stage` 为 `INIT_WORKSPACE`。
4. 检查 `work/skills/c-analyzer.md`、`work/skills/rust-implementer.md`、`work/skills/test-migrator.md`、`work/skills/repairer.md` 均存在且声明 `mode: subagent`。
5. 写入 `logs/trace/agent-registry.json`，记录 4 个 subagent 的路径、模式和职责阶段。
6. 创建 `logs/trace/subagent-invocations.jsonl`。
7. 写入中文 `logs/trace/01-init-workspace.md`。
8. 运行 `python3 work/tools/gate.py --stage INIT_WORKSPACE`。

### READ_C_PROJECT

1. 优先调用 `c-analyzer` subagent；如果原生 subagent 不可用，拉起隔离任务代理读取 `work/skills/c-analyzer.md` 后执行；连续 3 次失败后才允许主控 fallback。`READ_C_PROJECT`、`BUILD_C_MODEL`、`DESIGN_RUST_API` 必须作为 `C_ANALYSIS 阶段族` 由一次 `c-analyzer` 任务连续执行。
2. 选择 `$FLASHDB_SOURCE`，只读取目录结构和文件清单，不修改平台输入。
3. 运行 `python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json`。
4. 写入中文 `logs/trace/02-read-c-project.md`。
5. 更新 `workflow_state.json`，记录 `input_path` 和 `input_manifest`。
6. 运行 `python3 work/tools/gate.py --stage READ_C_PROJECT`。

### BUILD_C_MODEL

1. 继续由同一次 `c-analyzer` subagent 执行，读取 `work/skills/flashdb-migration/SKILL.md` 中 `BUILD_C_MODEL` 规则。如果 `READ_C_PROJECT` 已通过后从本阶段恢复，主控只能一次拉起 `c-analyzer`，从 `BUILD_C_MODEL` 继续执行剩余 C 分析阶段。
2. 运行 `python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace`。
3. 生成 `logs/trace/c_project_model.json`、`logs/trace/c_api_model.json`、`logs/trace/c_test_model.json`。
4. 写入中文 `logs/trace/03-build-c-model.md`。
5. 更新 `workflow_state.json`。
6. 运行 `python3 work/tools/gate.py --stage BUILD_C_MODEL`。

### DESIGN_RUST_API

1. 继续由同一次 `c-analyzer` subagent 执行，读取 `work/skills/flashdb-migration/SKILL.md` 中 `DESIGN_RUST_API` 规则。
2. 运行 `python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json`。
3. 写入中文 `logs/trace/04-design-rust-api.md`，记录核心 API、扩展兼容、未映射符号和未生成源码边界。
4. 更新 `workflow_state.json`。
5. 运行 `python3 work/tools/gate.py --stage DESIGN_RUST_API`。

### GENERATE_RUST_SCAFFOLD

1. 优先调用 `rust-implementer` subagent；如果原生 subagent 不可用，拉起隔离任务代理读取 `work/skills/rust-implementer.md` 后执行；连续 3 次失败后才允许主控 fallback。本阶段结束后该 subagent session 可退出，下一阶段不得依赖本阶段对话历史。
2. 读取 `logs/trace/rust_api_design.json` 中生成脚手架所需的局部设计事实；不得读取 C 源码。
3. 运行 `python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust`。
4. 写入中文 `logs/trace/05-generate-rust-scaffold.md`。
5. 更新 `workflow_state.json`，`current_stage` 为 `GENERATE_RUST_SCAFFOLD`。
6. 运行 `python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD`。

### REWRITE_CORE_MODULES

1. 由新的 `rust-implementer` subagent session 执行，读取 `work/skills/flashdb-migration/SKILL.md` 中 `REWRITE_CORE_MODULES` 规则，不继承 `GENERATE_RUST_SCAFFOLD` 的对话历史。
2. 基于 `rust_api_design.json` 和 C 模型的必要局部片段完善 `flashDB_rust/src/` 中设计声明的模块；不得全文读取 trace 大 JSON。
3. 不链接 C 源码，不写 `todo!()`、`unimplemented!()`。
4. 写入中文 `logs/trace/06-rewrite-core-modules.md` 和必要的 `logs/trace/core_rewrite_batches.jsonl`。
5. 更新 `workflow_state.json`，`current_stage` 为 `REWRITE_CORE_MODULES`。
6. 运行 `python3 work/tools/gate.py --stage REWRITE_CORE_MODULES`。
7. 只有本阶段可按需读取 C 源码局部窗口。读取前必须说明要验证的模型缺口或实现疑点；超过 400 行的 C/Rust 文件禁止全文读取，必须先用 `rg` 定位，再读取命中点附近窗口，单次窗口不超过 120 行。

### VERIFY_RUST_WITH_C_TESTS

1. 由新的 `rust-implementer` subagent session 执行；本阶段是 Rust 源码迁移完成条件，不属于测试迁移阶段，不继承 `REWRITE_CORE_MODULES` 的对话历史。
2. 默认只读取 `flashDB_rust/`、验证命令输出、失败 tail 和必要的 layout/API 局部片段；不得全文读取 `logs/trace/c_test_model.json`、`c_api_model.json`、`rust_api_design.json` 或 C 源码。
3. 运行 `python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --mode full --attempt-kind checkpoint --trigger core_complete`。局部实现期间可根据模型动态发现的 suite 重复传入 `--suite <suite>` 做检查点，不得硬编码 suite 名或用例总数。
4. `c_cross_validate.py` 必须编译 Rust `staticlib`，再编译并运行动态发现的原始 C 测试 runner 链接到 Rust C ABI facade，并解析 runner 的 `Running:` / `FAIL` 输出形成逐测试结果。
5. 写入 `logs/trace/c-cross/cross-compile.log`、`cross-test.log`、`case-results.jsonl`、`attempts.jsonl`、`workbench-issues.jsonl` 和 `logs/trace/validation-matrix.json`。
6. 中间 C-cross 是诊断检查点：全量 runner invocation 必须都有结果和证据；阶段结果为 `PASS` 或 `CONTINUE_WITH_FAILURES`。任何编译、layout、链接、运行、解析或测试失败都不得伪装为通过，但必须继续 `MIGRATE_TESTS`、Rust 测试、评分和最终报告。
7. 写入中文 `logs/trace/06-5-verify-rust-with-c-tests.md`。
8. 更新 `workflow_state.json`，`current_stage` 为 `VERIFY_RUST_WITH_C_TESTS`。
9. 运行 `python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS`。
10. 本阶段只允许把临时 C harness 证据写入 `logs/trace/c-cross/`，不得把 C 源码放进 `flashDB_rust/src/`，不得让最终 Rust 项目依赖 FlashDB C 实现。
11. 若验证失败显示 C 模型或 API 设计缺口，必须回派 `c-analyzer`，不得在本阶段系统性重读 C 工程。

### MIGRATE_TESTS

1. 必须在 `VERIFY_RUST_WITH_C_TESTS` 写出完整证据后执行；`PASS` 与 `CONTINUE_WITH_FAILURES` 都允许进入 `MIGRATE_TESTS`，后者不代表最终 C-cross 已通过。
2. 优先调用 `test-migrator` subagent；如果原生 subagent 不可用，拉起隔离任务代理读取 `work/skills/test-migrator.md` 后执行；连续 3 次失败后才允许主控 fallback。
3. 读取 `work/skills/test-migrator.md` 和 `work/skills/flashdb-test-migration/SKILL.md`。
4. 读取 `logs/trace/validation-matrix.json` 的结论或相关局部片段；不得全文读取无关 trace 大 JSON。Rust 源码已由 C 原始测试证据验证，Rust 测试失败默认先怀疑测试迁移或 harness。
5. 运行 `python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project flashDB_rust --mapping logs/trace/rust_test_mapping.json`。
6. 以 `c_test_model.json.scorer_standard_cases` 为评分覆盖合同，逐项一一迁移；`standard_scenarios` 只作为动态 C 证据来源。
7. 生成逐场景 baseline 后，根据每项 `semantic_obligations` 和 `semantic_facts` 完成 Rust 测试。
8. 清除 `MIGRATION_PENDING` 后，只有 `validated_obligations` 覆盖全部 `semantic_obligations`，且 `assertion_evidence` 证明关键 `verify_*`、`data_shape:*`、`scenario:*` 义务，才可把对应 mapping 更新为 `coverage: semantic`。
9. 生成 `flashDB_rust/tests/kvdb_tests.rs`、`flashDB_rust/tests/tsdb_tests.rs`、`flashDB_rust/tests/equivalence_tests.rs`。
10. 写入中文 `logs/trace/07-migrate-tests.md`。
11. 更新 `workflow_state.json`，记录 `rust_test_mapping`。
12. 运行 `python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json`。
13. 运行 `python3 work/tools/gate.py --stage MIGRATE_TESTS`；评分 case 集合不一致、pending、unmapped、重复、semantic 义务未验证或测试断言过浅时必须失败。

### BUILD_TEST_REPAIR

1. 优先调用 `repairer` subagent；如果原生 subagent 不可用，拉起隔离任务代理读取 `work/skills/repairer.md` 后执行；连续 3 次失败后才允许主控 fallback。
2. 运行 `python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace`。
3. 如果 `cargo test` 失败，必须先运行 `python3 work/tools/test_failure_triage.py --root . --out logs/trace`；`cargo_capture.py` 也会在 test 失败时自动生成同一 triage 记录。
4. `test_failure_triage.py` 必须写入 `logs/trace/test-failure-triage.jsonl` 和 `workflow_state.json.test_failure_triage_required = true`。
5. `repairer` 只在 triage 允许的 `allowed_edit_scope` 内按最小补丁修复，最多 8 轮；系统性问题必须回派 `c-analyzer`、`rust-implementer` 或 `test-migrator`。
6. 若 `validation-matrix.json` 已通过而 Rust 测试失败，默认优先分类为 `test_oracle_suspect` 或 `harness_suspect`；只有完整 C evidence 支持测试预期时，才允许改 Rust 源码。
7. 写入中文 `logs/trace/08-build-test-repair.md`，只记录命令、产物、结果和失败摘要，不写成长篇过程复盘。
8. 更新 `workflow_state.json`，`build_status` 和 `test_status` 必须为 `pass`。
9. 运行 `python3 work/tools/gate.py --stage BUILD_TEST_REPAIR`。

### REPORT_AND_VERIFY

1. 在所有 Rust 修复和测试完成后，最后一次运行 `python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --mode full --attempt-kind final --trigger final_verification`。这是最终全量 C-cross，不得带 `--suite`；所有场景通过才可报告 C-cross PASS，失败时仍必须输出最终报告和真实部分成绩。
2. 运行 `python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json`。
3. 运行 `python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json`。
4. 写入中文 `logs/trace/final-verification.md` 和 `logs/trace/09-report-and-verify.md`。
5. 更新 `workflow_state.json`，`current_stage` 为 `DONE`，`checkpoint` 为 `REPORT_AND_VERIFY`。
6. 运行 `python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md`。最终报告和最终问题摘要只在本阶段统一生成，前置 subagent 不维护这两个文件。
7. 运行 `python3 work/tools/gate.py --stage REPORT_AND_VERIFY`。
8. gate 通过后，`result/output.md` 可保留 `STATUS: SUCCESS`。

## 完成判定

完整任务只在以下条件全部满足时通过：

- `logs/trace/workflow_state.json` 存在且 `current_stage == DONE`；
- 01 到 09 的中文阶段日志都存在；
- `logs/trace/input_manifest.json`、`c_project_model.json`、`c_api_model.json`、`c_test_model.json` 存在；
- `logs/trace/rust_api_design.json` 存在；
- `logs/trace/agent-registry.json` 存在；
- `logs/trace/subagent-invocations.jsonl` 存在且记录主要阶段 subagent 或连续失败后的 fallback 证据；
- `logs/trace/validation-matrix.json` 存在；
- `flashDB_rust/Cargo.toml`、`flashDB_rust/src/`、`flashDB_rust/tests/` 存在；
- `logs/trace/rust_test_mapping.json` 存在；
- `logs/trace/cargo-build.log`、`logs/trace/cargo-test.log` 存在且对应状态通过；
- `logs/trace/unsafe-ratio.json` 存在且 unsafe 比例低于 10%；
- `logs/trace/final-verification.md` 存在；
- `logs/trace/09-report-and-verify.md` 存在；
- `result/output.md` 包含 `STATUS: SUCCESS`；
- `result/issues/00-summary.md` 存在；
- `python3 work/tools/gate.py --stage REPORT_AND_VERIFY` 退出码为 0。

## 禁止事项

- 不得修改平台 FlashDB 输入目录。
- 不得把中间检查点写成最终成功。
- 不得删除测试或弱化断言。
- 不得把测试改成恒真。
- 不得在最终 Rust 项目中链接或编译 C 源码。
- 不得超过 unsafe 比例限制。
- 不得手写 `attempts.jsonl` 或 `workbench-issues.jsonl`。repair attempt 必须通过 `python3 work/tools/c_cross_validate.py --attempt-kind repair --changed-file <path>` 记录；平台问题由主控工具生成。
