# Q6：Rust 测试为空实现问题修复方案

## 0. 审定后的实施约束（2026-07-13）

本方案实施时以下审定结论优先于后文中的原始建议：

1. 不新增全局 `REWRITE_TESTS` 或 `TEST_REPAIR` 阶段；真实测试重写属于现有 `MIGRATE_TESTS`，编译、运行、归因和修复属于现有 `BUILD_TEST_REPAIR`，系统性测试迁移问题回派 `test-migrator`。
2. `gate.py` 只校验结构化事实，不承担流程路由；回派和预算耗尽后的继续动作由 orchestrator 决定。
3. 无论 Rust 测试最终是否全部修复，达到预算后都必须如实记录状态并继续 `REPORT_AND_VERIFY`，确保生成 `result/` 下的比赛产物；失败不得伪报成功。
4. suite、场景名和场景总数全部从当前 C 模型及 `scorer_standard_cases` 动态推导，工具和契约不得硬编码 24、13、11 或固定 case 清单。
5. `migrate_tests.py` 只生成测试迁移任务映射，不创建或覆盖 Rust 测试文件，也不生成 `todo!()` 等占位函数；真实测试由 `test-migrator` 直接编写。
6. `placeholder_check.py` 只执行确定性检查；操作与断言的语义对应关系由 `test_consistency_check.py` 根据 mapping、obligation 和 evidence 检查。

后文提到的新增全局阶段、gate 路由、固定 24 个场景以及生成 `todo!()` baseline 的内容均不再作为实施要求。

## 1. 文档目的

本方案用于修复 C-to-Rust 自动迁移流水线中 Rust 测试仅生成占位符、`cargo test` 假通过、测试一致性检查结果被忽略的问题。

本次修复的核心目标是：

1. Rust 测试必须真实调用迁移后的 Rust 实现。
2. Rust 测试必须保留对应 C 测试的关键验证语义。
3. `cargo test` 通过不能再单独代表测试迁移成功。
4. 测试一致性检查失败后必须自动进入修复流程。
5. 任何测试失败都不能中断整个比赛流水线。
6. 达到修复预算后仍未解决的问题必须真实记录，不能伪报成功。
7. C-Cross 与 Rust 测试一致性必须分别评价，不能相互替代。

---

# 2. 问题说明

## 2.1 问题现象

在五次评分运行中，Run 3 和 Run 5 使用 `manual_rust` 策略，即 Strategy B。

Strategy B 检查迁移后的 Rust 测试是否与原始 C 测试保持语义一致，最终发现所有 Rust 测试均没有实际验证 FlashDB 功能：

* Rust 测试不调用 FlashDB Rust API；
* 不验证返回值；
* 不验证数据读写结果；
* 不验证数据库状态变化；
* 不验证地址对齐、删除、GC、迭代等场景；
* 每个测试只检查一个固定字符串是否非空；
* 测试语义上等价于 `assert!(true)`。

因此，虽然 `cargo test` 显示全部测试通过，但 Strategy B 判定测试逻辑全部不一致，评分结果为：

```text
0/24 passed
```

测试数量应统一核实为 24 个，避免文档中同时出现 23 和 24 两种统计口径。

---

## 2.2 当前占位测试示例

当前 `migrate_tests.py` 生成的代码类似：

```rust
fn exercise_kvdb_scenario(name: &str) {
    assert!(!name.is_empty());
}

#[test]
fn kvdb_test_fdb_kvdb_init() {
    // MIGRATION_PENDING: replace baseline coverage with the C scenario semantics.
    exercise_kvdb_scenario("test_fdb_kvdb_init");
}
```

由于传入参数是固定非空字符串：

```rust
"test_fdb_kvdb_init"
```

所以：

```rust
assert!(!name.is_empty());
```

实际是恒真断言，不具备任何测试价值。

---

## 2.3 当前错误状态链路

当前流水线的问题链条如下：

```text
migrate_tests.py 生成占位测试
        ↓
没有阶段真正重写 Rust 测试
        ↓
cargo test 执行恒真断言并全部通过
        ↓
test_consistency_check.py 检测到大量问题
        ↓
一致性检查结果没有参与最终状态判断
        ↓
workflow_state.json 将 test_status 标记为 pass
        ↓
C-Cross 部分通过被用于解释 Rust 测试问题
        ↓
最终报告错误地认为测试迁移已经完成
        ↓
Strategy B 独立检查 Rust 测试语义，最终得到 0 分
```

