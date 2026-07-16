# 编译与测试自愈规则

| 分类 | 诊断证据 | 首选动作 |
|---|---|---|
| 名称/模块 | unresolved import、not found | 核对符号映射和可见性，不复制重复实现 |
| 类型 | mismatched types | 回到接口不变量，使用显式转换并检查范围 |
| 所有权 | moved/borrowed/lifetime | 缩短借用、调整所有权边界，避免无依据 clone |
| trait | bound not satisfied | 在抽象边界补真实能力，避免空实现 |
| 链接 | undefined reference | 检查遗漏模块；不得重新链接 C 核心实现 |
| 行为 | assertion/diff | 对照 C 数据与状态转换，先定位首个分歧 |
| 超时 | hang/timeout | 检查循环进度、锁和迭代终止条件 |

每次尝试必须改变根因假设或减少错误集合。相同错误、相同修改重复出现不算进展。恢复不能修改原 C 测试、删除 Rust 测试、放宽断言或把错误变成无条件成功。
