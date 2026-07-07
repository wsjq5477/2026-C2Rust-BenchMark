以下是我跑用例遇到的问题，分析下怎么优化。
# FlashDB C-to-Rust 转换工程优化 Todolist

> 基于 run_1 / run_3 / run_4 三次评分报告分析，聚焦**转换流程和工具链**的改进。

---

## 一、语义义务提取粒度不足（build_c_model.py）

### 1. 语义义务没有提取"断言验证了什么属性"

- **问题描述**: 用例 `kvdb_init`(case_1) 三次评分中有两次失败，原因都是 Rust 测试只检查了 `get 返回 None`，而 C 测试还验证了 `oldest_addr 对齐` 和 `fdb_kvdb_control 设置步骤`。但 `semantic_obligations` 里只有 `calls:fdb_kvdb_init` 和 `assertion_intent`，没有 "must_verify_oldest_addr_alignment" 和 "must_use_control_interface" 这样的义务，所以 agent 认为只要调了 init + 有 assert 就满足了。同理 `del_kv`(case_7) 的 C 测试验证了 `oldest_addr 对齐 + reboot 持久性`，但义务里没有这些，agent 就只写了 `assert!(get 返回 None)`。
- **根因**: `semantic_obligations_from_facts()` 只做了语法级提取（"调了哪些函数"、"有没有 assert 宏"），没有分析断言的具体验证目标。一个 `assert(addr % sec_size == 0)` 和一个 `assert(result.is_none())` 在义务层面都只是 `assertion_intent`，无法区分。
- **优化方案**: 在 `build_c_model.py` 中增强断言语义提取：
  1. 解析 assert 宏中的比较表达式，提取验证目标关键词（如 `addr`/`oldest_addr` → `obligation: "verify_addr_alignment"`，`init_ok` → `obligation: "verify_init_state"`）
  2. 检测 C 测试中通过 control 接口设置参数的模式 → `obligation: "use_control_interface"`
  3. 检测 reboot/reload 验证模式 → `obligation: "verify_persistence_after_reboot"`

### 2. 语义义务没有提取"测试数据规模和布局"

- **问题描述**: `gc`(case_9/10) 三次都失败，C 测试用 4 阶段 KV 表（kv0-kv3）精确驱动 GC 流程，`gc2` 用 6 个 KV + 3×value_len 大 blob 触发跨 sector GC。但 `semantic_obligations` 里只有 `gc` 和 `calls:fdb_kvdb_set` 标签，没有"需要 4 个以上 KV"和"需要大 blob 跨 sector"的义务。Agent 用 1 个小 KV 就满足了现有义务。`tsl_iter_by_time`(case_19) 同理，C 用精心计算的 TSL 数量确保跨 5 个 sector，义务里没有"需要跨 sector 边界"的要求。
- **根因**: 提取逻辑不分析测试数据的规模特征（KV 数量、blob 大小、TSL 数量是否跨越 sector 边界）
- **优化方案**: 增加数据规模义务提取：
  1. 统计测试中 set/kv_set_blob 调用次数，如果 ≥ N → `obligation: "multi_kv_count:N"`
  2. 检测 blob 大小参数是否超过 sector 大小 → `obligation: "cross_sector_blob"`
  3. 统计 TSL append 数量与 sector 容量的关系 → `obligation: "cross_sector_tsl_count:N"`

### 3. 语义义务没有提取"测试场景完整性"

- **问题描述**: `tsl_set_status`(case_22) 在 run_1 和 run_4 都失败，C 测试设置了 `USER_STATUS1 + DELETED` 两种状态并按状态过滤计数，Rust 只设了单个 TSL 的 `UserStatus1`。`tsl_iter_reverse`(case_18) 在 run_1 和 run_3 失败，C 有反向迭代验证，Rust 完全没有。`tsdb_control`(case_23) 在 run_1 和 run_3 失败，C 测试 7KB/8KB/9KB 大 blob，Rust 只用小数据。这些缺失场景在义务层面都没有体现——义务只说了 `iter` 和 `set_status`，没说"必须测试反向迭代"和"必须测试多状态组合"和"必须测试大 blob"。
- **根因**: 行为标签太粗粒度，`iter` 包含正向/反向/按时间/跨 sector 等多种子场景，但只生成一个 `iter` 义务
- **优化方案**: 细化行为标签：
  1. 从 C 测试函数名和调用模式推断子场景：`iter` → `iter_forward` + `iter_reverse` + `iter_by_time` + `iter_cross_sector`
  2. 从 set_status 调用参数推断状态组合：`set_status(USER_STATUS1)` + `set_status(DELETED)` → `obligation: "verify_multi_status_filter"`
  3. 从 append 大小参数推断：大 blob → `obligation: "verify_large_blob_persistence"`