---

# 3. 根因分析

## 3.1 `migrate_tests.py` 职责设计错误

当前 `migrate_tests.py` 同时承担以下职责：

* 创建 Rust 测试文件；
* 生成测试函数；
* 表示测试迁移已经完成。

但实际上，它只具备生成测试框架的能力，不具备完整重建 C 测试语义的能力。

完整 Rust 测试需要理解：

* 原始 C 测试代码；
* 测试 fixture；
* FlashDB 初始化参数；
* 操作顺序；
* 输入数据；
* 回调函数；
* 宏展开结果；
* C API 和 Rust API 的映射关系；
* Rust 实现当前暴露的接口；
* 编译错误和运行结果；
* 中间状态和最终断言。

这些内容不能通过简单的字符串模板稳定生成。

因此，`migrate_tests.py` 应定位为：

> 测试场景映射和脚手架生成器。

而不是：

> 完整 Rust 语义测试生成器。

---

## 3.2 缺少正式的测试重写阶段

当前流水线中虽然存在 `07-migrate-tests`，但这个阶段实际只完成了测试函数框架生成。

没有明确阶段负责：

* 读取原始 C 测试；
* 读取 `rust_test_mapping.json`；
* 理解 `semantic_facts`；
* 检查 Rust API；
* 编写真实 Rust 测试；
* 运行测试；
* 根据编译或运行错误持续修复。

测试迁移实际上处于未完成状态，但被错误标记为完成。

---

## 3.3 质量门只检查执行结果，不检查测试价值

当前状态判断过度依赖：

```bash
cargo test
```

但 `cargo test` 只能证明：

* 测试代码可以编译；
* 测试函数可以运行；
* 现有断言没有失败。

它不能证明：

* 测试调用了被测实现；
* 测试覆盖了 C 测试语义；
* 断言依赖实际执行结果；
* 测试不是占位符；
* 测试能发现实现错误。

因此，仅凭 `cargo test` 返回码设置：

```json
{
  "test_status": "pass"
}
```

属于错误状态建模。

---

## 3.4 一致性检查结果被忽略

`test_consistency_check.py` 已经发现问题，并生成：

```json
{
  "status": "fail",
  "issue_count": 38
}
```

但后续阶段仍然记录：

```text
test_consistency_check.py：通过，0 个问题
```

这说明当前流程存在以下至少一种问题：

1. 没有读取真实的检查结果文件；
2. 读取了错误路径下的旧结果；
3. 仅执行脚本但没有检查退出结果；
4. Agent 根据预期结果生成了错误报告；
5. `workflow_state.json` 没有绑定一致性检查结果；
6. 报告阶段允许人工语言覆盖机器结果。

---

## 3.5 C-Cross 与 Rust 测试职责混淆

C-Cross 验证的是：

> 原始 C 测试是否可以通过 FFI 或兼容层调用 Rust 实现，并验证 Rust 实现的行为兼容性。

Strategy B 验证的是：

> 新生成的 Rust 测试是否保留了原始 C 测试的操作和断言语义。

两者关注点不同：

| 机制         | 验证对象                   |
| ---------- | ---------------------- |
| C-Cross    | Rust 实现是否兼容原始 C 行为     |
| Rust 测试一致性 | Rust 测试是否正确迁移原始 C 测试语义 |
| cargo test | 当前 Rust 测试是否编译并执行通过    |

所以：

```text
C-Cross 通过
```

不能推导出：

```text
Rust 测试迁移完成
```

---

# 4. 解决思路

本次修复采用以下总体思路：

## 4.1 将测试生成拆成三个职责

### 第一层：测试场景建模

由现有分析脚本负责：

* 切分 C 测试场景；
* 提取调用函数；
* 提取断言；
* 提取操作顺序；
* 提取关键语义义务；
* 记录 C 测试与 Rust 测试映射。

主要产物：

```text
rust_test_mapping.json
semantic_facts
semantic_obligations
assertion_evidence
```

### 第二层：完整测试重写

由 REWRITE Agent 完成：

* 读取 C 测试源码；
* 读取测试场景模型；
* 读取 Rust 实现和公共 API；
* 生成完整 Rust 测试；
* 编译和运行；
* 迭代修复。

### 第三层：一致性检查和自动修复

由检查脚本和 TEST_REPAIR Agent 完成：

