# 阶段06：重写核心模块

## 执行内容

1. 读取 flashdb-migration SKILL.md 中 REWRITE_CORE_MODULES 规则。
2. 基于 rust_api_design.json 和 C 模型，完善 flashDB_rust/src/ 中的所有核心模块。

## 重写模块详情

### error.rs
- 定义完整错误类型：ReadErr, WriteErr, EraseErr, NameErr, NameExist, SavedFull, InitFailed, InvalidInput, Io, NotFound, KvErrHdr, SectorErrHdr
- 与 C fdb_err_t 对应
- 实现 Display 和 std::error::Error

### flash.rs
- 重新设计 FlashStorage trait：sector_size, sectors_count, read, write, erase_sector
- write 操作遵循 NOR flash 1→0 位翻转语义
- MemFlash：内存模拟 flash，每个扇区为 Vec<u8> 初始化为 0xFF
- FileFlash：文件模拟 flash，每个扇区存储为独立文件

### kvdb.rs
- 完整实现 KVDB 核心逻辑：
  - 扇区头（16字节）：store_status + dirty_status + magic(0x30424446) + combined + reserved
  - KV 头（24字节）：status + magic(0x3030564B) + len + crc32 + name_len + value_len
  - 状态编码：位翻转协议（0xFF→0x7F→0x3F→0x1F→0x0F→0x07）
  - Tombstone 删除：标记 PRE_DELETE 后写入新 KV，再标记旧 KV 为 DELETED
  - GC：移动存活 KV 到空闲扇区，格式化脏扇区
  - CRC32 校验：每个 KV 带 CRC32 校验码
  - 扫描重建索引：遍历所有扇区找到最新有效 KV

### tsdb.rs
- 完整实现 TSDB 核心逻辑：
  - 扇区头（56字节）：store_status + magic(0x304C5354) + start_time + end_info + reserved
  - TSL 索引头（20字节）：status + time + log_len + log_addr
  - 双栈布局：索引从上往下增长，数据从下往上增长
  - 时间戳严格递增
  - 时间范围查询：遍历扇区过滤时间范围
  - 状态设置：TslStatus (Write/UserStatus1/Deleted/UserStatus2)
  - 清理：格式化所有扇区

### lib.rs
- 导出所有公共类型：FdbError, Result, FlashStorage, MemFlash, FileFlash, KvDb, TsDb, TslRecord, TslStatus

## 语义保证

- KVDB 删除必须是 tombstone 行为（标记 DELETED，不立即擦除）
- KVDB reload 必须扫描存储重建最新值索引
- KVDB GC 必须保留每个键最新的有效记录
- TSDB append 必须保持时间戳排序
- TSDB 迭代避免回调式 unsafe
- FlashStorage 是内存/文件测试存储边界

## 实现规则遵守

- 不链接 C 源码
- 不写 todo!() 或 unimplemented!()
- 使用安全 Rust（无 unsafe 块）
- 所有核心模块都有完整实现逻辑
