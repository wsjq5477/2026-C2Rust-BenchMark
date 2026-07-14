# IMPLEMENT 与 VERIFY_AND_REPAIR - Rust 实现闭环

主执行者根据动态设计实现 `flashDB_rust/`，然后运行真实 C-Cross。REWRITE 不再包含 parent run、CORE/FACADE worker、packet、receipt 或 revision。

```text
实现最小行为
    ↓
ABI layout check
    ↓
原 C runner compile/link/run
    ↓
failure-summary.json
    ↓
最小 Rust 修复并复跑
```

每次失败只消费当前 failure summary 中的场景、日志和必要代码窗口。C-Cross 不通过时不能伪报通过，也不能通过排除场景推进；允许继续生成最终失败报告。全量通过后必须以 `--attempt-kind final` 进行新鲜确认。
