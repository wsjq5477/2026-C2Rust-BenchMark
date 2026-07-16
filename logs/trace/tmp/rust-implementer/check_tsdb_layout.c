#include <stdio.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define FDB_WRITE_GRAN 1
#define FDB_STATUS_TABLE_SIZE(status_number) ((status_number * FDB_WRITE_GRAN + 7)/8)
#define FDB_KV_STATUS_NUM 6
#define FDB_SECTOR_STORE_STATUS_NUM 4
#define FDB_SECTOR_DIRTY_STATUS_NUM 4
#define FDB_TSL_STATUS_NUM 6

#define FDB_WG_ALIGN(size) (((size) + ((FDB_WRITE_GRAN + 7)/8) - 1) - (((size) + ((FDB_WRITE_GRAN + 7)/8) -1) % ((FDB_WRITE_GRAN + 7)/8)))

#define KV_STATUS_TABLE_SIZE FDB_STATUS_TABLE_SIZE(FDB_KV_STATUS_NUM)
#define STORE_STATUS_TABLE_SIZE FDB_STATUS_TABLE_SIZE(FDB_SECTOR_STORE_STATUS_NUM)
#define DIRTY_STATUS_TABLE_SIZE FDB_STATUS_TABLE_SIZE(FDB_SECTOR_DIRTY_STATUS_NUM)
#define TSL_STATUS_TABLE_SIZE FDB_STATUS_TABLE_SIZE(FDB_TSL_STATUS_NUM)

#define TSL_UINT32_ALIGN_SIZE (FDB_WG_ALIGN(sizeof(uint32_t)))
#define TSL_TIME_ALIGN_SIZE (FDB_WG_ALIGN(sizeof(int32_t)))
#define SECTOR_HDR_PADDING_SIZE (FDB_WG_ALIGN(4) - 4)

// TSDB sector header - uses uint8_t arrays!
struct tsdb_sector_hdr_data {
    uint8_t status[STORE_STATUS_TABLE_SIZE];
    uint8_t magic[TSL_UINT32_ALIGN_SIZE];
    uint8_t start_time[TSL_TIME_ALIGN_SIZE];
    struct {
        uint8_t time[TSL_TIME_ALIGN_SIZE];
        uint8_t index[TSL_UINT32_ALIGN_SIZE];
        uint8_t status[TSL_STATUS_TABLE_SIZE];
    } end_info[2];
    uint32_t reserved;
#if SECTOR_HDR_PADDING_SIZE > 0
    uint8_t padding[SECTOR_HDR_PADDING_SIZE];
#endif
};

// Log index data - with fdb_time_t = int32_t
#ifndef FDB_TSDB_FIXED_BLOB_SIZE
struct tsdb_log_idx_data {
    uint8_t status_table[TSL_STATUS_TABLE_SIZE];
    int32_t time;
    uint32_t log_len;
    uint32_t log_addr;
};
#else
struct tsdb_log_idx_data_fixed {
    uint8_t status_table[TSL_STATUS_TABLE_SIZE];
    int32_t time;
};
#endif

// KVDB sector header - uses uint32_t fields
struct kvdb_sector_hdr_data {
    struct {
        uint8_t store[STORE_STATUS_TABLE_SIZE];
        uint8_t dirty[DIRTY_STATUS_TABLE_SIZE];
    } status_table;
    uint32_t magic;
    uint32_t combined;
    uint32_t reserved;
};

// KV header - uses uint32_t fields
struct kv_hdr_data {
    uint8_t status_table[KV_STATUS_TABLE_SIZE];
    uint32_t magic;
    uint32_t len;
    uint32_t crc32;
    uint8_t name_len;
    uint32_t value_len;
};

