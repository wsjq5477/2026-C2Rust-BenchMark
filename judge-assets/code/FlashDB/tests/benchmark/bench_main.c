#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <stdarg.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <pthread.h>
#include <flashdb.h>

#define BENCH_SEC_SIZE    4096
#define BENCH_KVDB_SECS   128
#define BENCH_TSDB_SECS   128

#define BENCH_KV_COUNT    1000
#define BENCH_KV_BLOB_SIZE 128
#define BENCH_TSL_COUNT   2000
#define BENCH_TSL_BLOB_SIZE 64
#define BENCH_ITER_COUNT  3

#define KVDB_PATH "bench_kvdb"
#define TSDB_PATH "bench_tsdb"

typedef struct {
    double elapsed_us;
    uint32_t count;
    double ops_per_sec;
    double us_per_op;
} bench_result_t;

static struct timespec bench_ts_start;

static void bench_start(void)
{
    clock_gettime(CLOCK_MONOTONIC, &bench_ts_start);
}

static double bench_end(void)
{
    struct timespec ts_end;
    clock_gettime(CLOCK_MONOTONIC, &ts_end);
    double elapsed = (ts_end.tv_sec - bench_ts_start.tv_sec) * 1e6
                   + (ts_end.tv_nsec - bench_ts_start.tv_nsec) / 1e3;
    return elapsed;
}

static void bench_calc(bench_result_t *r, double elapsed_us, uint32_t count)
{
    r->elapsed_us = elapsed_us;
    r->count = count;
    if (elapsed_us > 0) {
        r->ops_per_sec = count / (elapsed_us / 1e6);
        r->us_per_op = elapsed_us / count;
    } else {
        r->ops_per_sec = 0;
        r->us_per_op = 0;
    }
}

static void bench_print(const char *name, bench_result_t *r)
{
    printf("  %-30s | %6u ops | %9.1f us | %8.1f ops/s | %7.2f us/op\n",
           name, r->count, r->elapsed_us, r->ops_per_sec, r->us_per_op);
}

static void dir_delete(const char *path)
{
    DIR *dir = opendir(path);
    if (!dir) return;
    struct dirent *d;
    char full[1024];
    while ((d = readdir(dir))) {
        if (strcmp(d->d_name, ".") == 0 || strcmp(d->d_name, "..") == 0) continue;
        snprintf(full, sizeof(full), "%s/%s", path, d->d_name);
        if (d->d_type == DT_DIR) dir_delete(full);
        else unlink(full);
    }
    closedir(dir);
    rmdir(path);
}

static void cleanup(void)
{
    dir_delete(KVDB_PATH);
    dir_delete(TSDB_PATH);
}

static fdb_time_t bench_cur_time;

static fdb_time_t bench_get_time(void)
{
    return ++bench_cur_time;
}

static void print_separator(void)
{
    printf("  %-30s | %-8s | %-11s | %-10s | %-10s\n",
           "Benchmark", "Count", "Elapsed", "Ops/s", "Us/op");
    printf("  %-30s-+-%-8s-+-%-11s-+-%-10s-+-%-10s\n",
           "------------------------------", "--------", "-----------", "----------", "----------");
}

static void bench_kvdb_set_string(fdb_kvdb_t db, uint32_t count)
{
    bench_result_t r;
    char key[32], val[32];
    bench_start();
    for (uint32_t i = 0; i < count; i++) {
        snprintf(key, sizeof(key), "str_%u", i);
        snprintf(val, sizeof(val), "val_%u", i);
        fdb_kv_set(db, key, val);
    }
    bench_calc(&r, bench_end(), count);
    bench_print("KVDB set (string)", &r);
}

static void bench_kvdb_get_string(fdb_kvdb_t db, uint32_t count)
{
    bench_result_t r;
    char key[32];
    bench_start();
    for (uint32_t i = 0; i < count; i++) {
        snprintf(key, sizeof(key), "str_%u", i);
        fdb_kv_get(db, key);
    }
    bench_calc(&r, bench_end(), count);
    bench_print("KVDB get (string)", &r);
}

static void bench_kvdb_set_blob(fdb_kvdb_t db, uint32_t count, size_t blob_size)
{
    bench_result_t r;
    struct fdb_blob blob;
    char key[32];
    uint8_t *buf = malloc(blob_size);
    memset(buf, 0xAB, blob_size);
    bench_start();
    for (uint32_t i = 0; i < count; i++) {
        snprintf(key, sizeof(key), "blob_%u", i);
        fdb_kv_set_blob(db, key, fdb_blob_make(&blob, buf, blob_size));
    }
    bench_calc(&r, bench_end(), count);
    bench_print("KVDB set (blob)", &r);
    free(buf);
}

