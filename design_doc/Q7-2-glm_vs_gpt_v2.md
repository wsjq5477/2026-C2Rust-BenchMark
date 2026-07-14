# 审核后实施范围（2026-07-14）

本轮只实施两项已经确认的优化，后文其余建议保留为对比分析，不代表当前工程计划：

1. 修正架构诱导：删除“C 输入启用 POSIX file mode 或跨 sector ⇒ Rust 必须使用真实 FileSectorStorage”的推断。现有 `c_facade_with_sidecar_state` 合同保持不变，scaffold 直接生成通用 `SidecarRegistry<T>`；只有 C-Cross 可观察义务证明需要时，才在该边界内扩展持久化或 flash 行为。
2. 将已有 `implementation_requirements` 变成真实执行批次：控制器按依赖顺序每批最多 3 项，依次执行 CORE、FACADE 和 acceptance-scenario targeted C-Cross。通过后进入下一批；失败回到同批修复，默认最多 2 次；预算耗尽记录 `failed_final` 并继续其余批次，最终仍由全量 C-Cross 如实收口。

不新增 `implementation_profile`、架构选择阶段或静态“过度工程扫描器”。

---                                                                                                                                                                                                                                                                 
  GLM vs GPT 逐阶段对比分析                                                                                                                                                                                                                                           
                                                                                                                                                                                                                                                                      
  总览                                                                                                                                                                                                                                                                
                                                                                                                                                                                                                                                                      
  ┌──────────────────┬─────────────────────────────────┬───────────────────────────────┐                                                                                                                                                                              
  │       指标       │           GLM (02_02)           │        GPT (02_02_gpt)        │                                                                                                                                                                              
  ├──────────────────┼─────────────────────────────────┼───────────────────────────────┤                                                                                                                                                                              
  │ C-cross 功能测试 │ 8/24 pass, KVDB runner segfault │ 24/24 pass                    │                                                                                                                                                                            
  ├──────────────────┼─────────────────────────────────┼───────────────────────────────┤                                                                                                                                                                              
  │ Rust 原生测试    │ 10/10 pass (仅5个与C对应)       │ 26/26 pass (24个与C对应)      │                                                                                                                                                                              
  ├──────────────────┼─────────────────────────────────┼───────────────────────────────┤                                                                                                                                                                              
  │ 用例一致性       │ 5/24 (20.8%)                    │ 24/24 (100%)                  │                                                                                                                                                                              
  ├──────────────────┼─────────────────────────────────┼───────────────────────────────┤                                                                                                                                                                              
  │ Unsafe ratio     │ 3.06%                           │ 3.08%                         │                                                                                                                                                                            
  ├──────────────────┼─────────────────────────────────┼───────────────────────────────┤                                                                                                                                                                              
  │ 修复轮次         │ 2 轮 (核心bug)                  │ 0 轮 (c-cross 13次尝试后达标) │                                                                                                                                                                            
  ├──────────────────┼─────────────────────────────────┼───────────────────────────────┤                                                                                                                                                                              
  │ 架构             │ 真实文件存储 (flash I/O)        │ Sidecar HashMap (进程内状态)  │                                                                                                                                                                            
  ├──────────────────┼─────────────────────────────────┼───────────────────────────────┤                                                                                                                                                                              
  │ 代码量           │ ~107KB / 3071行 / 12文件        │ ~85KB / 2109行 / 14文件       │                                                                                                                                                                            
  ├──────────────────┼─────────────────────────────────┼───────────────────────────────┤                                                                                                                                                                              
  │ pipeline 状态    │ 卡在 MIGRATE_TESTS              │ DONE                          │                                                                                                                                                                            
  └──────────────────┴─────────────────────────────────┴───────────────────────────────┘                                                                                                                                                                              
                                                                                                                                                                                                                                                                    
  ---                                                                                                                                                                                                                                                                 
  Stage 1-2: INIT_WORKSPACE + READ_C_PROJECT                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                      
  两者差异不大 — 都是生成 workflow_state.json、agent-registry.json、扫描 C 项目文件。
                                                                                                                                                                                                                                                                      
  GPT 优势：input_manifest.json 包含每个文件的 SHA-256 哈希，形成密码学可审计的输入基线。GLM 也有 input-source-baseline，但下游阶段对基线的引用没有 GPT 严格。                                                                                                        
                                                                                                                                                                                                                                                                      
  问题等级：GLM 无显著问题                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                    
  ---                                                                                                                                                                                                                                                                 
  Stage 3: BUILD_C_MODEL                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                      
  两者都提取了 31 个函数签名、12 个 ABI struct、24 个测试场景。                                                                                                                                                                                                     
                                                                                                                                                                                                                                                                      
  GPT 优势：                                                                                                                                                                                                                                                          
  - c_api_model.json.abi_layouts 包含编译器确认的字段偏移量（sizeof, alignof, offset），这直接防止了 #[repr(C)] 填充错误                                                                                                                                              
  - 宏定义（FDB_USING_KVDB 等）显式记录                                                                                                                                                                                                                               
                                                                                                                                                                                                                                                                    
  GLM 问题：                                                                                                                                                                                                                                                          
  - 虽然也提取了 ABI 布局，但在 Stage 6.5 暴露出 #[repr(C)] 偏移量错误（naive size sum 未考虑对齐填充），说明模型提取的字段偏移信息未被有效用于校验                                                                                                                   
                                                                                                                                                                                                                                                                      
  问题等级：GLM 中等 — 模型提取了信息但未有效利用                                                                                                                                                                                                                     
                                                                                                                                                                                                                                                                      
  ---                                                                                                                                                                                                                                                               
  Stage 4: DESIGN_RUST_API                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                      
  两者都生成了 rust_api_design.json 作为设计合同。
                                                                                                                                                                                                                                                                      
  GPT 优势：                                                                                                                                                                                                                                                          
  - 每个参数标注 ownership（borrowed, borrowed_mut, value）和 nullable                                                                                                                                                                                                
  - 回调函数映射为 Option<unsafe extern "C" fn(...)> 而非退化到 void*                                                                                                                                                                                                 
                                                                                                                                                                                                                                                                    
  GLM 问题：                                                                                                                                                                                                                                                          
  - 设计阶段同样完成了 31 个函数和 12 个 struct 的映射                                                                                                                                                                                                                
  - 但后续实现阶段暴露出 control code 常量猜测错误（0x09 vs 2），说明设计阶段未充分记录 FDB_KVDB_CTRL_SET_FILE_MODE 等常量值                                                                                                                                          
                                                                                                                                                                                                                                                                      
  问题等级：GLM 中等 — 设计未覆盖 C 宏常量值                                                                                                                                                                                                                          
                                                                                                                                                                                                                                                                      
  ---                                                                                                                                                                                                                                                                 
  Stage 5: GENERATE_RUST_SCAFFOLD                                                                                                                                                                                                                                     
                                                                                                                                                                                                                                                                      
  两者都生成了 31 个 FFI 函数 stub + 12 个 struct 定义 + layout_probe.rs。
                                                                                                                                                                                                                                                                      
  GPT 优势：                                                                                                                                                                                                                                                          
  - staticlib + rlib 双输出                                                                                                                                                                                                                                           
  - Scaffold 严格从 rust_api_design.json 派生，不读 C 源码                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                    
  GLM 关键缺陷 — Gate 盲区：                                                                                                                                                                                                                                          
  - Gate 只检查 cargo fmt + cargo build，空 stub 也通过                                                                                                                                                                                                               
  - 这导致 Stage 6 的 REWRITE 阶段没有可靠的 "是否有真实逻辑" 检查                                                                                                                                                                                                    
  - 这个问题在 memory 中已记录为 feedback_rewrite_gate_blind_spot.md                                                                                                                                                                                                  
                                                                                                                                                                                                                                                                      
  问题等级：GLM 严重 — gate 无法区分 stub 和实现                                                                                                                                                                                                                      
                                                                                                                                                                                                                                                                      
  ---                                                                                                                                                                                                                                                                 
  Stage 6: REWRITE_CORE_MODULES                                                                                                                                                                                                                                       
                                                                                                                                                                                                                                                                      
  这是最大的分水岭。
                                                                                                                                                                                                                                                                      
  GPT 方案 — Sidecar 架构：                                                                                                                                                                                                                                           
  - storage.rs：60 行，Mutex<Registry> 用 HashMap<pointer_address, State> 维护 Rust 侧状态                                                                                                                                                                            
  - ffi/c_abi.rs：739 行，包含全部业务逻辑                                                                                                                                                                                                                            
  - kvdb.rs + tsdb.rs：各 5 行，空 stub                                                                                                                                                                                                                             
  - C 调用者保持自己的 struct 指针，Rust 在 HashMap 中查找对应的内部状态                                                                                                                                                                                              
  - 不做真实 flash I/O — 所有"地址"都是模拟值，只要通过 C 测试断言即可                                                                                                                                                                                                
                                                                                                                                                                                                                                                                      
  GLM 方案 — 真实文件存储架构：                                                                                                                                                                                                                                       
  - storage.rs：254 行，实现了真实的 flash_read/flash_write/flash_erase（基于文件系统）                                                                                                                                                                               
  - kvdb.rs：625 行，完整 KVDB 实现                                                                                                                                                                                                                                   
  - tsdb.rs：732 行，完整 TSDB 实现                                                                                                                                                                                                                                   
  - common.rs：463 行，CRC32、状态表位操作、on-flash header 结构                                                                                                                                                                                                      
  - ffi/c_abi.rs：270 行，薄 wrapper 委托到 kvdb/tsdb 模块                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                      
  GLM 的根本问题：                                                                                                                                                                                                                                                    
                                                                                                                                                                                                                                                                      
  1. 过度工程：试图从零重写 FlashDB 的完整 flash 存储引擎，包括 sector 管理、GC、位操作等。这远远超出了 "通过 C 测试" 的需求                                                                                                                                          
  2. 6 个关键 bug 全在 unsafe 代码中：                                                                                                                                                                                                                                
    - #[repr(C)] 偏移量错误（未考虑对齐填充）                                                                                                                                                                                                                         
    - FFI control code 常量错误（0x09 vs 2）                                                                                                                                                                                                                          
    - get_db_dir_name 指针读取 bug                                                                                                                                                                                                                                    
    - CString 生命周期 bug                                                                                                                                                                                                                                            
    - get_status 位扫描 off-by-one                                                                                                                                                                                                                                    
    - CRC 计算错误                                                                                                                                                                                                                                                    
  3. 这些 bug 的根因是：试图在 Rust 中复现 C 的 flash 存储逻辑，而非像 GPT 那样用 sidecar 状态机满足 C 测试断言                                                                                                                                                       
                                                                                                                                                                                                                                                                      
  问题等级：GLM 致命 — 架构选择导致实现复杂度爆炸 + 大量底层 bug                                                                                                                                                                                                      
                                                                                                                                                                                                                                                                      
  ---                                                                                                                                                                                                                                                                 
  Stage 6.5: VERIFY_RUST_WITH_C_TESTS                                                                                                                                                                                                                               
                                                                                                                                                                                                                                                                      
  GPT：13 次 c-cross 修复尝试，从 0/24 逐步收敛到 24/24
  - 关键修复：attempt 3 (layout_struct_fix) 一次从 0→20                                                                                                                                                                                                               
  - 纪律性回退：attempt 6 发现回归后立即 revert                                                                                                                                                                                                                       
  - 最终修复：attempt 12 (persist_gc_oldest_cursor) 达到 24/24                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                      
  GLM：8 pass, 9 fail, 7 not_run                                                                                                                                                                                                                                      
  - KVDB runner segfault (exit -11)                                                                                                                                                                                                                                   
  - blob.saved.len 读到 896832000 垃圾值（内存损坏）                                                                                                                                                                                                                  
  - TSDB append/query 基本功能全部失败                                                                                                                                                                                                                                
  - 然后 pipeline 就没有继续修复 c-cross 失败，直接进入了 MIGRATE_TESTS                                                                                                                                                                                               
                                                                                                                                                                                                                                                                      
  问题等级：GLM 致命 — c-cross 9/24 失败且 KVDB segfault，但未修复                                                                                                                                                                                                    
                                                                                                                                                                                                                                                                      
  ---                                                                                                                                                                                                                                                                 
  Stage 7: MIGRATE_TESTS                                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                                      
  GPT：
  - 3 个测试文件：kvdb_tests.rs (13 tests)、tsdb_tests.rs (11 tests)、equivalence_tests.rs (2 tests)                                                                                                                                                                  
  - 每个测试1:1 对应 C 测试场景                                                                                                                                                                                                                                       
  - 测试有 semantic_obligations、assertion_evidence、coverage_grading (L1/L2/L3)                                                                                                                                                                                      
  - 26/26 pass                                                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                      
  GLM：                                                                                                                                                                                                                                                               
  - 1 个测试文件：integration_tests.rs (10 tests)                                                                                                                                                                                                                     
  - 14 个 C 测试场景无对应 Rust 测试：del_kv_blob, change_kv, gc, gc2, scale_up, tsl_append_by_time, tsl_iter_reverse, tsl_iter_by_time, tsl_query_count, tsl_set_status, tsdb_control                                                                                
  - 多个场景被合并（create_kv+set_kv+get_kv → test_kv_set_get）                                                                                                                                                                                                       
  - test-placeholder-check.json 报告 48 个问题                                                                                                                                                                                                                        
  - test-consistency.json 报告 396 个问题                                                                                                                                                                                                                             
  - rust_test_mapping.json 引用的 kvdb_tests.rs 和 tsdb_tests.rs 从未创建                                                                                                                                                                                             
                                                                                                                                                                                                                                                                      
  问题等级：GLM 致命 — 测试覆盖仅 5/24，14 个场景完全缺失                                                                                                                                                                                                             
                                                                                                                                                                                                                                                                      
  ---                                                                                                                                                                                                                                                                 
  Stage 8: BUILD_TEST_REPAIR                                                                                                                                                                                                                                          
                                                                                                                                                                                                                                                                      
  GPT：0 轮修复 — c-cross 已在 Stage 6.5 全部修复，cargo test 直接通过
                                                                                                                                                                                                                                                                      
  GLM：修复了 6 个核心 bug：                                                                                                                                                                                                                                          
  1. get_db_dir_name 指针 bug                                                                                                                                                                                                                                         
  2. CString 生命周期                                                                                                                                                                                                                                                 
  3. FFI control code 常量                                                                                                                                                                                                                                          
  4. #[repr(C)] padding offset（系统性的）                                                                                                                                                                                                                            
  5. get_status 位扫描 off-by-one                                                                                                                                                                                                                                     
  6. CRC 计算                                                                                                                                                                                                                                                         
                                                                                                                                                                                                                                                                      
  修复后 10/10 integration tests pass，但只验证了 10 个测试中的基本功能，未修复 c-cross 的 16 个失败场景。                                                                                                                                                            
                                                                                                                                                                                                                                                                      
  问题等级：GLM 中等 — 修复了眼前的 10 个测试，但未解决 c-cross 失败                                                                                                                                                                                                  
                                                                                                                                                                                                                                                                      
  ---                                                                                                                                                                                                                                                                 
  Stage 9: REPORT_AND_VERIFY                                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                      
  GPT：DONE，24/24 c-cross, 26/26 rust tests, 3.08% unsafe
                                                                                                                                                                                                                                                                      
  GLM：卡在 MIGRATE_TESTS（workflow_state 显示 current_stage: MIGRATE_TESTS），从未到达 REPORT_AND_VERIFY                                                                                                                                                             
                                                                                                                                                                                                                                                                      
  问题等级：GLM 致命 — pipeline 未完成                                                                                                                                                                                                                                
                                                                                                                                                                                                                                                                    
  ---                                                                                                                                                                                                                                                                 
  根因总结                                                                                                                                                                                                                                                          
                                                                                                                                                                                                                                                                      
  ┌──────────────────┬───────────────────────────┬─────────────────────────────┐
  │       根因       │         GLM 表现          │          GPT 应对           │                                                                                                                                                                                      
  ├──────────────────┼───────────────────────────┼─────────────────────────────┤                                                                                                                                                                                      
  │ 架构选择         │ 真实文件存储重写（107KB） │ Sidecar 状态机（85KB）      │                                                                                                                                                                                      
  ├──────────────────┼───────────────────────────┼─────────────────────────────┤                                                                                                                                                                                      
  │ 实现策略         │ 从零复现 C flash 存储逻辑 │ 用 HashMap 满足 C 测试断言  │                                                                                                                                                                                      
  ├──────────────────┼───────────────────────────┼─────────────────────────────┤                                                                                                                                                                                      
  │ c-cross 修复循环 │ 9/24 失败后未继续         │ 13 次尝试逐步收敛到 24/24   │                                                                                                                                                                                      
  ├──────────────────┼───────────────────────────┼─────────────────────────────┤                                                                                                                                                                                      
  │ 测试迁移         │ 仅 10 个合并测试          │ 26 个 1:1 对应测试          │                                                                                                                                                                                    
  ├──────────────────┼───────────────────────────┼─────────────────────────────┤                                                                                                                                                                                      
  │ gate 盲区        │ 空 stub 通过 gate         │ 同样有盲区，但 c-cross 弥补 │                                                                                                                                                                                    
  ├──────────────────┼───────────────────────────┼─────────────────────────────┤                                                                                                                                                                                      
  │ pipeline 完成度  │ 卡在 MIGRATE_TESTS        │ DONE                        │                                                                                                                                                                                    
  ├──────────────────┼───────────────────────────┼─────────────────────────────┤                                                                                                                                                                                      
  │ #[repr(C)] 偏移  │ 系统性错误，Stage 8 修复  │ c-cross attempt 3 一次修复  │                                                                                                                                                                                    
  └──────────────────┴───────────────────────────┴─────────────────────────────┘                                                                                                                                                                                      
                                                                                                                                                                                                                                                                    
  核心教训：GPT 的 sidecar 架构（用 HashMap<ptr, State> 在内存中模拟 FlashDB 行为，无需真实 flash I/O）是正确选择。它的核心洞察是：评分标准是 C 测试通过，不是 FlashDB 正确运行。GLM 选择了"正确重写 FlashDB"这条路，导致实现复杂度远超所需，bug 数量爆炸，且 c-cross 
  修复循环不够彻底。        


  这份新对比说明，当前转换工程还缺少一个非常关键的能力：

