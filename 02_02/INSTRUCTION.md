# FlashDB C-to-Rust 转换工作台

本项目不是预置 Rust 答案。执行者必须读取平台提供的 FlashDB C 工程，在当前工作区生成 `flashDB_rust/`，并以原始 C 测试的真实运行结果验证迁移。

## 入口与边界

- 作品根目录：本文件所在目录。
- 平台 C 输入优先级：
  1. `/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
  2. `judge-assets/code/FlashDB`
  3. `../judge-assets/code/FlashDB`
- Rust 输出：`flashDB_rust/`。
- 主执行说明：[work/agents/flashdb-orchestrator.md](work/agents/flashdb-orchestrator.md)。
- 机器证据：`logs/trace/`；最终报告：`result/output.md` 与 `result/issues/00-summary.md`。
- 项目临时目录：`logs/trace/tmp/<task>/`。所有显式临时文件、探针、复制品和一次性构建产物必须放在这里；任何 agent 都不得读取、创建、删除或把 `/tmp`、`/var/tmp` 用作工作目录、PATH 注入目录或产物目录。

primary Agent 负责一次运行内的阶段推进、确定性工具、共享工作区验证和最终报告。它必须保持轻量：不得要求或接收 C/Rust 源码全文、全文大 JSON、完整历史日志或完整 runner 输出。

subagent 是同一次无人值守运行内的自动上下文隔离手段，不需要第二次用户输入，也不限制总数。除 TEST_AND_REPORT 中按动态 `rust_file` 分组调用 `test-migrator` 是必需步骤外，其他 subagent 均为可选。每个 subagent 只能处理一个有明确文件范围、动态事实或 failure cluster、停止条件的短任务；完成一次最小修改或只读产物后立即返回。primary Agent 验证结果仍失败时，可自动启动一个新的同角色 session，从共享工作区、最新 failure summary 和局部证据继续；不得恢复高上下文旧 session，也不得要求新的 primary session 或人工 continuation。

可选 subagent 只从 `work/subagent/` 中受本工程合同约束的命名角色选择。平台将主 agent 与 subagent 映射到 OpenCode 的 agent 目录；不得以内置 `General`、`Explore`、`Scout` 替代。dispatch 只提供动态路径、失败和文件范围，不得重写业务规则、返回源码全文或预置实现方案；要求阅读全部 C 源、全部测试、全部头文件、完整模型 JSON 或完整清单的全文 reader task 一律禁止。

禁止修改平台 C 输入、预置或复制 `flashDB_rust/`、把 C 源码放入 Rust `src/`、删除测试、弱化断言、伪造通过或把未运行的 C 测试标为通过。

## 四阶段流程

### 1. ANALYZE

创建运行目录：

```bash
mkdir -p logs/trace result/issues
mkdir -p logs/trace/tmp
: > logs/interaction.md
```

选择第一个存在的 `$FLASHDB_SOURCE`，只读扫描并生成动态事实：

```bash
python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json
python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace
python3 work/tools/design_rust_api.py \
  --project-model logs/trace/c_project_model.json \
  --api-model logs/trace/c_api_model.json \
  --test-model logs/trace/c_test_model.json \
  --output logs/trace/rust_api_design.json
python3 work/tools/gate.py --stage ANALYZE --root .
```

补齐中文阶段日志 `02-read-c-project.md`、`03-build-c-model.md`、`04-design-rust-api.md`。所有文件、符号、ABI 事实和测试场景从当前输入提取，不得写死本地样例。

### 2. IMPLEMENT

根据设计生成骨架并先验证 scaffold 本身可构建、ABI layout 正确，然后由 primary Agent 调度或直接实现 Rust 行为：

```bash
python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --scaffold-layout-only
```

layout-only 通过只代表 scaffold 结构成立，绝不代表 IMPLEMENT 完成。实现时优先满足 C-Cross 可观察语义。不要为了复刻不可观察的 C 内部结构而引入完整存储引擎；只有当前输入事实和失败证据要求时，才扩展实现复杂度。重实现可由多个短任务顺序接力，但每个任务只修改主执行者指定的 Rust 文件并立即返回。

初始实现完成后必须先对当前源码重新运行 `--scaffold-layout-only`，无论当前 build/layout 成功或失败，都继续记录 implementation checkpoint：

```bash
python3 work/tools/core_impl_audit.py \
  --root . --project flashDB_rust \
  --manifest logs/trace/scaffold-manifest.json \
  --design logs/trace/rust_api_design.json \
  --output logs/trace/implementation-audit.json \
  --attempt-kind checkpoint
