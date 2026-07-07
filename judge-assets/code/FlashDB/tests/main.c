/*
 * Linux test runner for FlashDB unit tests.
 * Provides main() and calls the UTEST_TC_EXPORT-ed testcase functions.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>

extern int _test_failed;
extern const char *_test_cur_test;

/* forward declarations from test files */
extern void testcase(void); /* kvdb tests */

/* simple recursive directory delete for test cleanup */
static int dir_delete(const char *path) {
    DIR *dir = opendir(path);
    if (!dir) return -1;

    struct dirent *d;
    char full[1024];
    while ((d = readdir(dir))) {
        if (strcmp(d->d_name, ".") == 0 || strcmp(d->d_name, "..") == 0)
            continue;
        snprintf(full, sizeof(full), "%s/%s", path, d->d_name);
        if (d->d_type == DT_DIR) {
            dir_delete(full);
        } else {
            unlink(full);
        }
    }
    closedir(dir);
    rmdir(path);
    return 0;
}

static void clean_test_dirs(void) {
    dir_delete("fdb_kvdb1");
    dir_delete("fdb_tsdb1");
    dir_delete("storage_tsdb");
}

int main(int argc, char **argv) {
    int total = 0, passed = 0;

    printf("=== FlashDB Unit Tests ===\n\n");

    /* run kvdb tests */
    _test_failed = 0;
    clean_test_dirs();
    printf("[KVDB Tests]\n");
    testcase();
    total++;
    if (!_utest_failed) {
        printf("  KVDB: PASSED\n");
        passed++;
    } else {
        printf("  KVDB: FAILED\n");
    }
    clean_test_dirs();

    printf("\n=== Results: %d/%d test suites passed ===\n", passed, total);
    return (passed == total) ? 0 : 1;
}
