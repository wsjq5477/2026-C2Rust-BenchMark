# 阶段04：设计Rust API

## 执行内容

1. 读取 flashdb-migration SKILL.md 中 DESIGN_RUST_API 规则。
2. 读取 c_project_model.json、c_api_model.json、c_test_model.json 和 flashdb-rust-architecture.md。
3. 运行 design_rust_api.py，生成 rust_api_design.json。
4. 本阶段仅做 Rust API 设计决策，不生成 Rust 源码，不运行 cargo。

## 核心API设计

### crate名：flashdb_rust

### 模块划分
- error：错误类型 FdbError，Result<T, FdbError>
- flash：FlashStorage trait，MemFlash、FileFlash 实现
- kvdb：KvDb 及其 open/set/get/set_blob/get_blob/delete/iter/reload/gc 方法
- tsdb：TsDb 及其 open/append/iter/query_by_time/set_status/clean/reload 方法

### KVDB API（9个方法）
- KvDb::open → 映射 fdb_kvdb_init
- KvDb::set → 映射 fdb_kv_set
- KvDb::get → 映射 fdb_kv_get
- KvDb::set_blob → 映射 fdb_kv_set_blob/fdb_kv_to_blob
- KvDb::get_blob → 映射 fdb_kv_get_blob/fdb_kv_get_obj
- KvDb::delete → 映射 fdb_kv_del（tombstone删除）
- KvDb::iter → 映射 fdb_kv_iterator_init/fdb_kv_iterate
- KvDb::reload → 重建索引扫描
- KvDb::gc → 映射 fdb_kvdb_check（保留最新有效记录）

### TSDB API（7个方法）
- TsDb::open → 映射 fdb_tsdb_init
- TsDb::append → 映射 fdb_tsl_append/fdb_tsl_append_with_ts
- TsDb::iter → 映射 fdb_tsl_iter/fdb_tsl_iter_reverse
- TsDb::query_by_time → 映射 fdb_tsl_iter_by_time/fdb_tsl_query_count
- TsDb::set_status → 映射 fdb_tsl_set_status
- TsDb::clean → 映射 fdb_tsl_clean
- TsDb::reload → 重建TSDB状态

### 语义要求
- KVDB删除必须是 tombstone 行为
- KVDB reload 必须扫描存储重建最新值索引
- KVDB GC 必须保留每个键最新的有效记录
- TSDB append 必须保持时间戳排序
- TSDB 迭代必须避免回调式 unsafe
- FlashStorage 是内存/文件测试存储边界

### 未映射符号
部分 C 函数（如 fdb_reboot、fdb_blob_make 等辅助函数）不直接映射为 Rust 公共 API，通过 Rust 内部实现封装。

### 测试映射
- 13个 KVDB 测试 → kvdb_tests.rs
- 10个 TSDB 测试 → tsdb_tests.rs
- 1个 issue 测试 → equivalence_tests.rs

## 状态

- Rust API 设计完成，准备进入 GENERATE_RUST_SCAFFOLD。
