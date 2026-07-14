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

只有控制器绑定的活跃 `REPORT_AND_VERIFY` 事务可生成 `STATUS: SUCCESS` 候选报告；最终 gate 失败时该状态不得作为成功结论保留。任何更早阶段都不得写入 `STATUS: SUCCESS`。

## 机器控制合同（强制）

阶段状态、调用证据和完成判定由 `work/tools/workflowctl.py` 独占维护。主控与 subagent 都不得手写 `workflow_state.json`、阶段回执或 `subagent-invocations.jsonl`。下文若仍出现“更新状态”或“记录调用”，其含义一律是调用本工具，不是直接编辑 JSON。

阶段顺序、允许路径、required outputs、保护路径和 task packet 上限只有一个权威源：`work/knowledge/workflow-contract.json`。代理不得通过 `--allow-path` 动态扩权。

新运行先执行：

```bash
python3 work/tools/workflowctl.py --root . init
```

每个后续阶段都使用同一协议：

```bash
python3 work/tools/workflowctl.py --root . begin --stage <STAGE> --agent <ROLE>
# 保存 stdout 中的 run_id 和 nonce；只执行 task_packet 指定范围内的工作
python3 work/tools/workflowctl.py --root . finish --run-id <RUN_ID> --nonce <NONCE>
python3 work/tools/workflowctl.py --root . status
```

约束如下：

1. `begin` 生成最小化动态 task packet、允许路径和基线 hash；调度 subagent 时只传 task packet 路径、run_id、根目录和停止条件，不复制大模型文件。
2. subagent 只提交职责范围内的源码/测试/阶段日志；不得直接编辑工作流状态、声明 gate 通过或写调用记录。C_ANALYSIS 这类同一 session 多阶段任务可调用 `workflowctl finish/begin` 继续，但状态仍只能由工具生成。
3. 主控收到 subagent 回复后必须检查作品根目录中的 receipt 和 `workflowctl status`；若该 session 尚未调用 `finish`，主控必须执行。`finish` 会检查 root identity、required outputs、真实 changed files、保护路径和内容 hash，再运行 gate；缺文件、写到隔离 worktree、虚报改动或越界编辑都会失败。
4. gate 通过后，主控用 `workflowctl record-agent` 引用已通过的 stage receipt 记录调用；不得手写 JSONL。
5. 只服从 `status` 输出的 `next_action`、`expected_stage` 和可直接复制的 `next_command`。`REPAIR_ABI_LAYOUT`、`REANALYZE_C_MODEL`、`ISOLATE_SCENARIOS`、`REPAIR_RUST` 等 machine action 可直接作为 `begin --stage` 参数，控制器会映射到正确阶段。自然语言“完成”、subagent 最终回复和单独一次 cargo build 都不能推进阶段。
6. `--resume` 只能重试当前阶段，不能跳到任意后续阶段。工具保存的 best-known 源码快照只能由收敛控制器显式恢复，禁止 `git reset`、`git checkout` 或覆盖用户工作树。
7. 代理不得运行任何 Git 命令，也不得创建、清理或写入 `/tmp/**`。阶段重试的源码基线由 `workflowctl` 自动保留；不得用 `cp` 备份、手工回退 `flashDB_rust/` 或重新运行 scaffold generator 来伪造新的基线。

旧 trace 没有 `controller_contract_version` 时 gate 仍可读取；所有新运行必须使用上述合同。

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

## 工具命令参考（禁止脱离控制器逐条执行）

以下字面命令用于说明 `workflowctl finish` 内部 gate 和 task packet 可能调用的工具，保留给检查契约；主控不得照此代码块绕过 `begin/finish` 手工逐条推进。实际只执行当前 task packet 列出的业务命令，并由 `workflowctl` 调用 gate：

