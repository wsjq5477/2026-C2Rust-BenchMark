# REWRITE_CORE_MODULES 阶段日志

## 概述

本阶段基于 rust_api_design.json 和 C 模型，完善 flashDB_rust/src/ 中的核心模块实现。所有模块完整实现，无 todo!() 或 unimplemented!()。

## 执行内容

1. 读取 `work/skills/flashdb-migration/SKILL.md` 中 `REWRITE_CORE_MODULES` 规则。
2. 基于 C 模型和 Rust API 设计，重写核心模块。

## 模块实现详情

### error.rs
- FdbError 枚举映射所有 C 错误码：NoErr、EraseErr、ReadErr、WriteErr、NameErr、NameExist、SavedFull、InitFailed、NotFound、InvalidInput、Io
- Result<T> 类型别名统一错误处理

### flash.rs
- FlashStorage trait 定义地址级读写和扇区擦除操作：read(addr, buf)、write(addr, data)、erase(addr, size)、sector_size()、total_size()
- MemFlash：Vec<u8> 模拟闪存，初始化为 0xFF（擦除态），支持扇区级擦除和字节级写入
- FileFlash：文件模拟闪存，内存缓存 + 文件持久化

### kvdb.rs
- KvDb 使用扇区基础闪存模型
- 扇区头格式：store_status + dirty_status + magic("FDB1") + padding
- KV 记录格式：status + magic("KV00") + name_len + value_len + name + value
- HashMap 索引追踪最新有效 KV
- Tombstone 删除（status 改为 PRE_DELETE/DELETED）
- GC：查找脏扇区，移动有效记录到空扇区，擦除旧扇区
- open：扫描闪存构建索引，格式化空扇区
- set/get/delete/set_blob/get_blob/iter/gc/reload 全部完整实现

### tsdb.rs
- TsDb 使用内部 MemFlash 扇区模型
- 扇区头格式：3 标记字节（EMPTY/USING/FULL） + magic("TSL0") + start_time
- TSL 索引格式：status + timestamp + log_len + log_addr（17字节）
- 数据从扇区底部存储，索引从扇区顶部增长
- Vec<TslRecord> 索引追踪所有记录
- TslStatus 枚举映射 C 状态：Unused/PreWrite/Write/UserStatus1/Deleted/UserStatus2
- append：追加记录，时间戳严格递增，自动扇区转换
- iter/iter_reverse/query_by_time/count_by_time/set_status/clean/reload 全部完整实现

## 禁止事项遵守

- 不链接 C 源码
- 不写 todo!()、unimplemented!()
- 不把 C 源码放进 flashDB_rust/src/

## 下一步

进入 MIGRATE_TESTS 阶段，迁移 C 测试到 Rust 测试。