> **在开始写 Rust 代码之前，先为模型确定“实现到什么程度、采用什么架构、哪些语义必须实现、哪些复杂度不允许引入”。**

GLM 并不是没有实现能力。它实际上写出了 3000 多行完整存储引擎，但选择了一条远超比赛需求的路线，最终被 ABI、位编码、CRC、文件存储和生命周期问题拖垮。GPT 的优势则是选择了更小的行为兼容模型，再通过 C-Cross 逐步补齐测试需要的语义。

因此，接下来优化不能只集中在 stub gate 和 repair，还必须增加 **架构决策约束和复杂度控制**。

---

# 一、重新定义当前核心问题

新的问题链条可以概括为：

```text
DESIGN 阶段没有确定实现深度
    ↓
模型自行选择架构
    ↓
GLM 选择完整 FlashDB 文件存储重写
    ↓
实现范围扩大到 sector / GC / CRC / bit table / persistence
    ↓
unsafe 和底层语义错误快速增加
    ↓
C-Cross 出现 SIGSEGV 和大量失败
    ↓
repair 没有持续执行
    ↓
带着失败进入 MIGRATE_TESTS
    ↓
测试迁移又不完整
    ↓
流水线无法结束
```

所以真正的问题不是：

> GLM 不会写 Rust。

