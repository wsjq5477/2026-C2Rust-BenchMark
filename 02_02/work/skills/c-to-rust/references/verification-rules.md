# 验证和报告规则

## 硬门禁

1. C 基线副本构建和测试通过。
2. `cargo build --release` 与 `cargo test` 通过。
3. `cargo fmt --check` 与 `cargo clippy -- -D warnings` 通过。
4. 所有核心 C 文件、公共 API 和 C 测试映射为已验证 Rust 实现。
5. unsafe 行比例严格小于 10%。
6. 最终 Cargo 项目不构建或链接原 C 核心逻辑。

## 报告证据

每条命令记录工作目录、命令文本、开始/结束时间、退出码和完整日志路径。摘要只能引用本轮日志。没有运行、输出被截断或退出码未知时，该门禁视为失败。

## 状态

- `SUCCESS`：所有硬门禁通过。
- `FAILED`：任何硬门禁失败或证据缺失。
- `LIMITED_VALIDATION`：只适用于通用输入缺少 C 测试的情况；FlashDB 评测不得以此代替成功。
