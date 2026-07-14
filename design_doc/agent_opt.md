# Agent 优化记录

本文档记录 `02_02`（opencode + GLM）与 `02_02_gpt`（Codex + GPT 标准答案）逐阶段对比后确认的 Agent、工作流和证据链优化点。

## INIT_WORKSPACE

### 对比结论

当前 GLM 初始化结果已经优于 GPT 标准答案：

- `02_02/logs/trace/workflow_state.json` 保留了 `INIT_WORKSPACE` 当前状态、`READ_C_PROJECT` 下一步、运行目录身份和 `last_gate.status=pass`。
- `02_02/logs/trace/input-source-baseline.json` 已生成，记录了输入工程 216 个文件及其 SHA256，可用于后续阶段防止修改题目输入。
- `02_02/logs/trace/agent-registry.json` 已注册四个 subagent，和 GPT 结果的职责划分一致。
- 当前没有预生成 `flashDB_rust`，符合脚手架必须由后续阶段生成的约束。

GPT 结果中的初始化日志对“尚未生成 Rust 项目”的表达更明确，但 GPT 最终覆盖后的 `workflow_state.json` 不再保留初始化阶段的运行身份、基线和 gate 信息，因此不适合作为可暂停恢复的阶段证据。

### 已确认的优化点

1. 让 `workflowctl init` 自动生成更完整的 `logs/trace/01-init-workspace.md`，至少包含：
   - 当前阶段和下一阶段；
   - `workflow_state.json`、`input-source-baseline.json`、`agent-registry.json` 是否生成；
   - 输入基线文件数量和摘要 hash；
   - init gate 结果；
   - `flashDB_rust` 尚未生成的确认。
2. 初始化日志只作为人类可读摘要，机器状态仍由 `workflowctl` 独占维护，避免要求弱模型手写状态 JSON。
3. 后续阶段不得覆盖或丢失初始化阶段的重要控制证据；如果状态文件采用滚动更新，至少应保留 `completed_stages`、输入基线引用、运行目录身份和最近 gate 结果。

### 当前处理决定

本阶段没有发现需要立即修改 GLM 调度提示或初始化契约的功能性缺陷。上述优化属于证据表达和状态持久化增强，待后续阶段对比完成后统一评估是否实施。

## READ_C_PROJECT

### 对比结论

GLM 生成的 `input_manifest.json` 与 GPT 标准结果逐字节一致，输入摘要也一致：

- 核心源码 5 个、头文件 7 个、测试源码 6 个、构建文件 3 个；
- `input_digest` 均为 `ff175c4ec62915a60350dd5a428f4fa5d2b35639cdab8c9a18b54fd86d4707f4`；
- 文件路径、大小和 SHA256 证据一致；
- 阶段 receipt 显示 `gate_exit_code=0`、`unexpected_changes=[]`，没有修改平台 C 输入。

因此本阶段没有发现扫描范围或模型能力差异，GLM 已达到 GPT 标准结果。

### 已确认的优化点

1. `02-read-c-project.md` 应补充输入只读校验结果、`input_digest` 和 `unexpected_changes=[]`，使人类日志能够直接说明输入未被修改，而不是只记录文件数量。
2. 上述摘要应由 `workflowctl` 根据 receipt 和 manifest 自动生成，避免弱模型自行复制 hash 或声称“只读成功”。

### 当前处理决定

不需要修改扫描工具和阶段 gate；仅建议增强自动阶段摘要。

## BUILD_C_MODEL

### 对比结论

本阶段大部分结果达到或超过 GPT 标准结果：

- `c_project_model.json` 与 GPT 结果逐字节一致；
- 31 个公开函数及其 `function_signatures` 与 GPT 一致，`unresolved_signatures=[]`、`unresolved_types=[]`；
- 12 个 ABI 结构体的 `sizeof`、`alignof`、字段 offset 和字段 size 与 GPT 一致；GLM 结果还新增了字段声明、字段类型、数组维度、指针目标和回调签名等结构化证据；
- 23 个唯一注册测试函数、24 次注册调用和 24 个动态场景均已生成；
- 新版模型增加了有序 `scenario_ir`，总体信息量高于 GPT 标准结果。

