# Q13 - Rust 骨架越过 IMPLEMENT 门禁问题与修复方案

> 状态：已实施；2026-07-16 已接入 IMPLEMENT audit/gate、C-Cross preflight、阶段化失败报告与回归测试
>
> 日期：2026-07-16
>
> 范围：`02_02` 的 IMPLEMENT 阶段合同、实现审计、阶段 gate、C-Cross 前置检查、失败终态和回归测试。不修改平台 C 输入，不预置 Rust 答案。
>
> 事实边界：问题现象来自评分平台本轮结论；工程依据只取当前工作台文件，不使用其他电脑的 OpenCode 历史记录。

## 1. 结论

评分平台的分析方向基本准确：`generate_rust_scaffold.py` 按设计只生成 ABI 骨架、中性 FFI stub 和 placeholder module，真正的 Rust 行为必须在其后由 primary 或有界的 `rust-implementer` 完成。

但根因不能只归结为“primary Agent 误以为 scaffold 已经实现”。当前工作流同时存在三处可被弱模型穿透的缺口：

1. IMPLEMENT 只有自然语言要求，没有独立的机器完成门禁；
2. 已存在的 `core_impl_audit.py` 没有接入简化后的四阶段主链路；
3. `c_cross_validate.py` 的正常模式不会在写入 C-Cross attempt 前拒绝 untouched scaffold。

因此本次不应把 scaffold generator 改造成业务代码生成器，也不应恢复旧的 workflow controller。正确修改是：

```text
复用并补强 core_impl_audit.py
        ↓
新增结果型 IMPLEMENT gate
        ↓
C-Cross 在任何正式 attempt 前复用该 gate 并 fail-fast
        ↓
只有确认脱离 scaffold 的 Rust 工程才能进入语义验证
```

实现动作必须发生，但“是否调用过某个 subagent”不是通过证据。primary 可以直接实现，也可以把动态、有限的实现簇交给新的短期 `rust-implementer` session；唯一完成依据是当前 Rust 文件通过 IMPLEMENT gate。

## 2. 问题现象与当前证据

### 2.1 评分平台现象

本轮运行出现了以下错误顺序：

```text
生成 flashDB_rust scaffold
        ↓
FFI 仍返回 null / 0 / false，核心模块仍是 placeholder
        ↓
未完成真实 Rust 行为实现
        ↓
直接启动 full C-Cross 或后续测试
```

骨架能够通过 Rust 编译或 ABI layout 检查，只能证明生成结构可编译、布局探针可运行，不能证明业务行为已经实现。把 layout-only 成功解释为 IMPLEMENT 成功，是本次断链的直接表现。

### 2.2 scaffold generator 的真实职责

`02_02/work/tools/generate_rust_scaffold.py` 明确声明并写入：

- `@c2rust-scaffold:neutral-ffi:v1`；
- `@c2rust-scaffold:placeholder-module:v1`；
- `stub_symbols`；
- `placeholder_modules`；
- 每个 FFI 函数的生成体指纹和 `neutral_expression`；
- `rewrite_ownership` 与冻结的 ABI symbol 签名。

这说明生成器的输出是后续实现审计所需的基线，不是完整 Rust 迁移结果。生成器只生成骨架属于正确设计，不是缺陷。

### 2.3 当前流程缺口

| 位置 | 当前行为 | 缝隙 |
|---|---|---|
| `INSTRUCTION.md` 的 IMPLEMENT | 运行 scaffold generator 和 `--scaffold-layout-only`，随后用文字要求“调度或直接实现” | 没有 IMPLEMENT gate 命令，弱模型可直接跳到下一阶段 |
| `flashdb-orchestrator.md` | 要求生成骨架后“直接实现或调度实现” | 没有规定正式验证前必须消费当前实现审计结果 |
| `rust-implementer.md` | 定义为可选、有界实现角色 | 角色可选本身没有问题，但当前没有结果门禁兜底 |
| `core_impl_audit.py` | 已能识别未改写 FFI、直接中性返回、placeholder 和纯注释/空白修改 | 工具仍存在，却未接入 `gate.py`、orchestrator 和 C-Cross 主入口 |
| `gate.py` | 只有 `ANALYZE`、`VERIFY_AND_REPAIR`、`TEST_AND_REPORT`、`FINAL` | 缺少 `IMPLEMENT` 阶段检查 |
| `c_cross_validate.py` | `--scaffold-layout-only` 单独处理；其他模式随后直接准备 matrix/attempt 并运行验证 | 没有检查 scaffold marker、函数体基线或 placeholder residue |

