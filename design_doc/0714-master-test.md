# C2Rust 五轮转换测试问题复盘与改进建议报告

- **报告日期**：2026-07-15
- **原始测试日期**：2026-07-14
- **项目**：`02_02/flashDB_rust`
- **Pipeline**：12 阶段 C→Rust 自动转换流水线
- **分析范围**：五轮运行结果、阶段 Gate、c-cross、Rust-native 测试、评分聚合及工作区状态
- **目标**：完整保留原始报告中的所有问题，并对问题的证据边界、根因关系、修复优先级和预期效果进行重新分析

---

## 1. 执行摘要

本次五轮转换的最终得分为 **29/100**，其中：

| 评分项 | 满分 | 得分 |
|---|---:|---:|
| 准确性 | 30 | 0 |
| 稳定性 | 30 | 0 |
| 客观总分 | 60 | 0 |
| 泛用性 | 20 | 13 |
| 规范性 | 10 | 6 |
| 性能 | 10 | 10（默认） |
| 主观总分 | 40 | 29 |
| **总分** | **100** | **29** |

最终客观分归零的直接原因是：

> 五次运行全部以 `executor_status: timeout` 结束，Pipeline 均未进入可被正式聚合器采纳的完成状态，最终投票器将 24 个 case 全部判定为失败。

但从运行内部结果看，系统并非完全没有转换能力：

- 五轮内部 `scoring accuracy` 均为 `5/24`
- c-cross 最佳单轮达到 `17/24`
- 以 c-cross 多数投票粗略计算，有 13 个 case 至少在 3 轮中通过
- 有 6 个 case 在 5 轮中全部通过
- Run 1/4 的 Rust-native integration tests 经修复后达到 `10/10 PASS`

因此，本项目当前的核心矛盾不是单纯的“Rust 代码完全不可用”，而是以下三类问题叠加：

1. **Pipeline 无法在预算内有界完成**
2. **控制面协议和 Gate 格式问题大量消耗时间，并阻止有效结果进入下一阶段**
3. **Rust 实现和测试迁移仍存在真实的语义、ABI、状态管理和覆盖不足问题**

修复顺序必须是：

> 先保证 Pipeline 必定完成并产出可评分结果，再消除控制面空转，之后修复测试映射和 Rust 核心功能。

如果只继续增强 Rust repair，但仍然 timeout，客观分仍可能保持为 0。

---

## 2. 结果解读与证据边界

### 2.1 c-cross 通过率不等于正式准确性得分

原始报告根据五轮 c-cross 投票计算出：

- 多数通过：13/24
- 五轮稳定通过：6/24

该结论只能表示：

> 若仅按 c-cross 每个 case 的 pass/fail 做多数投票，13 个 case 至少在 3 轮中通过，6 个 case 在 5 轮中全部通过。

它不能直接推导正式准确性为 `13/24`，因为正式评分还可能检查：

- Rust 测试是否真实存在
- Rust 测试与 C 测试是否一一对应
- Rust 测试是否包含完整的关键断言
- 测试是否调用正确的 Rust API
- 是否存在弱断言、占位断言或场景合并
- 测试名称、case ID、调用链和断言语义是否一致

现有证据已经表明：

> c-cross 在部分 Run 中达到 15/24 或更高，但内部 scoring accuracy 始终只有 5/24。

因此后续报告和系统实现中必须明确区分：

| 指标 | 含义 |
|---|---|
| `c_cross_pass_count` | C 测试通过 Rust 实现的 case 数 |
| `rust_native_pass_count` | Rust 测试自身通过数 |
| `test_consistency_count` | Rust 测试与标准 C case 语义一致的数量 |
| `scoring_accuracy_count` | 正式评分器最终认可的准确性 case 数 |

---

### 2.2 Rust integration tests 10/10 PASS 不代表 24 个标准场景正确

Run 1/4 在 BUILD_TEST_REPAIR 后实现了 `10/10 integration tests PASS`，但当前 Rust 测试只有 10 个，而标准 C 场景有 24 个。

并且存在：

- 多个 C case 被合并成一个 Rust test
- 11 个 C case 没有独立 Rust 对应
- 部分 Rust test 只覆盖成功路径
- c-cross 仍停留在 8/24

因此，`10/10 PASS` 只能说明：

> 现有 10 个 Rust 测试所覆盖的有限路径在修复后通过。

不能证明：

- 24 个标准场景全部正确
- C ABI 行为正确
- blob、GC、scale-up、TSDB query 等未覆盖功能正确
- 指针、生命周期和内存布局问题已经全部消除

---

### 2.3 `cargo fmt` 不是语义签名变化的充分根因

原始报告中提到：

> cargo fmt 会修改 frozen signatures。

该结论需要拆分：

1. 如果 frozen signature Gate 使用原始文本比较，`cargo fmt` 的换行、空格、属性布局变化可能导致**文本误判**
2. 如果参数类型、参数数量、返回值或 ABI 真实变化，则是 agent 修改了接口，`cargo fmt` 不是根因

因此准确描述应为：

> frozen signature 检查可能存在文本级比较缺陷，同时个别 Run 也确实发生了 FFI 参数类型或函数签名被修改的问题。

建议使用 Rust AST、`syn` 或规范化签名模型进行比较。

---

### 2.4 `prepare_workspace()` 删除目录需区分正常隔离和错误重置

原始报告将 Run 1/4 中 `flashDB_rust` 目录不存在归因于 `prepare_workspace()` 删除目录。

需要进一步确认删除时机：

- 新 Run 开始时清理旧目录：属于正常隔离
- 同一 Run 的 retry/resume/repair 中重新清理：属于严重错误
- VERIFY 回退到 REWRITE 时清理：会丢失有效成果
- workspace recovery 恢复到错误基线：会造成状态回退

因此修复方向不应是简单地“永远不删除”，而应是：

- 新 Run 初始化允许清理
- 同一 Run 内重试和恢复禁止重新初始化
- 每轮使用独立 workspace
- 通过 `run_id`、`workspace_generation` 和 checkpoint 防止误删

---

## 3. 五轮运行总体分析