* 检查占位符；
* 检查 API 调用；
* 检查断言证据；
* 检查语义义务覆盖；
* 检查测试运行结果；
* 对失败场景进行定向修复。

---

## 4.2 将“阻塞门”改成“强制路由门”

比赛流水线不得因为测试失败而终止。

因此一致性检查失败后的行为不能是：

```text
fail → exit
```

而应是：

```text
fail
  ↓
强制进入 TEST_REPAIR
  ↓
重新检查
  ↓
达到修复次数或 Token 预算上限
  ↓
标记 degraded
  ↓
继续后续 C-Cross、评分、报告和产物交付
```

质量门负责：

* 禁止错误状态被记录为成功；
* 强制触发修复；
* 保存未解决问题；
* 不允许中止整个比赛执行。

---

## 4.3 分离测试的多个状态

需要将原来的单一状态：

```json
{
  "test_status": "pass"
}
```

拆分成：

```json
{
  "rust_test": {
    "rewrite_status": "completed",
    "compile_status": "pass",
    "execution_status": "pass",
    "placeholder_status": "pass",
    "semantic_consistency_status": "pass",
    "overall_status": "pass"
  }
}
```

这样可以准确区分：

* Rust 测试是否已经完成重写；
* 是否可以编译；
* 是否执行通过；
* 是否包含占位符；
* 是否覆盖 C 测试语义；
* 整体测试迁移是否完成。

---

# 5. 优化后的总体流程

优化后的测试迁移流程如下：

```text
C 测试解析
    ↓
生成 rust_test_mapping.json
    ↓
生成测试场景脚手架
    ↓
REWRITE_TESTS
    ├── 读取 C 测试
    ├── 读取 semantic_facts
    ├── 读取 Rust API
    ├── 生成完整 Rust 测试
    └── 清除所有占位符
    ↓
PLACEHOLDER_CHECK
    ↓
cargo test --no-run
    ↓
cargo test
    ↓
TEST_CONSISTENCY_CHECK
    ↓
┌──────────────────────────────┐
│ 全部通过                      │
│ rust_test.overall_status=pass │
└──────────────────────────────┘
    ↓
继续 C-Cross

任意检查失败
    ↓
TEST_REPAIR
    ↓
重新执行：
    ├── PLACEHOLDER_CHECK
    ├── cargo test --no-run
    ├── cargo test
    └── TEST_CONSISTENCY_CHECK
    ↓
达到修复预算仍失败
    ↓
rust_test.overall_status=degraded
    ↓
记录 unresolved issues
    ↓
继续 C-Cross 和最终报告
```

---

# 6. 详细解决方案

## 6.1 修改 `migrate_tests.py`

### 6.1.1 修改目标

`migrate_tests.py` 不再生成能够假通过的恒真测试。

它只负责：

* 创建 Rust 测试文件；
* 创建测试函数名称；
* 添加场景元数据；
* 建立 C/Rust 场景映射；
* 明确标记测试尚未完成；
* 为 REWRITE_TESTS 提供任务入口。

### 6.1.2 删除当前恒真辅助函数

删除类似：

```python
fn exercise_{suite}_scenario(name: &str) {
    assert!(!name.is_empty());
}
```

禁止生成任何基于固定字符串的断言。

### 6.1.3 推荐生成方式

可以生成显式待实现代码：

```rust
#[test]
fn kvdb_test_fdb_kvdb_init() {
    todo!("REWRITE_TESTS must implement scenario: test_fdb_kvdb_init");
}
```

但要注意：

* `todo!()` 只能作为 REWRITE_TESTS 的输入；
* 在进入正式测试验证前必须全部清除；
* 不能在最终提交产物中保留；
* 不能将包含 `todo!()` 的测试状态记录为成功。

另一种更安全的方式是不创建函数体，只生成任务描述文件：

```json
{
  "scenario_id": "test_fdb_kvdb_init",
  "suite": "kvdb",
  "rust_test_file": "tests/kvdb_tests.rs",
  "rust_test_name": "kvdb_test_fdb_kvdb_init",
  "implementation_status": "pending"
}
```

再由 REWRITE_TESTS Agent 创建完整测试。

### 6.1.4 扩展映射状态

在 `rust_test_mapping.json` 中，为每个场景增加：