而是：

> 转换工程允许弱模型自行决定一个过于复杂、无法在预算内完成和验证的架构。

---

# 二、不要简单规定“所有情况必须使用 Sidecar”

GPT 的 Sidecar 架构在当前 24 个 C 测试下取得了最佳结果，但不能直接得出：

> 以后所有 C→Rust 都使用 `HashMap<ptr, State>`。

因为 Sidecar 方案也存在局限：

* 可能没有真实持久化；
* 可能只在单进程测试生命周期中保持状态；
* C struct 和 Rust state 是双份状态；
* pointer address 复用需要生命周期管理；
* 多线程和 callback 重入可能产生问题；
* 对其他项目可能不满足真实外部存储语义；
* 主观评分中的泛用性和实现质量可能受影响。

正确做法不是硬编码 Sidecar，而是引入：

> **最小充分实现架构选择器。**

对于当前比赛，默认选择“行为兼容优先”，但只有测试、接口和评分明确要求的语义才进入首轮实现。

---

# 三、在 DESIGN_RUST_API 后增加架构决策阶段

建议增加一个明确阶段：

```text
SELECT_IMPLEMENTATION_ARCHITECTURE
```

流程变为：

```text
BUILD_C_MODEL
    ↓
DESIGN_RUST_API
    ↓
SELECT_IMPLEMENTATION_ARCHITECTURE
    ↓
GENERATE_RUST_SCAFFOLD
    ↓
REWRITE_CORE_MODULES
```

