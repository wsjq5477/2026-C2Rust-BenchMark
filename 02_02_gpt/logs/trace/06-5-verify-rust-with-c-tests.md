# 使用原始 C 测试验证 Rust

已通过 `c_cross_validate.py` 编译 Rust staticlib、链接动态发现的原始 C runner 并生成逐场景矩阵。最后一次 repair attempt `persist_gc_oldest_cursor` 结果为 `PASS`：24/24 场景通过。逐场景矩阵、原始 runner 输出、attempt 和 diagnostics 均保存在 `logs/trace/c-cross/`。
