# 阶段05：生成Rust脚手架

## 执行内容

1. 读取 rust_api_design.json。
2. 运行 generate_rust_scaffold.py，生成 flashDB_rust 项目骨架。
3. 脚手架按设计文档的模块和API形状创建，不链接C源码，不迁移测试。

## 生成结果

- flashDB_rust/Cargo.toml：项目配置文件
- flashDB_rust/src/lib.rs：库入口
- flashDB_rust/src/error.rs：FdbError 和 Result 类型定义
- flashDB_rust/src/flash.rs：FlashStorage trait、MemFlash、FileFlash
- flashDB_rust/src/kvdb.rs：KvDb 结构体及方法签名
- flashDB_rust/src/tsdb.rs：TsDb 结构体及方法签名
- flashDB_rust/tests/：测试目录（空，待迁移阶段填充）

## 状态

- Rust 脚手架已生成，准备进入 REWRITE_CORE_MODULES 实现核心逻辑。