```json
{
  "scenario_id": "test_fdb_kvdb_init",
  "suite": "kvdb",
  "c_test_file": "tests/fdb_kvdb_tc.c",
  "rust_test_file": "tests/kvdb_tests.rs",
  "rust_test_name": "kvdb_test_fdb_kvdb_init",
  "implementation_status": "pending",
  "compile_status": "unknown",
  "execution_status": "unknown",
  "consistency_status": "unknown",
  "repair_attempts": 0,
  "unresolved_issues": []
}
```

`implementation_status` 可使用：

```text
pending
implemented
repairing
validated
degraded
```

---

## 6.2 重构 `07-migrate-tests` 阶段

### 6.2.1 当前问题

当前阶段生成占位符后就声明：

```text
MIGRATION_PENDING 标记已全部移除
```

但实际文件中仍然存在该标记。

### 6.2.2 修改后的阶段职责

建议将该阶段改名或拆分为：

```text
07-build-test-model
08-rewrite-tests
```

如果不希望调整阶段编号，也可以在原阶段内明确区分两个子步骤：

```text
07-migrate-tests
├── 07.1 build-test-scaffold
└── 07.2 rewrite-semantic-tests
```

### 6.2.3 REWRITE_TESTS 输入

REWRITE_TESTS Agent 必须读取：

1. 原始 C 测试文件；
2. `rust_test_mapping.json`；
3. 每个场景的 `semantic_facts`；
4. `semantic_obligations`；
5. `assertion_evidence`；
6. Rust 实现源码；
7. Rust crate 导出的公共 API；
8. 已有 fixture、mock storage 和测试工具；
9. `Cargo.toml`；
10. 上一次编译和测试错误。

### 6.2.4 REWRITE_TESTS 输出要求

每个 Rust 测试必须至少包含：

* 被测 Rust API 调用；
* 与原始 C 测试对应的操作序列；
* 对执行结果的有效断言；
* 对关键状态或数据的验证；
* 必要的初始化和清理逻辑。

示例：

```rust
#[test]
fn kvdb_test_fdb_kvdb_init() {
    let storage = create_test_storage();
    let mut db = KvDb::new(storage);

    db.set_sector_size(TEST_SECTOR_SIZE)
        .expect("set sector size failed");

    db.init().expect("kvdb init failed");

    assert!(db.is_initialized());
    assert_eq!(db.oldest_addr() % TEST_SECTOR_SIZE, 0);
}
```

具体 API 以实际 Rust 实现为准，不要求与 C API 同名，但验证语义必须等价。

---

## 6.3 新增 `placeholder_check.py`

### 6.3.1 目的

在执行正式测试前，检查 Rust 测试中是否仍存在明显占位实现。

### 6.3.2 检查对象

扫描：

```text
flashDB_rust/tests/**/*.rs
```

必要时也扫描：

```text
flashDB_rust/src/**/*test*.rs
```

### 6.3.3 基础规则

检查以下模式：

```rust
assert!(true)
assert_eq!(1, 1)
assert_ne!(1, 0)
todo!()
unimplemented!()
panic!("MIGRATION_PENDING")
assert!(!"literal".is_empty())
```

检查以下注释：

```text
MIGRATION_PENDING
PLACEHOLDER
replace baseline coverage
TODO: implement semantic test
dummy test
```

### 6.3.4 语义型占位检查

仅靠正则不够，还应增加基础结构检查。

对于每个 Rust 测试函数：

1. 是否调用目标 crate 或目标 API；
2. 是否存在断言；
3. 断言是否引用被测操作的结果；
4. 是否只对常量、字面量或测试名称断言；
5. 是否只有初始化，没有结果验证；
6. 是否直接无条件返回；
7. 是否用 `#[ignore]` 跳过。

例如以下代码仍应判定为失败：

```rust
#[test]
fn test_set() {
    let result = db.set("key", b"value");
    assert!(true);
}
```

因为断言没有使用 `result`。

### 6.3.5 输出格式

生成：

```text
logs/trace/test-placeholder-check.json
```

建议格式：

```json
{
  "status": "fail",
  "issue_count": 2,
  "issues": [
    {
      "code": "literal_only_assertion",
      "file": "tests/kvdb_tests.rs",
      "test_name": "kvdb_test_fdb_kvdb_init",
      "message": "Assertion only checks a string literal and does not depend on the tested operation."
    }
  ]
}
```

状态只能是：

```text
pass
fail
error
```

---

## 6.4 增强 `test_consistency_check.py`

