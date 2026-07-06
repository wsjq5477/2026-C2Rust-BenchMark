# DESIGN_RUST_API 阶段日志

## 概述

本阶段基于 C 模型设计 Rust API 边界，确定 crate 名称、核心类型、模块划分、API 表面和测试映射策略。

## 执行内容

1. 读取 `work/skills/flashdb-migration/SKILL.md` 中 `DESIGN_RUST_API` 规则。
2. 运行 `design_rust_api.py`，基于三个 C 模型 JSON 生成 Rust API 设计。
3. 生成 `logs/trace/rust_api_design.json`。

## 设计决策

### 基本配置
- Crate 名称：`flashdb_rust`
- 模块：`error`、`flash`、`kvdb`、`tsdb`
- 错误模型：`Result<T, FdbError>`，C 成功映射为 `FdbError`

### 核心类型
- `FlashStorage` trait：存储抽象边界
- `MemFlash`：内存模拟存储（测试用）
- `FileFlash`：文件模拟存储
- `FdbError`：错误类型
- `KvDb`：键值数据库
- `TsDb`：时序数据库
- `TslRecord`：时序日志记录

### KVDB API（9个方法）
- `KvDb::open` → `fdb_kvdb_init`
- `KvDb::set` → `fdb_kv_set`
- `KvDb::get` → `fdb_kv_get`
- `KvDb::set_blob` → `fdb_kv_set_blob`
- `KvDb::get_blob` → `fdb_kv_get_blob`
- `KvDb::delete` → `fdb_kv_del`
- `KvDb::iter` → `fdb_kv_iterate`
- `KvDb::reload` → 无直接C对应，重建索引
- `KvDb::gc` → `fdb_kvdb_check`

### TSDB API（7个方法）
- `TsDb::open` → `fdb_tsdb_init`
- `TsDb::append` → `fdb_tsl_append`
- `TsDb::iter` → `fdb_tsl_iter`
- `TsDb::query_by_time` → `fdb_tsl_iter_by_time`
- `TsDb::set_status` → `fdb_tsl_set_status`
- `TsDb::clean` → `fdb_tsl_clean`
- `TsDb::reload` → 无直接C对应，重建状态

### 测试映射
- KVDB 测试 13 个 → `kvdb_tests.rs`
- TSDB 测试 10 个 → `tsdb_tests.rs`
- 等价性测试 → `equivalence_tests.rs`

## 未映射符号

- `fdb_kv_print`：调试辅助，不纳入核心 API
- `fdb_kvdb_control`：控制接口，后续可选扩展
- `fdb_tsdb_control`：控制接口，后续可选扩展
- `fdb_kv_set_default`：已有独立方法但在 API 中合并为 `set` 语义
- `fdb_tsl_max_blob_count`：内部计算辅助

## 语义要求

- KVDB 删除必须以 tombstone 行为持久化
- KVDB reload 必须扫描存储重建最新值索引
- KVDB GC 必须保留每个键的最新有效记录
- TSDB append 必须保持时间戳排序
- TSDB 迭代必须避免回调式 unsafe 拥有权
- FlashStorage 是内存/文件测试存储边界

## 边界遵守

本阶段不生成 Rust 源码，不运行 cargo，不进入 GENERATE_RUST_SCAFFOLD。

## 下一步

进入 GENERATE_RUST_SCAFFOLD 阶段，生成 Rust 项目骨架。