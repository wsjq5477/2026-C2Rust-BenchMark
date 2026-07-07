# 比赛规则

## 输入

FlashDB C 输入目录由 `INSTRUCTION.md` 和 orchestrator 阶段规则选择。knowledge 文档只记录约束，不预置具体平台路径或本地 fallback 路径。

## 最终输出

完整迁移最终必须生成可构建、可测试的 Rust 项目，项目根目录使用比赛要求的 `flashDB_rust`。

第一个 framework checkpoint 不得生成此目录。

## 硬性约束

- 不得修改平台提供的 FlashDB 源码或测试。
- 不得只提交编译后的二进制文件。
- 不得预安装或预构建伪造的 `flashDB_rust`。
- 最终 Rust 项目必须通过 `cargo build`。
- 最终 Rust 测试必须通过 `cargo test`。
- Unsafe ratio 必须低于 10%。
- knowledge 文档不得预置具体 C 函数、Rust 类型、Rust 文件或测试 case 清单；这些内容必须由当前输入和阶段产物动态推导。