但对比发现一个会影响后续阶段的高优先级解析缺陷：

- `test_fdb_kvdb_deinit` 在 C 输入中先出现 prototype，后出现 definition；
- `extract_functions()` 以 `(file_name, name)` 去重，先保存 prototype 后跳过同名 definition；
- `extract_function_body_records()` 只接收 `kind=definition`，因此没有提取该测试的函数体；
- GLM 的该场景最终只有 `invoke_test` 一步，`public_api_calls=[]`、`assertion_count=0`；
- GPT 标准结果正确提取到 `fdb_kvdb_deinit` 调用以及 `== FDB_NO_ERR` 断言；
- 该场景的 `semantic_obligations` 从 GPT 的 `assertion_count + assertion_intent + calls:fdb_kvdb_deinit + deinit + init` 退化为只有 `deinit + init`。

旧 GPT 模型中额外出现的 `free` 函数语义属于旧解析器把控制块误识别为函数的假阳性；新版消除该假阳性是正确改进，不能为了对齐 GPT 而恢复。

### 已确认的优化点

1. **高优先级：修复 prototype/definition 去重。** `extract_functions()` 遇到同文件同名记录时必须让 definition 覆盖 prototype，或分别记录声明与定义，不能采用“第一次出现即永久占用”的去重方式。
2. 增加回归测试：测试文件中同一函数先声明、后定义时，`test_semantics` 和 `scenario_ir` 必须包含定义体中的 API 调用与断言。
3. 强化 `BUILD_C_MODEL` gate：对于能够在当前测试文件中定位到 definition 的注册测试，`scenario_ir` 不能只有 `invoke_test`；至少应包含一条来自测试体或其 helper/callback 的语义步骤。该规则必须动态基于解析出的 definition，不能写死测试名称或固定数量。
4. 阶段日志应明确区分：23 个唯一注册测试函数、24 次注册调用、24 个场景。当前“注册测试数量：23”容易让后续弱模型误以为只有 23 个待迁移用例。
5. `scenario_ir_schema_version` 应纳入 gate 校验，避免字段存在但 schema 版本或语义内容不可用时仍然通过。

### 当前处理决定

该解析缺陷会直接削弱 Rust API 设计、实现要求和后续测试迁移，建议在继续依赖当前模型实施核心逻辑前修复并重新执行 `BUILD_C_MODEL + DESIGN_RUST_API`。如果先继续跑脚手架，本问题仍应在进入测试迁移前修复并重建下游产物。

### 修复设计

#### 1. 修复函数声明与定义的选择规则

修改 `work/tools/build_c_model.py` 的 `extract_functions()`：

- 不再使用 `seen` 让同文件同名函数的第一条记录永久胜出；
- 改为以 `(file_name, function_name)` 为键保存当前最佳记录；
- 同名记录优先级固定为 `definition > prototype`；
- 如果先遇到 prototype、后遇到 definition，必须用 definition 替换；
- 如果先遇到 definition、后遇到 prototype，保持 definition；
- 不根据具体测试名、文件名或函数前缀写特殊分支。

`extract_function_body_records()` 继续只消费 definition。这样修复选择规则后，它会自然提取真实函数体，无需为 `test_fdb_kvdb_deinit` 增加例外。

#### 2. 增加注册测试解析闭环

构建 `c_test_model.json` 时检查每个动态发现的 `registered_tests`：

- 注册目标必须能够在当前测试输入中解析到 definition；
- 必须能够在 `test_semantics` 中找到同名语义记录；
- 无法解析时写入通用的 `unresolved_registered_tests`，包含测试名、注册位置和失败原因；
- 正常比赛流程要求 `unresolved_registered_tests=[]`，不得用空语义场景冒充成功。

该检查以当前输入中实际提取出的注册目标为准，不写死 23、24 或任何测试函数名。

#### 3. 强化 BUILD_C_MODEL gate

在 `work/tools/gate.py` 增加以下动态约束：

