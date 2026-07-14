# Agent 优化记录

本文档按阶段维护 `02_02`（OpenCode + GLM）与 `02_02_gpt`（Codex + GPT）对比结果。每个阶段固定记录：问题、修复、复跑结果和当前状态。后续不得在文档末尾追加未归属阶段的问题。

## INIT_WORKSPACE

### 问题

- [x] GPT 的初始化证据能明确说明输入基线、运行身份、agent registry、下一阶段和 Rust 项目尚未生成；旧版 GLM 日志信息不足。
- [x] `02_02/fdb_test_blob/kvdata.bin` 是用户主动删除的运行数据，不属于 Agent 问题，不得恢复。

### 修复记录

- `workflowctl init` 自动生成 `01-init-workspace.md`，记录输入文件数量、基线 SHA256、状态文件、agent registry、下一阶段、init gate 和 `flashDB_rust` 未生成状态。
- 初始化日志由控制器生成，Agent 不得手写状态或 gate 结论。

### 复跑结果

- OpenCode/GLM 本轮生成 216 个输入文件的基线，日志包含基线摘要和 `INIT_WORKSPACE gate: PASS`。
- `flashDB_rust` 未预生成；阶段状态正确指向 `READ_C_PROJECT`。

### 当前状态

已解决。没有发现需要继续修改初始化调度的功能性问题。

## READ_C_PROJECT

### 问题

- [x] 旧版阶段日志只记录扫描数量，不能直接显示输入摘要和只读完整性结果。
- [ ] 阶段日志尚未直接列出 `gate_exit_code=0` 和 `unexpected_changes=[]`，目前只有机器 receipt 记录这两个字段。

### 修复记录

- `workflowctl finish` 自动生成 `02-read-c-project.md`，写入 `input_digest`、源码/头文件/测试/构建文件数量和只读校验说明。
- receipt 由控制器记录 `gate_exit_code` 和 `unexpected_changes`，输入基线由控制器持续保护。

### 复跑结果

- GLM 的 `input_manifest.json` 与 GPT 标准结果逐字节一致。
- 核心源码 5 个、头文件 7 个、测试源码 6 个、构建文件 3 个；`input_digest` 为 `ff175c4ec62915a60350dd5a428f4fa5d2b35639cdab8c9a18b54fd86d4707f4`。
- READ receipt：`gate_exit_code=0`、`unexpected_changes=[]`。

### 当前状态

扫描范围和输入证据达到 GPT 标准。仍有一个低优先级证据表达优化：阶段日志目前写有只读校验说明，但没有直接列出 `gate_exit_code=0` 和 `unexpected_changes=[]`；机器 receipt 已记录这两个字段，暂不影响 gate。

## BUILD_C_MODEL

### 问题

- [x] 测试文件中同名函数先出现 prototype、后出现 definition；旧版 `extract_functions()` 采用首次出现去重，导致 `test_fdb_kvdb_deinit` 丢失函数体。
- [x] 该场景退化为只有 `invoke_test`，API 调用和断言消失，但旧 gate 仍可通过。
- [x] 输入摘要字段曾可被省略；BUILD task packet 曾没有明确绑定 `input_manifest.json`。
- [x] 日志容易把 23 个唯一测试函数误读为 24 个注册场景。

### 修复记录

- `build_c_model.py` 按 `(file, name)` 选择最佳函数记录，`definition` 覆盖 `prototype`，不写具体测试名特判。
- 增加 `unresolved_registered_tests`，注册测试缺 definition 或语义记录时保留失败证据。
- BUILD gate 强制校验 scenario IR schema、注册测试/场景一一对应、unresolved 为空，以及 semantic facts 与 IR 中 API/assertion 步骤一致。
- BUILD 和 DESIGN 模型必须携带非空且匹配 manifest 的 `input_digest`。
- `workflowctl begin BUILD_C_MODEL` 将输入摘要和 `input_manifest.json` 文件 hash 注入 task packet；finish 校验三方一致性。
- BUILD 日志由控制器区分唯一注册测试、注册调用、标准场景、unresolved 和 invoke-only 场景。
- 增加 prototype/definition、注册测试解析和 semantic facts/IR 一致性回归测试。

### 复跑结果

- GLM 本轮：23 个唯一注册测试、24 次注册调用、24 个标准场景，`unresolved_registered_tests=[]`，invoke-only 场景为无。
- `test_fdb_kvdb_deinit` 已恢复：`public_api_calls=["fdb_kvdb_deinit"]`、`assertion_count=1`，IR 包含 `invoke_test`、API `call` 和 `assertion`。
- 三个 C 模型的 `input_digest` 均为 `ff175c4ec62915a60350dd5a428f4fa5d2b35639cdab8c9a18b54fd86d4707f4`。
- BUILD receipt：`gate_exit_code=0`、`unexpected_changes=[]`。

### 当前状态

已解决。该结果比旧 GLM 产物正确，且关键事实与 GPT 标准一致；GLM 仍保留更丰富的结构化 ABI 和 scenario IR 证据。

