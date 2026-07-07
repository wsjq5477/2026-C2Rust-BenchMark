#include "test_helpers.h"
#include <flashdb.h>
#include "fdb_tsdb_tc.c"

static int dir_delete_simple(const char *path) {
    DIR *dir = opendir(path);
    if (!dir) return -1;
    struct dirent *d;
    char full[1024];
    while ((d = readdir(dir))) {
        if (strcmp(d->d_name, ".") == 0 || strcmp(d->d_name, "..") == 0)
            continue;
        snprintf(full, sizeof(full), "%s/%s", path, d->d_name);
        if (d->d_type == DT_DIR) {
            dir_delete_simple(full);
        } else {
            unlink(full);
        }
    }
    closedir(dir);
    rmdir(path);
    return 0;
}

int main(void) {
    _test_failed = 0;
    dir_delete_simple("fdb_kvdb1");
    dir_delete_simple("fdb_tsdb1");
    dir_delete_simple("storage_tsdb");

    printf("=== FlashDB TSDB Test ===\n");
    utest_tc_init();
    testcase();
    utest_tc_cleanup();
    printf("\n=== TSDB Test: %s ===\n", _test_failed ? "FAILED" : "PASSED");

    return _test_failed ? 1 : 0;
}