static void bench_kvdb_get_blob(fdb_kvdb_t db, uint32_t count, size_t blob_size)
{
    bench_result_t r;
    struct fdb_blob blob;
    char key[32];
    uint8_t *buf = malloc(blob_size);
    bench_start();
    for (uint32_t i = 0; i < count; i++) {
        snprintf(key, sizeof(key), "blob_%u", i);
        fdb_kv_get_blob(db, key, fdb_blob_make(&blob, buf, blob_size));
    }
    bench_calc(&r, bench_end(), count);
    bench_print("KVDB get (blob)", &r);
    free(buf);
}

static void bench_kvdb_update_string(fdb_kvdb_t db, uint32_t count)
{
    bench_result_t r;
    char key[32], val[32];
    bench_start();
    for (uint32_t i = 0; i < count; i++) {
        snprintf(key, sizeof(key), "str_%u", i);
        snprintf(val, sizeof(val), "upd_%u", i);
        fdb_kv_set(db, key, val);
    }
    bench_calc(&r, bench_end(), count);
    bench_print("KVDB update (string)", &r);
}

static void bench_kvdb_del(fdb_kvdb_t db, uint32_t count)
{
    bench_result_t r;
    char key[32];
    bench_start();
    for (uint32_t i = 0; i < count; i++) {
        snprintf(key, sizeof(key), "str_%u", i);
        fdb_kv_del(db, key);
    }
    bench_calc(&r, bench_end(), count);
    bench_print("KVDB delete", &r);
}

static void bench_kvdb_iterate(fdb_kvdb_t db, uint32_t expected_count)
{
    bench_result_t r;
    struct fdb_kv_iterator iterator;
    uint32_t found = 0;
    bench_start();
    fdb_kv_iterator_init(db, &iterator);
    while (fdb_kv_iterate(db, &iterator)) {
        found++;
    }
    bench_calc(&r, bench_end(), found);
    bench_print("KVDB iterate all", &r);
    printf("    (found %u, expected %u)\n", found, expected_count);
}

static void bench_tsdb_append(fdb_tsdb_t db, uint32_t count, size_t blob_size)
{
    bench_result_t r;
    struct fdb_blob blob;
    uint8_t *buf = malloc(blob_size);
    memset(buf, 0xCD, blob_size);
    bench_start();
    for (uint32_t i = 0; i < count; i++) {
        fdb_tsl_append(db, fdb_blob_make(&blob, buf, blob_size));
    }
    bench_calc(&r, bench_end(), count);
    bench_print("TSDB append", &r);
    free(buf);
}

static uint32_t tsdb_iter_count;

static bool tsdb_iter_cb(fdb_tsl_t tsl, void *arg)
{
    tsdb_iter_count++;
    return false;
}

static void bench_tsdb_iter(fdb_tsdb_t db, uint32_t expected_count)
{
    bench_result_t r;
    tsdb_iter_count = 0;
    bench_start();
    fdb_tsl_iter(db, tsdb_iter_cb, NULL);
    bench_calc(&r, bench_end(), tsdb_iter_count);
    bench_print("TSDB iterate all", &r);
    printf("    (found %u, expected %u)\n", tsdb_iter_count, expected_count);
}

static void bench_tsdb_iter_by_time(fdb_tsdb_t db, fdb_time_t from, fdb_time_t to, uint32_t expected_count)
{
    bench_result_t r;
    tsdb_iter_count = 0;
    bench_start();
    fdb_tsl_iter_by_time(db, from, to, tsdb_iter_cb, NULL);
    bench_calc(&r, bench_end(), tsdb_iter_count);
    bench_print("TSDB iter by time", &r);
    printf("    (found %u, expected %u)\n", tsdb_iter_count, expected_count);
}

static void bench_tsdb_query_count(fdb_tsdb_t db, fdb_time_t from, fdb_time_t to)
{
    bench_result_t r;
    size_t count;
    bench_start();
    count = fdb_tsl_query_count(db, from, to, FDB_TSL_WRITE);
    bench_calc(&r, bench_end(), (uint32_t)count);
    bench_print("TSDB query count", &r);
}

