/*
 * Linux test helpers for FlashDB unit tests.
 * Provides test assertion macros and utility functions.
 */

#ifndef _TEST_HELPERS_H_
#define _TEST_HELPERS_H_

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <time.h>
#include <dirent.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <limits.h>
#include <assert.h>

typedef struct slist_node {
    struct slist_node *next;
} slist_t;

static inline void slist_init(slist_t *l) { l->next = NULL; }
static inline void slist_append(slist_t *l, slist_t *n) {
    n->next = NULL;
    slist_t **p = &l->next;
    while (*p) p = &(*p)->next;
    *p = n;
}
static inline unsigned int slist_len(slist_t *l) {
    unsigned int c = 0;
    slist_t *p = l->next;
    while (p) { c++; p = p->next; }
    return c;
}
#define slist_entry(node, type, member) \
    ((type *)((char *)(node) - (unsigned long)(&((type *)0)->member)))

static inline uint32_t test_tick_get(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}
static inline void test_msleep(int ms) {
    usleep(ms * 1000);
}

#define LOG_W(fmt, ...) fprintf(stderr, "[WARN] " fmt "\n", ##__VA_ARGS__)

static int _test_failed;
static int _test_skip;
static const char *_test_cur_test;

#define test_assert_true(expr) do { \
    if (_test_skip) break; \
    if (!(expr)) { fprintf(stderr, "  FAIL %s: %s (line %d)\n", _test_cur_test, #expr, __LINE__); _test_failed = 1; _test_skip = 1; } \
} while(0)

#define test_assert_int_equal(a, b) do { \
    if (_test_skip) break; \
    if ((a) != (b)) { fprintf(stderr, "  FAIL %s: %s==%d vs %s==%d (line %d)\n", _test_cur_test, #a, (int)(a), #b, (int)(b), __LINE__); _test_failed = 1; _test_skip = 1; } \
} while(0)

#define test_assert_int_not_equal(a, b) do { \
    if (_test_skip) break; \
    if ((a) == (b)) { fprintf(stderr, "  FAIL %s: %s==%d should != %s==%d (line %d)\n", _test_cur_test, #a, (int)(a), #b, (int)(b), __LINE__); _test_failed = 1; _test_skip = 1; } \
} while(0)

#define test_assert_not_null(p) do { \
    if (_test_skip) break; \
    if ((p) == NULL) { fprintf(stderr, "  FAIL %s: %s is NULL (line %d)\n", _test_cur_test, #p, __LINE__); _test_failed = 1; _test_skip = 1; } \
} while(0)

#define test_assert_null(p) do { \
    if (_test_skip) break; \
    if ((p) != NULL) { fprintf(stderr, "  FAIL %s: %s is not NULL (line %d)\n", _test_cur_test, #p, __LINE__); _test_failed = 1; _test_skip = 1; } \
} while(0)

#define test_assert_str_equal(a, b) do { \
    if (_test_skip) break; \
    if (strcmp((a), (b)) != 0) { fprintf(stderr, "  FAIL %s: \"%s\" != \"%s\" (line %d)\n", _test_cur_test, (a), (b), __LINE__); _test_failed = 1; _test_skip = 1; } \
} while(0)

#define test_assert_buf_equal(a, b, len) do { \
    if (_test_skip) break; \
    if (memcmp((a), (b), (len)) != 0) { fprintf(stderr, "  FAIL %s: buffer mismatch (line %d)\n", _test_cur_test, __LINE__); _test_failed = 1; _test_skip = 1; } \
} while(0)

typedef void (*test_func_t)(void);

#define TEST_RUN(f) do { \
    _test_cur_test = #f; \
    _test_skip = 0; \
    printf("  Running: %s ...\n", #f); \
    f(); \
} while(0)

#endif /* _TEST_HELPERS_H_ */