---

## 二、Rust API 设计缺少测试所需的观察接口（design_rust_api.py）

### 4. 没有为 C 测试中的内部状态访问设计 Rust 等价接口

- **问题描述**: 多个用例失败的根本原因是 Rust 无法验证 C 测试验证的内部状态：`kvdb_init`/`del_kv`/`gc`/`gc2` 都验证了 `oldest_addr`，但 Rust 没有 `oldest_addr()` 观察方法；`kvdb_deinit` 验证了 `init_ok=false`，但 Rust 没有 `is_initialized()` 方法；`scale_up` 需要动态改变扇区数量，但 Rust 的 init 接口不支持。不是 agent 不想验证，而是 Rust API 根本没有暴露这些状态。
- **根因**: `design_rust_api.py` 只转换了 C 的 public API（fdb_kvdb_init → Kvdb::init），没有分析 C 测试中访问的内部字段和 control 接口，没有为测试需要设计对应的观察方法
- **优化方案**: 在 `design_rust_api.py` 中增加测试观察接口生成：
  1. 分析 C 测试中通过 `fdb_kvdb_control` 设置的参数 → 生成 Rust 的 builder/config 接口
  2. 分析 C 测试中直接读取的内部字段（`db->oldest_addr`、`db->init_ok`、sector 状态）→ 生成 `pub fn oldest_addr()` / `pub fn is_initialized()` / `pub fn sector_status()` 等观察方法
  3. 分析 C 测试中的扇区数量变化模式 → 生成 `Kvdb::reinit()` 或 `Kvdb::resize()` 接口
  4. 将这些接口加入 `rust_api_design.json` 的 `test_api` 部分，标记为 `test_observable: true`

### 5. storage_model 没有约束后端实现方式

- **问题描述**: 三次运行产生了三种不同的存储后端：run_1 用 MemFlash（纯内存）、run_3 用文件 I/O（性能只有 C 的 16-41%）、run_4 用 HashMap+文件序列化（架构与 C 完全不同）。C 的 benchmark 用的是 `FDB_USING_FILE_POSIX_MODE`（每个 sector 一个 POSIX 文件），性能数据本应可比，但因为 Rust 后端不一致导致无法公平比较。
- **根因**: `design_rust_api.py` 的 `storage_model` 只声明了三个语义要求（`record_append`, `reload_scan`, `retain_valid_records`），没有从 C 代码中提取后端实现约束
- **优化方案**: 在 `design_rust_api.py` 中：
  1. 检测 C 代码中的 `FDB_USING_FILE_POSIX_MODE` → 在 storage_model 中加入 `backend: "file_sector_mode"` 强制约束
  2. 提取 C 的扇区文件命名模式（`{dir}/{name}.fdb.{index}`）→ 加入 `sector_file_pattern`
  3. 提取 C 的文件描述符缓存机制 → 加入 `fd_cache_required: true`
  4. 在 `rust_api_design.json` 中增加 `storage_constraints` 字段，REWRITE 阶段必须遵守

---

## 三、MIGRATE_TESTS 阶段 agent 指导不足

### 6. test-migrator 缺少"禁止简化"的具体约束

- **问题描述**: `test-migrator.md` 说了 "Must NOT weaken assertions"，但 agent 理解为"只要调了对应 API + 有 assert 就行"。结果 `gc` 测试只写了 `assert!(kv.get("key").is_some())`，`tsl_set_status` 只设了单个 TSL 的一个状态，`tsl_iter_by_time` 只用 3 条记录。这些在 agent 看来都没有"削弱"——它确实调了 gc、设了 status、做了 iter——只是验证深度远不如 C。
- **根因**: "不削弱"的约束太模糊，agent 无法区分"调用了 API"和"验证了 API 的正确行为"
- **优化方案**: 在 `test-migrator.md` 中增加具体约束：
  1. 每条 `semantic_obligation` 必须对应一条**具体断言**，不能只是 `is_ok()` / `is_some()` / `is_none()`
  2. 如果 C 测试的 `assertion_count` 为 N，Rust 测试的断言数量不得少于 N 的 50%
  3. 如果义务包含 `verify_*` 前缀（来自 #1 的改进），必须有一条断言直接验证该属性