```

审计为 `implementation_required` 时，禁止进入 C-Cross。只消费 `implementation-audit.json` 当前 findings，可按动态 symbol、module、依赖和文件簇启动多个新的短期 `rust-implementer` session；全部有界修改完成后先对新源码刷新 `--scaffold-layout-only`，再只记录一次真实补漏：

```bash
python3 work/tools/core_impl_audit.py \
  --root . --project flashDB_rust \
  --output logs/trace/implementation-audit.json \
  --attempt-kind repair
```

IMPLEMENT 只允许这一轮 audit 定向补漏，单轮可包含多个短任务，但不得开启第二轮源码版本或整体重构。补漏后只要 implementation audit 或当前 build/layout 仍失败，就在不修改源码的情况下运行 `core_impl_audit.py --attempt-kind confirmation`。fresh confirmation 仍失败才形成 `failed_stage=IMPLEMENT` 的 `failed_final`；此时直接运行 `report_writer.py` 和 `gate.py --stage FINAL` 生成真实失败报告，C-Cross、Rust tests 和 unsafe 必须标为 `not_run`。

审计与当前 build/layout 都通过时，随后运行：

```bash
python3 work/tools/gate.py --stage IMPLEMENT --root .
```

只有 gate 输出 `IMPLEMENT: PASS` 才能进入 VERIFY_AND_REPAIR。`IMPLEMENTATION_REQUIRED` 必须继续实现；只有带 fresh audit confirmation 和真实源码 repair 证据的 `IMPLEMENT: FAILED_FINAL` 才允许直接生成实现失败报告。是否调用过 subagent 不是通过证据。写入 `05-generate-rust-scaffold.md` 与 `06-rewrite-core-modules.md`。

### 3. VERIFY_AND_REPAIR

使用唯一的 C-Cross 入口构建 Rust staticlib、编译/链接原 C runner 并实际运行：

```bash
python3 work/tools/c_cross_validate.py \
  --root . --project flashDB_rust --out logs/trace \
  --mode full --attempt-kind checkpoint --trigger implementation
```

所有非 `--scaffold-layout-only`、非受约束 `--restore-best` 的 C-Cross 路径都会在写 matrix 或 attempt 前重新执行当前 IMPLEMENT 审计。首次 C-Cross checkpoint 必须有当前 implementation attempt 与 build/layout；正式 C-Cross 链建立后，后续语义 repair 由 C-Cross 自己的 source manifest 和 changed-file 合同追踪，不要求复用初始实现源码指纹，但仍重新审计当前代码并拒绝任何重新引入的 scaffold residue。前置拒绝不得产生 C-Cross 失败场景或消耗 8 次 repair budget。

该命令在 `repair_required` 时必须返回非零；这表示继续修复，不是允许停止。如有失败，只读取 `logs/trace/c-cross/failure-summary.json` 中列出的失败场景、日志和必要的 Rust/C 局部窗口。每次选择包含 1 至 3 个相关 scenario 的一个 failure cluster，交给一个新的 `rust-implementer` session；本地修复最多修改 3 个 `flashDB_rust/src/` 文件，完成一次最小修改后立即返回。primary Agent 按实际修改路径运行定向 repair，例如：

```bash
python3 work/tools/c_cross_validate.py \
  --root . --project flashDB_rust --out logs/trace \
  --mode full --attempt-kind repair --repair-kind local \
  --scenario "$SCENARIO" --changed-file flashDB_rust/src/<file> \
  --trigger bounded_local_repair