## DESIGN_RUST_API

### 问题

- [x] 上游空语义会传播到 Rust API 设计，导致设计只保留场景标签而缺少真实 API/断言义务。
- [x] 设计阶段生成 `ffi_manifest.json`，但旧 workflow contract 未将它列入 DESIGN 的允许路径和 required outputs，真实 OpenCode 运行会被控制器拒绝。
- [x] implementation requirements 的建议路径曾写成 `src/c_abi.rs`，与实际 FFI 导出文件 `src/ffi/c_abi.rs` 不一致。
- [x] 设计日志应明确写 C ABI facade，而不是误称独立 FFI manifest API 数量。
- [ ] `04-design-rust-api.md` 尚未直接列出 `ffi_manifest.json` 的路径、API 数量和摘要校验结果。

### 修复记录

- DESIGN gate 继续消费并校验上游 semantic facts/IR，禁止空语义静默进入设计。
- 将 `logs/trace/ffi_manifest.json` 加入 DESIGN 的 allowed paths 和 required outputs。
- `design_rust_api.py` 为 FFI manifest 写入 schema、阶段和 input digest；gate 校验其摘要及 API 集合与 `c_abi_facade.functions` 一致。
- implementation requirements 使用 `src/ffi/c_abi.rs`，并保留 schema v2 的 symbols、acceptance scenarios、dependency IDs 和 bounded task packet 结构。
- DESIGN 阶段日志由控制器自动生成，并使用“C ABI facade”表述。

### 复跑结果

- GLM 本轮 DESIGN receipt：`gate_exit_code=0`、`unexpected_changes=[]`，下一阶段正确指向 `GENERATE_RUST_SCAFFOLD`。
- `rust_api_design.json` 包含 31 个 facade 函数、12 个 facade 结构体和 9 项 implementation requirements。
- `test_fdb_kvdb_deinit` 在设计产物中仍包含 `fdb_kvdb_deinit` 调用和 1 条断言义务，没有发生上游语义回退。
- `ffi_manifest.json` 包含 31 个 API，schema 为 1，阶段为 `DESIGN_RUST_API`，input digest 与三份 C 模型一致。
- 9 项 requirements 均包含 `src/ffi/c_abi.rs`，没有错误的 `src/c_abi.rs` 路径。

### 当前状态

阶段 4 产物和调度契约一致，无需回退到 GPT 的较弱结构。仍可补充一个低优先级日志优化：`04-design-rust-api.md` 目前没有直接列出 `ffi_manifest.json` 的路径、API 数量和摘要校验结果，机器 gate 已完成这些校验。

## GENERATE_RUST_SCAFFOLD

### 问题

- [x] 旧版脚手架阶段缺少可验证的 scaffold manifest、ownership 信息和真实 C/Rust layout-only 检查。
- [x] `generate_rust_scaffold.py` 本身曾覆盖已有 `flashDB_rust` 源码；现在只有 manifest 文件 hash 与设计 hash 都匹配的原始 scaffold 才允许再次生成，已有实现或额外项目文件会被拒绝覆盖。
- [x] 当前 `generate_rust_scaffold.py` 曾把大量具有明确 ABI 证据的字段降成 `[u8; N]`；现在 pointer、fixed-width/已解析 typedef、定长数组和具名 struct 会生成可访问 Rust 字段，同时保持 layout 验证。
- [ ] 匿名 struct/union 与 callback 的内部语义字段仍使用精确 `[u8; N]`；这是当前缺少嵌套字段 ABI 证据时的安全边界，若后续 extractor 提供嵌套 layout，再生成具名辅助类型。
- [x] layout-only 流程曾同时留下 `scaffold-layout-check.log` 和 `scaffold_layout-check.log` 两个近似重复日志；现在统一使用前者。

### 修复记录

- `workflowctl` 为阶段 5 强制绑定 `rust_api_design.json`、`input_manifest.json` 和 task packet 摘要。
- `workflowctl init` 在已有 `flashDB_rust` 时默认拒绝初始化；只有显式 `--force` 才允许清理并开始全新运行。REWRITE repair 复用原始 scaffold baseline，不要求重新生成脚手架。
- 生成器新增 manifest/hash 内容级覆盖保护：缺 manifest、设计摘要不同、项目文件新增/缺失或 hash 变化都会拒绝写入；`init --force` 仍是主控显式启动全新运行的唯一清理路径。
- `rust_field_type()` 现在消费 ABI extractor 的 field kind、array extents、resolved C->Rust 类型和具名 struct 布局；只对无法可靠解释的匿名聚合/callback 保留 byte region。
- scaffold layout checker 的内部编译/运行输出写回 canonical `scaffold-layout-check.log`，不再生成下划线副本。
- 脚手架生成 `scaffold-manifest.json`，记录 31 个 FFI 函数、neutral stub、placeholder module、设计 hash 和 rewrite ownership。
- `c_cross_validate.py --scaffold-layout-only` 执行真实 Rust staticlib 编译、C layout checker 编译和运行；layout 不匹配时 gate 失败。
- 当前保留 byte-region 的确定性策略，避免弱模型在未知 C 类型上猜测并破坏 ABI；字段类型恢复列为本阶段后续优化，必须以 ABI 模型的明确类型证据为依据，不能凭 Rust 侧猜测。