### 6.4.1 检查重点

一致性检查不能只依赖断言数量。

断言数量只能作为辅助信号，不能作为主要判断依据。

需要重点检查：

1. C 场景中的关键函数是否有对应 Rust 操作；
2. C 场景中的断言目标是否在 Rust 测试中被验证；
3. `semantic_obligations` 是否有对应证据；
4. 操作顺序是否保持；
5. 返回值是否被检查；
6. 数据写入后是否被读取验证；
7. 状态转换是否被验证；
8. 错误和边界场景是否保留；
9. 测试是否依赖真实运行结果；
10. 测试是否被跳过或弱化。

### 6.4.2 增加 obligation evidence

每项语义义务应记录证据，例如：

```json
{
  "obligation": "must_verify_oldest_addr_alignment",
  "status": "covered",
  "evidence": {
    "rust_test_file": "tests/kvdb_tests.rs",
    "rust_test_name": "kvdb_test_fdb_kvdb_init",
    "line": 38,
    "expression": "assert_eq!(db.oldest_addr() % TEST_SECTOR_SIZE, 0)"
  }
}
```

如果没有证据：

```json
{
  "obligation": "must_verify_oldest_addr_alignment",
  "status": "missing",
  "evidence": null
}
```

### 6.4.3 检查结果必须成为事实来源

后续报告不得自行描述检查是否通过。

必须读取：

```text
logs/trace/test-consistency.json
```

并直接使用其中：

```json
{
  "status": "fail",
  "issue_count": 38
}
```

禁止报告阶段把 `fail` 改写成“通过”。

---

## 6.5 新增 TEST_REPAIR 阶段

### 6.5.1 触发条件

满足以下任一条件时进入 TEST_REPAIR：

```text
placeholder_status != pass
compile_status != pass
execution_status != pass
semantic_consistency_status != pass
```

### 6.5.2 修复输入

TEST_REPAIR Agent 每轮读取：

* 当前 Rust 测试；
* 对应 C 测试；
* `rust_test_mapping.json`；
* `test-placeholder-check.json`；
* `test-consistency.json`；
* `cargo test --no-run` 错误；
* `cargo test` 失败输出；
* Rust 实现代码；
* 已有测试工具。

### 6.5.3 修复方式

必须逐场景修复，不允许通过批量增加无意义断言绕过检查。

单个场景的修复过程：

```text
读取 scenario_id
    ↓
定位 C 测试代码
    ↓
读取 semantic obligations
    ↓
定位当前 Rust 测试
    ↓
判断缺失的操作、初始化和断言
    ↓
修改 Rust 测试
    ↓
执行定向测试
    ↓
执行一致性检查
```

建议优先运行单用例：

```bash
cargo test kvdb_test_fdb_kvdb_init -- --nocapture
```

单用例通过后再运行完整测试：

```bash
cargo test --all -- --nocapture
```

### 6.5.4 修复次数限制

为避免无限循环，应设置修复预算，例如：

```json
{
  "max_test_repair_rounds": 3
}
```

也可以基于：

* 总轮数；
* 每个场景最大轮数；
* Token 预算；
* 总工具调用次数。

达到上限后：

* 不得终止流水线；
* 将未解决场景标记为 `degraded`；
* 保存最后一次错误；
* 继续执行后续流程。

---

## 6.6 修改 `gate.py`

### 6.6.1 当前错误行为

当前 `gate.py` 可能只检查：

```text
cargo test exit code == 0
```

并据此认定测试成功。

### 6.6.2 新的门控条件

Rust 测试整体成功必须同时满足：

```python
rust_test_passed = (
    rewrite_status == "completed"
    and compile_status == "pass"
    and execution_status == "pass"
    and placeholder_status == "pass"
    and semantic_consistency_status == "pass"
)
```

### 6.6.3 门控动作

如果全部通过：

```text
route = CONTINUE
overall_status = pass
```

如果任一失败且未超过修复预算：

```text
route = TEST_REPAIR
overall_status = repairing
```

如果任一失败且已经超过修复预算：

```text
route = CONTINUE_DEGRADED
overall_status = degraded
```

不得返回：

```text
ABORT
TERMINATE
STOP_WORKFLOW
```

除非发生无法读取工程、工作目录不存在等基础设施级异常；即使发生这类异常，也应尽量生成失败报告和最终产物，而不是静默退出。