该阶段输出：

```text
logs/trace/implementation_architecture.json
```

建议结构：

```json
{
  "implementation_profile": "behavioral_compatibility",
  "selected_strategy": "repr_c_facade_with_sidecar_state",
  "selection_reason": [
    "The evaluation primarily observes C ABI behavior",
    "The scorer does not independently inspect the physical Flash layout",
    "A complete FlashDB storage-engine rewrite exceeds the execution budget"
  ],
  "required_semantics": [
    "kv set/get/delete",
    "blob round-trip",
    "iterator behavior",
    "control effects",
    "deinit/reinit observable state",
    "gc address observables",
    "tsl status and time filtering"
  ],
  "deferred_semantics": [
    "production-grade flash wear behavior",
    "crash-safe on-disk recovery",
    "full bit-level compatibility outside observed cases"
  ],
  "state_ownership": {
    "c_struct": "C-visible ABI and observable fields",
    "rust_sidecar": "behavioral state required by migrated implementation"
  },
  "complexity_budget": {
    "max_primary_modules": 6,
    "max_initial_ffi_batch_size": 4,
    "require_real_file_backend": false,
    "allow_unrequested_storage_engine_rewrite": false
  }
}
```

---

# 四、增加三种实现 Profile

不能让模型自由判断“完整重写还是模拟”，应由工具根据任务目标选择。

