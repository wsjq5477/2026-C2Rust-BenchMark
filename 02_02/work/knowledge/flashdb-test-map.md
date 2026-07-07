# FlashDB 测试映射

## 目的

本文件记录后续 `MIGRATE_TESTS` 检查点使用的测试映射原则。测试覆盖必须从当前 C 输入和模型产物动态推导，不得在 knowledge 中预置固定函数名、固定测试名或固定评分 case 清单。

## Scenario 真相来源

- `BUILD_C_MODEL` 从当前 C 输入中抽取可执行的已注册 scenario 集合，写入 `standard_scenarios`。
- `BUILD_C_MODEL` 可根据当前输入和公开评分证据产出 scorer-facing 覆盖集合，但该集合必须由工具或模型产物生成，不能写死在 knowledge 中。
- Rust 测试和 `rust_test_mapping.json.scenarios` 必须与当前阶段产物中的 scorer-facing 覆盖集合一对一匹配。
- `standard_scenarios` 作为源文件、helper 调用、C API 调用和断言事实的证据；仅凭它不足以证明 scorer coverage。

## 覆盖推导

- 覆盖集合必须来自当前 C 测试注册信息、测试函数事实、断言事实、公开评分证据和阶段模型产物。
- 不得在 knowledge 中列出固定 case 名；新增、缺失或变化的 C 测试应通过模型产物反映到迁移计划。
- 每个迁移 scenario 都应保留来源证据，包括源测试、相关 C API 调用、helper 行为和断言意图。
- 如果某个 C 测试无法直接映射，应在 mapping 产物中标明 unmapped 原因，而不是静默删除或用占位测试替代。

## 高风险语义

- 对涉及持久化、删除、清理/回收、容量变化、迭代顺序、时间范围、状态变更和控制接口的测试，应优先保留完整语义证据。
- 高风险 obligations 必须从 C 测试事实、断言、helper 调用和评分证据中抽取，不能在 knowledge 中按固定函数名列举。
- 若测试事实体现重启恢复、地址/偏移变化、跨 sector 行为、状态枚举或边界查询，Rust 测试必须保留这些可观察语义。

## 映射原则

- Rust tests 必须保留 C test intent，而不是逐行复刻语法。
- 每个迁移后的 scenario 都必须包含有意义的断言。
- 生成的 baseline tests 会标记为 `MIGRATION_PENDING`，不计入 semantic coverage。
- 只有当 scenario 的 `semantic_obligations` 已反映到 Rust test 且复制到 `validated_obligations` 后，才能使用 `coverage: semantic`。
- coverage 维度必须由当前 C API 分组和测试事实推导，不能用固定函数清单代替。
- stage gate 必须在缺失、pending、重复、额外、unmapped 或 semantic 标记缺少 validated obligations 时失败。

第一个 framework checkpoint 不迁移测试。