### 复跑结果

- OpenCode/GLM 本轮 receipt：`gate_exit_code=0`、`unexpected_changes=[]`，下一阶段正确指向 `REWRITE_CORE_MODULES`。
- `scaffold-layout-check.json`：`build_status=pass`、`layout_status=pass`、12 个结构体全部匹配。
- manifest 的设计 hash 与 `rust_api_design.json` 一致；31 个 FFI 函数全部映射到 `src/ffi/c_abi.rs`，ownership 路径和 frozen contract 路径均已生成。
- 生成 4 个 placeholder core modules 和 31 个 neutral FFI stubs，符合阶段 5 尚未实现核心逻辑的边界。

### 当前状态

阶段契约、真实 layout 验证、ownership 证据、生成器内容级覆盖保护、已知 ABI 字段类型保真度和重复日志文件已修复。匿名聚合/callback 的嵌套字段提取仍是后续增强；neutral scaffold 仍不代表已实现 Rust 核心逻辑。

## REWRITE_CORE_MODULES

### 问题

- [x] 旧版 frozen signature 采用格式敏感的文本比较，`cargo fmt` 给多行 FFI 参数添加尾逗号后会被误判为签名变化，曾导致多次完整重跑。
- [x] 旧版 task packet 使用固定 24576-byte 限制，真实 packet 约 32 KiB 时失败，弱模型又不能在活跃阶段修改受保护 contract。
- [x] 旧版 REWRITE 父阶段没有 generic task packet，但 gate 曾错误强制要求父阶段 packet，导致控制器与 gate 契约冲突。
- [x] 旧版 REWRITE 失败后容易通过 `init --force` 全量重来，重复执行 C 分析、脚手架、IMPLEMENT_CORE 和 WIRE_FACADE，造成约 75% 时间消耗在重复劳动。
- [ ] 上述 REWRITE 修复尚未经过当前新版本 OpenCode/GLM 的阶段 6 完整复跑验证。

### 修复记录

- frozen signature 使用语法归一化比较，忽略空白和 Rust 合法的末尾参数逗号；已增加 trailing-comma 回归测试，不再依赖 `#[rustfmt::skip]` 维持文本格式。
- task packet 改为按 requirement、scenario 和 scenario step 数量做结构化边界，不再用 24576-byte 硬上限；本轮阶段 5 的 32678-byte packet 已正常提交。
- REWRITE 父事务明确为 controller-only，不生成 generic broad packet；`IMPLEMENT_CORE` 和 `WIRE_FACADE` 各自由 `next-rewrite-worker` 生成精确 ownership packet。
- REWRITE gate/worker 失败时保留首次 scaffold-era baseline，并在当前源码上释放新的定向 worker；禁止重新生成 scaffold、Git 回退或通过 `/tmp`/复制备份恢复。
- worker receipt 绑定 parent run、role、revision、changed files、hash 和 bounded check，facade 必须基于最新 core revision。

### 复跑结果

- 旧版本运行累计约 187 分钟的 subagent 时间，其中 frozen signature、脚手架覆盖和控制器契约问题导致约 3 次完整重跑；该数据作为优化前基线保留。
- 当前代码级回归测试已覆盖 cargo fmt 尾逗号等价性，控制器代码已实现父事务/worker packet 分离及 retry baseline 复用。
- 当前新版本尚未执行完阶段 6，因此 IMPLEMENT_CORE/WIRE_FACADE 是否一次收敛、是否仍发生完整重跑，需要下一次阶段暂停时核验。

### 当前状态

历史控制器与签名格式缺陷已修复；端到端复跑验证待阶段 6 完成。若仍出现要求 `init --force`、重跑 scaffold 或父阶段 packet 缺失，应视为回归。

## 本轮阶段 1–5 总结

- OpenCode/GLM 本轮阶段 1–5 均由控制器 receipt 通过，并记录了 C 分析阶段族和脚手架阶段的 subagent 调用证据。
- 输入 manifest 与 GPT 标准逐字节一致；C project model 与 GPT 标准逐字节一致。
- C API/test/design 模型的 JSON hash 与 GPT 不同，但差异来自 GLM 更丰富的 ABI 字段、scenario IR、摘要绑定和 FFI manifest，不是关键事实回退。
- 当前剩余项包括阶段日志表达、匿名聚合/callback 的嵌套字段 ABI 提取，以及阶段 6 的端到端复跑验证。
- 后续阶段应继续由 OpenCode 执行；Codex 只读检查产物并更新本文件，不得重跑或写入 `02_02/logs/**`。