### 6.6.4 推荐伪代码

```python
def decide_test_route(state: dict, config: dict) -> str:
    rust_test = state["rust_test"]

    all_passed = all(
        rust_test.get(key) == "pass"
        for key in (
            "compile_status",
            "execution_status",
            "placeholder_status",
            "semantic_consistency_status",
        )
    )

    if (
        rust_test.get("rewrite_status") == "completed"
        and all_passed
    ):
        rust_test["overall_status"] = "pass"
        return "CONTINUE"

    repair_rounds = rust_test.get("repair_rounds", 0)
    max_rounds = config.get("max_test_repair_rounds", 3)

    if repair_rounds < max_rounds:
        rust_test["overall_status"] = "repairing"
        return "TEST_REPAIR"

    rust_test["overall_status"] = "degraded"
    return "CONTINUE_DEGRADED"
```

---

## 6.7 修改 `workflow_state.json`

### 6.7.1 新状态结构

建议替换原有单一 `test_status`：

```json
{
  "rust_test": {
    "rewrite_status": "completed",
    "compile_status": "pass",
    "execution_status": "pass",
    "placeholder_status": "pass",
    "semantic_consistency_status": "fail",
    "overall_status": "repairing",
    "repair_rounds": 1,
    "passed_tests": 24,
    "failed_tests": 0,
    "total_tests": 24,
    "consistency_issue_count": 3,
    "placeholder_issue_count": 0,
    "unresolved_scenarios": [
      "test_fdb_gc"
    ]
  },
  "c_cross": {
    "status": "partial",
    "passed": 21,
    "failed": 3,
    "total": 24
  }
}
```

### 6.7.2 兼容旧字段

如果其他脚本仍然读取：

```json
{
  "test_status": "pass"
}
```

可以暂时保留兼容字段，但它必须由新状态推导：

```python
state["test_status"] = state["rust_test"]["overall_status"]
```

不得继续单独更新 `test_status`。

---

## 6.8 修改报告阶段

涉及文件可能包括：

```text
07-migrate-tests.md
09-report-and-verify.md
final-verification.md
```

### 6.8.1 禁止报告自行推断状态

报告必须读取实际 JSON 文件：

```text
test-placeholder-check.json
test-consistency.json
workflow_state.json
c-cross-report.json
cargo-test-report.json
```

### 6.8.2 分别报告不同验证维度

最终报告必须包含：

| 验证项       | 状态                 | 说明                    |
| --------- | ------------------ | --------------------- |
| Rust 测试重写 | completed/degraded | 是否已经完成真实测试代码          |
| Rust 测试编译 | pass/fail          | `cargo test --no-run` |
| Rust 测试执行 | pass/fail          | `cargo test`          |
| 占位符检查     | pass/fail          | 是否有恒真或待实现测试           |
| 测试语义一致性   | pass/fail          | 是否覆盖 C 测试语义           |
| C-Cross   | pass/partial/fail  | Rust 实现兼容性            |
| 整体测试迁移    | pass/degraded      | 综合结论                  |

### 6.8.3 禁止使用错误结论

禁止继续输出：

```text
Rust 单元测试使用最小断言以满足编译要求。
```

禁止输出：

```text
虽然测试一致性失败，但 C-Cross 已证明实现正确，因此可以忽略。
```

正确表述应为：

```text
C-Cross 验证 Rust 实现的行为兼容性；Rust 测试一致性验证测试迁移质量。
两项检查相互独立，任何一项失败都需要单独记录。
```

---

# 7. 单个测试场景的生成要求

每个场景需要满足以下最小结构。

## 7.1 Arrange：初始化测试环境

包括：

* 创建存储；
* 创建数据库；
* 配置扇区大小；
* 注册回调；
* 准备初始数据；
* 初始化 FlashDB。

## 7.2 Act：执行原始 C 场景中的操作

包括：

* set；
* get；
* delete；
* append；
* iterate；
* control；
* GC；
* reboot/reopen；
* error injection。

## 7.3 Assert：验证原始 C 测试所验证的属性

包括：

* 返回值；
* 数据内容；
* 数据长度；
* 地址对齐；
* 状态变化；
* 删除结果；
* 重启后持久化结果；
* 迭代数量；
* 时间戳顺序；
* GC 后空间或数据状态。

## 7.4 Cleanup：清理测试环境

包括：