| 维度 | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|---|---:|---:|---:|---:|---:|
| 最远阶段 | MIGRATE_TESTS | VERIFY_RUST | VERIFY_RUST | MIGRATE_TESTS | VERIFY_RUST |
| REWRITE gate 尝试 | 4 | 4 | 2 | 4 | 3 |
| VERIFY gate 尝试 | 7 | 4 | 5 | 7 | 0 |
| c-cross 通过 | 8/24 | 15/24 | 14/24 | 8/24 | 15/24 |
| c-cross 失败 | 9 | 5 | 6 | 9 | 9 |
| c-cross not_run | 7 | 4 | 4 | 7 | 0 |
| scoring accuracy | 5/24 | 5/24 | 5/24 | 5/24 | 5/24 |
| flashDB_rust 目录 | 不存在 | 存在 | 存在 | 不存在 | 存在 |
| Repair 轮次 | 2 | 3 | 2 | 2 | 0 |
| Pipeline 最终状态 | pending | pending | pending | pending | pending |

### 3.1 总体问题

1. **五轮均未完成**
   - 所有 Pipeline 最终状态均为 `pending`
   - executor 均 timeout
   - REPORT_AND_VERIFY / SCORING 未被正式执行

2. **结果未稳定使用最佳尝试**
   - Run 3 最高达到 16/24，最终为 14/24
   - Run 5 最高达到 17/24，最终为 15/24
   - 表明系统可能使用最后一次结果，而不是 best-so-far

3. **运行之间存在隔离和复制异常**
   - baseline 文件数从 88 到 265
   - Run 4 与 Run 1 的 nonce、attempt、receipt 完全一致
   - Run 4 实际上是 Run 1 的 workspace 副本，降低了五轮独立性的可信度

4. **Repair 调度不可靠**
   - `test-migrator` 和 `repairer` 注册但未稳定 dispatch
   - Run 5 已生成 repair plan，但 repair 从未真正执行
   - 部分 repair 修改了代码，但 receipt/diff 未记录，Gate 判定为无修改

---

## 4. 逐阶段问题与建议

## 4.1 阶段 1：BOOTSTRAP

### 当前表现

五轮均隐式通过，无独立 Gate。

### 保留问题

- 未发现直接功能问题
- 但该阶段没有对运行预算、run_id、workspace generation、checkpoint 目录做强校验

### 分析建议

建议在 BOOTSTRAP 显式初始化：

- `run_id`
- `workspace_generation`
- 全局 deadline
- 每阶段预算
- best checkpoint 目录
- stage receipt schema 版本
- 当前 Git baseline commit

避免后续阶段依赖不稳定的隐式状态。

---

## 4.2 阶段 2：INIT_WORKSPACE

### 当前表现

五轮 Gate 均 PASS。

### 保留问题 1：Input baseline files 数量不一致

| Run | baseline files |
|---|---:|
| Run 1/4 | 130 |
| Run 2 | 88 |
| Run 3/5 | 265 |

### 风险

- workspace 输入不一致
- 忽略规则或路径解析不稳定
- 可能混入上轮产物、日志或构建缓存
- 五轮不是在相同基线下独立运行

### 建议

1. 在初始化时生成输入清单及 hash：
   - 相对路径
   - 文件大小
   - SHA-256
2. 五轮必须使用同一个 baseline manifest
3. 将输出目录、target、日志、checkpoint 与输入目录物理隔离
4. Gate 校验 manifest hash，而不是只统计文件数

---

### 保留问题 2：`test-migrator` 和 `repairer` 注册但未正确 dispatch

### 风险

- agent-registry 与 orchestrator 实际调度脱节
- repair plan 只生成不执行
- Pipeline 状态显示阶段已准备，但没有实际工作发生

### 建议

为每个 agent 引入明确状态：

```text
registered -> queued -> dispatched -> running -> completed/failed/skipped
```

Gate 必须校验：

- 是否存在 dispatch 记录
- 是否存在 agent completion receipt
- plan 是否被消费
- 未执行时是否有明确 skip 原因

不能用“已注册”替代“已执行”。

---

## 4.3 阶段 3：READ_C_PROJECT

### 当前表现

五轮 Gate 均 PASS。

### 保留问题 1：Run 2 路径解析失败并通过状态篡改恢复

出现：

- `environment path resolution failure`
- `stage-abort`
- `state_tampering_restored`

### 风险

- 环境路径依赖当前工作目录
- 恢复逻辑可能直接改 workflow state，而不是重新执行失败步骤
- 状态恢复后产物是否完整无法保证

### 建议

1. 所有路径使用 workspace-root 相对路径
2. 运行时解析为 canonical absolute path
3. stage 恢复必须基于产物校验，不允许仅修改状态字段
4. `state_tampering_restored` 应视为高风险事件，必须触发完整重验

---

### 保留问题 2：头文件和测试文件数量轻微不一致

- 头文件 7~8
- 测试文件 6~7

### 风险

- glob 规则不一致
- 条件编译文件遗漏
- symlink、generated header 或 fixture 被不同 Run 处理不同

### 建议

- 固化扫描规则
- 输出 source inventory
- 标记每个文件为何被纳入或排除
- 对核心目录设置 minimum expected file set

---

## 4.4 阶段 4：BUILD_C_MODEL

### 当前表现

五轮 Gate 均 PASS，但 Run 2 的模型规模明显较小。

| 字段 | Run 1/3/4/5 | Run 2 |
|---|---:|---:|
| public_functions | 31 | 31 |
| all_functions | 281 | 256 |
| structs | 54 | 48 |
| typedefs | 24 | 23 |
| enums | 6 | 6 |
| macros | 165 | 165 |
| abi_layouts | 12 | 12 |
| unresolved_types | 0 | 0 |

### 保留问题：C 模型提取不稳定

Run 2：

- 少 25 个 function
- 少 6 个 struct
- 少 1 个 typedef

### 风险

- 后续 Rust 设计基于不完整模型
- 某些 internal helper、状态结构或宏语义遗漏
- 虽然 public API 相同，但实现语义可能缺失
- `unresolved_types=0` 不能证明模型完整

### 建议