1. `scenario_ir_schema_version` 必须是工作台支持的版本。
2. `registered_tests` 必须全部存在于 `test_semantics`。
3. `unresolved_registered_tests` 必须为空。
4. 每个注册调用必须一一对应 `standard_scenarios` 和 `scorer_standard_cases`。
5. 如果 `semantic_facts.assertion_count > 0`，对应 `scenario_ir` 必须存在 assertion 步骤。
6. `semantic_facts.public_api_calls` 中的每个 API，必须能在对应 `scenario_ir` 中找到 public API 调用步骤。

这些规则可以阻止“只有 invoke_test、没有函数体语义”的场景通过，同时允许真正没有 API 调用或断言的空函数通过结构解析检查；是否接受空测试可由独立质量规则判断。

#### 4. 增加回归测试

在工作流测试中至少增加以下通用夹具：

- 先 prototype、后 definition：最终记录必须是 definition，并成功提取 API 调用和断言；
- 先 definition、后 prototype：definition 不得被降级覆盖；
- 控制块中的 `free(...)`：不得误识别为函数 definition；
- 注册目标没有 definition：模型必须产生 unresolved 证据，gate 必须失败；
- semantic facts 声明了 API/断言但 scenario IR 缺失对应步骤：gate 必须失败。

#### 5. 重建下游产物

修复后通过 `workflowctl` 支持的重新执行路径重跑 `BUILD_C_MODEL` 和 `DESIGN_RUST_API`，不得手工编辑 `c_test_model.json` 或 `rust_api_design.json`。重跑后重点确认：

- `test_fdb_kvdb_deinit` 的 `public_api_calls` 包含 `fdb_kvdb_deinit`；
- `assertion_count` 恢复为 1；
- `scenario_ir` 包含 API 调用和 assertion；
- `semantic_obligations` 恢复 API 调用与断言义务；
- 两个阶段重新生成并通过 receipt/gate。

## DESIGN_RUST_API

### 对比结论

除继承上游 `test_fdb_kvdb_deinit` 语义缺失外，GLM 的设计产物整体强于 GPT 标准结果：

- crate、模块、KVDB/TSDB API 数量、31 个 C 到 Rust 符号映射和 12 个 ABI facade 结构均完整；
- ABI 数值布局与 GPT 一致，同时保留了更丰富的字段类型证据；
- 9 项核心实现要求的 ID 与 GPT 一致；
- 新版 `implementation_requirements_schema_version=2`，每项要求增加 `symbols`、`acceptance_scenarios`、`suggested_files` 和 `dependency_ids`，更适合弱模型按边界实施和验证；
- DESIGN_RUST_API receipt 通过，下一阶段正确指向 `GENERATE_RUST_SCAFFOLD`。

上游解析缺陷已经传播到设计产物：`test_api.scorer_standard_cases` 中的 `test_fdb_kvdb_deinit` 缺少 `fdb_kvdb_deinit` 调用和成功返回断言，因此后续模型可能只迁移“deinit 场景名称”，却不验证真实行为。

### 已确认的优化点

1. 修复阶段 3 后必须重新生成 `rust_api_design.json`，不能只手工补阶段 4 的 JSON。
2. `DESIGN_RUST_API` gate 应拒绝“注册场景只有标签义务、但其已解析 definition 中存在 API 调用或断言”的设计输入，防止上游空语义静默传播。
3. `04-design-rust-api.md` 中“FFI manifest API 数量：31”命名不准确；本阶段尚未生成独立 `ffi_manifest.json`，应写成“C ABI facade 函数数量：31”。
4. 保留 schema v2 的结构化实现要求。相较让弱模型阅读完整大 JSON，应继续通过 bounded task packet 按相关 requirement 和 scenario 下发局部证据。

### 当前处理决定

阶段 4 的设计结构和调度边界无需回退到 GPT 版本；需要修复的是阶段 3 的事实提取，以及阶段 4 对空语义输入的拒绝能力。

## 阶段 1–4 复跑复查（2026-07-14）

### 总体结论