int main() {
    printf("=== KVDB sector header ===\n");
    printf("sizeof(kvdb_sector_hdr_data) = %zu\n", sizeof(struct kvdb_sector_hdr_data));
    printf("offsetof(store) = %zu\n", offsetof(struct kvdb_sector_hdr_data, status_table.store));
    printf("offsetof(dirty) = %zu\n", offsetof(struct kvdb_sector_hdr_data, status_table.dirty));
    printf("offsetof(magic) = %zu\n", offsetof(struct kvdb_sector_hdr_data, magic));
    printf("offsetof(combined) = %zu\n", offsetof(struct kvdb_sector_hdr_data, combined));
    printf("offsetof(reserved) = %zu\n", offsetof(struct kvdb_sector_hdr_data, reserved));
    printf("KVDB SECTOR_HDR_DATA_SIZE = %zu\n", FDB_WG_ALIGN(sizeof(struct kvdb_sector_hdr_data)));
    
    printf("\n=== KV header ===\n");
    printf("sizeof(kv_hdr_data) = %zu\n", sizeof(struct kv_hdr_data));
    printf("offsetof(status_table) = %zu\n", offsetof(struct kv_hdr_data, status_table));
    printf("offsetof(magic) = %zu\n", offsetof(struct kv_hdr_data, magic));
    printf("offsetof(len) = %zu\n", offsetof(struct kv_hdr_data, len));
    printf("offsetof(crc32) = %zu\n", offsetof(struct kv_hdr_data, crc32));
    printf("offsetof(name_len) = %zu\n", offsetof(struct kv_hdr_data, name_len));
    printf("offsetof(value_len) = %zu\n", offsetof(struct kv_hdr_data, value_len));
    printf("KV_HDR_DATA_SIZE = %zu\n", FDB_WG_ALIGN(sizeof(struct kv_hdr_data)));
    
    printf("\n=== TSDB sector header (uint8_t arrays) ===\n");
    printf("sizeof(tsdb_sector_hdr_data) = %zu\n", sizeof(struct tsdb_sector_hdr_data));
    printf("offsetof(status) = %zu\n", offsetof(struct tsdb_sector_hdr_data, status));
    printf("offsetof(magic) = %zu\n", offsetof(struct tsdb_sector_hdr_data, magic));
    printf("offsetof(start_time) = %zu\n", offsetof(struct tsdb_sector_hdr_data, start_time));
    printf("offsetof(end_info[0].time) = %zu\n", offsetof(struct tsdb_sector_hdr_data, end_info[0].time));
    printf("offsetof(end_info[0].index) = %zu\n", offsetof(struct tsdb_sector_hdr_data, end_info[0].index));
    printf("offsetof(end_info[0].status) = %zu\n", offsetof(struct tsdb_sector_hdr_data, end_info[0].status));
    printf("offsetof(end_info[1].time) = %zu\n", offsetof(struct tsdb_sector_hdr_data, end_info[1].time));
    printf("offsetof(end_info[1].index) = %zu\n", offsetof(struct tsdb_sector_hdr_data, end_info[1].index));
    printf("offsetof(end_info[1].status) = %zu\n", offsetof(struct tsdb_sector_hdr_data, end_info[1].status));
    printf("offsetof(reserved) = %zu\n", offsetof(struct tsdb_sector_hdr_data, reserved));
    printf("TSDB SECTOR_HDR_DATA_SIZE = %zu\n", FDB_WG_ALIGN(sizeof(struct tsdb_sector_hdr_data)));
    
    printf("\n=== Log index data (non-fixed blob) ===\n");
    printf("sizeof(tsdb_log_idx_data) = %zu\n", sizeof(struct tsdb_log_idx_data));
    printf("offsetof(status_table) = %zu\n", offsetof(struct tsdb_log_idx_data, status_table));
    printf("offsetof(time) = %zu\n", offsetof(struct tsdb_log_idx_data, time));
    printf("offsetof(log_len) = %zu\n", offsetof(struct tsdb_log_idx_data, log_len));
    printf("offsetof(log_addr) = %zu\n", offsetof(struct tsdb_log_idx_data, log_addr));
    printf("LOG_IDX_DATA_SIZE = %zu\n", FDB_WG_ALIGN(sizeof(struct tsdb_log_idx_data)));
    
    printf("\nSizes: KVDB_SEC_HDR=%zu, KV_HDR=%zu, TSDB_SEC_HDR=%zu, LOG_IDX=%zu\n",
        FDB_WG_ALIGN(sizeof(struct kvdb_sector_hdr_data)),
        FDB_WG_ALIGN(sizeof(struct kv_hdr_data)),
        FDB_WG_ALIGN(sizeof(struct tsdb_sector_hdr_data)),
        FDB_WG_ALIGN(sizeof(struct tsdb_log_idx_data)));
    
    return 0;
}
