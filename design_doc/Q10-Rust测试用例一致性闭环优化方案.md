# Q10 - Rust 测试用例一致性闭环优化方案

> 状态：已实施  
> 优先级：P0  
> 关联阶段：`TEST_AND_REPORT`  
> 证据来源：`design_doc/0715-test-19pass.json`、`.opencode/skills/c-to-rust-scoring/SKILL.md`、当前 `02_02` 测试迁移与最终 gate 合同

## 1. 结论

评分平台能够识别多阶段 GC、扩容、跨 sector 查询、精确配置和重启恢复缺失，不是因为它拥有一个隐藏的确定性语义比较脚本，而是因为评分 Agent 按 `c-to-rust-scoring` Skill 直接逐用例阅读 C/Rust 测试，提取 API、数据、初始化参数和断言，再做语义判断。

因此，本轮不再尝试让 Python 静态检查器独自证明任意 C/Rust 测试等价，而是在 Q9 四阶段简化流程中建立两层闭环：

1. **确定性检查层**：负责动态用例集合、一对一 mapping、测试函数存在、占位检测、证据格式、文件指纹、cargo 结果和最终状态一致性；
2. **独立语义 Reviewer 层**：使用与评分平台一致的审查方法，逐项阅读原 C 测试、相关 helper 和 Rust 测试，比较目标 API、数据/配置、生命周期、操作顺序和断言语义。

语义 Reviewer 只允许读取 C/Rust 源码和必要模型事实，只允许写审查结果，不得修改 Rust tests、mapping、实现源码、工作流合同或最终报告。发现问题后由测试迁移者修复，再使用新的审查轮次复检。

本方案不新增 workflow controller、receipt、task packet、revision 或新的阶段状态机；只在现有 `TEST_AND_REPORT` 内增加一个边界明确的只读审查角色和最多两轮修复闭环。

所有用例、函数、数量和语义要求均从当前 C 输入动态取得。`0715-test-19pass.json` 中的失败项仅作为验收证据，不进入工具或 Skill 的固定 case 表。

## 2. 评分平台实际机制

### 2.1 方案 B 的执行顺序

评分 Skill 对包含 Rust tests 的项目执行：

```text
cargo test
    ↓
枚举原 C 测试函数与 Rust #[test] 函数
    ↓
逐个读取 C 测试并提取：目标 API、测试数据/初始化参数、断言与期望值
    ↓
逐个读取 Rust 测试并提取相同维度
    ↓
按场景语义、API 调用链、函数名相似度依次匹配
    ↓
输出 c_only、rust_only、logic_mismatch
```

其中：

- C 有而 Rust 缺失：失败；
- Rust 额外测试：warning；
- API、数据或断言任一维度不一致：失败；
- 一致性结论优先于 `cargo test`，即 Rust 测试全部运行通过仍可能被判失败。

### 2.2 不是可直接复用的 Python 工具

`.opencode/skills/c-to-rust-scoring/` 目录当前只有 `SKILL.md`，没有负责语义比较的脚本。Skill 中的 grep 命令只枚举函数名；“提取测试逻辑要素”和“基于语义而非名称匹配”由评分 Agent 完成。

这也解释了评分报告能够识别：

- 多阶段操作及阶段间 reboot；
- `oldest_addr` 等断言目标；
- 4→8 sector 扩容前后的旧/新数据验证；
- 跨多个 sector 的边界组合查询；
- sector size、max size、control flag、blob 大小和重启恢复。

### 2.3 不能照搬评分 Skill 的固定表

评分 Skill 文档仍包含固定“23 个标准测试场景”，而当前输入和评分报告实际使用 24 个场景；报告中的部分 case 名称与实际 C 函数也存在错位。因此内部工作台只复用其**审查方法**，不复制固定 case 表、case 数量、路径、性能流程或方案选择逻辑。

内部权威用例集合仍为当前运行的 `c_test_model.json.scorer_standard_cases`，并与 `rust_test_mapping.json` 一对一关联。