### 2.4 允许与禁止的骨架检查

骨架刚生成时允许：

- `cargo fmt --check`；
- Rust build/check；
- ABI/layout probe；
- `c_cross_validate.py --scaffold-layout-only`。

骨架刚生成时禁止：

- 正式的 `--mode build/layout/link/full` C-Cross attempt；
- 把 layout-only 结果写成实现完成；
- 进入 Rust 语义测试迁移；
- 计算 unsafe ratio；
- 生成声称已经完成 VERIFY 的报告。

## 3. 根因分析

### 3.1 IMPLEMENT 没有可观察完成条件

当前合同描述了“应该实现”，却没有回答以下机器可判定问题：

- 哪些 FFI 函数仍与生成体完全相同；
- 哪些模块仍是 availability placeholder；
- 是否只删除了 marker 或修改了空白和注释；
- 是否保留了生成时冻结的 ABI 签名；
- 当前审计证据是否对应最新 Rust 源码。

因此 primary 即使跳过实现，后续工具也无法区分“刚生成的 scaffold”和“已经完成初始实现的 Rust 工程”。

### 3.2 简化流程时丢失了审计接线

Q7 阶段已经新增 `core_impl_audit.py`，旧 REWRITE gate 曾使用它阻止空实现。Q9 删除事务 controller、REWRITE worker/receipt 和重复过程状态后，保留了审计工具，但没有把这个结果型检查重新接到简化四阶段中。

所以当前问题不是缺少检测算法，而是有效检测能力成为孤立工具。

### 3.3 C-Cross 缺少调用前置条件

`c_cross_validate.py --scaffold-layout-only` 已经正确区分“骨架布局检查”，但正常路径没有相反约束：只要调用者未传该开关，工具就会继续准备 C-Cross。

文档要求无法阻止弱模型发出错误命令。必须由 C-Cross 自身在创建 matrix、execution id、attempt 或消耗 repair budget 之前执行 IMPLEMENT 预检。

### 3.4 Agent 跳步是结果，不是唯一根因

primary 没有实现代码便开始测试，确实是一次执行错误；但只修改提示词仍会复发。可靠工作流必须假设模型可能：

- 把 build/layout 成功误当成实现成功；
- 认为 generator 已经完成迁移；
- 忽略可选实现角色；
- 直接复制下一阶段命令；
- 删除 marker 后误以为通过。

因此最终约束必须落在当前文件和确定性工具结果上，而不是依赖 Agent 对自然语言阶段的正确理解。

## 4. 设计目标与非目标

### 4.1 目标

1. untouched scaffold 只能执行 layout-only，不能进入正式 C-Cross。
2. IMPLEMENT 是否完成由当前 Rust 源码与 scaffold baseline 共同决定。
3. 删除 marker、修改注释或空白不能绕过检查。
4. 检查结果必须绑定当前 design、manifest 和 Rust 源码，旧 JSON 不能复用。
5. IMPLEMENT 未完成不得产生 C-Cross attempt，也不得消耗现有 8 次 C-Cross repair budget。
6. 初始实现可由多个短任务接力，不能要求一个长 session 读取完整 C 工程或持续调试。
7. 工具不得写死 FlashDB 函数名、模块名、suite、scenario 或固定测试数量。
8. 自动运行最终必须有真实结果；无法完成实现时只能形成 IMPLEMENT 阶段的 `failed_final`，不得假装进入过语义验证。

### 4.2 非目标

- 不让 `generate_rust_scaffold.py` 自动生成完整业务逻辑。
- 不通过静态审计证明 Rust 与 C 语义等价；该责任仍属于 full C-Cross。
- 不恢复 `workflowctl.py`、task packet、worker receipt、revision 或 agent registry。
- 不把“成功调用 rust-implementer”当作 gate 通过条件。
- 不固定拆成 KVDB/TSDB、CORE/FACADE 等样例专用 worker。
- 不要求 primary 或 subagent 阅读全部 C 源、全部测试、完整模型 JSON 或完整历史日志。
- 不改变现有 C-Cross 语义修复预算和 `success/repair_required/ready_for_final/failed_final` 判定规则。

## 5. 目标流程

