# ANALYZE - Rust API 设计

`design_rust_api.py` 将当前 C project/API/test 模型转为 `rust_api_design.json` 与 `ffi_manifest.json`。设计只记录动态发现的 ABI、公共符号、测试义务和实现边界。

它不决定流程路由、不生成 task packet，也不要求固定模块、函数或测试数量。实现时优先选择满足当前 C-Cross 可观察语义的最小架构；只有模型事实或真实失败证明需要时才引入更深的存储、持久化或 sector 语义。

完成后运行 `python3 work/tools/gate.py --stage ANALYZE --root .`，由模型、ABI 与设计产物本身验证事实一致性。