* 删除临时文件；
* 释放 mock storage；
* 重置全局回调；
* 避免测试间共享状态。

---

# 8. 不允许采用的绕过方式

Codex 实施时不得通过以下方式让检查形式通过。

## 8.1 机械增加断言数量

禁止：

```rust
assert!(result.is_ok());
assert!(result.is_ok());
assert!(result.is_ok());
```

断言数量不是目标，语义覆盖才是目标。

## 8.2 对常量或固定字符串断言

禁止：

```rust
assert!(true);
assert!(!"test_name".is_empty());
assert_eq!(1, 1);
```

## 8.3 只检查 API 返回成功

例如原 C 测试验证写入后读取数据，则以下代码不完整：

```rust
db.set("key", b"value").unwrap();
```

必须继续读取并验证：

```rust
let actual = db.get("key").unwrap();
assert_eq!(actual.as_deref(), Some(b"value".as_slice()));
```

## 8.4 用 C-Cross 结果替代 Rust 测试

C-Cross 成功不能修改：

```text
semantic_consistency_status
```

## 8.5 通过 `#[ignore]` 跳过测试

任何原 C 测试映射出的正式 Rust 测试如果被 `#[ignore]`，应判定为未完成。

## 8.6 修改评分脚本规避问题

本次修复目标是完善 Rust 测试和流水线状态，不能通过降低 Strategy B 的检查标准获得通过。

---

# 9. 优化后预期效果

## 9.1 测试不再假绿

优化前：

```text
cargo test: 24/24 passed
测试语义一致性: 0/24
workflow_state: pass
```

优化后：

```text
cargo test: 24/24 passed
占位符检查: pass
测试语义一致性: 24/24 或真实的部分通过结果
workflow_state: pass 或 degraded
```

只有以下检查全部通过时，整体状态才允许为 `pass`：

* 测试重写完成；
* 测试编译通过；
* 测试运行通过；
* 不存在占位符；
* 测试语义一致性通过。

---

## 9.2 一致性问题会自动进入修复

优化前：

```text
consistency fail
    ↓
被忽略
    ↓
继续报告成功
```

优化后：

```text
consistency fail
    ↓
TEST_REPAIR
    ↓
修复缺失操作和断言
    ↓
重新验证
```

---

## 9.3 比赛流水线不会中断

即使有个别测试无法修复：

```text
达到修复预算
    ↓
标记 degraded
    ↓
保留 unresolved scenarios
    ↓
继续 C-Cross
    ↓
继续评分与最终报告
    ↓
交付完整产物
```

---

## 9.4 Strategy A 和 Strategy B 可分别反映真实质量

优化后：

* Strategy A 反映 Rust 实现兼容性；
* Strategy B 反映 Rust 测试迁移质量；
* 两种策略互不覆盖；
* 最终报告可以准确说明实现和测试分别完成到什么程度。

---

## 9.5 报告结果与机器证据保持一致

报告不再出现：

```text
JSON 中 status=fail
Markdown 中写“检查通过”
```

所有报告状态必须由结构化结果文件生成。

---

# 10. 验收标准

## 10.1 必须通过的静态验收

执行：

```bash
grep -RInE \
  'MIGRATION_PENDING|PLACEHOLDER|assert!\(true\)|todo!\(|unimplemented!\(' \
  flashDB_rust/tests
```

正式交付时应无匹配结果。

允许注释或工具自身测试中出现相关字符串时，应通过白名单明确排除。

---

## 10.2 必须通过的构建验收

```bash
cd flashDB_rust
cargo test --no-run
```

要求：

```text
exit code = 0
```

---

## 10.3 必须执行的测试验收

```bash
cargo test --all -- --nocapture
```

要求：

* 所有正式测试都实际执行；
* 无 `ignored` 场景；
* 无占位测试；
* 测试失败数量如实写入状态。

---

## 10.4 必须执行的一致性验收

```bash
python work/tools/test_consistency_check.py \
  --mapping logs/trace/rust_test_mapping.json \
  --rust-tests flashDB_rust/tests \
  --output logs/trace/test-consistency.json
```

要求：

```json
{
  "status": "pass",
  "issue_count": 0
}
```

如果未达到，则必须：

* 进入 TEST_REPAIR；
* 或在达到预算后标记 `degraded`；
* 不能标记 `pass`。

---

## 10.5 必须执行的占位符验收