```text
ANALYZE gate 通过
        ↓
generate_rust_scaffold.py
        ↓
c_cross_validate.py --scaffold-layout-only
        ↓
primary 直接实现，或按动态文件/依赖簇调用短期 rust-implementer
        ↓
core_impl_audit.py 生成最新 implementation-audit.json
        ↓
gate.py --stage IMPLEMENT
        ├─ implementation_required：返回实现阶段
        ├─ failed_final：只允许生成 IMPLEMENT 未完成的失败报告
        └─ pass：允许进入 VERIFY_AND_REPAIR
                ↓
        c_cross_validate.py --mode full --attempt-kind checkpoint
                ↓
        现有 C-Cross 有界修复与 fresh final
```

IMPLEMENT gate 只证明工程已经脱离 scaffold，不代表 C-Cross 会通过。初始真实实现仍可能存在大量语义错误，这些错误在 VERIFY_AND_REPAIR 阶段按当前 failure cluster 策略处理。

## 6. IMPLEMENT 完整性门禁

### 6.1 复用现有 `core_impl_audit.py`

不新增功能重复的 `implementation_check.py`。以现有 `core_impl_audit.py` 为唯一实现审计器，并补齐当前缺失的 freshness、ABI 和阶段证据。

审计继续使用 `scaffold-manifest.json` 中的动态事实：

- `ffi_functions`；
- `stub_symbols`；
- `placeholder_modules`；
- `files.*.normalized_sha256`；
- `rewrite_ownership.frozen_contract_symbols`；
- `design_sha256`。

### 6.2 必须拒绝的情况

任一条件成立，IMPLEMENT 均不能通过：

1. scaffold manifest 或 Rust API design 缺失、损坏或互相不匹配；
2. design 要求的任一导出符号缺失或无法解析；
3. 任一 FFI 函数体的规范化指纹仍等于 scaffold baseline；
4. 任一 FFI 函数体只有空体、null、0、1、true、false、None 或 zeroed 等直接中性结果；
5. 任一 placeholder module 仍包含 marker，或原始/规范化 hash 未变化；
6. 文件只发生注释、marker、格式或空白变化；
7. 任一冻结 ABI symbol 的签名与 manifest 不一致；
8. 必需的核心模块被删除；
9. 当前 `flashDB_rust/src/**` 含禁止的 C 源文件；
10. 审计产物的输入指纹不对应当前 design、manifest 和 Rust 源码。

审计禁止采用“发现调用了某个函数就认为已实现”等启发式通过条件。调用链可能仍返回中性值，真正语义只能交给 C-Cross；审计只负责排除确定的 scaffold 残留。

对于原 C 语义确实返回固定值的函数，也不增加按函数名配置的豁免。实现应进入明确的 Rust 语义路径；含真实操作后返回 0 不属于“直接中性函数体”。极少数纯常量 API 也应通过设计事实和实际 Rust 函数表达，而不是保留生成 stub。

### 6.3 freshness 与输出

`implementation-audit.json` 增加稳定输入指纹，至少覆盖：

```text
scaffold-manifest.json 内容 hash
+ rust_api_design.json 内容 hash
+ manifest 涉及的当前 Rust 文件路径与内容 hash
```

建议保留以下结果字段：

```json
{
  "schema_version": 2,
  "status": "pass | fail",
  "input_fingerprint": "sha256:...",
  "summary": {
    "findings": 0,
    "checked_ffi_functions": 0,
    "checked_placeholder_modules": 0,
    "checked_frozen_signatures": 0
  },
  "findings": []
}
```

`gate.py` 不得只相信磁盘上的旧 `implementation-audit.json`。它应调用同一个 `audit(...)` 逻辑重新计算当前结果，再核对落盘产物的 `status`、`input_fingerprint` 和关键 summary；不一致即失败。

### 6.4 `gate.py --stage IMPLEMENT`

`gate.py` 增加 `IMPLEMENT` 选项和 `check_implement(root)`。当前实现完成后先刷新无正式 attempt 的 build/layout 证据，再记录审计 checkpoint：

```bash
python3 work/tools/c_cross_validate.py \
  --root . --project flashDB_rust --out logs/trace \
  --scaffold-layout-only

python3 work/tools/core_impl_audit.py \
  --root . --project flashDB_rust \
  --manifest logs/trace/scaffold-manifest.json \
  --design logs/trace/rust_api_design.json \
  --output logs/trace/implementation-audit.json \
  --attempt-kind checkpoint

python3 work/tools/gate.py --stage IMPLEMENT --root .
```

