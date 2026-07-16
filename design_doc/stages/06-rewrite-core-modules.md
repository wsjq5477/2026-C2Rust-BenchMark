# IMPLEMENT 与 VERIFY_AND_REPAIR - Rust 实现闭环

主执行者根据动态设计实现 `flashDB_rust/`，先通过结果型 IMPLEMENT 审计和 gate，然后运行真实 C-Cross。REWRITE 不再包含 parent run、CORE/FACADE worker、packet、receipt 或 revision。

```text
实现最小行为
    ↓
当前实现 build / ABI layout check
    ↓
core_impl_audit checkpoint
    ↓
IMPLEMENT gate
    ↓
原 C runner compile/link/run
    ↓
failure-summary.json
    ↓
最小 Rust 修复并复跑
```

审计发现 scaffold residue 时，只允许一轮 findings 定向补漏；该轮可拆成多个短任务，但只记录一次真实 repair。repair 后仍失败则在不修改源码的情况下 fresh confirmation，形成 IMPLEMENT `failed_final` 后只生成实现未完成报告，下游证据全部标记为未运行。

所有正式 C-Cross 模式都会在写 matrix/attempt 前复用当前 IMPLEMENT 审计。首次 checkpoint 还要求当前 implementation attempt 与 build/layout；C-Cross 链建立后的语义 repair 改由其 source manifest/changed-file 合同追踪，不要求初始实现指纹保持不变，但重新引入 scaffold residue 仍会被拒绝。前置拒绝不生成场景失败，也不消耗 C-Cross repair budget。

每次失败只消费当前 failure summary 中的场景、日志和必要代码窗口。C-Cross 不通过时不能伪报通过，也不能通过排除场景推进；允许继续生成最终失败报告。全量通过后必须以 `--attempt-kind final` 进行新鲜确认。