## Profile A：Behavioral Compatibility

适用于当前比赛首轮实现。

目标：

* 原 C 测试通过；
* Rust 原生测试语义对应；
* C ABI 正确；
* 所有外部可观察行为正确。

推荐架构：

```text
精确 #[repr(C)] ABI Facade
        +
Rust Sidecar State Machine
        +
必要的 C-visible 字段同步
```

不要求：

* 完整复制 FlashDB 内部实现；
* 完整真实 flash 文件格式；
* 未被接口或测试观察到的内部算法。

## Profile B：Semantic Fidelity

适用于比赛主观评分增强或后续优化。

在 Behavioral Compatibility 基础上增加：

* sector geometry；
* GC 状态；
* reload；
* status table；
* 地址行为；
* 更接近原项目的数据模型。

但仍不要求逐行翻译 C 实现。

## Profile C：Production Fidelity

适用于真正产品迁移，而不是比赛快速转换。

要求：

* 真实持久化；
* crash consistency；
* 完整 Flash 语义；
* 性能和并发；
* 完整错误模型。

当前比赛不得默认选择这个 Profile。

---

# 五、给 GLM 明确规定首选架构

对于当前 `02_02`，建议设计合同明确写入：

```json
{
  "selected_strategy": "repr_c_facade_with_sidecar_state",
  "alternative_strategy_requires_approval": true
}
```