## 3. 当前问题

### 3.1 确定性检查器验证的是 mapping 声明，不是完整测试语义

当前 `test_consistency_check.py` 能检查测试存在、断言数量、部分 API/data/assertion evidence，但仍存在以下缺口：

- `semantic_obligations`、`validated_obligations` 和 evidence 由同一迁移者填写；
- 任意一条 data/assertion evidence 可能被用于证明过大的语义范围；
- 无法可靠判断多阶段流程、helper 展开后的真实意图和操作顺序；
- 静态字符串存在不等价于数据值、配置值和断言语义一致；
- 复杂但等价的 Rust 写法容易被纯文本规则误报。

### 3.2 一致性检查执行过晚

简化后的流程主要在 `FINAL` 中间接运行 consistency。测试迁移完成后没有一个显式步骤负责读取 `logic_mismatch`、修改 Rust tests 并复检；报告还可能先于最新 consistency 结果生成。

### 3.3 转换者自审与评分者独立审查不是同一件事

测试迁移者知道自己想证明什么，容易接受自己写入的 mapping 和抽象说明；评分 Agent 则在独立任务中重新阅读两侧源码，只判断最终测试是否真的一致。当前工程缺少这个独立视角。

## 4. 设计目标与非目标

### 4.1 目标

1. 内部预评分使用与外部评分一致的 API、数据、生命周期、顺序和断言维度；
2. Reviewer 从当前 C 输入动态取得全部场景，不依赖固定 FlashDB case 表；
3. Reviewer 直接查看 C/Rust 源码，不把迁移者写入的 `validated_obligations` 当事实；
4. 每个失败结论包含足以修复的 C/Rust 源码证据和具体差异；
5. 一致性失败自动回到测试迁移修复，最多两轮；
6. 修复耗尽后仍生成比赛产物，但状态必须为 `FAILED`；
7. 任何测试或 mapping 修改都会使旧审查结果失效。

### 4.2 非目标

- 不编写通用 C/Rust 程序等价证明器；
- 不把评分 Skill 的固定 23/24 项表复制进工作台；
- 不直接调用或依赖评分平台的完整 Skill；
- 不让 Reviewer 修改被审查对象；
- 不新增 controller、任务队列、receipt 或审查状态机；
- 不因为 Reviewer 是 Agent 就接受无源码证据的自然语言结论；
- 不以内部审查替代外部最终评分。

## 5. 目标架构

```text
migrate_tests.py
    │  只生成动态 task map
    ▼
测试迁移者写 Rust tests + mapping
    ▼
placeholder_check.py + test_consistency_check.py
    │  确定性结构检查
    ▼
test-semantic-reviewer（独立、只读）
    │  逐用例阅读 C/helper/Rust
    │  输出 test-semantic-review.json
    ├─ PASS ───────────────┐
    └─ FAIL → 定向修复 → 新 Reviewer 复检（最多两轮）
                           │
                           ▼
                     cargo_capture.py
                           ▼
                     report_writer.py
                           ▼
                     gate.py --stage FINAL
```

Reviewer 是一次边界明确的审查任务，不负责流程推进。审查规则保存在 `work/skills/test-semantic-reviewer.md`；调度信息只携带作品根目录、当前动态场景集合、mapping 路径、输出路径和停止条件，不复制 Skill 业务规则。

## 6. Q10-1：新增评分同款独立语义 Reviewer

### 6.1 Reviewer 输入

Reviewer 必须读取：

- `logs/trace/c_test_model.json.scorer_standard_cases` 的动态 case 标识、C 函数和来源位置；
- `logs/trace/rust_test_mapping.json` 的 C→Rust 对应关系；
- 每个 case 对应的原 C 测试函数窗口；
- 该 C 测试直接依赖、且影响测试语义的 helper 函数窗口；
- 对应 Rust `#[test]` 函数及其局部 helper；
- 必要时读取 `rust_api_design.json` 确认 C API 与 Rust API 的语义映射。

