# FlashDB Linux 测试指南

## 概述

FlashDB 的测试体系包含 **单元测试** 和 **性能基准测试** 两部分，均在 Linux 平台上运行。

单元测试原本基于 RT-Thread Utest 框架编写，通过添加 RT-Thread API 兼容层（`utest.h`），移植到 Linux 平台，使用 POSIX 文件模式模拟 Flash 存储，实现本地编译和执行。

性能基准测试对 KVDB 和 TSDB 的核心操作进行定量测量，使用 `-O2` 优化级别编译，更接近实际生产环境的性能表现。为避免日志 IO 影响性能数据，基准测试故意关闭 `FDB_DEBUG_ENABLE`。

## 目录结构

```
tests/
├── fdb_cfg.h             # 单元测试配置（文件模式、写粒度等）
├── dfs_file.h            # RT-Thread DFS 文件系统头文件兼容桩
├── utest.h               # RT-Thread Utest 框架及 API 兼容层
├── fdb_kvdb_tc.c         # KVDB 测试用例源文件
├── fdb_tsdb_tc.c         # TSDB 测试用例源文件
├── kvdb_main.c           # KVDB 测试运行器（main 入口）
├── tsdb_main.c           # TSDB 测试运行器（main 入口）
├── Makefile              # 单元测试构建脚本
├── README_test.md        # 本文档
└── benchmark/
    ├── bench_main.c      # 基准测试源代码
    ├── fdb_cfg.h         # 基准测试配置（关闭调试输出）
    └── Makefile          # 基准测试构建脚本（-O2 优化）
```

## 前置条件

- Linux 系统（x86_64 / ARM64）
- GCC 或兼容 C 编译器（`cc`）
- POSIX 线程库（`libpthread`）

## 单元测试

### 构建与运行

```bash
cd tests
make clean && make
```

构建产物：

| 文件 | 说明 |
|------|------|
| `kvdb_test` | KVDB 单元测试可执行文件 |
| `tsdb_test` | TSDB 单元测试可执行文件 |

运行方式：

| 命令 | 说明 |
|------|------|
| `make test` | 执行全部测试 |
| `make kvdb_run` | 仅执行 KVDB 测试 |
| `make tsdb_run` | 仅执行 TSDB 测试 |
| `./kvdb_test` | 手动执行 KVDB 测试 |
| `./tsdb_test` | 手动执行 TSDB 测试 |

退出码：0 = 通过，1 = 失败。

### 用例一览

#### KVDB 测试（13 个单元）

| 用例 | 说明 |
|------|------|
| `test_fdb_kvdb_init` | KVDB 初始化 |
| `test_fdb_kvdb_init_check` | 初始化后 oldest_addr 校验 |
| `test_fdb_create_kv_blob` | 创建 KV blob 类型 |
| `test_fdb_change_kv_blob` | 修改 KV blob 类型 |
| `test_fdb_del_kv_blob` | 删除 KV blob 类型 |
| `test_fdb_create_kv` | 创建 KV string 类型 |
| `test_fdb_change_kv` | 修改 KV string 类型 |
| `test_fdb_del_kv` | 删除 KV string 类型 |
| `test_fdb_gc` | GC 基本场景（4 sector） |
| `test_fdb_gc2` | GC 含大 KV 场景（跨 sector KV） |
| `test_fdb_scale_up` | 动态扩容（4→8 sector） |
| `test_fdb_kvdb_set_default` | 重置为默认 KV |
| `test_fdb_kvdb_deinit` | KVDB 反初始化 |

#### TSDB 测试（11 个单元）

| 用例 | 说明 |
|------|------|
| `test_fdb_tsdb_init_ex` | TSDB 初始化 |
| `test_fdb_tsl_clean` | 清空 TSL |
| `test_fdb_tsl_append` | 追加 TSL |
| `test_fdb_tsl_iter` | 正向遍历 TSL |
| `test_fdb_tsl_iter_by_time` | 按时间范围遍历 |
| `test_fdb_tsl_query_count` | 查询 TSL 数量 |
| `test_fdb_tsl_set_status` | 设置 TSL 状态 |
| `test_fdb_tsl_clean` | 清空验证 |
| `test_fdb_tsl_iter_by_time_1` | 跨 sector 时间遍历边界测试 |
| `test_fdb_tsdb_deinit` | TSDB 反初始化 |
| `test_fdb_github_issue_249` | GitHub Issue #249 回归测试 |