```bash
python3 work/tools/workflowctl.py --root . init
python3 work/tools/gate.py --stage INIT_WORKSPACE
python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json
python3 work/tools/gate.py --stage READ_C_PROJECT
python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace
python3 work/tools/gate.py --stage BUILD_C_MODEL
python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json
python3 work/tools/gate.py --stage DESIGN_RUST_API
python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --scaffold-layout-only
python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD
python3 work/tools/core_impl_audit.py --root . --project flashDB_rust --manifest logs/trace/scaffold-manifest.json --design logs/trace/rust_api_design.json --output logs/trace/implementation-audit.json
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

1. 确认主控已明确归档或删除旧运行产物，作品根目录下不存在预置 `flashDB_rust`。
2. 运行 `python3 work/tools/workflowctl.py --root . init`。该工具删除旧的工具自有运行目录后重新创建 `result/`、`logs/` 与 trace 骨架；`logs/interaction.md` 只生成空文件，不得写入标题、模板、阶段记录或自动执行内容，同时原子创建完整状态、agent registry、空 invocation 文件和中文阶段日志。
3. `workflowctl init` 会在 gate 工具存在时内部等价运行 `python3 work/tools/gate.py --stage INIT_WORKSPACE`；主控不得重复手工推进，只按 `workflowctl status` 的 `next_action` 前进。

每次 subagent 调用结束且 `workflowctl finish` 已通过 gate 后，用 `workflowctl record-agent` 引用 receipt 追加证据。禁止直接向 JSONL 写一行。实际命令形如：

```bash
python3 work/tools/workflowctl.py --root . record-agent --agent c-analyzer --stage C_ANALYSIS --mode native --status pass --run-id <RUN_ID> --receipt <FINISH_STDOUT中的不可变RECEIPT_PATH>
```

`agent` 只能是注册的角色名；`mode` 只能是 `native`、`generic_subagent`、`isolated_proxy` 或 `primary_fallback`；`status` 必须非空。`c-analyzer` 成功记录只能用单一 `stage=C_ANALYSIS`，不能按三个子阶段拆行。若使用 `primary_fallback`，同一行还必须写入 `consecutive_failures >= 3` 和非空 `fallback_to_primary_reason`。

### READ_C_PROJECT

1. 优先调用 `c-analyzer` subagent；如果原生 subagent 不可用，拉起隔离任务代理读取 `work/skills/c-analyzer.md` 后执行；连续 3 次失败后才允许主控 fallback。`READ_C_PROJECT`、`BUILD_C_MODEL`、`DESIGN_RUST_API` 必须作为 `C_ANALYSIS 阶段族` 由一次 `c-analyzer` 任务连续执行。
2. `workflowctl init/begin` 已在代理运行前生成 `logs/trace/input-source-baseline.json`；选择同一个 `$FLASHDB_SOURCE`，只读取目录结构和文件清单，不修改平台输入。后续每次 `finish` 都会对新增、删除和 hash 变化做全量复核。
3. 运行 `python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json`。
4. 写入中文 `logs/trace/02-read-c-project.md`。
5. 调用 `workflowctl finish`，由控制器记录 `input_path` 和 `input_manifest` 并内部等价运行 `python3 work/tools/gate.py --stage READ_C_PROJECT`。

### BUILD_C_MODEL

1. 继续由同一次 `c-analyzer` subagent 执行，读取 `work/skills/flashdb-migration/SKILL.md` 中 `BUILD_C_MODEL` 规则。如果 `READ_C_PROJECT` 已通过后从本阶段恢复，主控只能一次拉起 `c-analyzer`，从 `BUILD_C_MODEL` 继续执行剩余 C 分析阶段。
2. 运行 `python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace`。
3. 生成 `logs/trace/c_project_model.json`、`logs/trace/c_api_model.json`、`logs/trace/c_test_model.json`。
4. 写入中文 `logs/trace/03-build-c-model.md`。
5. 调用 `workflowctl finish`，由控制器更新状态并内部等价运行 `python3 work/tools/gate.py --stage BUILD_C_MODEL`。

### DESIGN_RUST_API

1. 继续由同一次 `c-analyzer` subagent 执行，读取 `work/skills/flashdb-migration/SKILL.md` 中 `DESIGN_RUST_API` 规则。
2. 运行 `python3 work/tools/design_rust_api.py --project-model logs/trace/c_project_model.json --api-model logs/trace/c_api_model.json --test-model logs/trace/c_test_model.json --output logs/trace/rust_api_design.json`。
3. 写入中文 `logs/trace/04-design-rust-api.md`，记录核心 API、扩展兼容、未映射符号和未生成源码边界。
4. 调用 `workflowctl finish`，由控制器更新状态并内部等价运行 `python3 work/tools/gate.py --stage DESIGN_RUST_API`。

### GENERATE_RUST_SCAFFOLD

1. 优先调用 `rust-implementer` subagent；如果原生 subagent 不可用，拉起隔离任务代理读取 `work/skills/rust-implementer.md` 后执行；连续 3 次失败后才允许主控 fallback。本阶段结束后该 subagent session 可退出，下一阶段不得依赖本阶段对话历史。
2. 读取 `logs/trace/rust_api_design.json` 中生成脚手架所需的局部设计事实；不得读取 C 源码。
3. 运行 `python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust`。
4. 工具必须同时生成 `logs/trace/scaffold-manifest.json`，记录生成文件、FFI body baseline、stub symbols 和 placeholder module hash。
5. 立即运行 `python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --scaffold-layout-only`，写入 `logs/trace/c-cross/scaffold-layout-check.json`；layout 未一次通过时先修复生成工具事实，不把错误 ABI 留给模型猜。
6. 写入中文 `logs/trace/05-generate-rust-scaffold.md`，由 `workflowctl finish` 更新状态、核验回执并运行 gate。

### REWRITE_CORE_MODULES

1. 由新的 `rust-implementer` subagent session 执行，读取 `work/skills/flashdb-migration/SKILL.md` 中 `REWRITE_CORE_MODULES` 规则，不继承 `GENERATE_RUST_SCAFFOLD` 的对话历史。
2. 基于 `rust_api_design.json` 和 C 模型的必要局部片段完善 `flashDB_rust/src/` 中设计声明的模块；不得全文读取 trace 大 JSON。
3. 不链接 C 源码，不写 `todo!()`、`unimplemented!()`。
4. 写入中文 `logs/trace/06-rewrite-core-modules.md` 和必要的 `logs/trace/core_rewrite_batches.jsonl`。
   `core_rewrite_batches.jsonl` 每行必须是合法 JSON，并包含 `stage=REWRITE_CORE_MODULES`、`status=complete|pass`、非空 `changed_files` 和非空 `obligations`；changed files 只能位于 `flashDB_rust/src/`。
5. 运行 `core_impl_audit.py` 生成 `logs/trace/implementation-audit.json`。任一 required FFI body 与 scaffold baseline 相同、仅删除 marker/改空白、仍为恒定 neutral return，或核心模块仍是 `module_available() -> true`，都必须失败。
6. 由 `workflowctl finish` 对账真实源码 diff、batch 中的 changed_files 和产物 hash，再运行 gate。gate 还会执行 `cargo fmt --all -- --check` 与 `cargo build --release`，任一失败都不得推进。
   若返回 `REPAIR_REWRITE_CORE_MODULES`，直接执行 `status.next_command` 并重新 begin；控制器会复用首次 REWRITE 的脚手架基线，禁止 Git、`/tmp` 备份、`cp` 回退或再次生成 scaffold。
7. 只有本阶段可按需读取 C 源码局部窗口。读取前必须说明要验证的模型缺口或实现疑点；超过 400 行的 C/Rust 文件禁止全文读取，必须先用 `rg` 定位，再读取命中点附近窗口，单次窗口不超过 120 行。

### VERIFY_RUST_WITH_C_TESTS

1. 由新的 `rust-implementer` subagent session 执行；本阶段是 Rust 源码迁移完成条件，不属于测试迁移阶段，不继承 `REWRITE_CORE_MODULES` 的对话历史。
2. 默认只读取 `flashDB_rust/`、验证命令输出、失败 tail 和必要的 layout/API 局部片段；不得全文读取 `logs/trace/c_test_model.json`、`c_api_model.json`、`rust_api_design.json` 或 C 源码。
3. 运行 `python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --mode full --attempt-kind checkpoint --trigger core_complete`。局部实现期间可根据模型动态发现的 suite 重复传入 `--suite <suite>` 做检查点，不得硬编码 suite 名或用例总数。
4. `c_cross_validate.py` 必须编译 Rust `staticlib`，再编译并运行动态发现的原始 C 测试 runner 链接到 Rust C ABI facade，并解析 runner 的 `Running:` / `FAIL` 输出形成逐测试结果。
5. 写入 `logs/trace/c-cross/cross-compile.log`、`cross-test.log`、`case-results.jsonl`、`attempts.jsonl`、`workbench-issues.jsonl` 和 `logs/trace/validation-matrix.json`。
6. 中间 C-cross 是诊断检查点：全量 runner invocation 必须都有结果和证据；阶段结果为 `PASS` 或 `CONTINUE_WITH_FAILURES`。checkpoint/repair 只要证据完整就返回 0；只有 final 非全通过才返回非零。
7. 写入中文 `logs/trace/06-5-verify-rust-with-c-tests.md`。
8. 非全通过时必须消费 `logs/trace/c-cross/repair-plan.json`：控制器按 `REPAIR_ABI_LAYOUT`（`--abi-only` 确定性再生成）、`REANALYZE_C_MODEL`、`ISOLATE_SCENARIOS` 或 `REPAIR_RUST` machine route 生成单 cluster task packet，执行 targeted repair、比较 progress/regression、再做 full confirmation；默认预算 8 轮。不得在有 pending repair queue 时进入 `MIGRATE_TESTS`。
9. crash/timeout 后必须执行工具生成的逐 scenario isolation queue，不能把 runner 崩溃后的全部场景永久记为 `not_run`。回归 attempt 不得覆盖 best-known；只能恢复工具在 `logs/trace/c-cross/snapshots/` 内保存的快照。
10. 由 `workflowctl finish` 更新 functional status、repair rounds 和 `next_action` 并运行 gate。
11. 本阶段只允许把临时 C harness 证据写入 `logs/trace/c-cross/`，不得把 C 源码放进 `flashDB_rust/src/`，不得让最终 Rust 项目依赖 FlashDB C 实现。
12. 若验证失败显示 C 模型或 API 设计缺口，必须回派 `c-analyzer`，不得在本阶段系统性重读 C 工程。

### MIGRATE_TESTS

1. 必须在 `VERIFY_RUST_WITH_C_TESTS` 写出完整证据并消费 repair queue 后执行；全通过可直接进入，未全通过只有在显式修复预算耗尽且保留 best-known/真实部分成绩后才能进入。单次 `CONTINUE_WITH_FAILURES` 不再允许直接跳过修复。
2. 优先调用 `test-migrator` subagent；如果原生 subagent 不可用，拉起隔离任务代理读取 `work/skills/test-migrator.md` 后执行；连续 3 次失败后才允许主控 fallback。
3. 读取 `work/skills/test-migrator.md` 和 `work/skills/flashdb-test-migration/SKILL.md`。
4. 读取 `logs/trace/validation-matrix.json` 的结论或相关局部片段；不得全文读取无关 trace 大 JSON。Rust 源码已由 C 原始测试证据验证，Rust 测试失败默认先怀疑测试迁移或 harness。
5. 运行 `python3 work/tools/migrate_tests.py --test-model logs/trace/c_test_model.json --design logs/trace/rust_api_design.json --project flashDB_rust --mapping logs/trace/rust_test_mapping.json` 生成动态任务映射；该工具不得创建或覆盖 Rust 测试文件。
6. 以 `c_test_model.json.scorer_standard_cases` 动态推导评分覆盖合同和数量，逐项一一迁移；不得硬编码 suite、case 名或总数，`standard_scenarios` 只作为动态 C 证据来源。
7. 根据每项 `semantic_obligations` 和 `semantic_facts` 直接完成真实 Rust 测试，不生成 `todo!()`、恒真断言或其他可收集的占位测试。
8. 只有 `validated_obligations` 覆盖全部 `semantic_obligations`，且 `assertion_evidence` 证明关键 `verify_*`、`data_shape:*`、`scenario:*` 义务，才可把对应 mapping 更新为 `implementation_status: implemented` 和 `coverage: semantic`。
9. 生成 `flashDB_rust/tests/kvdb_tests.rs`、`flashDB_rust/tests/tsdb_tests.rs`、`flashDB_rust/tests/equivalence_tests.rs`。
10. 写入中文 `logs/trace/07-migrate-tests.md`。
11. 由 `workflowctl finish` 记录 `rust_test_mapping`，代理不得编辑 `workflow_state.json`。
12. 运行 `python3 work/tools/placeholder_check.py --root . --tests flashDB_rust/tests --mapping logs/trace/rust_test_mapping.json --output logs/trace/test-placeholder-check.json`，再运行 `python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json`。
13. 调用 `workflowctl finish`，由控制器内部等价运行 `python3 work/tools/gate.py --stage MIGRATE_TESTS`；评分 case 集合不一致、pending、unmapped、重复、占位实现、semantic 义务未验证或测试断言过浅时必须失败并由主控回派 `test-migrator`。

### BUILD_TEST_REPAIR

1. 优先调用 `repairer` subagent；如果原生 subagent 不可用，拉起隔离任务代理读取 `work/skills/repairer.md` 后执行；连续 3 次失败后才允许主控 fallback。
2. 运行 `python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace`。
3. 如果 `cargo test` 失败，必须先运行 `python3 work/tools/test_failure_triage.py --root . --out logs/trace`；`cargo_capture.py` 也会在 test 失败时自动生成同一 triage 记录。
4. `test_failure_triage.py` 只写入 `logs/trace/test-failure-triage.jsonl`；`workflow_state.json.test_failure_triage_required` 由 `workflowctl finish` 从机器产物投影。
5. `repairer` 只在 triage 允许的 `allowed_edit_scope` 内按最小补丁修复，最多 8 轮；系统性问题必须回派 `c-analyzer`、`rust-implementer` 或 `test-migrator`。
6. 若 `validation-matrix.json` 已通过而 Rust 测试失败，默认优先分类为 `test_oracle_suspect` 或 `harness_suspect`；只有完整 C evidence 支持测试预期时，才允许改 Rust 源码。
7. 写入中文 `logs/trace/08-build-test-repair.md`，只记录命令、产物、结果和失败摘要，不写成长篇过程复盘。
8. `workflowctl finish` 如实投影 `build_status`、`test_status`、修复轮次和未解决问题，代理不得把失败改写为通过。
9. 控制器内部等价运行 `python3 work/tools/gate.py --stage BUILD_TEST_REPAIR`。未通过且预算未耗尽时继续修复；预算耗尽后保留失败证据并强制进入 `REPORT_AND_VERIFY`，不得阻止比赛产物生成。

### REPORT_AND_VERIFY

1. 在所有 Rust 修复和测试完成后，最后一次运行 `python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --mode full --attempt-kind final --trigger final_verification`。这是最终全量 C-cross，不得带 `--suite`；所有场景通过才可报告 C-cross PASS，失败时仍必须输出最终报告和真实部分成绩。
2. 运行 `python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json`。
3. 运行 `python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json`。
4. 写入中文 `logs/trace/final-verification.md` 和 `logs/trace/09-report-and-verify.md`。
5. 在活跃 REPORT 事务内运行 `python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md`。报告工具只把控制器绑定的活跃事务视为候选完成态；前置 subagent 不维护这两个文件。
6. 无论前置检查是否全部通过，都必须先生成 `result/output.md` 和 `result/issues/00-summary.md`，再调用 `workflowctl finish`；由控制器把 `current_stage` 提交为 `DONE` 并内部等价运行 `python3 work/tools/gate.py --stage REPORT_AND_VERIFY`。
7. gate 通过后进入 `next_action=DONE, final_status=pass`；若 C-cross 或测试修复预算已耗尽但仍失败，则进入 `next_action=DONE_WITH_FAILURES, final_status=fail`，保留真实报告和非零退出码，不得在 REPORT 内死循环。

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
