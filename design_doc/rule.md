## 题目名称
将FlashDB用Rust重写

## 项目要求 
1. 赛题目标 本赛题要求参赛作品
自动读取平台提供的 FlashDB C 工程，并将其核心源码与测试用例重写为 Rust。 
参赛作品应从源码出发完成迁移、构建和验证，不应只提交已经编译好的二进制产物。 

解题要求
跨文件深度关联性上下文管理：在不破坏项目各模块调用关系的前提下，实现单点渐进式重构。
编译/编译自愈双向闭环：当遇到重构后库API更新带来的各种语法不兼容时，Agent 需要能根据错误栈（Error Stack）进行精准自愈、自动打补丁。
语义等价性保证：要求重构升级后的业务逻辑100%不受破坏，且自生成覆盖全部主干路径的单元测试。

验证用例
./code/FlashDB/src，全部转成Rust代码并确保编译通过。
./code/FlashDB/tests，单元测试测试项完成重构，全部通过构建并测试执行成功。
Rust unsafe比例小于10%

## 目录结构
假设当前工作目录为workspace, 打分平台目录judge-assets，本次项目目录为02_02，包含以下几个目录，具体信息见下
./judge-assets/code/FlashDB/src
./judge-assets/code/FlashDB/tests
./02_02/INSTRUCTION.md
./02_02/work
./02_02/result
./02_02/logs

### 打分平台目录
平台提供材料 评测平台会提供 FlashDB 原始工程，参赛选手不需要提交该工程。 
平台材料路径： judge-assets/code/FlashDB
​其中重点包括： 
FlashDB/src/ 原始 C 源码，需要重写为 Rust 
FlashDB/tests/  原始 C 测试，需要迁移或等价覆盖​参赛作品应读取平台提供的 FlashDB 工程，完成源码转换、测试迁移和构建验证。 

### 作品项目目录
/INSTRUCTION.md	文件	必选	作品运行的入口，平台通过加载该Markdown执行作品运行过程，验证用例通过性
/work	目录	必选	用于存放作品可运行交付件的目录，可以存放Skill/Agent/MCP等
/work/skills/{your-skill-name}/SKILL.md	文件	可选	如提交Skill，按Skill规范存放Skill的目录和入口文件
/work/skills/{your-subagent-name}.md	文件	可选	如提交subagent，在skills目录下存放，并在INSTRUCTION.md中使用
/result	目录	必选	用于存放作品自验证的记录
/result/screenshot	目录	可选	存放作品运行成功、用例通过的截图文件
/result/output.md	文件	必选	记录作品运行成功的输出信息，如有图片，以Markdown规范引用
/logs	目录	必选	用于存放推理过程的记录和交互信息
/logs/interaction.md	文件	必选	记录选手与作品人工交互的记录，如全程无干预，留空
/logs/trace	目录	必选	用于存放推理过程日志

注意事项
1. INSTRUCTION.md 要求 INSTRUCTION.md 是自动评测系统执行参赛作品的唯一说明书，必须能指导裁判自动完成执行，不得依赖人工操作。 至少需要说明： 
4.1 环境准备 说明运行参赛作品所需的依赖安装、编译构建、服务启动、Docker 准备、Skill/Agent/MCP 安装等步骤。 
4.2 执行方式 说明如何执行参赛作品，包括启动命令、执行命令、参数说明、调用顺序。 如果需要读取平台材料，应明确使用： /app/code/judge-assets/02_02_c_to_rust/code/FlashDB
​4.3 完成判定 说明如何判断参赛作品执行完成，例如命令退出、文件生成、接口返回成功等。 
4.4 结果获取方式 必须说明修复/重写后的 Rust 项目生成在哪里，以及评测系统如何找到最终交付件。 

2. 最终交付件要求 参赛作品执行完成后，应生成 Rust 重写项目： 
flashDB_rust/ 
├── Cargo.toml 
├── src/ 
└── tests/
​要求： flashDB_rust 应为可构建的 Rust 项目； 
项目根目录应包含 Cargo.toml； 
FlashDB/src 中核心逻辑应转换为 Rust 实现； 
FlashDB/tests 中测试场景应迁移为 Rust 测试，或通过兼容方式等价覆盖； 
Rust 测试应使用 Rust 主流测试框架； 
项目应能够执行 cargo build 和 cargo test； 
unsafe 使用比例应低于 10%。 
建议同时生成执行说明报告： result/output.md 
result/issues/00-summary.md​用于说明转换过程、最终 Rust 项目位置、测试迁移情况、已知问题和验证结果。 

3. 禁止事项 以下情况可能导致自动评测失败或得分为 0：
缺少 INSTRUCTION.md； INSTRUCTION.md 无法指导自动执行； 
执行过程需要人工交互； 无法判断执行是否完成； 
无法找到 flashDB_rust 或 Cargo.toml； 
Rust 项目无法构建； 
测试用例缺失或与原始 C 测试语义不一致； 
修改平台提供的原始测试材料； 
只提交编译产物，不提供可复现源码或执行流程；
