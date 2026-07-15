# Q11 - OpenCode 上下文爆炸分析与优化方案

> 分析对象：2026-07-15 从 `/home/nv_test/c2rust` 启动、执行 `02_02` 转换工程的 OpenCode 运行  
> 分析快照：2026-07-15 20:58（Asia/Shanghai）  
> 文档状态：分析与待审批方案，尚未实施

## 1. 结论

本次故障不是“subagent 数量太多”或“递归层级太深”导致的。

本次 7 个 subagent 全部是主 Agent 的直接子会话，没有递归创建；第六个仍然因为在一个 session 中连续承担源码读取、实现、验证、崩溃排查和再次修复而达到 GLM-5.1 的输入上限。限制递归不能解决本次问题。

正确方向是：

1. 主 Agent 保持轻量，只负责阶段推进、运行确定性工具、验证共享工作区和生成最终报告；
2. 允许按实际失败数量启动多个短生命周期 subagent，不设置固定总数上限；
3. 每个 subagent 只处理一个边界明确的工作单元，完成一次修改后立即退出；
4. 新 session 通过工作区文件、最新 failure summary 和短交接继续，不继承旧 session 的全部对话；
5. 在平台允许加载项目插件时，增加提前触发的自动 summarize/compact 兜底；插件不可用时，依靠主动 session 轮换保证任务不会因上下文耗尽停止。

因此，目标执行模型不是“单 Agent”或“限制只能启动一个 subagent”，而是：

```text
薄主 Agent + 多个短期、边界明确的 subagent + 可选的项目级自动 compact 兜底
```

## 2. 证据范围与口径

本次分析只读取以下本地证据，没有中断或修改仍在运行的 OpenCode 任务：

- OpenCode 进程与工作目录；
- `~/.local/share/opencode/opencode.db` 中的 session、message、part 和 event；
- OpenCode 1.17.20 的已安装插件与 SDK 类型；
- 当前解析后的自定义模型配置结构；
- `02_02/INSTRUCTION.md` 与 `02_02/work/skills/*.md`；
- 本次主 Agent 和 7 个 subagent 的真实 task prompt、工具调用和输出规模。

需要区分两个 token 指标：

- session 表中的 `tokens_input` 是多次请求的累计输入量，不能代表当前上下文窗口；
- 每条 assistant message 的 `tokens.total` 才能近似表示该次模型请求实际携带的上下文规模。

第六个 subagent 的 `tokens_input = 1,209,998` 是累计量；导致失败的最后一次有效请求为 `202,669 tokens`。

## 3. 本次运行拓扑

主 session：

```text
ses_09cace0c0ffeGXzmmMIuxJrUAD
标题：读取并执行02_02指令
Agent：build
```

7 个直接子 session：

| 序号 | 标题 | 最后/最大上下文 | 状态 | 风险 |
|---:|---|---:|---|---|
| 1 | Read FlashDB C source files | 25,222 | 已完成 | 低 |
| 2 | Read FlashDB kvdb/tsdb C source | 50,679 | 已完成 | 低 |
| 3 | Read FlashDB test files | 27,958 | 已完成 | 低 |
| 4 | Implement Rust core modules | 90,375 | 已完成 | 中 |
| 5 | Implement full Rust FFI modules | 175,930 | 已完成 | 若恢复则极高 |
| 6 | Fix GC sector allocation logic | 202,669 | APIError 失败 | 已触顶 |
| 7 | Fix GC sector allocation | 160,024 | 仍在运行 | 高 |
| 主 Agent | 读取并执行02_02指令 | 157,788 | 等待第七个 task | 高 |

GLM-5.1 本次由服务端返回的输入上限为 `202,745`。第六个在失败前已使用：

```text
202,669 / 202,745 = 99.96%
```

## 4. 问题一：第六个 subagent 在做什么，为什么爆

### 4.1 原始任务

第六个 subagent 负责修复剩余两个 GC 场景：

- `test_fdb_gc`；
- `test_fdb_gc2`。

主要目标是修正：

- sector 空间搜索顺序；
- dirty sector 选择；
- GC 搬移与格式化；
- KV 实际写入 sector；
- `oldest_addr` 更新。

允许修改的核心文件实际集中在：

- `flashDB_rust/src/storage.rs`；
- `flashDB_rust/src/kvdb.rs`。

这本应是一个边界明确的修复任务。

### 4.2 实际执行规模

第六个 session 共出现 88 个 assistant step、95 次工具调用：

