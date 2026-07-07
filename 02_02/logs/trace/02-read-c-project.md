# 阶段02：读取C项目

## 执行内容

1. 按优先级搜索 FlashDB C 源码路径，确认路径为：/home/nv_test/777/flashdb2rust/judge-assets/code/FlashDB
2. 运行 scan_c_project.py 扫描项目，生成 input_manifest.json。
3. 仅读取目录结构和文件清单，不修改平台输入。

## 扫描结果

- 核心源文件：5个（fdb.c, fdb_file.c, fdb_kvdb.c, fdb_tsdb.c, fdb_utils.c）
- 头文件：7个
- 测试源文件：6个（fdb_kvdb_tc.c, fdb_tsdb_tc.c, bench_main.c, kvdb_main.c, tsdb_main.c, main.c）
- 构建文件：3个（Makefile）

## 状态

- input_manifest.json 已生成，准备进入 BUILD_C_MODEL。
