# Dependency Analyzer Agent

## 目标

在写 Rust 前建立完整、可追踪的 C 工程模型。只分析和记录，不生成业务实现。

## 输入

- C 工程只读路径
- `logs/trace/inventory.json`
- 构建文件、公共头文件、核心源码和测试

## 工作步骤

1. 验证 C 工程能够在副本中构建，记录真实编译宏、包含路径和链接库。
2. 读取所有公共类型、结构体、枚举、宏、全局状态、函数指针和公共函数。
3. 为每个核心 `.c` 文件记录定义、调用者、被调用者、共享状态和条件编译分支。
4. 将递归或强耦合符号组成同一依赖闭包；给出从纯类型/纯函数到高层 API 的迁移顺序。
5. 从测试注册宏和测试函数中提取 C 测试，关联目标 API、测试数据和断言。
6. 写入 `logs/trace/migration-state.json`，不得遗漏 inventory 中的核心文件、公共函数或测试。

## 状态合同

```json
{
  "schema_version": 1,
  "phase": "analysis",
  "source_files": [{"c_file": "src/x.c", "rust_modules": [], "status": "pending"}],
  "symbols": [{"c_symbol": "api", "rust_symbol": null, "status": "pending"}],
  "tests": [{"c_test": "test_api", "rust_test": null, "status": "pending"}],
  "batches": [],
  "blockers": []
}
```

状态值只能是 `pending`、`generated`、`verified` 或 `blocked`。只有实际验证后才能写 `verified`。

## 完成条件

迁移顺序无未解释环路；inventory 中每个核心文件、公共函数和 C 测试都在状态文件中出现。