| 工具 | 调用次数 | 返回内容规模 |
|---|---:|---:|
| `skill` | 1 | 17,323 字符 |
| `read` | 26 | 215,131 字符 |
| `grep` | 12 | 6,592 字符 |
| `edit` | 11 | 260 字符 |
| `bash` | 45 | 27,878 字符 |

它还加载了与本次实现修复无关的 `c-to-rust-scoring` Skill，单次引入 17,323 字符。

重复读取包括：

- `storage.rs` 多次大窗口读取；
- `kvdb.rs`；
- GC 测试函数多个重叠窗口；
- `fdb_kvdb.c` 多个重叠窗口；
- 多轮 C-Cross、runner 日志和调试输出。

后期任务从“修复 GC sector allocation”扩展到了：

- runner 崩溃；
- segfault；
- iterator/FFI 行为；
- standalone runner 与 gdb 调试；
- 多轮验证和再次修改。

### 4.3 直接失败

最后一次有效上下文达到 `202,669` 后，下一次请求收到：

```text
litellm.BadRequestError: DashscopeException
Range of input length should be [1, 202745]
Model Group=GLM-5.1
```

OpenCode 将其记录为：

```text
name: APIError
statusCode: 400
isRetryable: false
```

因此，第六个不是被某个单独的大文件瞬间打爆，而是在同一 session 中不断累积源码、工具结果、修改、验证和调试历史，最终达到硬上限。

### 4.4 根因

根因可以归纳为：

```text
任务虽然被分派给 subagent，但没有把一次修复限制为一个短生命周期工作单元。
```

具体包括：

1. dispatch prompt 本身长达 8,937 字符，预先重复写入大量 GC 分析和实现方案；
2. 没有“完成一次最小补丁后立即返回”的停止条件；
3. subagent 自己承担了实现、验证、失败分析和下一轮修复；
4. 没有在验证失败后切换到新 session；
5. 没有工具输出或上下文压缩兜底；
6. 实际使用的是内置 `general` subagent，不是受当前工程合同约束的 `rust-implementer` 或 `repairer`。

## 5. 问题二：其他 subagent 和主 Agent 的风险

### 5.1 第七个 subagent

第七个是第六个失败后的 GC 接力 session，但正在复制同一种风险模式。

截至快照时：

- 当前上下文 `160,024`，约占已知上限的 `78.9%`；
- 13 次 read，返回约 150,242 字符；
- 56 次 bash，返回约 66,451 字符；
- 7 次 glob；
- 6 次 edit；
- 已创建 `/tmp/test_kv.c`；
- 已查找和尝试使用 isolation 目录下的 standalone runner。

这同时违反了工程已有的三项规定：

1. 显式临时产物不得写入 `/tmp`；
2. `c_cross_validate.py` 是唯一 C runner 入口；
3. repair subagent 不负责运行 C-Cross 或自行形成成功结论。

即使第七个当前没有报错，只要继续几轮读取、编译和运行，就存在与第六个相同的触顶风险。

### 5.2 第五个 subagent

第五个最终上下文为 `175,930`，约占上限的 `86.8%`。它已经完成，因此不会自行继续增长；但如果恢复该 session 或继续交给它集成修复，很容易在下一轮触顶。

它的任务范围包括完整 FFI、KVDB、TSDB、公共模块、构建修复和阶段日志，本身就不是短任务。

### 5.3 主 Agent

主 Agent 当前上下文为 `157,788`，约占上限的 `77.8%`，而且后续还需要：

- 接收第七个 subagent 的结果；
- 运行验证；
- 迁移 Rust tests；
- 进行语义一致性审查；
- 生成最终报告；
- 运行最终 gate。

主 Agent 已直接读取约 377,822 字符，其中包括三份约 60 KB 的完整 JSON：

- `c_test_model.json`；
- `rust_api_design.json`；
- `c_api_model.json`。

这与当前合同中“大 JSON 是冷数据，只读必要片段”的要求相反。即使第七个返回内容很短，主 Agent 也没有足够余量安全完成剩余阶段。

### 5.4 subagent 数量不是风险指标

本次 7 个 subagent 全部是主 Agent 的直接子会话，没有递归 fan-out。由此可以确认：

- “限制递归深度”不能防止第六个触顶；
- “最多只能启动一个 subagent”会把更多源码、验证和修复历史压回主 Agent，风险更高；
- 单纯增加 subagent 数量也不能解决问题，因为重复读取、任务重叠和长 session 仍会浪费上下文。

