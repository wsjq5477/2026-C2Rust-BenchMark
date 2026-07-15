# FlashDB C-to-Rust 转换工作台

本项目不是预置 Rust 答案。执行者必须读取平台提供的 FlashDB C 工程，在当前工作区生成 `flashDB_rust/`，并以原始 C 测试的真实运行结果验证迁移。

## 入口与边界

- 作品根目录：本文件所在目录。
- 平台 C 输入优先级：
  1. `/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
  2. `judge-assets/code/FlashDB`
  3. `../judge-assets/code/FlashDB`
- Rust 输出：`flashDB_rust/`。
- 主执行说明：[work/skills/flashdb-orchestrator.md](work/skills/flashdb-orchestrator.md)。
- 机器证据：`logs/trace/`；最终报告：`result/output.md` 与 `result/issues/00-summary.md`。
- 项目临时目录：`logs/trace/tmp/<task>/`。所有显式临时文件、探针、复制品和一次性构建产物必须放在这里；任何 agent 都不得读取、创建、删除或把 `/tmp`、`/var/tmp` 用作工作目录、PATH 注入目录或产物目录。

primary Agent 负责一次运行内的阶段推进、确定性工具、共享工作区验证和最终报告。它必须保持轻量：不得要求或接收 C/Rust 源码全文、全文大 JSON、完整历史日志或完整 runner 输出。

可选 subagent 是同一次无人值守运行内的自动上下文隔离手段，不需要第二次用户输入，也不限制总数。每个 subagent 只能处理一个有明确文件范围、动态事实或 failure cluster、停止条件的短任务；完成一次最小修改或只读产物后立即返回。primary Agent 验证结果仍失败时，可自动启动一个新的同角色 session，从共享工作区、最新 failure summary 和局部证据继续；不得恢复高上下文旧 session，也不得要求新的 primary session 或人工 continuation。

优先调用 `work/skills/` 中受本工程合同约束的命名 subagent。若运行时只提供内置 `General`，可把它作为承载角色，但 dispatch 的第一条要求必须是完整读取并执行对应 `work/skills/{subagent}.md`；prompt 只提供动态路径、失败和文件范围，不得重写业务规则、返回源码全文或预置实现方案。不得使用 `Explore`、`Scout` 或全文 reader task。

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

根据设计生成骨架，然后由 primary Agent 调度或直接实现 Rust 行为：

```bash
python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --scaffold-layout-only
```

实现时优先满足 C-Cross 可观察语义。不要为了复刻不可观察的 C 内部结构而引入完整存储引擎；只有当前输入事实和失败证据要求时，才扩展实现复杂度。重实现可由多个短任务顺序接力，但每个任务只修改主执行者指定的 Rust 文件并立即返回。写入 `05-generate-rust-scaffold.md` 与 `06-rewrite-core-modules.md`。

### 3. VERIFY_AND_REPAIR

使用唯一的 C-Cross 入口构建 Rust staticlib、编译/链接原 C runner 并实际运行：

```bash
python3 work/tools/c_cross_validate.py \
  --root . --project flashDB_rust --out logs/trace \
  --mode full --attempt-kind checkpoint --trigger implementation
python3 work/tools/gate.py --stage VERIFY_AND_REPAIR --root .
```

如有失败，只读取 `logs/trace/c-cross/failure-summary.json` 中列出的失败场景、日志和必要的 Rust/C 局部窗口。每次只把一个 failure cluster 交给一个新的 repair session；repairer 完成一次最小修改后立即返回，由 primary Agent 重跑同一条命令，并把本次修改的 Rust 源文件作为 `--changed-file` 传给 repair 运行。仍失败时以最新 failure summary 自动启动新的 repair session，不让同一个 repair session 自行反复验证和调试。不得手工执行 runner；C-Cross 的运行隔离只使用 `logs/trace/c-cross/<suite>_run/`，其他临时产物只使用 `logs/trace/tmp/<task>/`，不得访问或使用 `/tmp/**`、`/var/tmp/**`。

只有全量场景通过后，才运行最终确认：

```bash
python3 work/tools/c_cross_validate.py \
  --root . --project flashDB_rust --out logs/trace \
  --mode full --attempt-kind final --trigger final_verification
```

失败必须如实保留；它不阻止最终报告生成。

### 4. TEST_AND_REPORT

从动态 C 测试模型迁移 Rust 测试并验证。`migrate_tests.py` 只生成 mapping 骨架；必须根据对应 C 测试和 helper 实现 Rust test 体，再执行只读语义审查。不得把 mapping 自称的 coverage 或 evidence 当作通过结论。

```bash
python3 work/tools/migrate_tests.py \
  --test-model logs/trace/c_test_model.json \
  --design logs/trace/rust_api_design.json \
  --project flashDB_rust \
  --mapping logs/trace/rust_test_mapping.json
```

每一轮测试迁移或 mapping 修改后，先运行确定性占位检查；随后按 [test-semantic-reviewer.md](work/skills/test-semantic-reviewer.md) 完成一次独立、只读的逐场景 C/Rust 审查，再汇总一致性结果：

```bash
python3 work/tools/placeholder_check.py \
  --root . --tests flashDB_rust/tests \
  --mapping logs/trace/rust_test_mapping.json \
  --output logs/trace/test-placeholder-check.json
# 按 work/skills/test-semantic-reviewer.md 只写 logs/trace/test-semantic-review.json
python3 work/tools/test_consistency_check.py \
  --root . --out logs/trace/test-consistency.json
```

若任一检查失败，只读取失败 scenario 的 C/Rust evidence 和 differences，最小修改测试或 mapping 后完整重跑上述三步；最多两轮修复。两轮后仍失败时保留失败 JSON，继续生成报告，不能伪造通过。

全部检查完成后捕获 Rust 测试并计算 unsafe ratio：

```bash
python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace || true
python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json
```

补齐 `07-migrate-tests.md`、`08-build-test-repair.md`、`final-verification.md` 与 `09-report-and-verify.md`。报告只能使用与当前 C model、Rust tests 和 mapping 指纹相符的检查产物；先生成报告，再做只读最终验证：

```bash
python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md
python3 work/tools/gate.py --stage FINAL --root .
```

最终 gate 通过时，`result/output.md` 必须为 `STATUS: SUCCESS`。任何真实 C-Cross、Rust 测试或一致性失败都必须为 `STATUS: FAILED`，但报告仍必须存在。