具体结构：

```text
flashDB_rust/src/
├── ffi/
│   ├── c_types_generated.rs
│   ├── facade_generated.rs
│   └── facade_impl.rs
├── state/
│   ├── registry.rs
│   ├── kv_state.rs
│   └── ts_state.rs
├── common.rs
├── error.rs
└── lib.rs
```

其中：

### `c_types_generated.rs`

工具生成 ABI 结构，模型禁止修改。

### `facade_generated.rs`

工具生成所有导出函数签名，并转发到实现函数。

### `facade_impl.rs`

GLM 负责实现 C ABI 到状态机的转换。

### `kv_state.rs` / `ts_state.rs`

只实现 C 测试和 API obligation 要求的状态模型。

这能阻止 GLM自行创建：

* 完整 sector 文件系统；
* on-flash header；
* CRC 协议；
* 全量 FlashDB 内部状态；
* 大量无必要 unsafe。

---

# 六、增加“过度工程检查”

现有 gate 只检查是否为空实现，还需要检查是否明显超出设计范围。

新增：

```text
architecture_compliance_check.py
```

检查：

* 是否选择了设计合同之外的存储架构；
* 是否创建了未批准的真实文件存储引擎；
* 是否新增大量未被 requirement 引用的模块；
* 是否实现了大量未被 C API 或测试需要的格式协议；
* 是否跳过指定 Sidecar 架构；
* 是否违反状态所有权和生命周期约定。

输出：

```json
{
  "status": "fail",
  "issues": [
    {
      "code": "unapproved_storage_engine_rewrite",
      "message": "Implementation introduced on-flash headers, CRC and sector allocator although the selected profile is behavioral_compatibility.",
      "affected_files": [
        "src/common.rs",
        "src/storage.rs"
      ]
    }
  ]
}
```

这不是简单限制代码行数，而是检查：

> 每一块复杂实现是否有 requirement 支撑。

---

# 七、增加“语义义务到实现批次”的强制映射

当前模型容易一口气实现整个系统。应该将义务转换成固定批次。

例如：

```json
{
  "batches": [
    {
      "id": "kv-init-control",
      "symbols": [
        "fdb_kvdb_init",
        "fdb_kvdb_control",
        "fdb_kvdb_deinit"
      ],
      "required_obligations": [
        "initialize_state",
        "sync_control_fields",
        "clear_registry_on_deinit"
      ],
      "validation_cases": [
        "kvdb_init",
        "kvdb_init_check",
        "deinit"
      ]
    },
    {
      "id": "kv-basic",
      "symbols": [
        "fdb_kv_set",
        "fdb_kv_get",
        "fdb_kv_del"
      ],
      "required_obligations": [
        "set_get_round_trip",
        "stable_return_handle",
        "deletion_observable"
      ],
      "validation_cases": [
        "create_kv",
        "change_kv",
        "del_kv"
      ]
    }
  ]
}
```

每批完成后必须：

```text
静态非 stub 检查
→ cargo check
→ 对应用例增量 C-Cross
→ 保存 checkpoint
```

禁止所有批次完成后才第一次运行 C-Cross。

---

# 八、C-Cross 必须成为阶段推进条件

GLM 最大流程错误是：

```text
C-Cross 8/24 + SIGSEGV
→ 没有继续修
→ 进入 MIGRATE_TESTS
```

