# 简化流程阶段说明

当前运行合同只有四个面向工作的阶段：

1. `ANALYZE`：扫描输入，生成 C/API/ABI/test 的动态事实和 Rust 设计。
2. `IMPLEMENT`：生成骨架并实现 Rust 行为，不拆固定 worker 事务。
3. `VERIFY_AND_REPAIR`：通过 ABI probe 和原 C runner 找到真实失败，最小修复后复跑。
4. `TEST_AND_REPORT`：迁移 Rust 测试，运行 cargo 与真实性检查，生成最终报告。

阶段不是状态机事务。是否继续由现有机器产物和验证命令判断；不使用 task packet、receipt、revision 或 `next_action`。

详细入口见 `02_02/INSTRUCTION.md`，架构取舍见 `design_doc/Q9-转换工程架构简化设计.md`。