1. 使用确定性预处理参数和 compile_commands
2. 固定宏、include path 和 target
3. 对模型生成结果做内容 hash
4. 比较符号集合，而不仅是数量
5. 关键 internal function/struct 缺失时 Gate 应警告或重试
6. 为当前输入动态提取的全部标准 case 建立依赖符号闭包，确保相关函数和类型全部进入模型

---

## 4.5 阶段 5：DESIGN_RUST_API

### 当前表现

五轮结果一致，是最稳定阶段：

- 5 个核心模块
- 31 个 C ABI facade
- 12 个 FFI struct
- crate 名一致
- 9 条 implementation requirements

### 保留问题

原始报告认为无显著问题，但仍存在潜在风险：

1. API 设计一致不代表实现义务足够细
2. 9 条 implementation requirements 可能不足以覆盖：
   - 指针所有权
   - 生命周期
   - C 状态机
   - 位操作
   - CRC
   - 迭代边界
   - GC 行为
3. 设计阶段没有绑定当前输入全部测试场景的可验证义务

### 建议

将每个标准 case 转换为可追踪的 semantic obligations，例如：

- required calls
- preconditions
- state transitions
- expected return codes
- memory/ABI invariants
- postconditions
- observable side effects

API 设计输出必须能被 REWRITE 和 MIGRATE_TESTS 共同消费。

---

## 4.6 阶段 6：GENERATE_RUST_SCAFFOLD

### 当前表现

五轮均 PASS：

- Cargo check PASS
- fmt PASS
- layout check PASS
- implementation audit 报告 0 findings

### 保留问题 1：Scaffold 全是 stub，但 Gate 仍 PASS

存在 `todo!()` 或空实现，但 Gate 只检查：

- 格式
- 构建
- layout

### 风险

- Gate 给出“通过”的假象
- 真正实现压力全部推迟到 REWRITE
- implementation audit 没有检测 stub，说明审计规则失效或范围不足

### 建议

Scaffold 阶段可以允许 stub，但 Gate 必须明确状态：

```text
PASS_SCAFFOLD_ONLY
```

并输出：

- stub 函数数
- todo 数
- unimplemented 数
- panic-only 实现数
- default-return 实现数

不得把 scaffold build success 表述为 implementation pass。

---

### 保留问题 2：Gate 盲区

### 建议

增加 spot-check：

- 31 个 facade 是否全部存在
- frozen signature 是否正确
- layout 是否正确
- 是否仍为 stub
- 是否有核心实现文件
- 是否形成下一阶段 bounded task packet

---

## 4.7 阶段 7：REWRITE_CORE_MODULES

这是第一个严重瓶颈阶段。

### 保留问题 1：frozen external signature 被修改

出现于 Run 2/5，典型为 `fdb_kv_del`。

### 风险

- ABI 兼容性破坏
- C 测试链接或调用错误
- 参数宽度、const、pointer level 变化

### 建议

- scaffold 生成后保存 canonical ABI manifest
- 使用 AST 解析实际签名
- Gate 比较函数名、ABI、参数类型、返回值
- 格式变化不应触发失败
- 真实签名变化必须阻止进入 VERIFY

---

### 保留问题 2：`changed_files` 为空

出现于 3 个 Run，是最常见 Gate 阻塞原因。

### 根因

- agent 自报元数据不可靠
- batch receipt 与真实 Git diff 脱节
- 后续 6 个 batch 可能是 no-op 或仅元数据未填

### 建议

`changed_files` 必须由 orchestrator 自动计算：

```bash
git diff --name-only <stage_start_commit>..<stage_end_commit>
```

Agent 可以提供 expected files，但不应作为事实来源。

---

### 保留问题 3：cumulative owner diff 不匹配

### 风险

- receipt 声称修改文件与实际修改不一致
- ownership 规则和多人/多 agent 修改冲突
- 可能误阻塞有效代码

### 建议

- Git diff 为事实源
- owner 信息只用于审计
- 对非越权修改给 warning
- 仅在修改冻结文件或不允许目录时 hard fail

---

### 保留问题 4：typed parameter 未保留

Run 3 中 `fdb_blob_make.value_buf` 类型丢失。

### 风险

- 指针语义错误
- const/mut 丢失
- ABI 调用错误
- blob 长度损坏可能与此类问题相关

### 建议

- 生成 ABI manifest
- 为每个参数记录：
  - C 类型
  - Rust FFI 类型
  - pointer depth
  - constness
  - size/alignment
- 编译前后自动比较

---

### 保留问题 5：task packet 格式错误

### 风险

- 工作已完成，但因 packet ID 或 bounded reference 格式错误被拒绝
- 控制面格式优先于数据面结果

### 建议

- packet schema 采用版本化 JSON Schema
- 缺失非关键字段自动补齐
- packet ID 由 orchestrator 生成
- agent 只消费 packet，不自行构造关键标识

---

### 保留问题 6：REWRITE no-op 重试

Run 1/4 各有 3 轮无有效修改的重试。

### 风险

- 大量 token 和时间浪费
- 相同错误重复出现
- 进入 VERIFY 的时间被挤压

### 建议

1. diff 为空立即判定 no-op
2. 不重新调用同一 agent 同一 prompt
3. 最多允许一次 metadata repair
4. 第二次无修改直接跳过并进入下一阶段或 fallback
5. 记录 no-op 原因并扣减该 agent 的后续预算

---

## 4.8 阶段 8：VERIFY_RUST_WITH_C_TESTS

这是 Pipeline 的主要卡点。

### 保留问题 1：c-cross 反复运行但无明确收敛策略

- Run 1/4：7 次尝试，始终 8/24
- Run 2：12 次尝试，停滞 15/24
- Run 3：31 次尝试，最高 16/24，最终 14/24
- Run 5：17 次尝试，最高 17/24，最终 15/24

### 根因

- 没有最大尝试次数
- 没有连续无提升退出条件
- 没有 best checkpoint
- repair 后未限定受影响 case
- 局部结果回退后仍覆盖较优结果

### 建议

