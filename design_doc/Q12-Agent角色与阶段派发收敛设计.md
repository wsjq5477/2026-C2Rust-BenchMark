# Q12 - Agent 角色与阶段派发收敛设计

> 状态：已实施；2026-07-16 已删除重复角色并同步当前合同与回归测试。
>
> 日期：2026-07-16
>
> 范围：`02_02` 的平台源目录 `work/agents/`、`work/subagent/` 与四阶段派发。平台复制到 `.opencode/` 的具体动作不属于本工程运行时逻辑。

## 1. 结论

当前的一个主 agent 加五个 subagent 不是最小必要集合。建议收敛为：

```text
1 个 primary
├── rust-implementer
├── test-migrator
└── test-semantic-reviewer
```

保留一个默认执行者和三个有不可替代边界的短期 subagent；删除 `c-analyzer` 与 `repairer` 两个重复角色。

subagent 永远是可选的上下文隔离手段，不是阶段推进前置条件。primary 在角色不可用、没有明确文件范围，或任务不足以抵消交接成本时直接执行该工作。

## 2. 逐角色决策

| 当前角色 | 决策 | 不可替代职责或删除理由 | 标准使用阶段 |
|---|---|---|---|
| `flashdb-orchestrator` | 保留 | 唯一负责阶段推进、确定性工具、共享工作区验证、真实 C-Cross 复跑与最终报告。任何 subagent 均不得替代这些责任。 | 全部四阶段 |
| `c-analyzer` | 删除 | ANALYZE 已由 `scan_c_project.py`、`build_c_model.py`、`abi_layout_extractor.py` 和 `design_rust_api.py` 直接生成事实产物。再派一个角色读取 C 源、头文件、测试或完整模型，只会重复输入并制造上下文爆炸。分析产物不完整时由 primary 重跑相应确定性工具。 | 不使用 |
| `rust-implementer` | 保留并吸收 repair | 唯一修改 Rust 生产代码的角色。它可处理“设计驱动实现”或“一个 C-Cross failure cluster 的最小修复”；两种任务的可编辑范围、证据来源、停止条件与复跑责任相同。 | IMPLEMENT；VERIFY_AND_REPAIR 的修复子步骤 |
| `repairer` | 删除并并入 `rust-implementer` | 当前只比 `rust-implementer` 多了“输入来自失败摘要”的文字差异，没有独立工具、权限、产物或验证责任。保留两个名称会让主控多一次路由判断，却不能提高真实 C-Cross 结果。 | 不使用 |
| `test-migrator` | 保留 | Rust 测试与 mapping 的编辑边界、逐场景语义约束不同于生产 Rust 实现，不能与实现角色混用。 | TEST_AND_REPORT 的测试生成或失败场景修复子步骤 |
| `test-semantic-reviewer` | 保留 | 唯一只读、独立的 C/Rust 场景语义比较者。它不修改 tests 或 mapping，避免测试迁移者自己证明自己通过。 | TEST_AND_REPORT 的每轮测试修改后 |

## 3. 四阶段派发矩阵

| 阶段 | primary 必做 | 可调用 subagent | 禁止或不需要的调用 | 交接输入与停止条件 |
|---|---|---|---|---|
| ANALYZE | 选择 C 输入，运行扫描、建模、ABI 提取、Rust API 设计与 ANALYZE gate。 | 无 | `c-analyzer`；任何全文 C/测试/头文件/JSON reader task。 | 不派发。模型与设计工具产物是后续事实源。 |
| IMPLEMENT | 生成 scaffold、执行 layout-only 检查，并决定当前可观察行为缺口。 | `rust-implementer`，仅当指定 Rust 文件与设计义务构成一个有界实现单元时。 | `repairer`；测试角色；要求回传完整 C 或模型摘要的任务。 | 指定 Rust 文件、相关 `rust_api_design.json` 局部事实、允许读取的局部窗口、停止条件“完成一次最小实现即返回”。 |
| VERIFY_AND_REPAIR | 运行 ABI 检查与 `c_cross_validate.py --mode full`，从 `failure-summary.json` 选取一个最小 failure cluster，并在每次修改后复跑。 | `rust-implementer`，每个 cluster 启动新的短 session。 | `repairer`；让 subagent 自行运行 C-Cross、连续调试或宣布成功。 | cluster、失败摘要、必要日志 tail、相关 C/Rust 函数窗口、允许修改文件；停止条件“完成一次最小修复即返回”。 |
| TEST_AND_REPORT | 生成 mapping、运行 placeholder/consistency/cargo/报告与最终 gate。 | `test-migrator` 用于一组明确 scenario 的测试实现或修复；`test-semantic-reviewer` 在每轮测试修改后做独立只读审查。 | 实现角色替代独立审查；任何全量 C tree 或完整 `c_test_model.json` 阅读。 | 迁移者接收 scenario id、模型片段和 C/Rust 局部窗口；审查者接收当前 mapping 与逐 scenario 的局部证据范围。两者均完成一次有界任务即返回。 |

## 4. 上下文与真实性边界

1. `c_api_model.json`、`c_test_model.json`、历史日志与总设计文档均为冷数据；先 `rg` 定位，再读取当前符号或 scenario 的必要片段。
2. 不存在“先读完全部 C 工程，再回传完整总结”的角色。C 输入只能由 ANALYZE 的确定性工具系统性读取一次。
3. 每次 `rust-implementer` 修复只消费一个 failure cluster；primary 根据新验证结果创建新的 session，而不恢复旧 session。
4. `test-semantic-reviewer` 不得编辑测试或 mapping；审查结论必须包含 C/Rust 源码证据，不能由 mapping 自称 coverage 代替。
5. primary 不以“调用过 subagent”作为阶段完成证据。唯一通过依据仍是 ABI probe、真实 C compile/link/run、Rust tests 与最终 gate 的当前产物。

## 5. 审核后的目录目标

```text
02_02/work/
├── agents/
│   └── flashdb-orchestrator.md       # mode: primary
├── subagent/
│   ├── rust-implementer.md           # mode: subagent
│   ├── test-migrator.md              # mode: subagent
│   └── test-semantic-reviewer.md     # mode: subagent
└── skills/
    └── <skill-name>/SKILL.md
```

平台复制时，`work/agents/*.md` 与 `work/subagent/*.md` 应同样映射到运行时 agent 目录，并分别由 `mode: primary`、`mode: subagent` 区分；skills 保持目录加 `SKILL.md` 形式。

## 6. 实施记录

2026-07-16 已完成以下收缩：

1. 删除 `work/subagent/c-analyzer.md` 与 `work/subagent/repairer.md`。
2. 从 `flashdb-orchestrator.md` 的 task 白名单删除这两个名称；VERIFY_AND_REPAIR 的最小 failure cluster 统一派给新的 `rust-implementer` session。
3. 将 C-Cross 中原本回派 `c-analyzer` 的模型或解析异常改为 `primary`，由 primary 重跑确定性分析工具或处理平台问题，避免指向不存在的角色。
4. 更新 `INSTRUCTION.md`、目录回归断言与上下文边界测试，使当前布局固定为 1 主 3 子。

实施后仍须运行 `python3 -m unittest 02_02/tests/test_conversion_system.py`；本次结构调整不运行或修改平台 C 输入、Rust 答案和 `.opencode/`。