### 兼容层说明

测试用例使用 RT-Thread API 编写，兼容层（`utest.h`）将它们映射到 POSIX/Linux 等价实现：

| RT-Thread API | Linux 映射 |
|---------------|-----------|
| `rt_bool_t` | `bool` |
| `rt_err_t` | `int` |
| `rt_malloc / rt_free` | `malloc / free` |
| `rt_strcmp / rt_strlen / rt_snprintf` | `strcmp / strlen / snprintf` |
| `rt_thread_mdelay` | `usleep` |
| `rt_tick_get` | `clock_gettime(CLOCK_MONOTONIC)` |
| `rt_slist_t` 及操作 | 内建单向链表实现 |
| `uassert_true` 等 | 日志 + `_utest_skip` 机制 |
| `UTEST_UNIT_RUN` | 函数调用 + 跳过标志重置 |
| `UTEST_TC_EXPORT` | 空宏（由运行器直接调用 testcase） |
| `dfs_file.h` | POSIX 头文件桩 |

关键适配点：

1. **`mkdir` 权限**：原测试用 `mkdir(path, 0)`，在 Linux 下产生无权限目录。已改为 `mkdir(path, 0777)`。
2. **断言 `return` 问题**：原 `uassert_true` 使用 `return;`，与 `bool` 返回类型的回调函数冲突。改用 `_utest_skip` 标志跳过当前单元内后续断言，每个 `UTEST_UNIT_RUN` 重置该标志。
3. **测试分离**：KVDB 和 TSDB 各有同名 `testcase()` 函数（`static`），采用 `#include` 方式将测试源文件直接包含到各自的运行器中，避免符号冲突，分别编译为独立可执行文件。

## 性能基准测试

### 构建与运行

```bash
cd tests/benchmark
make clean && make bench
```

或分步执行：

```bash
make            # 仅编译
./benchmark     # 运行
```

### 测试项目

#### KVDB 操作（7 项）

| 操作 | 说明 | 默认参数 |
|------|------|---------|
| set (string) | 批量写入字符串 KV | 1000 条 |
| get (string) | 批量读取字符串 KV | 1000 条 |
| set (blob) | 批量写入 blob KV | 1000 条 × 128 字节 |
| get (blob) | 批量读取 blob KV | 1000 条 × 128 字节 |
| update (string) | 批量更新已存在的字符串 KV | 1000 条 |
| iterate all | 遍历所有 KV | 预期 2000 条 |
| delete | 批量删除 KV | 1000 条 |

#### TSDB 操作（4 项）

| 操作 | 说明 | 默认参数 |
|------|------|---------|
| append | 批量追加时序记录 | 2000 条 × 64 字节 |
| iterate all | 遍历所有 TSL | 预期 2000 条 |
| iter by time | 按时间范围遍历 | 全范围 |
| query count | 查询时间范围内的 TSL 数量 | 全范围 |

每项操作默认执行 **3 次迭代**（`BENCH_ITER_COUNT`），输出每次迭代的结果，便于观察性能波动。

### 输出格式

```
============================================================
  FlashDB Linux Performance Baseline Benchmark
  Sector size: 4096 bytes, KVDB sectors: 128, TSDB sectors: 128
  FDB_WRITE_GRAN: 1, File mode: POSIX
============================================================

--- KVDB Benchmarks ---

  Benchmark                      | Count    | Elapsed     | Ops/s      | Us/op
  -------------------------------+----------+-------------+------------+-----------
  [Run 1/3]
  KVDB set (string)              |   1000 ops | 1425547.2 us |    701.5 ops/s | 1425.55 us/op
  ...
```

每行包含：操作名称、操作次数、总耗时(us)、每秒操作数、每次操作耗时(us)。