- 全量 c-cross 最大 5~8 次
- Repair 最大 2~3 轮
- 连续 2 次 best pass count 无提升，停止优化
- 保存 best source/test/result checkpoint
- 最终报告使用 best，不使用 last

---

### 保留问题 2：KVDB runner 段错误导致 not_run

Run 1/4 中：

- exit `-11`
- 后续 7 个 case not_run

### 风险

- 一个 case 崩溃污染整套结果
- not_run 不是功能失败，而是执行隔离失败

### 建议

每个标准 case 使用独立进程：

- 独立 init
- 独立临时目录
- 独立超时
- 捕获 signal/exit code
- 崩溃后继续后续 case
- 统一生成 machine-readable result

---

### 保留问题 3：`isolation-results.jsonl` 缺失

所有 Run 都出现。

### 根因

- runner 与 Gate 产物契约不一致
- isolation 结果可能只存在日志，没有规范落盘
- Gate 要求由 agent 生成本应由系统生成的事实数据

### 建议

由 c-cross runner 原生生成：

```text
case_id
suite
attempt_id
exit_code
signal
duration
result
stdout_path
stderr_path
source_checkpoint
```

Gate 不应依赖 agent 手写 isolation receipt。

---

### 保留问题 4：ISOLATE_SCENARIOS 必须消费 pending 记录

### 风险

- 状态机对记录消费顺序要求过严
- 实际隔离已经执行，但 pending bookkeeping 不匹配
- 重试时容易出现重复消费或未消费

### 建议

- pending queue 使用唯一 task ID
- runner 开始时原子 claim
- 完成时原子 ack
- Gate 根据 task 状态校验
- 已有结果可幂等复用，不强制重新执行

---

### 保留问题 5：REPAIR_RUST 必须修改至少一个文件

实际存在：

- repair 修改了文件但 receipt 未记录
- repair plan 生成但未 dispatch
- 有时 repair 可能合理地判断无需修改

### 建议

将 repair 结果分为：

```text
modified
no_change_needed
blocked
failed
```

只有声称 `modified` 时才要求 diff 非空。  
diff 必须由 orchestrator 计算，而不是 agent 自报。

---

### 保留问题 6：intermediate c-cross 要求 all-suite scope

### 分析

局部回归和全量回归用途不同：

- 局部回归：快速验证 repair 是否修复目标 case
- 全量回归：检查回归和更新 best score

如果所有 intermediate 都强制 all-suite，会浪费时间；如果只做局部又直接用于最终计分，会产生不完整结果。

### 建议

明确两类模式：

```text
targeted verification: 仅验证受影响 case，不参与最终评分
full verification: 当前输入的全量 case，可更新 best checkpoint
```

---

### 保留问题 7：REANALYZE_C_MODEL 要求确切一个确认尝试

### 风险

- 状态机过度依赖“次数格式”
- 合理的 0 次或多次重分析无法表达
- 格式问题阻止真实修复

### 建议

允许：

- `not_needed`
- `completed_once`
- `completed_multiple_with_reason`
- `failed`

关键是产物版本和依赖关系，不是硬编码“恰好一次”。

---

### 保留问题 8：VERIFY 阶段不允许修改源码

Run 3 因此两次 stage-abort。

### 根因

- VERIFY 和 REPAIR 边界设计冲突
- repair agent 在 VERIFY 流程中被调用，但状态机又禁止源码修改

### 建议

引入受控子事务：

```text
VERIFY
  -> DIAGNOSE
  -> REPAIR_TRANSACTION
  -> TARGETED_VERIFY
  -> FULL_VERIFY
```

只有 `REPAIR_TRANSACTION` 可以修改源码，完成后提交 checkpoint，再回到只读 VERIFY。

---

### 保留问题 9：Run 5 repair plan 生成但未 dispatch

### 建议

plan 创建必须和 dispatch 绑定：

- plan 状态 `created`
- orchestrator 自动转 `queued`
- budget 足够则立即 dispatch
- budget 不足则标记 `skipped_due_to_budget`
- 不允许无终态 plan

---

## 4.9 阶段 9：MIGRATE_TESTS

仅 Run 1/4 到达。

### 保留问题 1：24 个 C case 只迁移为 10 个 Rust test

### 风险

- 标准 case 粒度丢失
- 正式评分无法做一一对应
- 某个合并测试失败时无法判断具体 case
- 某个合并测试通过也不能证明每个子 case 都被正确验证

### 建议

强制：

- 当前输入动态提取的 N 个 case 对应 N 个 Rust test entry
- 允许共享 fixture/setup
- 禁止共享 test entry
- 每个 test 保存标准 case ID

---

### 保留问题 2：多个 C 测试被合并

例如：

- create + set + get
- create blob + get blob
- del + del blob

### 风险

- 独立语义被压缩
- 前置步骤失败会掩盖后续步骤
- 无法与 scoring consistency 对齐

### 建议

每个标准 case 独立测试，公共操作提取为 helper，但断言必须属于对应 case。

---

### 保留问题 3：11 个 C case 无 Rust 对应

### 建议

生成 `test_case_mapping.json`，要求：

- 当前输入动态提取的 N 个 case 全覆盖
- 无重复映射
- 无遗漏映射
- 映射包含 C source、Rust test、required calls、required assertions

Gate 在迁移阶段直接检查 coverage=N/N，N 从当前 `scorer_standard_cases` 推导。

---

### 保留问题 4：测试语义不完整

现有 Rust 测试通过数为 5/10，后修复到 10/10，但 scoring 始终 5/24，说明测试迁移不仅是数量不足，还存在一致性问题。

### 建议

从 C 测试提取：

- 初始化条件
- API 调用顺序
- 返回码
- 状态变化
- 输出值
- 边界值
- cleanup
- error path

禁止：

- `assert!(true)`
- 只验证“不 panic”
- 只验证返回值非空
- 删除关键 control 调用
- 用一个更宽松断言替代多个精确断言

---

## 4.10 阶段 10：BUILD_TEST_REPAIR

仅 Run 1/4 到达。

### 已修复问题

1. `get_db_dir_name` 指针错误
2. CString 生命周期
3. 控制码常量错误
4. `repr(C)` padding offset
5. `while(status_num--)` 语义 off-by-one
6. `write_kv` CRC 偏移错误

