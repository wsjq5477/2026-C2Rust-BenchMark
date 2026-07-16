---
name: c-to-rust
description: Use when OpenCode must migrate a multi-file C library and its tests into a buildable, behaviorally equivalent Rust project without modifying the source project.
---

# C-to-Rust Migration

## 核心原则

这是转换流程，不是预制答案。先取得 C 基线和跨文件上下文，再逐批生成安全 Rust；任何成功结论都必须有新鲜的构建、测试和差分证据。

## 强制流程

1. 运行项目扫描器，写入 `logs/trace/inventory.json`。
   若 inventory 匹配 `references/flashdb-profile.json` 的全部标志文件，加载该 profile 的构建命令和24个标准场景；profile 只提供验证元数据，不能代替源码分析。
2. 按 `../dependency-analyzer.md` 补全依赖、公共 API、状态和测试映射，创建 `logs/trace/migration-state.json`。
3. 运行基线器，只在 `logs/trace/c-baseline` 副本中构建和测试 C 工程。
4. 按 `references/migration-rules.md` 和 `../rust-translator.md` 创建 `flashDB_rust`，以依赖闭包为单位逐批迁移。
5. 每批先迁移/新增对应测试，再写实现；运行 `cargo check` 和定向测试。失败时调用 `../compile-healer.md`，规则见 `references/error-recovery.md`。
6. 按 `../test-migrator.md` 覆盖全部 C 测试；按 `../semantic-verifier.md` 执行完整验证。
7. 运行覆盖、unsafe 和无 C 链接检查，再执行 release build、全量测试、fmt、clippy。
8. 汇总所有门禁到 evidence JSON，并用报告器更新 `result/output.md`；缺少任一证据时报告器会强制失败。

## 命令模板

从作品根目录执行，`$SOURCE_ROOT` 和 `$OUTPUT_ROOT` 分别是只读 C 输入和 `flashDB_rust`：

```bash
python3 work/skills/c-to-rust/scripts/inspect_project.py --source "$SOURCE_ROOT" --output logs/trace/inventory.json
python3 work/skills/c-to-rust/scripts/run_baseline.py --source "$SOURCE_ROOT" --scratch logs/trace/c-baseline --build-command "make -C tests all" --test-command "make -C tests test" --output logs/trace/c-baseline.json
python3 work/skills/c-to-rust/scripts/check_coverage.py --inventory logs/trace/inventory.json --state logs/trace/migration-state.json --output logs/trace/coverage.json
python3 work/skills/c-to-rust/scripts/check_unsafe.py --source "$OUTPUT_ROOT/src" --maximum 0.10 --output logs/trace/unsafe.json
python3 work/skills/c-to-rust/scripts/check_no_c_linkage.py --project "$OUTPUT_ROOT" --output logs/trace/no-c-linkage.json
python3 work/skills/c-to-rust/scripts/generate_report.py --evidence logs/trace/evidence.json --rust-project "$OUTPUT_ROOT" --output result/output.md
```

非 Make 工程必须使用 inventory 发现的真实构建命令替换基线命令，不能照抄 FlashDB 参数。

## 硬性约束

- 不得预置 FlashDB Rust 实现，不得硬编码测试答案。
- 不得修改平台 C 工程；不得在最终 Cargo 构建中编译或链接其核心 C 源码。
- 必须维护逐 C 文件、公共符号和 C 测试的可审计映射。
- 必须逐批迁移；禁止一次生成全库后跳过中间验证。
- 不得用删除测试、弱化断言、吞掉错误或无限重试制造通过。
- 同类错误连续三次未改善时必须拆小批次或更换所有权设计。
- 任一门禁失败都必须报告失败，不能写 `STATUS: SUCCESS`。

## 快速参考

| 阶段 | Agent | 必要证据 |
|---|---|---|
| 建模 | `../dependency-analyzer.md` | inventory、migration-state |
| 转换 | `../rust-translator.md` | Rust 源码、批次记录 |
| 测试 | `../test-migrator.md` | C/Rust 测试映射 |
| 自愈 | `../compile-healer.md` | 错误分类、补丁和复验 |
| 验证 | `../semantic-verifier.md` | coverage、unsafe、cargo 输出 |

## 常见错误

- 把“能编译”当成“语义等价”：必须继续完成测试映射与差分检查。
- 按文件孤立翻译：先读取类型、调用者、被调用者和条件编译上下文。
- 机械保留裸指针：优先切片、所有权容器、`Option`、`Result` 和受控存储抽象。
- 修复扩散到已验证模块：回到最近批次边界，只修改直接依赖。
