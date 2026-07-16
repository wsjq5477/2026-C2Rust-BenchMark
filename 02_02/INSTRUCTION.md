# FlashDB C-to-Rust 转换工作台

本项目必须从平台提供的 FlashDB C 工程动态生成 `flashDB_rust/`，迁移真实 Rust tests，并用原 C 测试和当前源码证据验证结果。不得预置答案、修改平台输入、删除测试、弱化断言、伪造通过或把未运行场景标为通过。

## 0. 竞赛安全入口

进入作品根目录后，第一条命令必须启动独立看门狗：

```bash
python3 work/tools/contest_watchdog.py start --root . --freeze-after-minutes 540
```

平台硬截止为 600 分钟。正常修复不按时间动态缩减；到第 540 分钟，看门狗会无条件恢复评分最高且同分最新的 validated submission snapshot，生成 deadline 报告并冻结提交文件。任何工具返回 `CONTEST_FINALIZE_REQUIRED`，或存在 `logs/trace/contest-control/submission-frozen.json` 时，立即停止修复，运行允许的 FINAL gate 后结束任务。

平台 C 输入选择第一个存在的目录：

1. `/app/code/judge-assets/02_02_c_to_rust/code/FlashDB`
2. `judge-assets/code/FlashDB`
3. `../judge-assets/code/FlashDB`

产物边界：

- Rust 项目：`flashDB_rust/`
- 机器证据：`logs/trace/`
- 最终报告：`result/output.md`、`result/issues/00-summary.md`
- 项目临时目录：`logs/trace/tmp/<task>/`
- 禁止使用 `/tmp/**`、`/var/tmp/**`

primary Agent 只负责阶段推进、确定性工具、短任务派发和报告。只调用 `work/subagent/` 中的命名角色；不得调用内置 General、Explore 或 Scout。每个 subagent 只处理一个动态 task/最小共享根因 cluster，完成一次真实修改后立即返回，不自行循环验证或返回源码全文。

## 1. ANALYZE

```bash
mkdir -p logs/trace/tmp result/issues
: > logs/interaction.md
python3 work/tools/scan_c_project.py --source "$FLASHDB_SOURCE" --output logs/trace/input_manifest.json
python3 work/tools/build_c_model.py --manifest logs/trace/input_manifest.json --output-dir logs/trace
python3 work/tools/design_rust_api.py \
  --project-model logs/trace/c_project_model.json \
  --api-model logs/trace/c_api_model.json \
  --test-model logs/trace/c_test_model.json \
  --output logs/trace/rust_api_design.json
python3 work/tools/gate.py --stage ANALYZE --root .
```

所有源文件、符号、ABI 和 scorer scenario 必须来自当前输入，不得写死固定数量或名字。补齐 `02-read-c-project.md`、`03-build-c-model.md` 和 `04-design-rust-api.md`。

## 2. IMPLEMENT

```bash
python3 work/tools/generate_rust_scaffold.py --design logs/trace/rust_api_design.json --project flashDB_rust
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --scaffold-layout-only
```

layout-only 只证明 scaffold 可构建和 ABI layout 成立，不代表业务实现完成。primary 可直接实现，或把动态 symbol/module/dependency finding task 交给新的 `rust-implementer`；只读取当前 task 的设计义务、C/Rust 函数窗口和必要 helper。

初始实现后刷新 layout 并建立 audit checkpoint：

```bash
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --scaffold-layout-only
python3 work/tools/core_impl_audit.py --root . --project flashDB_rust \
  --output logs/trace/implementation-audit.json --attempt-kind checkpoint
```

`implementation_required` 时读取 `implementation-audit.json` 与 `repair-work-queue.json.phases.implement`。逐 task 修改后按真实 task id 记录 repair：

```bash
python3 work/tools/core_impl_audit.py --root . --project flashDB_rust \
  --output logs/trace/implementation-audit.json --attempt-kind repair --task "$TASK_ID"
```

一个 task 第一遍最多获得两次修改机会，随后让出给其他 finding；第二遍仍无进展才 exhausted。不存在全局一次补漏预算。所有 finding resolved 后进入 C-Cross；所有剩余 finding exhausted 时，在不修改源码的情况下记录 confirmation，才能形成 IMPLEMENT `failed_final`。

```bash
python3 work/tools/core_impl_audit.py --root . --project flashDB_rust \
  --output logs/trace/implementation-audit.json --attempt-kind confirmation
python3 work/tools/gate.py --stage IMPLEMENT --root .
```