应该限制的是每个 session 的工作单元，而不是全局 subagent 数量。

## 6. 问题三：为什么没有自动 compact

### 6.1 事实证据

第六个 session：

- `time_compacting = null`；
- 没有 `session.compacted` 事件；
- 没有进入 summarize/compact 状态；
- 最终错误类型是普通 `APIError`。

当前解析后的自定义模型 `csi-provider/GLM-5.1` 只配置了模型名称，没有配置：

- `limit.context`；
- `limit.input`；
- `limit.output`。

### 6.2 机制判断

最符合现有证据的机制链是：

1. OpenCode 的主动 overflow 判断需要模型元数据中的上下文上限；
2. 当前是自定义 provider/model，OpenCode 不知道其真实上限为 202,745；
3. 因此在 160K、180K、200K 时都没有主动触发 compact；
4. 真正触顶后，LiteLLM/Dashscope 返回普通 HTTP 400；
5. OpenCode 将它记录为 `APIError`，没有识别成可进入压缩恢复流程的上下文溢出错误；
6. session 直接失败，而不是先 summarize 再继续。

这不是“compact 执行失败”，而是 compact 根本没有被调度。

### 6.3 能否在工程内增加自动压缩兜底

可以尝试，但必须区分平台是否会加载项目插件。

当前安装的 OpenCode 1.17.20 插件接口提供：

- `message.updated` 事件；
- `session.error` 事件；
- `session.compacted` 事件；
- `experimental.session.compacting` hook；
- SDK `client.session.summarize(...)`。

其中 `experimental.session.compacting` 只能在压缩已经开始后修改压缩提示词，不能主动触发压缩。真正的主动兜底需要项目插件监听 token，并调用 `client.session.summarize(...)`。

建议的 context guard 行为：

1. 只处理已经完成、没有运行中 tool call 的 assistant message；
2. 读取该 message 的 `tokens.total`；
3. 当上下文达到安全阈值时调用 `session.summarize`；
4. 为每个 session 设置 in-flight 锁，避免同一批事件重复压缩；
5. 收到 `session.compacted` 后释放状态；
6. summarize 失败时只记录真实失败，不伪造已压缩或继续成功。

针对本次已知上限，建议初始阈值为：

```text
140,000 tokens 左右
```

该阈值约为 202,745 的 69%，可以为 summary 生成、一次大工具输出和下一次模型调用保留空间。不能等到 190K 以后再触发，因为 summarize 自己也需要输入和输出余量。

### 6.4 插件方案的限制

项目插件不是无条件可用：

1. 插件只在 OpenCode 启动时加载，不能补救当前已经运行的进程；
2. 当前本地 OpenCode 从 `/home/nv_test/c2rust` 启动，只有该项目根下的 `.opencode/plugins/` 会自然进入候选范围；
3. 比赛平台可能只打包或从 `02_02` 启动，也可能禁止提交方插件；
4. SDK 和 compaction hook 包含实验接口，升级 OpenCode 后可能变化；
5. summarize 本身也可能因为上下文过大或 provider 错误而失败。

因此，实施前必须先做一个最小兼容性试验，确认评分平台是否加载提交工程中的项目插件。插件只能作为第二层兜底，不能替代短 session 设计。

如果评分平台不加载项目插件，仅靠 `INSTRUCTION.md` 或 subagent Skill 无法实现真正的自动 compact，因为普通 Agent 不能可靠获得剩余上下文，也不能强制调用 OpenCode session API。

## 7. 问题四：当前工程为什么没有拦住

当前工程合同实际上已经写了正确方向：

- 默认主 Agent，subagent 只用于短、边界明确的辅助任务；
- 禁止使用内置 `General` 代替项目 subagent；
- 大 JSON 和历史日志是冷数据；
- C-Cross 失败时只读 failure summary、日志 tail 和相关源码窗口；
- subagent 不负责 C-Cross、cargo、gate 复跑或成功结论；
- 不得访问 `/tmp/**`；
- `c_cross_validate.py` 是唯一 runner 入口。

但本次真实运行与合同相反：

