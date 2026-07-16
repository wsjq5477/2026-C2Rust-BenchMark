---
name: rust-translator
description: Translate a bounded C dependency closure into safe, observable Rust behavior.
---

# Rust Translator

## 目标

将当前依赖闭包重写为安全、可维护且行为等价的 Rust，不机械复制 C 内存模型。

## 每批输入

- 当前批次涉及的 C 定义及完整调用上下文
- 上一批已验证的 Rust 接口
- 对应 C 测试、磁盘格式和错误行为
- `migration-state.json`

## 执行规则

1. 先为本批定义 Rust 接口、所有权、错误类型和数据不变量。
2. 先由 Test Migrator 添加当前行为的失败测试，再实现最小代码。
3. 裸数组优先用数组/切片/`Vec`，可空指针用 `Option`，状态码用明确错误枚举，资源用 RAII。
4. 持久化布局必须显式编解码，不依赖 Rust 结构体内存布局。
5. 回调使用泛型或 trait；只有明确要求 C ABI 时才建立隔离的 FFI 边界。
6. 每批执行 `cargo fmt`、`cargo check` 和定向测试，成功后更新映射为 `verified`。
7. 在 `logs/trace/batches/<id>.md` 记录输入符号、修改文件、命令和结果。

## 禁止

- 不得把 C 文件交给 `build.rs`、`cc` crate 或外部链接器参与最终实现。
- 不得以 `unsafe` 绕过所有权设计；必要边界必须写安全不变量并保持总比例低于 10%。
- 不得为了当前断言返回固定值或忽略持久化、重启、GC、遍历等状态行为。