int main(void)
{
    struct fdb_kvdb kvdb;
    struct fdb_tsdb tsdb;
    fdb_err_t result;
    bool file_mode = true;
    uint32_t sec_size = BENCH_SEC_SIZE;
    uint32_t kvdb_size = sec_size * BENCH_KVDB_SECS;
    uint32_t tsdb_size = sec_size * BENCH_TSDB_SECS;
    pthread_mutex_t kv_lock, ts_lock;
    pthread_mutexattr_t kv_attr, ts_attr;

    cleanup();
    mkdir(KVDB_PATH, 0777);
    mkdir(TSDB_PATH, 0777);

    printf("\n============================================================\n");
    printf("  FlashDB Linux Performance Baseline Benchmark\n");
    printf("  Sector size: %u bytes, KVDB sectors: %u, TSDB sectors: %u\n",
           sec_size, BENCH_KVDB_SECS, BENCH_TSDB_SECS);
    printf("  FDB_WRITE_GRAN: %d, File mode: POSIX\n", 1);
    printf("============================================================\n\n");

    bench_cur_time = 0;
    memset(&kvdb, 0, sizeof(kvdb));
    memset(&tsdb, 0, sizeof(tsdb));

    pthread_mutexattr_init(&kv_attr);
    pthread_mutexattr_settype(&kv_attr, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(&kv_lock, &kv_attr);

    pthread_mutexattr_init(&ts_attr);
    pthread_mutexattr_settype(&ts_attr, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(&ts_lock, &ts_attr);

    fdb_kvdb_control(&kvdb, FDB_KVDB_CTRL_SET_SEC_SIZE, &sec_size);
    fdb_kvdb_control(&kvdb, FDB_KVDB_CTRL_SET_MAX_SIZE, &kvdb_size);
    fdb_kvdb_control(&kvdb, FDB_KVDB_CTRL_SET_FILE_MODE, &file_mode);
    fdb_kvdb_control(&kvdb, FDB_KVDB_CTRL_SET_LOCK, (void (*)(fdb_db_t))pthread_mutex_lock);
    fdb_kvdb_control(&kvdb, FDB_KVDB_CTRL_SET_UNLOCK, (void (*)(fdb_db_t))pthread_mutex_unlock);

    result = fdb_kvdb_init(&kvdb, "bench_kv", KVDB_PATH, NULL, &kv_lock);
    if (result != FDB_NO_ERR) {
        fprintf(stderr, "KVDB init failed: %d\n", result);
        return 1;
    }

    printf("--- KVDB Benchmarks ---\n\n");
    print_separator();

    for (int run = 0; run < BENCH_ITER_COUNT; run++) {
        printf("\n  [Run %d/%d]\n", run + 1, BENCH_ITER_COUNT);

        fdb_kv_set_default(&kvdb);

        bench_kvdb_set_string(&kvdb, BENCH_KV_COUNT);
        bench_kvdb_get_string(&kvdb, BENCH_KV_COUNT);
        bench_kvdb_set_blob(&kvdb, BENCH_KV_COUNT, BENCH_KV_BLOB_SIZE);
        bench_kvdb_get_blob(&kvdb, BENCH_KV_COUNT, BENCH_KV_BLOB_SIZE);
        bench_kvdb_update_string(&kvdb, BENCH_KV_COUNT);
        bench_kvdb_iterate(&kvdb, BENCH_KV_COUNT + BENCH_KV_COUNT);
        bench_kvdb_del(&kvdb, BENCH_KV_COUNT);
    }

    fdb_kvdb_deinit(&kvdb);

    printf("\n--- TSDB Benchmarks ---\n\n");
    print_separator();

    fdb_tsdb_control(&tsdb, FDB_TSDB_CTRL_SET_SEC_SIZE, &sec_size);
    fdb_tsdb_control(&tsdb, FDB_TSDB_CTRL_SET_MAX_SIZE, &tsdb_size);
    fdb_tsdb_control(&tsdb, FDB_TSDB_CTRL_SET_FILE_MODE, &file_mode);
    fdb_tsdb_control(&tsdb, FDB_TSDB_CTRL_SET_LOCK, (void (*)(fdb_db_t))pthread_mutex_lock);
    fdb_tsdb_control(&tsdb, FDB_TSDB_CTRL_SET_UNLOCK, (void (*)(fdb_db_t))pthread_mutex_unlock);

    result = fdb_tsdb_init(&tsdb, "bench_ts", TSDB_PATH, bench_get_time, BENCH_TSL_BLOB_SIZE * 2, &ts_lock);
    if (result != FDB_NO_ERR) {
        fprintf(stderr, "TSDB init failed: %d\n", result);
        return 1;
    }

    fdb_time_t ts_start, ts_end;

    for (int run = 0; run < BENCH_ITER_COUNT; run++) {
        printf("\n  [Run %d/%d]\n", run + 1, BENCH_ITER_COUNT);

        fdb_tsl_clean(&tsdb);
        bench_cur_time = 0;
        ts_start = 1;

        bench_tsdb_append(&tsdb, BENCH_TSL_COUNT, BENCH_TSL_BLOB_SIZE);

        ts_end = BENCH_TSL_COUNT + 1;
        bench_tsdb_iter(&tsdb, BENCH_TSL_COUNT);
        bench_tsdb_iter_by_time(&tsdb, ts_start, ts_end, BENCH_TSL_COUNT);
        bench_tsdb_query_count(&tsdb, ts_start, ts_end);
    }

    fdb_tsdb_deinit(&tsdb);

    pthread_mutex_destroy(&kv_lock);
    pthread_mutex_destroy(&ts_lock);

    cleanup();

    printf("\n============================================================\n");
    printf("  Benchmark complete.\n");
    printf("============================================================\n\n");
    return 0;
}