读取边界：

- 逐 case 使用 `rg` 定位后读取函数窗口；
- 不默认全文读取大型模型、整个 C 工程、全部 Rust src 或历史报告；
- helper 只沿当前测试的直接语义依赖展开；
- 不读取迁移者的自然语言“已通过”结论作为证据。

### 6.2 Reviewer 比较维度

每个动态 case 必须独立比较：

| 维度 | Reviewer 必须回答 |
|---|---|
| 场景 | Rust test 是否测试了与 C 相同的行为，而非只使用相似名称？ |
| API | 关键 API/语义等价调用是否完整，是否调用了错误方向的 API？ |
| 数据 | key/value、blob、数量、大小、时间范围、sector 相关数据是否语义等价？ |
| 配置 | 初始化参数、control command、flag、sector size、max size 等是否一致？ |
| 生命周期 | init/deinit/reboot/reopen/reconfigure/clean 等关键边界是否保留？ |
| 顺序 | 写入、变更、触发、重启、恢复验证之间的必要先后关系是否保留？ |
| 断言 | C 中真正决定场景成立的断言目标、关系和期望行为是否在 Rust 中被验证？ |

以下不能单独证明一致：

- 函数名相似；
- 调用了部分相同 API；
- Rust 断言数量不少于 C；
- `cargo test` 通过；
- mapping 声明 `coverage: semantic`；
- 使用 `is_ok()`、`is_some()` 等浅层断言替代深层状态、数据或顺序验证。

### 6.3 Reviewer 独立性与写入边界

新增 `work/skills/test-semantic-reviewer.md`，其职责为只读审查：

- 允许读取平台 C 输入、`logs/trace` 必要片段和 `flashDB_rust/tests/**`；
- 只允许写 `logs/trace/test-semantic-review.json`；
- 禁止修改 `flashDB_rust/**`、`rust_test_mapping.json`、`work/**`、`INSTRUCTION.md` 和最终报告；
- 禁止把发现的问题直接“顺手修掉”；
- 必须先完成所有动态 case 的审查，再给出总状态；
- 若原生 subagent 可用，优先使用新的独立 reviewer session；若不可用，主执行者必须按同一 Skill 进入单独只读审查步骤，不得边审边改。

Reviewer 与测试迁移者不能是同一个并行任务。每次修复后必须重新执行审查；优先使用新的 reviewer session，避免沿用修复者的自我解释。

## 7. Q10-2：语义审查产物合同

### 7.1 输出文件

Reviewer 输出：

```text
logs/trace/test-semantic-review.json
```

建议结构：

```json
{
  "schema_version": 1,
  "status": "pass|fail|unresolved",
  "reviewer_mode": "independent_subagent|primary_readonly_fallback",
  "input_fingerprint": {
    "c_test_model_sha256": "...",
    "rust_api_design_sha256": "...",
    "rust_test_mapping_sha256": "...",
    "c_source_files": {"<dynamic path>": "..."},
    "rust_test_files": {"<dynamic path>": "..."}
  },
  "total_c_scenarios": 0,
  "reviewed_scenarios": 0,
  "c_only": [],
  "rust_only": [],
  "logic_mismatch": [],
  "cases": [
    {
      "scenario_id": "<dynamic id>",
      "c_function": "<dynamic function>",
      "rust_test": "<dynamic function>",
      "status": "pass|fail|unresolved",
      "dimensions": {
        "scenario": "pass|fail|unresolved",
        "api": "pass|fail|unresolved",
        "data": "pass|fail|unresolved",
        "configuration": "pass|fail|unresolved",
        "lifecycle": "pass|fail|unresolved",
        "ordering": "pass|fail|unresolved",
        "assertion": "pass|fail|unresolved"
      },
      "c_evidence": [
        {"path": "<dynamic path>", "function": "<symbol>", "line_start": 0, "line_end": 0, "summary": "..."}
      ],
      "rust_evidence": [
        {"path": "<dynamic path>", "function": "<symbol>", "line_start": 0, "line_end": 0, "summary": "..."}
      ],
      "differences": [
        {"dimension": "data|assertion|...", "detail": "具体、可修复的差异"}
      ]
    }
  ]
}
```