### 7. SKILL.md 的 "coverage: semantic" 标准太低

- **问题描述**: `flashdb-test-migration/SKILL.md` 定义 `coverage: semantic` 的条件是 `validated_obligations ⊇ semantic_obligations`，但由于 obligations 本身粒度太粗（见 #1-3），"semantic" 标签不能保证测试深度。gate 通过了，评分却大量失败。
- **根因**: 语义覆盖的定义只看义务集合的包含关系，不看义务本身的充分性
- **优化方案**: 在 SKILL.md 中增加验证深度分级：
  1. L1（API 调用覆盖）：Rust 测试调用了 C 测试对应的所有 API — 当前 semantic 标准
  2. L2（断言意图覆盖）：Rust 测试的断言验证了与 C 测试相同的属性 — 新增
  3. L3（数据规模覆盖）：Rust 测试使用了与 C 测试等价的数据规模和布局 — 新增
  4. `coverage: semantic` 必须达到 L2，`coverage: deep_semantic` 达到 L3

---

## 四、gate.py 验证逻辑漏洞

### 8. gate 不检查测试代码的实际断言深度

- **问题描述**: `check_migrate_tests()` 只验证 `validated_obligations ⊇ semantic_obligations` 和文件中没有 `MIGRATION_PENDING`。Agent 可以写 `assert!(true)` 就满足 gate，而评分时才发现测试逻辑不一致。gate 通过和评分通过之间存在巨大鸿沟。
- **根因**: gate 验证的是映射元数据（JSON 字段），不是测试代码质量（Rust 源码内容）
- **优化方案**: 在 gate.py 的 `check_migrate_tests()` 中增加 Rust 测试代码静态检查：
  1. 解析 Rust 测试文件，提取每个 `#[test]` 函数中的 `assert!` / `assert_eq!` / `assert_ne!` 数量
  2. 与 C 测试的 `assertion_count` 对比：Rust 断言数量 < C 的 50% 则 gate 失败
  3. 检测空壳断言模式：如果 `assert!(x.is_ok())` / `assert!(x.is_some())` 占比超过 70% 则警告

### 9. BUILD_TEST_REPAIR 不验证测试语义

- **问题描述**: BUILD_TEST_REPAIR 只运行 `cargo test` 确保通过，不检查通过的测试是否验证了正确的东西。`gc2` 在 run_3 实际运行报错 `SavedFull("no sector available")`，说明 GC 实现有 bug，但 repairer 只关注编译和运行时通过，没有发现"GC 逻辑错误"这个更深层的实现问题。
- **根因**: 修复阶段的标准是"cargo test 通过"，而不是"测试验证了正确的行为"
- **优化方案**: 在 BUILD_TEST_REPAIR 阶段增加测试质量检查：
  1. 如果 `cargo test` 有测试 panic 或返回 Err，除了修编译，还要分析 panic 原因是否是**实现逻辑错误**（如 GC sector 分配失败）而非测试代码错误
  2. 对 panic 原因分类：编译错误 / 测试断言失败 / 实现逻辑错误，分别走不同的修复路径
  3. 实现逻辑错误应反馈到 REWRITE_CORE_MODULES 重新生成，而非在 repair 阶段打补丁

---

## 五、Pipeline 执行效率

### 10. REWRITE_CORE_MODULES 阶段上下文耗尽

- **问题描述**: Run 1 在阶段 6 因上下文窗口耗尽中断，需要 4 次 context continuation 才完成。前 5 阶段累积的上下文（跑工具、写日志、反复修 workflow_state.json）+ 阶段 6 一次性读取全部 C 源码（~4000 行）超出窗口。
- **根因**: Pipeline 没有上下文预算管理，agent 无节制地读取文件；前 5 阶段的操作对阶段 6 没有信息价值但占据了大量上下文
- **优化方案**:
  1. 在 INSTRUCTION.md 中指示 REWRITE_CORE_MODULES 使用并行子代理：每个子代理只读一个 C 模块，在独立上下文中写 Rust 代码，主代理只做合并和编译修复
  2. 前 5 阶段精简指令：合并 Bash 命令，一次写完 workflow_state.json + 日志，减少反复读写
  3. 在 `build_c_model.py` 中预生成精简 API 摘要（函数签名 + 语义描述，不含实现细节），REWRITE 阶段读摘要而非原始 C 代码

### 11. Linter/Hook 覆写 agent 写入的文件