1. 7 个 task 全部指定 `subagent_type: general`；
2. 没有一个 task 要求 General 先读取对应的 `work/skills/{subagent}.md`；
3. 前三个 reader task 明确要求 `FULL content`、`do not summarize`；
4. 第四、第五个实现任务 prompt 分别达到 7,620 和 11,461 字符；
5. 第六个 prompt 达到 8,937 字符，并在 prompt 中重新编码完整 GC 方案；
6. 主 Agent 自己又重复读取大 JSON 和源码；
7. subagent 自己运行验证、standalone runner 和 `/tmp` 探针。

`work/skills/*.md` 是比赛工程内的权威合同，但本次 OpenCode 没有把这些文件注册成实际命名 subagent。于是 Markdown frontmatter 中的 permission 没有成为 General session 的工具层权限，只剩自然语言约束。

核心缺口不是“规则没写”，而是：

```text
调度行为没有稳定地引用并执行权威 subagent 合同。
```

## 8. 优化目标与非目标

### 8.1 目标

1. 不再出现单个 primary/subagent 因上下文耗尽而使工程直接停止；
2. 允许按任务需要启动多个 subagent；
3. 每个 subagent 都有明确输入、文件范围、修改次数和退出条件；
4. 主 Agent 不读取全文大模型产物和不必要源码；
5. subagent 失败后可由新 session 从共享工作区继续；
6. 平台支持时自动 compact，平台不支持时仍能依靠 session 轮换完成任务；
7. 不削弱真实 C-Cross、测试一致性、最终 gate 和失败报告要求。

### 8.2 非目标

本方案不做以下事情：

- 不设置“最多一个 subagent”或固定 subagent 总数；
- 不把禁止递归当成主要解法；
- 不新增 task queue、task packet、agent registry、receipt、controller 状态机；
- 不依赖修改评分平台的全局 OpenCode 配置；
- 不要求 subagent 自己精确计算剩余 token；
- 不让 subagent 自己判定阶段通过；
- 不通过删除测试、弱化断言或修改 gate 降低上下文压力。

## 9. 建议执行模型

```mermaid
flowchart TD
    P["薄主 Agent"] --> A["运行确定性分析和生成工具"]
    A --> I["实现任务"]
    I --> W1["短期实现 subagent"]
    W1 --> V["主 Agent 运行 C-Cross / cargo / gate"]
    V -->|"通过"| N["进入下一阶段"]
    V -->|"失败"| F["读取 failure summary 和必要 tail"]
    F --> W2["新的短期 repair subagent"]
    W2 --> V
    P -.-> G["项目 context guard"]
    G -. "达到安全阈值时 summarize" .-> P
    G -. "同样保护" .-> W1
    G -. "同样保护" .-> W2
```

### 9.1 主 Agent 职责

主 Agent 只负责：

- 运行工程工具；
- 读取短摘要和必要局部证据；
- 分派边界明确的实现或修复任务；
- 检查 subagent 实际写入；
- 运行 C-Cross、cargo、semantic review、consistency 和 gate；
- 根据最新失败决定是否启动新的 repair session；
- 生成最终报告。

主 Agent 不应：

- 让 reader subagent 返回源码全文；
- 自己全文读取大 JSON；
- 在 dispatch prompt 中重写 subagent 业务规则；
- 把全部实现或全部失败交给同一个长期 subagent；
- 在已经达到高风险上下文后继续承担新阶段。

### 9.2 subagent 工作单元

每个实现或 repair subagent 必须同时具备：

1. 权威 Skill 路径；
2. 当前动态失败或实现目标；
3. 明确允许读取的局部证据；
4. 明确允许修改的文件；
5. 一次修改后的退出条件。

建议最小 dispatch 形式：

```text
先完整读取并执行 work/skills/repairer.md。
动态任务：修复 failure-summary 中的 test_fdb_gc。
允许修改：flashDB_rust/src/storage.rs、flashDB_rust/src/kvdb.rs。
只读取该失败、日志尾部、对应 C test/helper 与 Rust 函数窗口。
完成一次最小修复后立即返回修改文件、根因和未解决点；不要运行 C-Cross、cargo、gate 或 standalone runner。
```

业务规则只保留在 `work/skills/{subagent}.md`。dispatch 只携带动态上下文，不再复制 4K–11K 的静态方案。

### 9.3 repair 轮换规则

建议 repair 流程：

1. 主 Agent 运行一次真实验证；
2. 从 `failure-summary.json` 选择一个可独立处理的 failure cluster；
3. 启动一个新的 repair subagent；
4. subagent 完成一次最小修改后退出；
5. 主 Agent 检查实际 diff 并复跑验证；
6. 若失败指纹变化或仍未解决，启动新的 repair session；
7. 新 session 只收到最新 failure summary、当前文件和上一次修改结果，不继承旧聊天历史。

