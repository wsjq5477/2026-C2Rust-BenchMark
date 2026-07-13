# 改写核心模块

已按 Rust API 设计完成 typed C ABI facade 与 Rust sidecar 状态机：KV/TSDB 的地址、blob、迭代、状态、控制与重入 callback 都由 Rust 实现。KV 的 live-record relocation 会更新地址和 oldest-sector cursor；TSDB 按物理 log 地址组织跨-sector iterator。C ABI 结构仍由调用方拥有，状态由数据库对象地址关联的 Rust sidecar 保存。已运行 `cargo fmt --all -- --check` 和 `cargo build --release`，两项通过。