### 运行参数

以下常量在 `bench_main.c` 中定义，可按需修改：

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `BENCH_SEC_SIZE` | 4096 | 模拟扇区大小（字节） |
| `BENCH_KVDB_SECS` | 128 | KVDB 扇区数量（总容量 512KB） |
| `BENCH_TSDB_SECS` | 128 | TSDB 扇区数量（总容量 512KB） |
| `BENCH_KV_COUNT` | 1000 | KV 操作次数 |
| `BENCH_KV_BLOB_SIZE` | 128 | KV blob 大小（字节） |
| `BENCH_TSL_COUNT` | 2000 | TSL 追加次数 |
| `BENCH_TSL_BLOB_SIZE` | 64 | TSL blob 大小（字节） |
| `BENCH_ITER_COUNT` | 3 | 每项操作迭代次数 |

### 测试原理

1. **KVDB 测试**：先 `fdb_kv_set_default` 清空数据库，再按 set → get → set_blob → get_blob → update → iterate → delete 的顺序执行，每步独立计时。
2. **TSDB 测试**：每轮迭代先 `fdb_tsl_clean` 清空数据库并重置时间戳计数器，再按 append → iterate → iter_by_time → query_count 的顺序执行。
3. **计时**：使用 `clock_gettime(CLOCK_MONOTONIC)` 微秒级精度计时。
4. **加锁**：使用 `pthread_mutex` 递归锁，模拟多线程环境下的实际使用场景。
5. **时间戳**：TSDB 使用单调递增计数器 `++bench_cur_time` 作为 `get_time` 回调，确保每条 TSL 时间戳唯一。
6. **数据清理**：测试结束后自动删除所有数据目录（`bench_kvdb/`、`bench_tsdb/`）。

## 配置项

两个测试各有独立的 `fdb_cfg.h`，共用配置如下：

| 宏 | 单元测试 | 基准测试 | 说明 |
|----|---------|---------|------|
| `FDB_USING_KVDB` | 定义 | 定义 | 启用 KVDB |
| `FDB_USING_TSDB` | 定义 | 定义 | 启用 TSDB |
| `FDB_USING_FILE_POSIX_MODE` | 定义 | 定义 | POSIX 文件模式模拟 Flash |
| `FDB_USING_NATIVE_ASSERT` | 定义 | 定义 | 使用标准 `assert()` |
| `FDB_WRITE_GRAN` | 1 | 1 | 写粒度 1 bit（模拟 NOR Flash） |
| `FDB_DEBUG_ENABLE` | **定义** | **未定义** | 单元测试需要日志；基准测试关闭以避免日志 IO 影响性能数据 |

## 写粒度测试

修改 `fdb_cfg.h` 中的 `FDB_WRITE_GRAN` 可测试不同 Flash 写粒度场景：

| 粒度 (bit) | 适用场景 |
|------------|---------|
| 1 | NOR Flash（默认） |
| 8 | 片上 Flash（如 Cortex-M4/M7） |
| 32 | 片上 Flash（如 Cortex-M3） |
| 64 | 片上 Flash（如 Cortex-M4 低功耗系列） |
| 128 | 片上 Flash（如 Cortex-M33 高性能系列） |
| 256 | 片上 Flash（如 Cortex-M7 高性能系列） |

单元测试中的 `TEST_KV_VALUE_LEN` 等参数会根据该值动态计算，确保各粒度下 GC 等场景的正确性。

写粒度越大，状态标记占用空间越多，GC 和写操作的性能可能下降。通过对比不同粒度的基准数据，可以评估 Flash 特性对数据库性能的影响。

## 清理

```bash
# 单元测试
cd tests && make clean

# 基准测试
cd tests/benchmark && make clean
```

分别删除各自的编译产物及测试数据目录。

## 注意事项

- 基准测试使用 POSIX 文件模拟 Flash，实际 Flash 硬件上的性能会有显著差异（特别是擦除操作）
- 文件系统的缓存机制可能影响首次和后续迭代的性能差异
- 基准测试数据目录在运行结束后自动删除，不会残留到下次运行