### 保留问题 1：这些问题发现过晚

这些均属于：

- ABI
- FFI
- C 语义转换
- 常量值
- 内存布局

理论上应在 BUILD_C_MODEL、DESIGN_RUST_API、SCAFFOLD 或 REWRITE Gate 中被更早发现。

### 建议

前移自动检查：

- C/Rust layout cross-check
- 常量值导入
- pointer-depth check
- lifetime ownership annotation
- C idiom translation lint
- CRC golden test

---

### 保留问题 2：修复仅改善 Rust-native 测试，未改善 c-cross

### 分析

可能原因：

1. Rust tests 覆盖的不是 c-cross 失败路径
2. c-cross 调用的是另一套 facade 或状态初始化路径
3. 修复只影响 test helper，不影响 ABI 实现
4. c-cross workspace 未使用修复后的代码
5. best/last checkpoint 或目录状态错误

### 建议

每个 repair 必须记录：

- 修改文件
- 目标 case
- 预期修复路径
- targeted Rust test
- targeted c-cross case
- full regression result
- 使用的 source commit/hash

避免 Rust-native 和 c-cross 使用不同产物。

---

## 4.11 阶段 11-12：REPORT_AND_VERIFY / SCORING

### 保留问题 1：无 Run 正式到达

虽然存在报告文件，但 workflow state 仍停留在前序阶段，说明：

- 报告可能由外部脚本生成
- 不属于正式 Pipeline terminal transition
- 评分器不认可该结果

### 建议

无论前序成功或失败，最终必须进入：

```text
completed
completed_with_partial_failures
```

并生成统一 final manifest。

---

### 保留问题 2：timeout 导致结果全归零

### 风险

- 部分有效结果完全丢失
- 优化越久，反而越可能得 0
- 系统激励与比赛目标冲突

### 建议

实现 deadline degradation：

1. 到达软截止时间：停止新 repair
2. 执行一次 final full verification
3. 输出 best result
4. 为当前输入的全量 case 生成 final matrix
5. 进入 completed_with_partial_failures

即使 executor 外层强制停止，也应周期性保存 partial result。

---

## 5. c-cross 跨 Run 结果分析

### 5.1 五轮稳定通过的 6 个 case

- kvdb_init
- kvdb_init_check
- tsdb_init_ex
- tsl_clean
- tsl_clean__2
- tsdb_deinit

说明基础初始化、清理和部分生命周期路径相对稳定。

### 5.2 多数通过但不稳定的 7 个 case

- change_kv
- change_kv_blob
- create_kv
- del_kv
- del_kv_blob
- tsl_append
- tsl_iter_by_time

这些 case 已具备部分实现能力，优先通过：

- 消除随机状态污染
- 修复 workspace/checkpoint 使用
- 独立 case 进程
- 固化初始化和 teardown

可能较快提升稳定性。

### 5.3 主要失败 case

- create_kv_blob
- tsl_iter
- gc
- gc2
- scale_up
- tsl_iter_by_time_1
- github_issue_249
- kvdb_deinit
- kvdb_set_default
- tsl_query_count
- tsl_set_status

可分为四类：

| 类别 | Case |
|---|---|
| Blob/内存布局 | create_kv_blob、github_issue_249 |
| TSDB iterator/query/status | tsl_iter、tsl_iter_by_time_1、tsl_query_count、tsl_set_status |
| GC/容量扩展 | gc、gc2、scale_up |
| 生命周期/控制接口 | kvdb_deinit、kvdb_set_default |

---

## 6. 系统性根因树

## 6.1 第一层：结果无法进入评分

- executor timeout
- pipeline pending
- terminal report 未正式生成
- 投票器不消费 partial completion
- last result 覆盖 best result

这是客观分归零的直接原因。

---

## 6.2 第二层：Pipeline 时间被控制面问题消耗

- changed_files 缺失
- receipt 与 diff 不一致
- isolation-results 缺失
- task packet 格式错误
- pending 消费规则不匹配
- verify 阶段修改源码冲突
- no-op 重试
- 31 次 c-cross 无界循环

这些问题导致系统没有足够时间完成测试迁移和最终评分。

---

## 6.3 第三层：调度与状态管理不稳定

- agent 注册但未 dispatch
- repair plan 未消费
- state tampering restore
- workspace baseline 不一致
- Run 4 复制 Run 1
- flashDB_rust 目录在部分 Run 丢失
- 结果未绑定明确 source checkpoint

---

## 6.4 第四层：Rust 实现存在真实缺陷

- blob 长度损坏
- 指针解引用错误
- CString 生命周期
- 控制码错误
- `repr(C)` offset 错误
- `while(x--)` 语义错误
- CRC 计算错误
- TSDB iterator/query 返回 0
- GC/scale-up 不可用
- runner 段错误
- teardown/全局状态可能污染后续 case

---

## 6.5 第五层：测试迁移和评分一致性不足

- 24 case → 10 tests
- case 合并
- 11 case 无对应
- 关键断言缺失
- Rust-native 与 c-cross 映射断裂
- scoring consistency 只有 5/24

---

## 7. 改进优先级

## P0：保证 Pipeline 有界完成

### 必须修改

1. 全局 deadline manager
2. 每阶段最大重试次数
3. 全量 c-cross 最大尝试次数
4. Repair 最大轮次
5. 连续无提升停止条件
6. best-so-far checkpoint
7. 剩余预算保护
8. terminal state 强制落地
9. partial result 可被投票器消费
10. 每轮输出当前输入的完整全量 case 状态

### 建议参数

| 项目 | 建议 |
|---|---:|
| REWRITE Gate 尝试 | 最多 2 次 |
| Repair 轮次 | 最多 2~3 次 |
| 全量 c-cross | 最多 5~8 次 |
| 无提升停止 | 连续 2 次 |
| 报告保护预算 | 总预算剩余 15%~20% |

### 预期效果

- 五轮不再因 timeout 全部归零
- 即使功能通过率不提升，也能形成可评分结果
- Run 3/5 可保留 16/24、17/24 的最佳尝试，而非回退结果

