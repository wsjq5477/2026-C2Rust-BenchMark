# Configuration

When using FlashDB, you can configure its functions through `fdb_cfg.h`. The file template is located in the `inc` directory, or you can copy it in the specific demo project. Let's introduce the configuration details in detail below

## FDB_USING_KVDB

Enable KVDB feature

### FDB_KV_AUTO_UPDATE

Enable KV automatic upgrade function. After this function is enabled, `fdb_kvdb.ver_num` stores the version of the current database. If the version changes, it will automatically trigger an upgrade action and update the new default KV collection to the current database.

## FDB_USING_TSDB

Enable TSDB feature

## FDB_USING_FILE_POSIX_MODE

Using POSIX file mode, you need to provide an open/read/write/close related file access interface. This is the recommended mode for Linux platforms.

## FDB_USING_FILE_LIBC_MODE

Using the file mode of the C standard library, you need to provide a fopen/fread/fwrite/fclose related file access interface.

> FDB_USING_FILE_LIBC_MODE and FDB_USING_FILE_POSIX_MODE can ONLY be one. The storage location, size and quantity of the database in file mode are not limited.

## FDB_WRITE_GRAN

Flash write granularity, the unit is bit. Currently supports

- 1: nor flash
- 8/32/64/128/256: on-chip flash

If multiple Flash specifications are used in the database, use the maximum value as the configuration item.

## FDB_PRINT(...)

The print function macro defines the configuration. When it is not configured by default, using `printf` as the print log is the output function. Users can also customize new print function macro definitions, for example:

```C
#define FDB_PRINT(...) my_printf(__VA_ARGS__)
```

## FDB_DEBUG_ENABLE

Enable debugging information output. When this configuration is closed, the system will not output logs for debugging.