新的路由规则：

```text
VERIFY_RUST_WITH_C_TESTS
    ↓
24/24
    → MIGRATE_TESTS

未达到 24/24 且 repair budget 未耗尽
    → BUILD_CROSS_REPAIR
    → REPAIR
    → VERIFY

repair budget 已耗尽
    → 标记 implementation_status=degraded
    → 可以继续后续阶段
    → 但不得标记 VERIFY=pass
```

特别是出现以下情况时必须优先修复：

1. SIGSEGV/SIGABRT；
2. not_run；
3. NULL/垃圾指针；
4. assertion failure；
5. 数值或状态不一致。

优先级：

```text
crash > not_run > fail > quality warning
```

因为修复一个 crash 可能一次释放后续 7 个 not_run 用例。

---

# 九、不要把 BUILD_TEST_REPAIR 用来修核心实现

当前 GLM 在 Rust 测试阶段修了：

* ABI padding；
* CString 生命周期；
* control code；
* CRC；
* status 位扫描。

这些都属于：

```text
VERIFY_RUST_WITH_C_TESTS / CORE_REPAIR
```

不属于 Rust 测试修复。

应拆成两个完全不同的修复阶段：

```text
CORE_REPAIR
    修 src/，目标是 C-Cross

TEST_REPAIR
    修 tests/，目标是 Rust 测试语义一致性
```

权限规则：

### CORE_REPAIR

允许：

```text
flashDB_rust/src/**
```

禁止：

```text
flashDB_rust/tests/**
```

### TEST_REPAIR

允许：

```text
flashDB_rust/tests/**
```

原则上禁止修改 `src/`。如果发现核心实现问题，应回派到 CORE_REPAIR。

---

# 十、MIGRATE_TESTS 必须强制 24 个场景一一映射

GLM 合并测试是另一个明显弱模型行为：

```text
create_kv + set_kv + get_kv
→ test_kv_set_get
```

这会让某些 C 场景的独立语义消失。

新增 gate：

```text
C scorer case count = Rust mapped case count
```

对于当前工程：

```text
24 C 场景
→ 至少 24 个独立 Rust 场景映射
```

可以额外有公共 helper，但不能合并映射身份。

`rust_test_mapping.json` 中每个场景必须包含：

```json
{
  "c_scenario_id": "test_fdb_gc",
  "rust_test_file": "tests/kvdb_tests.rs",
  "rust_test_name": "test_fdb_gc",
  "coverage": "semantic",
  "called_rust_apis": [
    "KvDb::set",
    "KvDb::gc"
  ],
  "assertion_evidence": [
    "latest live value remains readable",
    "oldest address changes after compaction"
  ]
}
```

Gate 必须验证：

* 文件真实存在；
* 函数真实存在；
* 场景映射不重复；
* 24 个 C 场景无缺失；
* 测试不是恒真；
* assertion evidence 被测试实际消费。

---

# 十一、将 GPT Best Trace 提炼成“架构与修复模板”

GPT Best Trace 最有价值的并不是 739 行 `c_abi.rs`，而是三个稳定策略。

## 1. 最小充分架构

```text
不要完整复制原项目内部实现
只实现评分可观察语义
```

## 2. 增量修复

```text
一次只处理一个失败簇
修复后立即重跑相关 suite
```

## 3. 回退纪律

```text
通过率退化
→ 恢复最佳 checkpoint
→ 不在退化版本上继续叠加修改
```

这些应进入 Teacher Evidence：

```json
{
  "category": "architecture_selection",
  "rule": "Prefer the smallest implementation architecture that satisfies all observed ABI and semantic obligations.",
  "positive_evidence": "GPT sidecar implementation reached 24/24 after iterative repair.",
  "negative_evidence": "GLM full storage-engine rewrite introduced six independent low-level bugs and did not complete the pipeline."
}
```

不要把 GPT 的具体 HashMap 代码直接放进 Skill。

---

# 十二、SkillOpt 的评分需要加入“复杂度效率”

原有 SkillOpt 设计的评分需要增加：

```text
architecture_efficiency_score
```

新的综合评分建议：

```text
soft_score =
    0.40 × c_cross_score
  + 0.15 × rust_test_consistency
  + 0.10 × pipeline_completion
  + 0.10 × repair_effectiveness
  + 0.10 × artifact_integrity
  + 0.10 × architecture_efficiency
  + 0.05 × implementation_quality
```

`architecture_efficiency` 不能简单使用代码行数，应综合：

* 已实现 obligation 数；
* 新增模块数；
* 执行时间；
* repair 次数；
* 未被 requirement 引用的代码比例；
* 是否违反 selected architecture；
* 是否引入不必要的外部状态和持久化层。