---

## P1：简化并自动化 Gate 控制面

### 必须修改

1. `changed_files` 由 Git diff 自动计算
2. isolation result 由 runner 自动生成
3. receipt 缺失非关键字段只 warning
4. task ID 和 packet ID 由 orchestrator 生成
5. frozen signature 改为 AST 比较
6. VERIFY 中增加合法 repair transaction
7. no-op repair 直接跳过
8. pending queue 使用原子 claim/ack

### 预期效果

- REWRITE 不再出现 3 轮空转
- VERIFY 不再因格式问题反复执行
- Token 和时间预算转向真实修复

---

## P2：重构测试迁移和评分映射

### 必须修改

1. 当前输入动态提取的 N 个 `scorer_standard_cases` → N 个独立 Rust test entry
2. 禁止 case 合并
3. 生成 `test_case_mapping.json`
4. 每个 case 保存 semantic obligations
5. Gate 检查 coverage=N/N，N 只能从当前 `scorer_standard_cases` 推导
6. scoring 直接消费映射文件
7. 禁止占位和弱断言

### 预期效果

- scoring consistency 不再固定在 5/24
- Rust-native、c-cross、正式评分可逐 case 对齐
- repair 可以针对单 case 定向执行

---

## P3：修复 Rust 核心功能

### 第一优先级：ABI 和内存安全

- blob saved.len 损坏
- pointer depth
- lifetime
- repr(C)
- offsets
- integer width
- control constants
- CRC

### 第二优先级：KVDB 执行隔离和生命周期

- runner 段错误
- init/deinit
- default DB
- global state reset
- case 独立进程

### 第三优先级：TSDB iterator/query/status

- 地址推进
- 时间范围边界
- status bit scan
- count
- reverse/forward iterator
- dirty/empty/full 状态

### 第四优先级：GC 和 scale-up

GC 依赖前述底层语义，最后处理更合理。

---

## 8. 推荐的 Pipeline 调整

在保持 12 阶段兼容的前提下，建议将 VERIFY 内部改为有界闭环：

```text
BOOTSTRAP
INIT_WORKSPACE
READ_C_PROJECT
BUILD_C_MODEL
DESIGN_RUST_API
GENERATE_RUST_SCAFFOLD
REWRITE_CORE_MODULES
VERIFY_RUST_WITH_C_TESTS
  ├─ INITIAL_FULL_VERIFY
  ├─ DIAGNOSE
  ├─ REPAIR_TRANSACTION
  ├─ TARGETED_VERIFY
  ├─ FULL_REGRESSION
  └─ SAVE_BEST
MIGRATE_TESTS
BUILD_TEST_REPAIR
REPORT_AND_VERIFY
SCORING
```

关键约束：

- repair 失败不得中止 Pipeline
- case 失败允许存在
- Gate 元数据问题优先自动修复
- 到达预算阈值必须进入 REPORT
- 最终使用 best checkpoint
- 所有 case 都必须有 pass/fail/not_run/timeout/crash 明确状态

---

## 9. 验收标准

## 9.1 Pipeline 验收

- 五轮全部进入 terminal state
- 不得停留在 `pending`
- 每轮生成 final manifest
- 每轮生成当前输入的全量 case 最终状态
- timeout 前已保存 partial result
- 最终使用 best checkpoint
- 五轮 workspace 独立且 baseline manifest 一致

## 9.2 Gate 验收

- changed_files 自动计算
- receipt 非关键字段缺失不阻塞
- frozen signature 语义比较
- repair transaction 可合法修改源码
- 无连续 no-op 重试
- runner 直接生成 isolation results

## 9.3 测试验收

- 当前输入的 N 个 scorer case 对应 N 个 Rust test entry
- N/N 映射完整，N 不得在工作台中写死
- 无 case 合并
- 无占位断言
- 关键调用和断言可追踪
- scoring consistency 可逐 case 解释

## 9.4 功能验收

建议分阶段目标：

| 阶段 | 目标 |
|---|---|
| 第一阶段 | Pipeline 五轮均完成，客观分不再归零 |
| 第二阶段 | 消除 runner 段错误和 not_run，c-cross best ≥17/24 |
| 第三阶段 | 修复 TSDB iterator/query，c-cross best ≥20/24 |
| 第四阶段 | 修复 GC/scale-up，c-cross best ≥22/24 |
| 最终阶段 | 提升 5/5 稳定通过数量，并使 scoring consistency 接近 c-cross |

---

## 10. 风险与注意事项

### 10.1 不应简单放宽所有 Gate

Gate 简化不等于删除全部约束。以下仍应 hard fail：

- Cargo 无法构建
- Rust 项目缺失
- ABI 真实变化
- 关键 frozen 文件被破坏
- 标准测试无法启动
- 最终产物不可读取

以下可降级为 warning 或自动修复：

- changed_files 未填
- receipt 非关键字段缺失
- packet 格式轻微问题
- isolation 元数据缺失但 runner 原始结果存在
- owner metadata 不一致

---

### 10.2 partial completion 不能伪装成完整成功

投票器可消费 partial result，但必须保留：

- case 是否实际执行
- 使用哪个 checkpoint
- 是否 crash/timeout/not_run
- 是否属于完整全量验证

不能把未执行 case 默认为 pass。

---

### 10.3 Run 4 与 Run 1 重复会影响稳定性可信度

五轮稳定性要求独立运行。后续必须确保：

- 新 nonce
- 新 workspace
- 新 agent session
- 清空对话上下文
- 使用同一输入 baseline
- 不复用 workflow state 和 receipts

---

## 11. 最终结论

本次五轮测试暴露了完整的三层问题：

1. **评分交付层失败**
   - timeout
   - pending
   - partial result 不被采纳
   - best result 未保留

2. **Pipeline 控制层失败**
   - Gate 过度依赖格式
   - agent 调度和 receipt 不一致
   - retry 无界
   - workspace 和状态恢复不稳定

3. **转换质量层失败**
   - ABI、指针、生命周期、layout、CRC、C 语义翻译错误
   - TSDB、GC、blob 等核心功能不完整
   - Rust 测试覆盖和语义映射不足