本次确实生成了全新的运行状态、task packet 和三个阶段 receipt，并以一条 `stage=C_ANALYSIS`、`mode=generic_subagent` 的调用记录覆盖 `READ_C_PROJECT + BUILD_C_MODEL + DESIGN_RUST_API`。阶段顺序、单 session 阶段族和控制器回执链均正确。

但阶段 3 的 prototype/definition 缺陷没有被修复，复跑只是确定性地重现了同一错误：

- `build_c_model.py` 仍使用 `seen`，同文件同名函数第一次出现后直接跳过后续记录；
- `c_test_model.json` 的 SHA256 仍为问题版本 `b235a0d2090fbe2cde81e569355ecbb7a0ff6b76925602e5203d53fff2f31389`；
- `test_fdb_kvdb_deinit` 仍不在 `test_semantics` 中；
- `standard_scenarios` 和 `scorer_standard_cases` 中该场景仍只有 `invoke_test`；
- `public_api_calls=[]`、`assertion_count=0`，语义义务仍只有 `deinit + init`；
- `rust_api_design.json` 继续继承同一空语义结果；
- BUILD_C_MODEL 与 DESIGN_RUST_API gate 仍错误返回 PASS。

因此本次复跑不能视为问题已修复，也不能因为三个 receipt 均为 PASS 就继续信任阶段 3、4 的全部测试语义。

### 分阶段复查

#### INIT_WORKSPACE

- 输入基线仍包含 216 个文件，状态、运行目录身份、agent registry 和空 interaction log 均正常。
- 没有预生成 `flashDB_rust`，符合阶段边界。
- `01-init-workspace.md` 仍是旧的单句摘要，之前记录的自动摘要优化尚未实施。

`02_02/fdb_test_blob/kvdata.bin` 是用户主动删除的旧运行数据，不属于本次 Agent 行为或阶段缺陷，不纳入优化项。

#### READ_C_PROJECT

- `input_manifest.json` 继续与 GPT 标准结果逐字节一致；扫描范围、文件摘要和 `input_digest` 均正确。
- receipt 为 PASS，`unexpected_changes=[]`。
- 新阶段日志比上一轮更完整，已经记录输入摘要和只读扫描说明。

本阶段无新增功能缺陷。

#### BUILD_C_MODEL

- C 项目模型与 GPT 逐字节一致；31 个公开函数签名、12 个 ABI 数值布局及 unresolved 状态正确。
- ABI 字段结构化证据和有序 scenario IR 仍比 GPT 版本丰富。
- 日志已正确区分 24 次注册调用和 24 个场景，比上一轮“注册测试数量 23”的摘要更清楚。
- prototype/definition 缺陷和 gate 漏检仍完整存在，必须按前述修复设计处理。

#### DESIGN_RUST_API

- 31 个符号映射、12 个 facade 结构、15 个 KVDB API、13 个 TSDB API 和 9 项 implementation requirements 均存在。
- 阶段日志已改用 `c_abi_facade` 表述，不再把本阶段产物误称为独立 `ffi_manifest.json`。
- `test_fdb_kvdb_deinit` 的空语义仍被复制到 `test_api.scorer_standard_cases`，所以阶段 4 仍需在阶段 3 修复后重新生成。

### 测试状态补充

- 有序 scenario IR 的专门单元测试通过。
- `ScenarioIrAndTaskPacketTests` 整组 9 项中有 4 项失败，失败集中在 task packet 的 allowed-path 预期与当前 workflow contract 不一致，涉及 VERIFY 和 REPORT 范围；这与本次 deinit 解析缺陷不是同一问题。
- 这些失败说明测试断言与现行 task packet 合同存在漂移，应单独校准，但不能用它们代替 prototype/definition 回归测试；当前仍没有覆盖该解析缺陷的测试。

### 继续执行建议

在执行 `GENERATE_RUST_SCAFFOLD` 前，先实际修改 `build_c_model.py`、补强 `gate.py`、增加 prototype/definition 回归测试，然后重新生成阶段 3、4。仅再次运行未修改的工作台不会改变结果。

## 阶段 1–4 其他优化项

以下问题不是 `test_fdb_kvdb_deinit` 解析缺陷的重复描述，但会降低弱模型后续执行的可靠性。

