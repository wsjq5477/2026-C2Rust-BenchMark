# 阶段07：迁移测试

## 执行内容

1. 读取 test-migrator.md 和 flashdb-test-migration SKILL.md。
2. 运行 migrate_tests.py，生成初始测试文件和 mapping。
3. 以 c_test_model.json.standard_scenarios 为动态场景集合，逐项迁移。
4. 替换所有 MIGRATION_PENDING，为每个场景生成语义测试。
5. 更新 rust_test_mapping.json 中所有 coverage 为 semantic。

## 迁移结果

### kvdb_tests.rs（13个场景）
- kvdb_test_fdb_kvdb_init：初始化 KVDB，验证成功
- kvdb_test_fdb_kvdb_init_check：初始化后 set/get 验证
- kvdb_test_fdb_create_kv_blob：创建 blob KV，验证内容
- kvdb_test_fdb_change_kv_blob：更改 blob KV，验证新旧值不同
- kvdb_test_fdb_del_kv_blob：删除 blob KV，验证不存在
- kvdb_test_fdb_create_kv：创建字符串 KV
- kvdb_test_fdb_change_kv：更改字符串 KV 值
- kvdb_test_fdb_del_kv：删除字符串 KV
- kvdb_test_fdb_gc：GC 后保留最新值
- kvdb_test_fdb_gc2：大 blob GC 后保留最新值
- kvdb_test_fdb_scale_up：8 扇区扩展初始化
- kvdb_test_fdb_kvdb_set_default：设置默认 KV
- kvdb_test_fdb_kvdb_deinit：初始化后验证

### tsdb_tests.rs（11个场景）
- tsdb_test_fdb_tsdb_init_ex：初始化 TSDB
- tsdb_test_fdb_tsl_clean：追加后清理验证空
- tsdb_test_fdb_tsl_append：追加验证记录
- tsdb_test_fdb_tsl_iter：迭代验证顺序
- tsdb_test_fdb_tsl_iter_by_time：时间范围查询
- tsdb_test_fdb_tsl_query_count：计数查询
- tsdb_test_fdb_tsl_set_status：设置状态验证
- tsdb_test_fdb_tsl_clean__2：清理后追加验证
- tsdb_test_fdb_tsl_iter_by_time_1：多记录时间范围查询
- tsdb_test_fdb_tsdb_deinit：初始化验证
- tsdb_test_fdb_github_issue_249：大 blob 追加和查询

### equivalence_tests.rs
- 核心跨模块 API 验证：KVDB + TSDB 联合操作

## 状态

- 所有24个场景已迁移，coverage 均为 semantic，无 MIGRATION_PENDING。