gate 还应复核：

- workspace 和 Rust project 存在；
- scaffold layout 证据存在且通过；
- implementation audit 是当前输入的最新结果；
- `ready_for_verify` 路径的当前 Rust build/layout 已通过；IMPLEMENT `failed_final` 路径保留当前 build/layout 失败作为终态证据；
- `flashDB_rust/src/` 中没有 C 源。

gate 只校验结果，不负责选择 Agent、派发任务或维护 controller 状态。

## 7. primary 与 rust-implementer 调度规则

### 7.1 强制的是实现动作，不是角色回执

scaffold layout 通过后，primary 必须完成以下二选一动作：

1. 直接修改 `flashDB_rust/` 完成初始行为实现；
2. 将一个明确、动态、有停止条件的实现簇交给新的 `rust-implementer` session。

无论采用哪种方式，都必须运行 IMPLEMENT audit 和 gate。不能因为“没有调用 subagent”失败，也不能因为“调用过 subagent”通过。

### 7.2 动态实现簇

任务范围从当前事实动态形成，可参考但不机械执行：

- `rewrite_ownership.core_owned_paths`；
- `rewrite_ownership.facade_owned_paths`；
- `rust_api_design.json` 中相关 API、implementation obligation 与依赖；
- 当前 audit finding 指向的 symbol、module 和文件。

这些字段用于缩小任务上下文，不恢复固定 CORE/FACADE worker 事务，也不成为文件 ownership receipt。

每个短任务只携带：

- 允许修改的 Rust 文件；
- 本次负责的动态 symbol/API/obligation；
- 必要的 C 模型或测试事实片段；
- 相关 C/Rust 函数和 helper 的局部窗口；
- 停止条件“完成一次最小实现并返回实际修改路径”。

禁止给单个实现 session 发送完整 C 源码、完整测试树、完整模型 JSON、全部历史日志或跨多个无关模块的重构任务。

### 7.3 audit finding 的消费

审计失败后只消费当前 findings：

- `unchanged_scaffold_body`：实现对应 symbol 的真实路径；
- `constant_only_neutral_body`：替换直接中性返回；
- `placeholder_module`：实现对应动态模块；
- `cosmetic_only_file_change`：完成实质代码修改；
- `missing_ffi_symbol` 或 ABI signature finding：恢复冻结的导出合同，再实现内部行为。

每次新的有界修改完成后由 primary 重跑审计；subagent 不自行运行 C-Cross，不连续调试，也不扩大到其他 finding cluster。

## 8. C-Cross 前置拒绝规则

### 8.1 fail-fast 位置

`c_cross_validate.py` 在所有正常验证 attempt 路径的最前面复用当前 IMPLEMENT 审计。`--scaffold-layout-only` 与 `--restore-best` 是两个特殊分支：前者用于骨架结构检查，后者只在已经存在真实 regression 和 best-known 证据时恢复先前实现；二者都不创建新的正式验证 attempt。除这两个分支外，预检必须发生在以下动作之前：

- 读取或比较正式 C-Cross previous matrix；
- 创建 execution id；
- 调用 `build_matrix()`；
- 写 `validation-matrix.json`；
- 追加 `c-cross/attempts.jsonl`；
- 创建或更新 best-known snapshot；
- 计算或消耗 repair budget。

首次正式 checkpoint 必须同时验证当前 implementation attempt 和 build/layout。正式 C-Cross matrix/attempt 链已经建立后，Rust 语义修复必然改变初始实现源码指纹；此时 preflight 继续重算 scaffold audit，但源码变化和 repair budget 改由现有 C-Cross source manifest/changed-file 合同验证，不能错误要求初始 implementation fingerprint 永久不变。

### 8.2 拒绝结果

若审计未通过，命令必须非零退出并输出稳定信息：

```text
VERIFY_RUST_WITH_C_TESTS: IMPLEMENTATION_REQUIRED
implementation_audit=logs/trace/implementation-audit.json
next_action=return_to_implement
```

同时满足：

- 不写新的 C-Cross attempt；
- 不覆盖已有 validation matrix；
- 不把 scaffold 失败记成某个 C scenario 失败；
- 不消耗 8 次 C-Cross repair budget；
- 不生成 `repair_required` C-Cross convergence。