### 7.2 通过规则

只有同时满足以下条件才允许 `status: pass`：

1. `reviewed_scenarios == total_c_scenarios`，总数由当前 C 模型动态推导；
2. `c_only` 为空；
3. `logic_mismatch` 为空；
4. 所有动态 case 的七个维度均为 pass；
5. 每个 case 至少包含可定位的 C 与 Rust 源码证据；
6. input fingerprint 与当前文件一致；
7. 没有 unresolved case。

`rust_only` 只作为 warning，不影响 pass。

### 7.3 禁止无证据结论

- `detail` 必须描述两侧实际差异，不能只写“语义不一致”；
- line range 必须位于当前 fingerprint 对应文件中；
- 仅引用 mapping、阶段日志或旧评分报告不能作为源码证据；
- Reviewer 无法判断时必须标为 unresolved，不能猜测 pass；
- 同一 Rust test 映射多个 C case 时，必须分别证明各自语义，不能因函数存在而全部通过。

## 8. Q10-3：确定性工具的职责收缩与增强

### 8.1 `test_consistency_check.py`

该工具不再尝试独自证明完整语义等价，职责调整为：

- 从当前 `scorer_standard_cases` 校验一对一 mapping；
- 定位 mapped Rust test 函数；
- 检查 placeholder、忽略测试、无断言和明显恒真断言；
- 校验 Reviewer JSON schema、动态 case 覆盖和源文件范围；
- 校验 reviewer fingerprint；
- 将 `c_only`、`rust_only`、`logic_mismatch` 和各 case 状态整理为最终 consistency 结果；
- 对 Reviewer fail/unresolved 返回非零退出码。

原有 API/data/assertion 字符串 evidence 可保留为 Reviewer 导航信息和确定性预检，但不再单独产生 semantic pass。

### 8.2 `validated_obligations`

- 测试迁移者可以填写候选 coverage/evidence，帮助 Reviewer 定位；
- mapping 中手写的 `validated_obligations` 不再作为 gate 通过依据；
- 最终 validated 状态由 Reviewer case 结论和确定性检查共同派生；
- mapping 自称 semantic、但 Reviewer 发现测试简化时必须失败。

### 8.3 新鲜度

`test-semantic-review.json`、`test-consistency.json` 和 `test-placeholder-check.json` 必须绑定：

- 当前 C test model；
- 当前 Rust API design；
- 当前 mapping；
- Reviewer 实际读取的 C 源文件；
- 所有 mapped Rust test 文件。

修改任意上述输入后，旧 pass 立即失效。

## 9. Q10-4：TEST_AND_REPORT 修复闭环

### 9.1 执行流程

```text
1. migrate_tests.py 生成动态 mapping 骨架
2. 测试迁移者实现 Rust tests 并填写候选 evidence
3. 运行 placeholder + deterministic consistency precheck
4. 运行独立 test-semantic-reviewer
5. test_consistency_check.py 校验并汇总 Reviewer 结果
6. 如失败：只把失败 case、源码证据和 differences 交给测试迁移者
7. 定向修改 Rust tests/mapping
8. 重新运行 placeholder、Reviewer、consistency 和 cargo
9. 最多两轮修复；预算耗尽后继续生成 FAILED 报告
10. report_writer.py
11. gate.py --stage FINAL
```

### 9.2 修复边界

- 默认只允许修改 `flashDB_rust/tests/**` 和 `rust_test_mapping.json`；
- 不允许通过删除 case、弱化断言或修改 Reviewer 规则消除失败；
- 如果 Reviewer 证明 Rust API/实现无法支持等价测试，记录为实现能力缺口，回到 `IMPLEMENT/VERIFY_AND_REPAIR`；
- 实现修复后必须重新运行 C-Cross、Rust tests 和语义 Reviewer；
- 每轮 Reviewer 都重新读取当前源文件，不复用旧自然语言结论。

