# 配置说明

FlashDB 的使用时，可以通过 fdb_cfg.h 对其进行功能配置，该文件模板位于 `inc` 目录下，也可以去具体的 demo 工程里拷贝。下面详细介绍一下配置详情

## FDB_USING_KVDB

使能 KVDB 功能

### FDB_KV_AUTO_UPDATE

使能 KV 自动升级功能。该功能使能后， `fdb_kvdb.ver_num` 存储了当前数据库的版本，如果版本发生变化时，会自动触发升级动作，将更新新的默认 KV 集合至当前数据库中。

## FDB_USING_TSDB

使能 TSDB 功能

## FDB_USING_FILE_POSIX_MODE

使用 POSIX 的文件模式，需要系统提供 open/read/write/close 相关文件访问接口。这是 Linux 平台推荐的存储模式。

## FDB_USING_FILE_LIBC_MODE

使用 C 标准库的文件模式，需要系统提供 fopen/fread/fwrite/fclose 相关文件访问接口。

> FDB_USING_FILE_LIBC_MODE 与 FDB_USING_FILE_POSIX_MODE 模式只能二选一。文件模式下数据库的存储位置、大小及数量没有限制。

## FDB_WRITE_GRAN

Flash 写粒度，单位为 bit。目前支持

- 1: nor flash
- 8/32/64/128/256: 片上 flash

如果数据库中使用了多种 Flash 规格，取最大值作为配置项。

## FDB_PRINT(...)

打印函数宏定义配置，默认不配置时，使用 printf 作为打印日志是输出函数。用户也可以自定义新的打印函数宏定义，例如：

```C
#define FDB_PRINT(...)              my_printf(__VA_ARGS__)
```

## FDB_DEBUG_ENABLE

使能调试信息输出。关闭该配置时，系统将不会输出用于调试的日志。