实现通过时会保存首个 buildable submission baseline。补齐 `05-generate-rust-scaffold.md` 和 `06-rewrite-core-modules.md`。

## 3. VERIFY_AND_REPAIR

唯一 C runner 入口：

```bash
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace \
  --mode full --attempt-kind checkpoint --trigger implementation
```

失败任务来自 `failure-summary.json` 与 `repair-work-queue.json.phases.c_cross`：

1. 每次处理一个 scenario 或有共同失败指纹/共同修改文件证据的最小 cluster；不固定 cluster 场景数量。
2. local task 最多修改 3 个声明的 Rust 源文件；连续两次无进展后让出队列，并在第二遍允许一次新的 architecture 诊断，architecture task 最多修改 6 个声明文件。
3. 定向 repair 后先验证当前 task；完成一组同 suite task 后做 suite 回归；每遍结束做全量 confirmation，不在每个 assertion 后重复全量执行。
4. 修改造成已通过场景回归且评分不提升时，立即用 `--restore-best` 恢复 C-Cross runtime-best。

```bash
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace \
  --mode full --attempt-kind repair --repair-kind local \
  --scenario "$SCENARIO" --changed-file flashDB_rust/src/<file> \
  --trigger queued_local_repair
```

不存在全局 8 次 repair 预算。只要还有 queued task 就是 `repair_required`；所有 remaining task resolved/exhausted 后做 full confirmation，仍失败才是 `failed_final`。全量通过后必须 fresh final：

```bash
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace \
  --mode full --attempt-kind final --trigger final_verification
python3 work/tools/gate.py --stage VERIFY_AND_REPAIR --root .
```

## 4. TEST_AND_REPORT

`migrate_tests.py` 只生成 mapping task，不生成测试体：

```bash
python3 work/tools/migrate_tests.py \
  --test-model logs/trace/c_test_model.json \
  --design logs/trace/rust_api_design.json \
  --project flashDB_rust \
  --mapping logs/trace/rust_test_mapping.json
```

按 queued scenario 或最小共享 Rust helper cluster 调用新的 `test-migrator`，不得按整个大文件一次迁移全部场景。每个 Rust test 必须保留对应 C test/helper 的 API、数据、配置、生命周期、顺序和 assertion 语义。

每轮运行：

```bash
python3 work/tools/placeholder_check.py --root . --tests flashDB_rust/tests \
  --mapping logs/trace/rust_test_mapping.json \
  --output logs/trace/test-placeholder-check.json
python3 work/tools/cargo_capture.py --project flashDB_rust --out logs/trace
```

placeholder 按 scenario 形成 task；一个缺失测试不能阻止其他已就绪场景取得 Cargo 结果。Cargo 必须证明 mapping 非空、测试文件存在、每个映射测试真实执行且未 ignored；0 tests 永远是 fail。

semantic reviewer 每次只审查分配的 scenario/最小 cluster，写入项目拥有的局部 JSON，再合并：

```bash
python3 work/tools/semantic_review_merge.py --root . \
  --input logs/trace/test-semantic-review-parts/<task>.json
python3 work/tools/test_consistency_check.py --root . --out logs/trace/test-consistency.json
```

consistency 必须逐 scenario 计分；一个 reviewer case 失败不能抹掉其他 current pass。测试任务同样采用每 task 两遍、每遍最多两次的调度配额，不存在全局两轮 repair 预算。测试或经证据授权的生产源码发生修改后，重新运行受影响场景；生产源码修改还必须回到 C-Cross 记录对应 repair。

每次 current 的完整 Cargo + consistency 结果提高评分时，工具自动保存完整 `submission-best`，覆盖 Rust src/tests、Cargo、mapping 和绑定证据，不依赖 Git。

所有测试 task success/exhausted 后：

```bash
python3 work/tools/gate.py --stage TEST_AND_REPORT --root .
python3 work/tools/unsafe_ratio.py --project flashDB_rust --out logs/trace/unsafe-ratio.json
python3 work/tools/report_writer.py --root . --output result/output.md --issues result/issues/00-summary.md
python3 work/tools/gate.py --stage FINAL --root .
python3 work/tools/contest_watchdog.py stop --root .
```

补齐 `07-migrate-tests.md`、`08-build-test-repair.md`、`final-verification.md` 和 `09-report-and-verify.md`。正常路径只有 task queue 全部终结才能生成 `success/failed_final`；540 分钟路径只有 validated snapshot 恢复、hash/evidence 校验和冻结证据完整时，才允许 `termination_reason: contest_deadline_freeze` 的 deadline final。