### 9.3 两轮预算

- “两轮”指 Reviewer 给出失败后，测试迁移者最多进行两次定向修改；
- 不新增 attempt controller 或状态机；最终 JSON 只保存当前审查事实；
- 两轮后仍失败或 unresolved，继续生成最终产物，但 `STATUS: FAILED`；
- 不允许用 `|| true` 把一致性失败改写为成功。

## 10. Q10-5：报告与 FINAL 对账

### 10.1 报告生成顺序

`report_writer.py` 只能在 placeholder、semantic review、consistency 和 cargo 当前结果都已生成后运行。

报告必须展示：

- 动态总场景数、已审查数；
- `c_only`、`rust_only`、`logic_mismatch` 数量；
- Reviewer mode；
- fail/unresolved case 及具体 dimensions；
- consistency fingerprint 是否新鲜；
- 修复预算耗尽时的真实终态。

### 10.2 FINAL 职责

`gate.py --stage FINAL`：

- 不生成或覆盖 semantic review；
- 不在报告之后偷偷产生新的 consistency 事实；
- 只校验当前 JSON 的 schema、覆盖、fingerprint、status 和报告一致性；
- semantic review 为 fail/unresolved 时 FINAL 失败；
- 即使 FINAL 失败，最终报告文件必须存在并保持 `STATUS: FAILED`。

## 11. 修改范围

批准实施后预计修改：

- `02_02/INSTRUCTION.md`
- `02_02/work/skills/flashdb-orchestrator.md`
- `02_02/work/skills/test-migrator.md`
- `02_02/work/skills/flashdb-test-migration/SKILL.md`
- 新增 `02_02/work/skills/test-semantic-reviewer.md`
- `02_02/work/tools/test_consistency_check.py`
- `02_02/work/tools/placeholder_check.py`（仅 fingerprint 对齐）
- `02_02/work/tools/gate.py`
- `02_02/work/tools/report_writer.py`
- `02_02/work/tools/migrate_tests.py`（仅 reviewer 导航字段和初始状态）
- `02_02/tests/test_conversion_system.py`
- `02_02/tests/test_workflow_optimizations.py`
- 当前设计说明中与 `TEST_AND_REPORT` 相关的合同

原则上不再为本问题扩展 `build_c_model.py` 成为完整 phase/order 等价分析器。只有当动态 case 缺少 C 函数位置、helper 关系或必要来源定位时，才做最小模型补充。

## 12. 验收设计

### 12.1 确定性框架测试

使用合成 fixture，不使用固定 FlashDB case 表，覆盖：

1. 动态 case 改名和数量变化后仍完整审查；
2. 缺少 Reviewer JSON 时 consistency 失败；
3. Reviewer 漏审任意动态 case 时失败；
4. `c_only` 或 `logic_mismatch` 非空时失败；
5. `rust_only` 只产生 warning；
6. case 没有 C/Rust 源码证据时失败；
7. evidence line range 越界或文件不存在时失败；
8. Reviewer 标记 unresolved 时失败；
9. 修改 mapping 或任意 mapped Rust test 后旧 fingerprint 失效；
10. mapping 手写 validated obligations 不能绕过 Reviewer fail；
11. consistency 失败时报告仍生成且为 `STATUS: FAILED`；
12. FINAL 不覆盖 Reviewer 或 consistency JSON；
13. 全部动态 case 审查通过时 report 与 FINAL 状态一致；
14. workbench 工具和 Skill 不包含本次失败 case 的固定名称、数量或期望值。

### 12.2 Reviewer 行为验收

准备动态、通用的正反例源对：