这里不限制总共可以启动多少个 repair subagent。限制的是每个 session 只承担一次有界修复，防止单 session 无限增长。

### 9.4 并发与递归

允许多个 subagent 并行的条件：

- 文件所有权不重叠；
- 失败场景相互独立；
- 不会同时修改公共 ABI、共享 storage 或同一测试；
- 主 Agent 能在共享工作区验证各自写入。

涉及同一共享模块或同一失败链时应顺序接力，避免并发覆盖。

是否由 subagent 再创建下一级 subagent不是主要验收指标。只有下级任务同样满足独立文件范围和短生命周期时才有意义；否则多一层只会增加重复读取和交接。工程不需要全局禁止递归，但也不应把递归当作自动扩容手段。

## 10. 上下文输入边界

### 10.1 默认冷数据

以下内容默认不得全文进入 primary 或 repair session：

- `c_api_model.json`；
- `c_test_model.json`；
- `rust_api_design.json`；
- 历史 C-Cross 完整日志；
- 完整 C 源码树；
- 完整 C tests；
- 总设计文档；
- 历史评分报告。

必须先由确定性工具生成摘要，或使用 `rg` 定位后读取必要窗口。

### 10.2 修复输入

一次 repair 只允许读取：

- 当前 failure summary；
- 当前失败日志 tail；
- 失败 C test 函数；
- 该 test 直接调用且影响语义的 helper；
- 对应 Rust 函数；
- 本轮允许修改文件中的必要窗口。

如果发现问题跨出允许范围，subagent 应返回 `unresolved` 和需要扩展的文件，不得自行扩成全工程排障。

### 10.3 工具输出

工程文档应继续要求：

- 使用 `rg`、`sed` 或工具提供的过滤参数读取局部；
- 验证输出只看 failure summary 和日志 tail；
- 不使用 `cat` 输出大日志；
- 不要求 subagent 返回源码全文；
- subagent 自然语言交接只包含修改文件、根因、未解决点，不回传源码和完整日志。

## 11. 项目级自动 compact 兜底设计

### 11.1 前置兼容性试验

实施 context guard 前，先确认评分平台：

1. 从哪个目录启动 OpenCode；
2. 是否打包提交工程中的 `.opencode/plugins/`；
3. 是否允许项目插件；
4. `message.updated` 是否携带 `tokens.total`；
5. `client.session.summarize` 在 GLM-5.1 自定义 provider 上是否成功；
6. summarize 后是否能正常 auto-continue。

最小试验插件只记录“已加载”和接收到的事件，不修改会话。兼容性确认后再加入主动 summarize。

### 11.2 触发规则

建议规则：

```text
默认安全阈值：140,000 tokens
触发时机：assistant message 完成且没有 tool 正在运行
每个 session 同时最多一个 summarize
成功依据：收到 session.compacted
失败依据：summarize API 返回错误或 session.error
```

如果以后模型元数据能提供真实 context limit，可改为动态阈值：

```text
threshold = context_limit * 0.65 ~ 0.70
```

若无法获得 limit，则使用经过当前 GLM-5.1 实测的保守 fallback，不能假设 OpenCode 会自动推断。

### 11.3 伪代码

```ts
const compacting = new Set<string>()

on("message.updated", async (event) => {
  const message = event.info
  if (message.role !== "assistant") return
  if (!messageCompleted(message)) return
  if (message.tokens.total < SAFE_THRESHOLD) return
  if (compacting.has(message.sessionID)) return

  compacting.add(message.sessionID)
  try {
    await client.session.summarize({
      path: { id: message.sessionID },
      body: {
        providerID: message.providerID,
        modelID: message.modelID,
      },
    })
  } finally {
    // 实际实现应结合 session.compacted/session.error 释放并防抖
  }
})
```

伪代码只说明机制，实际实现必须以 OpenCode 1.17.20 本地 SDK 类型和兼容性试验为准。

### 11.4 失败兜底

如果主动 summarize 不可用或失败：

- 不继续向该高风险 session 分派新工作；
- 当前 subagent 尽快返回短交接；
- 主 Agent 创建新的 session 从共享工作区继续；
- 如果主 Agent 自身达到高风险阈值，应在阶段边界 compact，或由新的主会话从当前产物和验证摘要继续。