### 1. 输入摘要校验可以被省略字段绕过

当前 `BUILD_C_MODEL` 和 `DESIGN_RUST_API` gate 仅在产物已经包含 `input_digest` 字段时比较摘要。模型如果完全省略该字段，条件不会报错，仍可能通过其他结构检查。

优化要求：

- `c_project_model.json`、`c_api_model.json`、`c_test_model.json` 和 `rust_api_design.json` 必须存在非空 `input_digest`；
- 每个摘要必须严格等于 `input_manifest.json.input_digest`；
- task packet 同时携带该摘要，receipt 保存 packet hash；
- gate 应将“字段缺失”和“摘要不一致”分别报告，不能采用可选字段语义。

### 2. BUILD_C_MODEL task packet 缺少输入身份

本次 `build_c_model.json.input_digest=null`，`source_artifacts` 也没有记录 `input_manifest.json`。虽然命令参数引用了 manifest，但调度包本身无法证明它针对哪一版输入生成。

优化要求：

- `workflowctl begin BUILD_C_MODEL` 从当前 `input_manifest.json` 注入 `input_digest`；
- `source_artifacts` 增加 manifest 的相对路径和文件 hash；
- `workflowctl finish` 校验 task packet digest、模型 digest 和当前 manifest digest 三者一致；
- `READ_C_PROJECT` 在 manifest 尚未生成前可以保持 digest 为空，但其 receipt 必须保存最终 manifest hash。

### 3. implementation requirements 的建议文件与真实实现落点偏离

当前 9 项 `implementation_requirements[*].suggested_files` 全部包含 `src/c_abi.rs`。但脚手架把真正的 31 个导出函数记录为 `src/ffi/c_abi.rs`，GPT 标准答案的核心重写批次也主要修改 `src/ffi/c_abi.rs`，而不是 `src/c_abi.rs`。

这会诱导弱模型修改 facade 占位层，却漏掉真正参与 C runner 链接的导出实现。

优化要求：

- 不在 `design_rust_api.py` 中无条件写死 `files={"src/c_abi.rs"}`；
- 将实现要求先表达为逻辑组件，例如 `ffi_export_facade`、`storage_core`、`kvdb_core`、`tsdb_core`；
- `GENERATE_RUST_SCAFFOLD` 生成 `scaffold-manifest.json.rewrite_ownership` 后，再把逻辑组件解析为真实文件路径；
- 如果设计阶段必须给出路径，FFI symbol requirement 至少应包含 `src/ffi/c_abi.rs`，并与脚手架中 `ffi_functions[*].path` 保持同一权威来源；
- 后续 task packet 应优先使用 scaffold ownership，而不是直接相信设计阶段的 suggested_files。

### 4. 阶段日志仍由弱模型手工总结

本次阶段 2–4 日志比上一轮清楚，但 BUILD_C_MODEL 日志仍声称 24 个场景都具有有序 call/control/assert 语义，而实际有一个场景只有 `invoke_test`。这说明长篇日志不能替代机器检查。

优化要求：

- 文件数量、摘要、unresolved 数量、invoke-only 场景数量和 gate 结果由工具自动生成；
- Agent 只补充简短决策说明，不手工复制大清单；
- 日志若存在 `invoke_only_scenarios` 或 `unresolved_registered_tests`，不得写“模型完整”或进入下一阶段。

### 5. task packet 测试与现行合同漂移

`ScenarioIrAndTaskPacketTests` 当前 9 项中有 4 项失败，均为测试期待的 allowed paths 与现行 workflow contract 不一致。专门的 scenario IR 顺序测试能够通过，但没有覆盖 prototype/definition 回归。

优化要求：

- allowed-path 测试从 `workflow-contract.json` 的权威规则构造期待值，避免复制旧路径集合；
- 对 VERIFY/REPORT 的路径收紧或扩展必须同步更新测试；
- 新增 prototype/definition、registered-test resolution 和 semantic-facts/IR 一致性测试；
- 在这些合同测试恢复全绿前，不把单次阶段 gate PASS 当作工作台整体健康证明。