- 正例：C/Rust 名称和语法不同，但 API、数据、生命周期、顺序与断言等价，应 pass；
- 反例：API 相同但数据规模不同，应报 data mismatch；
- 反例：数据相同但缺 reboot/reopen，应报 lifecycle mismatch；
- 反例：步骤齐全但顺序错误，应报 ordering mismatch；
- 反例：断言数量足够但目标或 expected value 错误，应报 assertion mismatch；
- 反例：mapping 自称 semantic，但 Rust 只做浅层成功断言，应 fail。

这些是 Reviewer Skill 的实跑验收，不伪装成纯 Python 单元测试。

### 12.3 新一轮工作台验收

新一轮隔离运行必须满足：

- 动态 `reviewed_scenarios == total_c_scenarios`；
- `c_only == []`；
- `logic_mismatch == []`；
- `rust_only` 可存在但仅 warning；
- placeholder、Reviewer、consistency、cargo 和最终 C-Cross 均绑定当前输入；
- 外部评分不再发现内部 Reviewer 已漏过的 API、数据、配置、生命周期、顺序或断言差异；
- 最终失败时报告仍正常生成且状态诚实。

## 13. 实施顺序

1. 新增并审核 `test-semantic-reviewer.md`，先固定与评分平台对齐的审查维度、读取边界和输出 schema；
2. 调整 `test_consistency_check.py`，使其验证 Reviewer 产物、动态覆盖和 fingerprint，而不是自证 mapping；
3. 调整 `report_writer.py` 与 `gate.py` 的生产/消费顺序和只读 FINAL 对账；
4. 更新 `INSTRUCTION.md`、orchestrator、test-migrator 和测试迁移 Skill，接入最多两轮修复；
5. 增加确定性框架测试和 Reviewer 正反例验收；
6. 运行隔离工作台；
7. 使用同一评分 Skill 再次独立评分，对比内部 Reviewer 与外部 `logic_mismatch`。

## 14. 待最终审核决策

以下为本版方案的实施边界，用户最终批准后才修改实现：

1. 不新增 MIGRATE_TESTS stage，在现有 `TEST_AND_REPORT` 内加入 Reviewer；
2. 新增一个只读 `test-semantic-reviewer` Skill，优先由独立新 session 执行；
3. Reviewer 复用评分平台的 API、数据、配置、生命周期、顺序、断言审查方法，但不复制固定 case 表；
4. Python checker 负责结构、覆盖、新鲜度和结果汇总，不再声称独自证明完整语义等价；
5. mapping 的 `validated_obligations` 不再作为通过依据；
6. `c_only`、`logic_mismatch`、unresolved 为失败，`rust_only` 为 warning；
7. 一致性失败最多两轮定向修复，耗尽后继续生成 `STATUS: FAILED` 报告；
8. FINAL 只读核对，不覆盖 Reviewer/consistency 产物；
9. 本轮不针对评分报告中的具体 5 个名字编写任何特判。

## 15. 实施状态

- [ ] 用户已最终批准本版设计
- [ ] test-semantic-reviewer Skill 已实现
- [ ] Reviewer JSON 与 fingerprint 校验已实现
- [ ] consistency 职责调整已实现
- [ ] TEST_AND_REPORT 两轮修复闭环已实现
- [ ] report/FINAL 只读对账已实现
- [ ] 确定性框架测试已通过
- [ ] Reviewer 正反例验收已通过
- [ ] 隔离工作台已验证
- [ ] 外部评分已验证

## 16. 验收汇总

| 项目 | 验收证据 | 状态 |
|---|---|---|
| Reviewer Skill | 动态逐用例 API/data/config/lifecycle/order/assertion 审查 | 未实施 |
| Reviewer 产物 | schema、源码证据、动态覆盖与 fingerprint | 未实施 |
| 确定性检查 | mapping 自证无法绕过 Reviewer fail | 未实施 |
| 修复闭环 | 两轮定向修复，耗尽后诚实失败 | 未实施 |
| 报告与 FINAL | 同一事实快照、FINAL 无覆盖副作用 | 未实施 |
| 新一轮实跑 | 内外部 logic mismatch 对齐 | 未验证 |