当前最优修复策略不是继续增加无限 repair，而是：

> 先让 Pipeline 在任何情况下都完成并产出最佳可用结果；再删除重复控制面产物并统一事实来源；随后建立从当前输入动态推导的 N 对 N 测试映射；最后按机器证据归类修复功能。

完成 P0 和 P1 后，即使 Rust 功能水平暂时不变，也能显著降低 0 分风险。完成 P2 后，正式 scoring 才可能真实反映 c-cross 的改善。完成 P3 后，才会进一步提升准确性和稳定性上限。

---

## 12. 精简后的改进方案

本节是在审计当前各阶段输出文件及其消费者后形成的修订方案。它取代“继续增加 receipt、planner、packet 或新状态文件”的方向。

### 12.1 总体判断

五轮测试问题不能只靠精简文件完全解决，但产物精简是后续修复的前提：

- 它能直接消除大量 Gate 格式阻塞、重复事实冲突、无效上下文和控制面空转；
- 它能降低 timeout 风险，但必须同时增加有界完成规则才能保证 Pipeline 收口；
- 它不能自动修复测试覆盖和 Rust 功能，因此还必须保留动态 N→N 测试迁移和真实验证。

实施边界：

1. 不新增全局阶段；
2. 不新增 planner、receipt、queue 或人工审核层；
3. `gate.py` 只检查事实，不承担流程路由；
4. 只保留能证明输入、ABI、构建、测试、C-cross 和最终报告真实性的产物；
5. 失败不阻止最终比赛产物生成，但不得把失败改写为成功；
6. 场景和测试总数始终从当前输入动态推导，不得写死 24 或任何固定总数。

### 12.2 产物分级原则

所有运行产物只分为三类：

| 类别 | 用途 | 保留规则 |
|---|---|---|
| 业务事实 | 后续阶段和最终评分直接消费 | 长期保留，只有一个权威文件 |
| 控制状态 | 支持当前阶段恢复、预算和路由 | 只保留当前状态与精简事件，不复制多套回执 |
| 诊断临时文件 | 编译器、runner、失败排查 | 只保留最终运行或最后一次失败，成功后清理临时二进制和中间文件 |

同一个事实不得同时由 Agent 自报、receipt、stage-run、JSONL 和 Markdown 分别维护。

### 12.3 各阶段保留产物

| 阶段 | 长期保留 | 合并或删除 |
|---|---|---|
| INIT_WORKSPACE | `workflow_state.json` | 删除 `01-init-workspace.md`、静态 `agent-registry.json`；subagent 调用只写精简 workflow event |
| READ_C_PROJECT | `input_manifest.json` | 将全输入 hash baseline 合并进 manifest；删除 `input-source-baseline.json` 和 `02-read-c-project.md` |
| BUILD_C_MODEL | `c_project_model.json`、`c_api_model.json`、去重后的 `c_test_model.json` | 删除 `03-build-c-model.md`；场景 IR 只保存一份 |
| DESIGN_RUST_API | 去重后的 `rust_api_design.json` | 删除 `04-design-rust-api.md`；删除独立设计期 `ffi_manifest.json`，FFI 设计直接读取 `c_abi_facade` |
| GENERATE_RUST_SCAFFOLD | Rust 工程、`scaffold-manifest.json` | layout 结果写入 manifest；删除 `05-generate-rust-scaffold.md`、临时 checker 源码、目标文件和二进制 |
| REWRITE_CORE_MODULES | 一个 `rewrite-result.json` | 合并 rewrite state、batch、audit、check 状态；删除 worker run/receipt、多份 batch JSONL 和阶段 Markdown |
| VERIFY_RUST_WITH_C_TESTS | `validation-matrix.json`、一个 `c-cross-state.json`、一个 best source snapshot | 合并 attempts、repair plan、isolation queue/results、build/layout/link/case/diagnostics 状态；只保留最终或最后失败日志 |
| MIGRATE_TESTS | `rust_test_mapping.json`、一个 `test-validation.json` | 合并 placeholder 与 consistency 结果；删除 `07-migrate-tests.md` |
| BUILD_TEST_REPAIR | `cargo-results.json` | build/test/fmt 日志只在失败或最终运行时保留；删除阶段 Markdown和独立重复 triage 历史 |
| REPORT_AND_VERIFY | `final-manifest.json`、`result/output.md`、`result/issues/00-summary.md` | 删除 `final-verification.md` 和 `09-report-and-verify.md`；其他阶段事实只引用，不复制 |

目标是将长期 trace 从当前三四十类文件收缩到约 15～18 类。数量不是硬门槛；判断标准是每个保留文件必须有明确的后续消费者，并且不能与其他文件重复维护同一事实。

### 12.4 必须消除的内容级重复

#### C 测试模型

`c_test_model.json` 中：

- `standard_scenarios` 保存唯一的完整 scenario IR；
- `scorer_standard_cases` 只保存 `case_id`、`scenario_id`、评分义务 ID 和必要的评分元数据；
- 不再把完整调用序列、断言和 helper 证据复制到两套列表中。

#### Rust API 设计

`rust_api_design.json.test_api` 只保存：

- observables；
- controls；
- test model path/hash；
- 与实现设计直接相关的义务引用。

不得再次复制 `standard_scenarios` 和 `scorer_standard_cases` 的完整内容。

#### FFI 证据

设计期 FFI 合同由 `rust_api_design.json.c_abi_facade` 唯一保存。C-cross 实际链接需求写入 `validation-matrix.json.layers.link`。禁止再让同一个 `ffi_manifest.json` 先表示设计合同、后又被删除并改写为链接结果。

### 12.5 最小控制状态

只保留两个运行状态文件：

#### `workflow_state.json`

至少包含：

```text
current_stage
next_action
completed_stages
input_digest
active_task
soft_deadline
hard_deadline
report_reserved_seconds
final_status
```

#### `c-cross-state.json`

至少包含：

```text
current_execution_id
attempts_used
max_attempts
stalled_rounds
best_execution_id
best_source_hash
best_summary
pending_action
budget_status
```