### 8.3 layout-only 例外

`--scaffold-layout-only` 是 untouched scaffold 唯一允许的 C-Cross 工具模式。它继续只生成 scaffold build/layout 证据，不生成正式 matrix 或 attempt。

`--restore-best` 不作为绕过入口：它必须继续满足现有“上一条正式 attempt 已记录 regression、best-known 快照存在且 hash 可验证”的前置条件。恢复完成后，下一次 full confirmation 仍须重新通过 IMPLEMENT 预检。

不能通过传 `--mode build`、`--mode layout` 或 `--mode link` 绕过 IMPLEMENT gate；除受约束的 `--restore-best` 恢复分支外，只要不是显式 `--scaffold-layout-only`，都必须先通过实现审计。

## 9. 状态、轮次与报告语义

### 9.1 阶段状态

| 阶段状态 | 机器含义 | 允许动作 |
|---|---|---|
| `layout_ready` | scaffold 可编译且 ABI layout 检查完成 | 只能进入初始实现 |
| `implementation_required` | 当前 audit 有确定 scaffold residue，且仍有实现补漏机会 | 返回 IMPLEMENT；禁止 C-Cross 和报告 |
| `ready_for_verify` | 当前 audit 与 IMPLEMENT gate 均通过 | 进入正式 C-Cross checkpoint |
| `failed_final`，`failed_stage=IMPLEMENT` | 有界初始实现与一次 audit 定向补漏后，fresh audit 仍失败 | 只生成明确的 IMPLEMENT 未完成失败报告 |

`layout_ready` 不是 IMPLEMENT 成功；`implementation_required` 也绝不能带失败进入正常报告链。

### 9.2 有界实现补漏

为避免上下文无限增长和弱模型后期整体重构，采用以下预算：

1. scaffold 后完成一轮动态初始实现；该轮可拆为多个新的短 session；
2. 运行一次全量 implementation audit；
3. 若失败，只允许一轮 audit finding 定向补漏；该轮仍可按 finding cluster 使用多个短 session；
4. 再运行一次不修改源码的 fresh audit confirmation；
5. 仍失败时形成 `failed_final`，不得继续无限接力或转入整体重构。

初始实现和 IMPLEMENT 补漏不计入 C-Cross repair budget。只有 IMPLEMENT gate 通过后产生的真实语义失败，才使用现有 8 次 C-Cross repair。

为了区分 `implementation_required` 和 `failed_final`，可维护最小的 `logs/trace/implementation-attempts.jsonl`，但它只能记录结果证据：

- attempt id 与种类：`checkpoint`、`repair`、`confirmation`；
- 当前 Rust source manifest；
- implementation audit input fingerprint；
- finding code 与数量；
- repair 前后实际变化的 Rust 文件。

它不记录 agent 回执、prompt、nonce、task packet 或 ownership transaction，也不控制任务派发。只有存在一次真实源码修改的 repair，且最新 confirmation 与当前源码指纹一致、audit 仍失败时，才能形成 IMPLEMENT `failed_final`。

### 9.3 IMPLEMENT 失败报告

IMPLEMENT `failed_final` 不进入正常 TEST_AND_REPORT 验证链，而进入只写真实失败的早期终态：

- `result/output.md` 写 `STATUS: FAILED`；
- 明确写 `failed_stage: IMPLEMENT`；
- 列出剩余 stub symbol、placeholder module 和 audit finding；
- C-Cross、Rust tests、unsafe ratio 标为“未执行”，不能填 0、pass 或估算值；
- `FINAL` gate 根据 fresh implementation audit 和 attempt evidence 验证该失败报告。

这样既保证比赛运行始终有结果，也不会把未实现工程伪装成“C-Cross 已验证但有少量失败”。

## 10. 修改范围