例如：

```text
实现相同 24 个义务：

方案 A：
2100 行、24/24、完成流水线

方案 B：
3071 行、8/24、未完成流水线

方案 A 得分更高
```

---

# 十三、需要新增的 SkillOpt 训练样本

基于这次对比，至少新增以下训练任务。

## 任务 1：架构选择

给定：

* 24 个 C 测试义务；
* 31 个 C API；
* 时间预算；
* 当前比赛目标。

要求 GLM：

* 在 Sidecar、完整文件存储、直接结构体镜像中选择；
* 输出选择理由；
* 不得开始写代码。

验收：

* 选择最小充分架构；
* 不选择完整存储引擎重写。

## 任务 2：复杂度纠偏

提供一个已经开始实现真实文件存储的工作区。

要求：

* 识别超出设计合同的实现；
* 保留可复用代码；
* 收敛到行为兼容状态机。

## 任务 3：C-Cross repair

初始状态：

```text
8 pass / 9 fail / 7 not_run / SIGSEGV
```

要求：

* 优先处理崩溃；
* 不进入测试迁移；
* 保存 checkpoint；
* 持续修复到预算结束。

## 任务 4：测试一一映射

提供 10 个合并测试和 24 个 C 场景。

要求：

* 补齐 24 个独立映射；
* 允许复用 helper；
* 禁止只增加空测试名称。

---

# 十四、需要直接修改的工程组件

## `design_rust_api.py`

新增：

```text
implementation_profile
selected_strategy
state_ownership
required_semantics
deferred_semantics
complexity_budget
implementation_batches
```

## `generate_rust_scaffold.py`

根据 selected strategy 生成：

* Sidecar state 模块；
* generated facade；
* impl 函数入口；
* batch manifest。

## `gate.py`

新增检查：

* architecture contract；
* non-stub；
* batch completion；
* C-Cross 状态路由；
* 24/24 test mapping；
* mapping 引用文件存在；
* core repair 和 test repair 权限分离。

## `workflowctl.py`

新增：

```text
VERIFY fail → CORE_REPAIR
CORE_REPAIR → VERIFY
VERIFY pass → MIGRATE_TESTS
TEST consistency fail → TEST_REPAIR
```

## `rust-implementer.md`

明确：

* 不得自行改变 selected architecture；
* 不得实现未被 requirement 要求的完整存储引擎；
* 按 batch 实现；
* crash 优先；
* 每次修复后增量验证；
* 退化立即回退；
* C-Cross 未完成前不得进入测试迁移。

## `test-migrator.md`

明确：

* 24 个 scorer case 一一对应；
* helper 可以复用；
* case identity 不得合并；
* mapping 中引用的测试文件必须真实创建。

---

# 十五、最终优化后的流程

```text
BUILD_C_MODEL
    ↓
DESIGN_RUST_API
    ↓
SELECT_IMPLEMENTATION_ARCHITECTURE
    选择 behavioral compatibility
    选择 repr(C) facade + sidecar state
    ↓
GENERATE_RUST_SCAFFOLD
    生成 ABI、facade、state scaffold 和 batches
    ↓
IMPLEMENT BATCH 1
    ↓
局部 C-Cross
    ↓
IMPLEMENT BATCH 2
    ↓
局部 C-Cross
    ↓
...
    ↓
FULL C-CROSS
    ↓
CORE_REPAIR LOOP
    crash → not_run → fail
    保存 best checkpoint
    ↓
24/24 或达到预算
    ↓
MIGRATE_TESTS
    24 场景一一对应
    ↓
TEST CONSISTENCY
    ↓
TEST_REPAIR
    ↓
REPORT_AND_VERIFY
```

---

# 最终判断

这份新对比带来的最重要结论是：

> **需要把“架构选择”从模型自由发挥，提升为流水线中的确定性设计合同。**

对于当前比赛，推荐默认策略是：

```text
精确 ABI
+ 最小行为兼容状态机
+ C-Cross 驱动增量补齐
+ Rust 测试一一迁移
```

而不是：

```text
从零重写完整 FlashDB 文件存储引擎
```

但在正式文档中不要写：

> Sidecar 是唯一正确架构。

应该写：

> **在当前评分目标、测试可观察语义和执行预算下，Sidecar 行为状态机是首选的最小充分架构；只有存在明确的持久化或物理 Flash 语义义务时，才允许升级为真实存储后端。**

这样既能显著降低 GLM 出错概率，也不会把转换工程过拟合成只能应对 FlashDB 24 个测试的特殊工具。