可选保留一个 `workflow-events.jsonl`，每个阶段或修复事务只追加一条精简事件：stage、action、result、changed files、artifact hash 和时间。它不能再复制 task packet、完整 baseline、完整 Gate 输出和大模型内容。

task packet 只作为当前 subagent 的临时输入文件。阶段结束后允许覆盖或删除，不作为最终事实证据。Agent 注册信息直接来自 `work/skills/{subagent}.md` 和控制器静态配置，不再生成运行期 registry 副本。

### 12.6 有界完成规则

产物精简只能降低开销，以下规则负责真正解决 timeout 和 pending：

1. 初始化时写入全局 soft/hard deadline；
2. MIGRATE_TESTS、最终 cargo 验证和 REPORT_AND_VERIFY 必须有保留预算；
3. C-cross repair 默认最多 2～3 轮；
4. 连续两轮 best 无提升立即停止继续 repair；
5. 到达 soft deadline 后禁止创建新的 repair 或 subagent 任务；
6. 若存在 best snapshot，先恢复 best；
7. 在保留预算内执行一次 final/full 验证；
8. 随后继续 MIGRATE_TESTS、BUILD_TEST_REPAIR 和 REPORT_AND_VERIFY；
9. 最终状态只能是 `DONE` 或 `DONE_WITH_FAILURES`，不得停留在 `pending`；
10. 所有未执行场景必须明确记录为 timeout、crash、not_run 或 unresolved，不得默认为 pass。

### 12.7 动态 N→N 测试迁移

测试迁移继续使用 `rust_test_mapping.json`，不新增新的 mapping 文件：

1. N 从当前 `c_test_model.json.scorer_standard_cases` 动态推导；
2. N 个 scorer case 必须对应 N 个唯一 Rust test entry；
3. 允许共享 fixture、setup 和 helper；
4. 禁止合并评分 test entry；
5. 每个映射必须保存 scenario ID、scorer case ID、Rust test、validated obligations 和 assertion evidence；
6. `test-validation.json` 同时检查占位实现、弱断言、映射缺失和义务缺口；
7. C-cross 失败可以真实保留并继续测试迁移，不得因为少数用例失败耗尽全部后续预算。

### 12.8 与五轮问题的对应关系

| 五轮问题 | 本方案处理方式 | 是否能直接解决 |
|---|---|---|
| receipt、packet、changed_files 冲突 | 删除多套事实源，由控制器状态和真实 diff 统一记录 | 是 |
| Gate 因 Markdown 或非关键元数据阻塞 | 删除阶段 Markdown和格式型硬门禁 | 是 |
| 上下文膨胀、trace 文件过多 | 大 JSON 去重、临时文件清理、task packet 临时化 | 是 |
| Pipeline timeout、最终 pending | deadline、阶段保留预算、有界 repair、强制 terminal | 是，需与精简同时实施 |
| last 覆盖 best | `c-cross-state.json` 绑定 best source hash，并在最终验证前恢复 | 是 |
| repair plan 生成但未执行 | `pending_action` 只有一个，必须完成、预算跳过或失败后才能变化 | 是 |
| Run 间 baseline 不一致或复制 | `input_manifest.json` 绑定输入 digest；每轮重新初始化 active state | 部分，还需五轮运行器确保独立 workspace/session |
| N 个 case 只迁移少量 Rust test | 动态 N→N 映射和统一 test validation | 是 |
| ABI、状态管理、TSDB、GC 等真实实现错误 | 仍需根据 validation matrix 定向修复 | 否，本方案只提供更可靠、更有界的修复输入 |

### 12.9 实施顺序

#### 第一批：纯减法

1. 删除各阶段 Markdown required outputs 及对应 Gate；
2. 合并 input baseline 与 manifest；
3. 删除 agent registry 和多重 stage receipt/run 历史；
4. 清理临时 layout checker、编译目标和成功日志；
5. 去除 `c_test_model`、`rust_api_design` 的完整场景复制。

验收：阶段顺序、真实 Gate 和最终产物能力不变，trace 文件数量和体积显著下降。

#### 第二批：统一 REWRITE 与 C-cross 状态

1. 将 REWRITE 的 batch、worker、check、audit 合并为 `rewrite-result.json`；
2. 将 C-cross attempts、plan、isolation 和 best 合并为 `c-cross-state.json`；
3. `validation-matrix.json` 成为场景结果、诊断和 build/layout/link 状态的唯一事实源；
4. 保留真实 Cargo 与 C compile/link/run 命令，不削弱验证路径。

验收：同一事实只存在一个权威位置，失败仍可定位，best 不会被回归结果覆盖。

#### 第三批：有界完成与动态测试映射

1. 增加 deadline 和报告保留预算；
2. 降低 repair 轮数并启用连续无提升停止；
3. 强制恢复 best、执行最终验证并进入 terminal；
4. 完成动态 N→N Rust test mapping 和统一 test validation。

验收：连续五轮均进入 terminal state，均生成最终比赛产物，测试映射达到动态 N/N。

#### 第四批：重新测试后再处理转换质量

只有前三批验证完成后，才依据新的 `validation-matrix.json` 修复真实转换缺陷。不在工作台继续增加新流程层来替代代码和测试修复。

### 12.10 最终验收标准

1. 五轮使用相同 workbench commit、输入 digest、模型配置和时间预算；
2. 五轮 workspace、session 和 active run 独立；
3. 五轮全部进入 `DONE` 或 `DONE_WITH_FAILURES`；
4. 每轮都生成 `final-manifest.json`、`result/output.md` 和 `result/issues/00-summary.md`；
5. 每个持久化文件都有明确消费者，不存在只为 Gate 检查“文件存在”而生成的产物；
6. 不保存成功后的临时二进制、对象文件和重复日志；
7. C-cross 最终结果绑定 source hash、execution ID 和动态全量场景集合；
8. best checkpoint 恢复后才允许执行 final verification；
9. Rust test mapping 达到动态 N/N，无合并评分 entry、无占位和弱断言；
10. 精简控制面失败不得影响最终比赛产物生成，真实验证失败必须如实记录。