```bash
python work/tools/placeholder_check.py \
  --tests flashDB_rust/tests \
  --mapping logs/trace/rust_test_mapping.json \
  --output logs/trace/test-placeholder-check.json
```

成功要求：

```json
{
  "status": "pass",
  "issue_count": 0
}
```

---

## 10.6 状态一致性验收

当：

```json
{
  "semantic_consistency_status": "fail"
}
```

时，以下状态不得出现：

```json
{
  "overall_status": "pass"
}
```

当修复预算尚未耗尽时，路由必须是：

```text
TEST_REPAIR
```

当修复预算耗尽时，路由必须是：

```text
CONTINUE_DEGRADED
```

不得中止整个流水线。

---

## 10.7 报告一致性验收

最终 Markdown 报告中的状态必须与以下 JSON 完全一致：

```text
workflow_state.json
test-placeholder-check.json
test-consistency.json
C-Cross 结果文件
cargo test 结果文件
```

不得由 Agent 自行编造“通过”结论。

---

# 11. 推荐实施顺序

Codex 按以下顺序修改，避免一次性改动过大。

## 第一阶段：修复假绿状态

1. 修改 `migrate_tests.py`，删除恒真断言。
2. 新增 `placeholder_check.py`。
3. 修改 `workflow_state.json` 状态结构。
4. 修改 `gate.py`，不再仅依赖 `cargo test`。
5. 修改报告阶段，直接读取机器结果。

完成后应保证：

> 占位测试不会再被标记为成功。

## 第二阶段：增加完整测试重写

1. 在 REWRITE 中增加 REWRITE_TESTS 子阶段。
2. 为 Agent 提供 C 测试、映射和 Rust API。
3. 按场景生成完整 Rust 测试。
4. 运行编译、测试和一致性检查。

完成后应保证：

> 正常流程可以直接产出有真实验证逻辑的 Rust 测试。

## 第三阶段：增加自动修复循环

1. 新增 TEST_REPAIR。
2. 根据结构化 issue 定向修复。
3. 设置最大修复轮数。
4. 超过预算后标记 degraded 并继续流程。

完成后应保证：

> 测试迁移失败不会被忽略，也不会导致比赛流水线提前终止。

---

# 12. Codex 开发任务清单

请在实际仓库中定位对应文件并完成以下任务。

* [ ] 修正测试总数统计口径，统一核实为 24 个。
* [ ] 删除 `migrate_tests.py` 中的固定字符串断言。
* [ ] 禁止 `migrate_tests.py` 将脚手架视为迁移完成。
* [ ] 扩展 `rust_test_mapping.json` 的场景状态字段。
* [ ] 增加 REWRITE_TESTS 阶段。
* [ ] REWRITE_TESTS 必须读取原始 C 测试和 Rust 实现。
* [ ] 新增 `placeholder_check.py`。
* [ ] 检查恒真断言、`todo!()`、`unimplemented!()` 和跳过测试。
* [ ] 增强 `test_consistency_check.py` 的 obligation evidence。
* [ ] 新增 TEST_REPAIR 阶段。
* [ ] TEST_REPAIR 按场景定向修改测试。
* [ ] 修改 `gate.py` 为强制修复路由门。
* [ ] 测试失败时不得终止整个比赛流水线。
* [ ] 达到修复预算后标记 `degraded`。
* [ ] 拆分 Rust 测试的编译、执行、占位符和一致性状态。
* [ ] C-Cross 状态与 Rust 测试状态分别保存。
* [ ] 修改所有 Markdown 报告，禁止覆盖机器检查结果。
* [ ] 补充脚本单元测试。
* [ ] 补充端到端回归测试。

---

# 13. 最终成功标准

本问题修复完成的标准不是简单的：

```text
cargo test 全部通过
```

而是：

```text
1. Rust 测试真实调用迁移后的 Rust 实现；
2. Rust 测试保留原始 C 测试的关键操作和断言语义；
3. Rust 测试中不存在占位符或恒真断言；
4. cargo test 可以编译和执行；
5. test_consistency_check 结果真实参与状态判断；
6. 检查失败会自动进入 TEST_REPAIR；
7. 修复失败不会中止整个比赛流程；
8. 最终状态和报告如实反映 pass、partial 或 degraded；
9. C-Cross 只用于评价 Rust 实现，不再替代 Rust 测试质量；
10. Strategy B 能够识别到真实 Rust 测试逻辑，而不是占位测试。
```