| 文件 | 实际修改 |
|---|---|
| `02_02/work/tools/core_impl_audit.py` | 增加输入指纹、冻结 ABI signature 检查、稳定结果 schema；保留现有 scaffold residue 检查 |
| `02_02/work/tools/gate.py` | 增加 `IMPLEMENT` stage；重新计算并校验最新 audit；支持阶段化 IMPLEMENT `failed_final` 的最终真实性检查 |
| `02_02/work/tools/c_cross_validate.py` | 所有非 layout-only 路径在写 attempt 前调用 IMPLEMENT 预检并 fail-fast |
| `02_02/INSTRUCTION.md` | 在 scaffold layout 与 full C-Cross 之间加入实现审计、IMPLEMENT gate、返回规则和阶段终态 |
| `02_02/work/agents/flashdb-orchestrator.md` | 明确初始实现动作不可跳过；按 audit finding 自动继续有界实现；禁止未过 gate 进入 VERIFY |
| `02_02/work/subagent/rust-implementer.md` | 补充初始实现 task 的动态输入和 audit finding 补漏边界；继续保持角色可选和短生命周期 |
| `02_02/work/tools/report_writer.py` | 支持 `failed_stage=IMPLEMENT` 的早期真实失败报告，不伪造未运行指标 |
| `design_doc/stages/05-generate-rust-scaffold.md` | 明确 layout-only 后的下一动作是实现与审计，不是 full C-Cross |
| `design_doc/stages/06-rewrite-core-modules.md` | 恢复结果型 implementation audit/gate，仍不恢复旧 controller/worker 事务 |
| `02_02/tests/test_conversion_system.py` | 增加工具、合同顺序、gate、C-Cross fail-fast 和终态回归测试 |

明确不修改：

- scaffold generator 的“只生成骨架”职责；
- 平台 C 输入；
- 任何预生成 `flashDB_rust/` 答案；
- C-Cross 动态 scenario 发现和 8 次语义 repair 预算；
- Q9 已删除的 controller、packet、receipt 和固定 worker 机制。

## 11. 回归测试与验收标准

### 11.1 实现审计测试

1. untouched scaffold：layout-only 通过，implementation audit 失败；
2. 只删除 FFI marker：仍因函数体指纹或直接中性返回失败；
3. 只修改注释、格式和空白：仍失败；
4. 只剩一个中性 FFI 函数：失败并准确报告 symbol；
5. 只剩一个 placeholder module：失败并准确报告动态 module；
6. 删除生成模块或导出 symbol：失败；
7. 修改冻结 ABI 签名：失败；
8. manifest 与 design 不匹配：失败；
9. 用真实 Rust 路径替换所有 stub 且 ABI 不变：audit 通过；
10. 审计结果对应旧 Rust 源码：IMPLEMENT gate 判定 stale 并失败。

### 11.2 C-Cross 前置测试

1. untouched scaffold 调用 `--mode full`：非零退出；
2. 被拒绝前后 `attempts.jsonl` 行数不变；
3. 被拒绝前后已有 `validation-matrix.json` 内容不变；
4. 被拒绝不会生成某个 scenario 的 fail/not_run；
5. `--scaffold-layout-only` 在同一 scaffold 上仍可正常执行；
6. IMPLEMENT gate 通过后，正式 C-Cross 能进入原有 compile/link/run 流程；
7. IMPLEMENT 预检不消耗 C-Cross repair 次数。

### 11.3 合同顺序测试

对 `INSTRUCTION.md` 和 orchestrator 断言以下顺序：

```text
generate scaffold
< scaffold-layout-only
< 初始实现
< core_impl_audit.py
< gate.py --stage IMPLEMENT
< c_cross_validate.py --mode full
```

同时断言：

- 实现动作必须完成，但 rust-implementer 调用记录不是 gate 证据；
- task 范围来自动态 manifest/design/finding，不写死模块名或数量；
- `implementation_required` 不得进入 VERIFY、unsafe 或报告；
- IMPLEMENT `failed_final` 的报告将未运行项写成“未执行”；
- 只有 current audit confirmation 才能支持 IMPLEMENT `failed_final`。

### 11.4 总体验收

完成实现后至少执行：

```bash
python3 -B -m unittest 02_02/tests/test_conversion_system.py -v
python3 -B -m unittest 02_02/tests/test_workflow_optimizations.py -v
python3 -B -m unittest discover -s 02_02/tests -p 'test*.py' -v
```

验收不要求本地样例 C-Cross 全部通过；它要求证明：scaffold 无法越过 IMPLEMENT、真实实现可以进入原有验证链、所有状态与报告都基于最新机器证据。

## 12. 实施顺序