自动 compact 是减少意外停止的第二层保护，session 轮换才是对平台差异更稳健的第一层保护。

## 12. 拟修改范围

方案获批后，预计按最小范围修改：

1. `02_02/INSTRUCTION.md`
   - 明确“薄主 Agent + 多个短期 subagent”；
   - 明确不限制总数，限制单 session 工作单元；
   - 禁止全文 reader task；
   - 增加修复后换新 session 的规则。

2. `02_02/work/skills/flashdb-orchestrator.md`
   - dispatch 只提供动态上下文；
   - General fallback 必须先读取权威 subagent Markdown；
   - 主 Agent 统一验证；
   - 失败后使用新 repair session，不让旧 session 无限迭代。

3. `02_02/work/skills/rust-implementer.md`
   - 一次有界实现/修复后退出；
   - 禁止自行扩展为全工程调试；
   - 禁止运行 C-Cross、standalone runner 和 `/tmp` 探针。

4. `02_02/work/skills/repairer.md`
   - 一个 failure cluster、一次补丁、短交接；
   - 超出允许文件时返回 unresolved；
   - 不负责复跑和成功结论。

5. 项目插件（仅在兼容性试验通过后）
   - 新增 context guard；
   - 140K 左右提前 summarize；
   - 加入 session 级防重入；
   - 不修改全局 OpenCode 配置。

6. `02_02/tests/`
   - 检查合同中不再要求全文读取；
   - 检查 General fallback 必须引用权威 Skill；
   - 检查 subagent 不负责 runner/gate；
   - 检查不设置固定 subagent 总数；
   - 插件可用时增加低阈值触发的隔离测试。

当前比赛目录要求 subagent Markdown 继续放在 `work/skills/{subagent}.md`，本方案不新增 `work/agents/`。

## 13. 实施顺序

### P0：先修正执行模型

1. 修改主执行与 subagent 合同；
2. 删除“返回全文”“读完所有源码”“迭代直到全部通过”等无限任务表述；
3. 明确一次补丁后退出、主 Agent 验证、新 session 接力；
4. 增加合同回归测试。

P0 不依赖 OpenCode 插件，必须先完成。

### P1：验证并实现 context guard

1. 在与评分平台一致的启动目录做插件加载试验；
2. 使用低测试阈值验证 `session.summarize`；
3. 验证 `session.compacted`、auto-continue 和防重入；
4. 再启用 140K 左右的正式阈值。

### P2：重新运行并对比

新运行至少记录：

- primary 最大上下文；
- 每个 subagent 最大上下文；
- subagent 数量和每个任务职责；
- 是否发生 compact；
- 是否出现 context overflow；
- 是否仍有全文读取、`/tmp` 或 standalone runner；
- C-Cross、测试一致性与最终 gate 的真实结果。

不能只以“没有爆上下文”作为成功；如果减少上下文导致实现或评分准确率下降，同样不算优化成功。

## 14. 验收标准

方案实施后应满足：

1. 不设置固定 subagent 总数上限；
2. 每个 subagent task 都引用权威 `work/skills/{subagent}.md`；
3. dispatch 不再复制完整业务规则或大段实现方案；
4. 不再出现要求返回 C/Rust 源码全文的 reader task；
5. repair subagent 不运行 C-Cross、cargo、gate、standalone runner；
6. repair subagent 不访问 `/tmp/**`、`/var/tmp/**`；
7. 每个 repair session 完成一次有界补丁后退出；
8. 主 Agent 只读取 failure summary、日志 tail 和局部源码窗口；
9. 插件可用时，在安全阈值附近产生真实 `session.compacted` 事件；
10. 插件不可用时，工作流仍能通过新 session 接力继续，不因单 session 达到 202,745 而整体停止；
11. 最终 C-Cross、semantic review、consistency 和 gate 仍使用真实结果，不能通过流程简化伪造成功；
12. 对比运行的最终迁移质量和评分准确率不低于当前 q9 基线。

## 15. 对当前仍在运行任务的判断

当前运行无法通过新增项目插件热修复，因为插件只在 OpenCode 启动时加载。

若需要保住本次运行，最安全的人工策略是：

1. 不让第七个继续无限调试；
2. 尽快让它只返回当前修改和未解决点；
3. 主 Agent 在继续测试迁移和报告前执行一次手动 compact；
4. 后续失败改用新的短 session，不恢复第六个或第五个高上下文 session。

以上属于当前运行的人工止损建议，不是本方案已执行的改动。
