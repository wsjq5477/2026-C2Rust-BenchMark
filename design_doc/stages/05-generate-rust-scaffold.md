# IMPLEMENT - 生成 Rust 骨架

`generate_rust_scaffold.py` 根据 `rust_api_design.json` 创建可编译的 crate、ABI 声明、layout probe 和测试目录。生成器只建立结构与事实边界，不代表业务实现已完成。

生成后先运行 layout-only checker。layout 失败时修复由模型或生成器产生的 ABI 定义；通过只说明 scaffold 可构建且 ABI layout 正确，不能进入 full C-Cross。

下一动作必须是由主执行者直接实现 Rust 行为，或把动态文件、symbol、依赖簇交给短期 `rust-implementer`。初始实现后先对当前源码重新执行 layout-only，再运行 `core_impl_audit.py --attempt-kind checkpoint`；审计和 build/layout 都通过后才能执行 `gate.py --stage IMPLEMENT`。

不得通过 controller 角色、文件 ownership 或 revision 合同限制实现者，也不得重生成骨架覆盖已有修复。是否调用过 subagent 不是通过证据，当前 implementation audit、build/layout 和 IMPLEMENT gate 才是。