- **问题描述**: Run 1 中 agent 写入的 Rust 文件被外部 hook 完全覆写，代码结构从 `Kvdb`/`Tsdb`/`Storage` 变成了 `KvDb`/`TsDb`/`FlashStorage` trait，agent 需要额外回合修复。
- **根因**: Write tool 触发了 linter/hook，执行了超出 rustfmt 格式化的重构操作
- **优化方案**: 在 INSTRUCTION.md 中增加防护指令：
  1. 写入文件后立即读取验证内容是否被篡改
  2. 如果被篡改，改用 Bash heredoc 写入（绕过 hook）
  3. 或排查 hook 配置，限制为只做 rustfmt

---

## 六、评分与 pipeline 的语义鸿沟

### 12. 评分标准远严于 gate 标准，但 pipeline 内部无法感知

- **问题描述**: gate.py 的 MIGRATE_TESTS 检查只看 obligations 数量匹配和 MIGRATION_PENDING 清除，评分工具则逐用例对比断言深度、数据规模、sector 边界。Run 3 和 Run 4 都是 gate 全部通过（19/24 pass），但评分显示 gc/gc2/scale_up 等用例的测试逻辑与 C 不一致。Pipeline 内部没有机制发现这个问题。
- **根因**: gate 是 pipeline 的"最低门槛"，评分是外部的"实际质量"，两者标准脱节
- **优化方案**: 将评分标准前置到 pipeline 中：
  1. 将评分 skill 中的用例一致性检查逻辑提取为独立 Python 工具 `test_consistency_check.py`
  2. 在 REPORT_AND_VERIFY 阶段运行此工具，作为 pipeline 内部预评分
  3. 如果预评分发现 logic_mismatch，回退到 MIGRATE_TESTS 阶段修复，而非直接提交

### 13. 评分工具对"缺少用例"的判定与 pipeline 映射不一致

- **问题描述**: Run 3 中 `tsl_append_by_time`(case_16)、`tsl_iter_reverse`(case_18)、`tsdb_control`(case_23) 被评为"C 原项目无此测试函数 — 场景缺失"，但这些 case 在 pipeline 中是有映射的（来自 C 测试中的子场景）。评分工具用固定的 case 名称去 C 代码中找同名函数，找不到就判"缺失"，但 pipeline 生成的 case 可能映射到不同的 C 函数。
- **根因**: 评分工具和 pipeline 对"一个 case 对应哪个 C 函数"的理解不一致
- **优化方案**: 在 `build_c_model.py` 输出 `scorer_standard_cases` 时，同时输出每个 case 对应的 C 源函数名和行号范围；评分工具应使用这个映射而非自行推断

---

## 优化优先级

| 优先级 | 编号 | 问题 | 改动位置 | 预期收益 |
|--------|------|------|----------|----------|
| **P0** | #1 | 义务缺少断言验证目标 | `build_c_model.py` | 解决 kvdb_init/del_kv 等 assertion 类失败 |
| **P0** | #2 | 义务缺少数据规模 | `build_c_model.py` | 解决 gc/gc2/tsl_iter_by_time 数据规模类失败 |
| **P0** | #3 | 义务缺少场景完整性 | `build_c_model.py` | 解决 tsl_set_status/tsl_iter_reverse/tsdb_control 场景缺失 |
| **P0** | #4 | API 缺少测试观察接口 | `design_rust_api.py` | 让 agent 能验证 oldest_addr/init_ok/sector_status |
| **P0** | #5 | storage 缺少后端约束 | `design_rust_api.py` | 统一后端实现，性能数据可比 |
| **P1** | #6 | test-migrator 约束模糊 | `test-migrator.md` | 明确禁止简化的具体标准 |
| **P1** | #7 | semantic 覆盖标准太低 | `flashdb-test-migration/SKILL.md` | 建立 L1/L2/L3 分级 |
| **P1** | #8 | gate 不检查断言深度 | `gate.py` | 提前发现浅层测试 |
| **P1** | #12 | 评分与 gate 鸿沟 | 新增 `test_consistency_check.py` | pipeline 内闭环 |
| **P2** | #9 | repair 不验证语义 | `cargo_capture.py` + repair skill | 区分实现 bug 和测试 bug |
| **P2** | #10 | 上下文耗尽 | `INSTRUCTION.md` + orchestrator | 提升 pipeline 稳定性 |
| **P2** | #11 | Linter 覆写 | `INSTRUCTION.md` | 减少无效回合 |
| **P2** | #13 | 评分映射不一致 | `build_c_model.py` + 评分 skill | 消除判定歧义 |