1. 为现有 `core_impl_audit.py` 补回归 fixture，固定当前可检测行为；
2. 增加 audit input fingerprint 和冻结 ABI signature 检查；
3. 在 `gate.py` 增加 IMPLEMENT stage，并先完成 gate 单元测试；
4. 在 `c_cross_validate.py` 接入前置审计，验证拒绝路径零副作用；
5. 更新 `INSTRUCTION.md`、orchestrator、rust-implementer 和阶段文档；
6. 增加最小 IMPLEMENT attempt/terminal evidence 与早期失败报告；
7. 运行两组定向测试和全量回归；
8. 使用动态 fixture 演示“layout-only 通过但 full 被拒绝”和“实现后 full 可进入”两条路径。

实施过程中不得先改文档让流程看似正确、再遗留工具绕过；必须以 `core_impl_audit → IMPLEMENT gate → C-Cross preflight` 的顺序完成机器链路。

## 13. 与既有设计的关系

### 13.1 Q7

Q7 已证明空 stub 会导致真实 C-Cross 失败，并引入 `core_impl_audit.py`。本设计复用该能力，但不恢复 Q7 当时的事务式 REWRITE controller。

### 13.2 Q9

Q9 的“删除过程编排、保留真实验证”原则继续有效。本次新增的是一个直接回答“当前 Rust 是否仍为 scaffold”的结果门禁，不是新的平行控制面。最小 attempt evidence 只用于区分 `implementation_required` 与阶段化 `failed_final`，不能成为 agent 调度系统。

### 13.3 Q11

Q11 的上下文边界继续有效。初始实现和 audit 补漏必须按动态文件/依赖/finding 簇使用新的短 session，不恢复一个长生命周期 implementer，也不把完整 C/Rust 工程塞进上下文。

### 13.4 Q12

Q12 的角色收敛继续有效：`rust-implementer` 保留但默认可选。这里强制的是“真实实现 + 当前 audit/gate”，不是“必须成功调用某个角色”。

### 13.5 Q6 与 Q10

Rust 测试为空、mapping 未生成真实 test body、Cargo 0 tests 假通过属于更下游的独立问题。IMPLEMENT gate 通过不能替代 test-migrator、placeholder、Cargo execution 和 semantic consistency 门禁；它只保证测试阶段面对的不是 untouched production scaffold。

## 14. 实施记录

2026-07-16 已完成：

1. `core_impl_audit.py` 升级为 schema v2，增加当前 Rust source manifest、输入指纹、FFI marker、scaffold body、直接中性返回、placeholder、纯 cosmetic 修改、动态导出完整性和冻结 ABI signature 检查。
2. 新增最小 `implementation-attempts.jsonl` 结果证据；每个 scaffold baseline 只允许一个 checkpoint、一个有真实源码变化的 repair 和一个无源码变化的 confirmation。
3. `gate.py` 增加 `IMPLEMENT` stage，并重新计算当前 audit，拒绝 stale JSON、stale build/layout 和伪造轮次；audit 或 build/layout 在一次补漏后仍失败，可形成 `failed_stage=IMPLEMENT` 的 `failed_final`。
4. `c_cross_validate.py` 的所有正式验证模式在写 matrix/attempt 前执行 IMPLEMENT preflight；首次 checkpoint 要求当前 implementation attempt 与 build/layout，C-Cross 链建立后的语义 repair 使用自身 source manifest/changed-file 合同并重审当前 scaffold residue，避免被初始实现指纹错误阻断。untouched/stale scaffold 不会覆盖既有 matrix、追加 attempt 或消耗 C-Cross repair budget；`--scaffold-layout-only` 和受既有 regression 证据约束的 `--restore-best` 保持特殊分支。
5. `report_writer.py` 和 FINAL gate 支持 IMPLEMENT 早期终态；报告明确写出 `C-Cross/Rust tests/unsafe ratio: not_run`，不再用 0、pass 或估算值填充未执行指标。
6. 更新 `INSTRUCTION.md`、orchestrator、rust-implementer 和阶段文档；强制真实实现和机器结果，不强制 subagent 调用记录。
7. 新增 untouched scaffold、marker-only、cosmetic-only、中性 FFI、placeholder、冻结签名、stale audit/layout、真实 repair/confirmation、build failure 终态、C-Cross 零副作用拒绝和合同顺序测试。

验证结果：

```text
python3 -B -m unittest 02_02/tests/test_conversion_system.py -v
39 tests passed

python3 -B -m unittest 02_02/tests/test_workflow_optimizations.py -v
5 tests passed

python3 -B -m unittest discover -s 02_02/tests -p 'test*.py' -v
44 tests passed
```
