# MIGRATE_TESTS 阶段日志

## 概述

本阶段将 C 测试模型中的 23 个测试场景迁移为 Rust 集成测试。

## 执行内容

1. 运行 `migrate_tests.py` 生成测试映射。
2. 手动完善测试文件以匹配当前 Rust API 签名。

## 测试文件详情

### kvdb_tests.rs
- kvdb_init_creates_empty_db：初始化空数据库
- kvdb_create_and_get_kv：创建和获取字符串 KV
- kvdb_change_kv：修改 KV 值
- kvdb_del_kv：删除 KV（tombstone）
- kvdb_create_and_get_blob：创建和获取二进制 KV
- kvdb_change_blob：修改二进制 KV
- kvdb_del_blob：删除二进制 KV
- kvdb_iter_exposes_written_entries：迭代所有 KV
- kvdb_gc_compacts_deleted_records：GC 压缩删除记录
- kvdb_set_default_stores_defaults：设置默认值
- kvdb_multiple_keys_stress：多键压力测试
- kvdb_reload_preserves_data：重载后数据保持

### tsdb_tests.rs
- tsdb_init_creates_empty_db：初始化空数据库
- tsdb_append_and_iter：追加和迭代
- tsdb_query_by_time：按时间查询
- tsdb_query_count：按时间计数
- tsdb_set_status：设置状态
- tsdb_set_user_status：设置用户状态
- tsdb_clean_removes_all：清除所有记录
- tsdb_clean_and_reuse：清除后重新使用
- tsdb_iter_reverse：反向迭代
- tsdb_reload_preserves_data：重载后数据保持
- tsdb_multi_sector：多扇区测试

### equivalence_tests.rs
- kvdb_and_tsdb_coexist_independently：KVDB 和 TSDB 独立共存
- kvdb_blob_string_interop：blob 和 string 互操作
- tsdb_status_then_query：设置状态后查询
- kvdb_gc_retains_latest_values：GC 保留最新值

## C 测试映射

- KVDB 测试 13 个场景映射到 kvdb_tests.rs
- TSDB 测试 10 个场景映射到 tsdb_tests.rs
- 等价性测试映射到 equivalence_tests.rs
- 所有 23 个 C 测试场景均已映射

## 下一步

进入 BUILD_TEST_REPAIR 阶段，构建和测试修复。