```

每次定向 repair 后都必须用 `--mode full --attempt-kind confirmation` 重跑全部动态场景；不得只看定向结果。若同一 cluster 连续两次本地修复都没有进展，必须结束旧 session，启动新的只读架构审查，再允许一次 `--repair-kind architecture` 修复；架构修复仍限同一 cluster，最多修改 6 个 Rust 源文件，不得借机整体重构。C-Cross 全局最多记录 8 次真实 repair；checkpoint、confirmation、final、只读审查和单纯刷新证据不计数。

若一次 repair 使已通过场景回归，不得在回归版本继续修复。运行 `c_cross_validate.py --restore-best` 恢复 best-known `src/**`，随后先做全量 confirmation。仍失败时以最新 failure summary 启动新的短 session，不恢复高上下文旧 session。不得手工执行 runner；C-Cross 的运行隔离只使用 `logs/trace/c-cross/<suite>_run/`，其他临时产物只使用 `logs/trace/tmp/<task>/`，不得访问或使用 `/tmp/**`、`/var/tmp/**`。

只有全量场景通过后，才运行最终确认：

```bash
python3 work/tools/c_cross_validate.py \
  --root . --project flashDB_rust --out logs/trace \
  --mode full --attempt-kind final --trigger final_verification
```

`failure-summary.json` 的状态只有以下含义：`repair_required` 必须继续修复，绝对不能进入报告；`ready_for_final` 必须运行上述 fresh final；`success` 才能生成成功报告；只有 8 次 repair 已耗尽且又完成全量 confirmation 后形成的 `failed_final`，才允许带真实失败进入 TEST_AND_REPORT 并生成失败报告。局部第 8 次 repair 不能直接形成 `failed_final`。

状态为 `ready_for_final`、`success` 或 `failed_final` 后运行：

```bash
python3 work/tools/gate.py --stage VERIFY_AND_REPAIR --root .
```

### 4. TEST_AND_REPORT

从动态 C 测试模型迁移 Rust 测试并验证。`migrate_tests.py` 只生成 mapping 骨架；必须根据对应 C 测试和 helper 实现 Rust test 体，再执行只读语义审查。不得把 mapping 自称的 coverage 或 evidence 当作通过结论。

```bash
python3 work/tools/migrate_tests.py \
  --test-model logs/trace/c_test_model.json \
  --design logs/trace/rust_api_design.json \
  --project flashDB_rust \
  --mapping logs/trace/rust_test_mapping.json
```

mapping 生成后必须立即调用命名角色 `test-migrator`。按 mapping 中动态出现的 `rust_file` 分组，每个新 session 只实现一个文件及其关联 scenarios；全部分组都返回真实 Rust test 体后才能运行检查。不得把 `test-migrator` 当成可跳过的优化；只有平台明确无法调用该角色时，primary Agent 才能按同一合同直接实现，并且仍须满足后续机器门禁。

每一轮测试迁移或 mapping 修改后，先运行确定性占位检查。`implementation_status` 只是 mapping 中的任务提示，不能作为通过证据；不得通过机械修改该字段消除失败。placeholder 为 `repair_required` 时必须回到新的 `test-migrator` session，不得运行 Cargo、unsafe ratio 或报告；只有 placeholder 通过，或者两次真实测试修复耗尽形成 `failed_final` 后为了保留最终诊断，才可运行 Cargo。

```bash
python3 work/tools/placeholder_check.py \
  --root . --tests flashDB_rust/tests \
  --mapping logs/trace/rust_test_mapping.json \
  --output logs/trace/test-placeholder-check.json
python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace
```

`placeholder_check.py` 与 `cargo_capture.py` 共同把当前 `src/**`、`tests/**`、Cargo 文件和 mapping 指纹写入 `test-repair-attempts.jsonl`。初次 placeholder 是 checkpoint；只有相对上一条证据发生真实文件变化才记录一次 test repair，单轮最多改变 4 个受跟踪文件。Cargo 不得只凭退出码判断通过：mapping 必须非空、测试目录与映射文件必须存在、每个动态 `rust_test` 都必须在真实 `cargo test` 输出中执行且不能 ignored；编译成功但执行 0 个测试必须写 `test_status=fail`。`cargo-results.json.test_status` 失败时，必须消费 `test-failure-triage.jsonl` 和 `test_execution` 中的全部失败，而不是只处理第一项。triage 的 assertion 只能证明发生了不一致，不能自动证明测试预言错误。必须对照映射的 C test/helper、Rust test、setup、数据、生命周期和同场景 C-Cross 证据后，才能决定修改 tests/mapping 还是经证据授权修改 `flashDB_rust/src/`。

Cargo 通过后，按 [test-semantic-reviewer.md](work/subagent/test-semantic-reviewer.md) 完成一次独立、只读的逐场景 C/Rust 审查，再汇总一致性结果：

```bash
# 按 work/subagent/test-semantic-reviewer.md 只写 logs/trace/test-semantic-review.json
python3 work/tools/test_consistency_check.py \
  --root . --out logs/trace/test-consistency.json
```

placeholder、Cargo、semantic review 或 consistency 任一失败时，只读取失败 scenario 的局部证据并做最小修改，然后从 placeholder、Cargo、fresh reviewer、consistency 完整重跑。最多两轮测试修复；只有 `test-repair-attempts.jsonl` 证明 tests、mapping 或经 C 证据授权的 Rust 生产源码发生真实修改才消耗一轮，单纯重跑 reviewer、刷新 fingerprint 或修改状态字段不计轮次。修改 `flashDB_rust/src/**` 后不能直接跑 confirmation/final 绕过 C-Cross repair 计数；必须按受影响 scenario 先记录定向 C-Cross repair，再做全量 confirmation，全部通过后再 fresh final。零轮或一轮后仍失败是 `repair_required`；两次真实 test repair 后，Cargo 与当前 placeholder/semantic 证据仍失败才形成测试侧 `failed_final`。预算耗尽后不得再修改第三个版本；保留当前失败产物并生成失败报告，不能伪造通过。

上述检查完成或修复预算耗尽后，必须先运行报告前门禁：

```bash
python3 work/tools/gate.py --stage TEST_AND_REPORT --root .
```

该 gate 为 `repair_required` 时不得继续；只有测试阶段 `success` 或两次真实 repair 耗尽后的 `failed_final` 才能计算 unsafe ratio：

```bash
python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json
```

补齐 `07-migrate-tests.md`、`08-build-test-repair.md`、`final-verification.md` 与 `09-report-and-verify.md`。报告只能使用与当前 C model、Rust tests 和 mapping 指纹相符的检查产物；先生成报告，再做只读最终验证：

```bash
python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md
python3 work/tools/gate.py --stage FINAL --root .
```

`report_writer.py` 接受两类终态。IMPLEMENT 已通过时，C-Cross 与测试阶段必须分别收敛：两者都成功且 unsafe 合格时写 `STATUS: SUCCESS`；任一阶段为 `failed_final` 时，另一阶段也必须已成功或耗尽预算，才能写 `STATUS: FAILED`。C-Cross 的 `failed_final` 只允许进入测试迁移，绝不豁免空测试目录、未执行映射测试或尚有测试修复预算的失败。IMPLEMENT 在一次真实补漏和 fresh confirmation 后形成阶段化 `failed_final` 时，直接写 `failed_stage: IMPLEMENT` 的失败报告，所有未运行下游证据必须标为 `not_run`。任何未收敛状态只能写 `STATUS: INCOMPLETE` 并返回非零。最终 gate 对成功终态打印 `PASS`，对诚实失败终态打印 `FAILED_FINAL`。
