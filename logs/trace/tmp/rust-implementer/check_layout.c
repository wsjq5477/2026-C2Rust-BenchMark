#include <stdio.h>
#include <stddef.h>
#include <stdint.h>

#define FDB_WRITE_GRAN 1
#define FDB_STATUS_TABLE_SIZE(status_number) ((status_number * FDB_WRITE_GRAN + 7)/8)
#define FDB_KV_STATUS_NUM 6
#define FDB_SECTOR_STORE_STATUS_NUM 4
#define FDB_SECTOR_DIRTY_STATUS_NUM 4
#define FDB_TSL_STATUS_NUM 6

#define KV_STATUS_TABLE_SIZE FDB_STATUS_TABLE_SIZE(FDB_KV_STATUS_NUM)
#define STORE_STATUS_TABLE_SIZE FDB_STATUS_TABLE_SIZE(FDB_SECTOR_STORE_STATUS_NUM)
#define DIRTY_STATUS_TABLE_SIZE FDB_STATUS_TABLE_SIZE(FDB_SECTOR_DIRTY_STATUS_NUM)
#define TSL_STATUS_TABLE_SIZE FDB_STATUS_TABLE_SIZE(FDB_TSL_STATUS_NUM)

struct sector_hdr_data {
    struct {
        uint8_t store[STORE_STATUS_TABLE_SIZE];
        uint8_t dirty[DIRTY_STATUS_TABLE_SIZE];
    } status_table;
    uint32_t magic;
    uint32_t combined;
    uint32_t reserved;
};

struct kv_hdr_data {
    uint8_t status_table[KV_STATUS_TABLE_SIZE];
    uint32_t magic;
    uint32_t len;
    uint32_t crc32;
    uint8_t name_len;
    uint32_t value_len;
};

struct tsdb_sec_hdr_data {
    uint8_t status[STORE_STATUS_TABLE_SIZE];
    uint32_t magic;
    int32_t start_time;
    struct {
        int32_t time;
        uint32_t index;
        uint8_t status[TSL_STATUS_TABLE_SIZE];
    } end_info[2];
    uint32_t reserved;
};

struct log_idx_data {
    uint8_t status[TSL_STATUS_TABLE_SIZE];
    int32_t time;
    uint32_t log_len;
    uint32_t log_addr;
};

int main() {
    printf("sizeof(sector_hdr_data) = %zu\n", sizeof(struct sector_hdr_data));
    printf("offsetof(sector_hdr_data, status_table.store) = %zu\n", offsetof(struct sector_hdr_data, status_table.store));
    printf("offsetof(sector_hdr_data, status_table.dirty) = %zu\n", offsetof(struct sector_hdr_data, status_table.dirty));
    printf("offsetof(sector_hdr_data, magic) = %zu\n", offsetof(struct sector_hdr_data, magic));
    printf("offsetof(sector_hdr_data, combined) = %zu\n", offsetof(struct sector_hdr_data, combined));
    printf("offsetof(sector_hdr_data, reserved) = %zu\n", offsetof(struct sector_hdr_data, reserved));
    
    printf("\nsizeof(kv_hdr_data) = %zu\n", sizeof(struct kv_hdr_data));
    printf("offsetof(kv_hdr_data, status_table) = %zu\n", offsetof(struct kv_hdr_data, status_table));
    printf("offsetof(kv_hdr_data, magic) = %zu\n", offsetof(struct kv_hdr_data, magic));
    printf("offsetof(kv_hdr_data, len) = %zu\n", offsetof(struct kv_hdr_data, len));
    printf("offsetof(kv_hdr_data, crc32) = %zu\n", offsetof(struct kv_hdr_data, crc32));
    printf("offsetof(kv_hdr_data, name_len) = %zu\n", offsetof(struct kv_hdr_data, name_len));
    printf("offsetof(kv_hdr_data, value_len) = %zu\n", offsetof(struct kv_hdr_data, value_len));
    
    printf("\nsizeof(tsdb_sec_hdr_data) = %zu\n", sizeof(struct tsdb_sec_hdr_data));
    printf("offsetof(tsdb_sec_hdr_data, status) = %zu\n", offsetof(struct tsdb_sec_hdr_data, status));
    printf("offsetof(tsdb_sec_hdr_data, magic) = %zu\n", offsetof(struct tsdb_sec_hdr_data, magic));
    printf("offsetof(tsdb_sec_hdr_data, start_time) = %zu\n", offsetof(struct tsdb_sec_hdr_data, start_time));
    printf("offsetof(tsdb_sec_hdr_data, end_info[0].time) = %zu\n", offsetof(struct tsdb_sec_hdr_data, end_info[0].time));
    printf("offsetof(tsdb_sec_hdr_data, end_info[0].index) = %zu\n", offsetof(struct tsdb_sec_hdr_data, end_info[0].index));
    printf("offsetof(tsdb_sec_hdr_data, end_info[0].status) = %zu\n", offsetof(struct tsdb_sec_hdr_data, end_info[0].status));
    printf("offsetof(tsdb_sec_hdr_data, end_info[1].time) = %zu\n", offsetof(struct tsdb_sec_hdr_data, end_info[1].time));
    printf("offsetof(tsdb_sec_hdr_data, end_info[1].index) = %zu\n", offsetof(struct tsdb_sec_hdr_data, end_info[1].index));
    printf("offsetof(tsdb_sec_hdr_data, end_info[1].status) = %zu\n", offsetof(struct tsdb_sec_hdr_data, end_info[1].status));
    printf("offsetof(tsdb_sec_hdr_data, reserved) = %zu\n", offsetof(struct tsdb_sec_hdr_data, reserved));
    
    printf("\nsizeof(log_idx_data) = %zu\n", sizeof(struct log_idx_data));
    printf("offsetof(log_idx_data, status) = %zu\n", offsetof(struct log_idx_data, status));
    printf("offsetof(log_idx_data, time) = %zu\n", offsetof(struct log_idx_data, time));
    printf("offsetof(log_idx_data, log_len) = %zu\n", offsetof(struct log_idx_data, log_len));
    printf("offsetof(log_idx_data, log_addr) = %zu\n", offsetof(struct log_idx_data, log_addr));
    
    printf("\nKV_STATUS_TABLE_SIZE=%zu, STORE_STATUS_TABLE_SIZE=%zu, DIRTY_STATUS_TABLE_SIZE=%zu, TSL_STATUS_TABLE_SIZE=%zu\n",
        KV_STATUS_TABLE_SIZE, STORE_STATUS_TABLE_SIZE, DIRTY_STATUS_TABLE_SIZE, TSL_STATUS_TABLE_SIZE);
    
    return 0;
}
