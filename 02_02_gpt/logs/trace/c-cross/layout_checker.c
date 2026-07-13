#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#include <time.h>
#include "fdb_cfg_template.h"
#include "fdb_def.h"
#include "fdb_low_lvl.h"
#include "flashdb.h"

extern size_t rust_sizeof_fdb_blob(void);
extern size_t rust_alignof_fdb_blob(void);
extern size_t rust_offsetof_fdb_blob_buf(void);
extern size_t rust_offsetof_fdb_blob_size(void);
extern size_t rust_offsetof_fdb_blob_saved(void);
extern size_t rust_sizeof_fdb_db(void);
extern size_t rust_alignof_fdb_db(void);
extern size_t rust_offsetof_fdb_db_name(void);
extern size_t rust_offsetof_fdb_db_type(void);
extern size_t rust_offsetof_fdb_db_storage(void);
extern size_t rust_offsetof_fdb_db_sec_size(void);
extern size_t rust_offsetof_fdb_db_max_size(void);
extern size_t rust_offsetof_fdb_db_oldest_addr(void);
extern size_t rust_offsetof_fdb_db_init_ok(void);
extern size_t rust_offsetof_fdb_db_file_mode(void);
extern size_t rust_offsetof_fdb_db_not_formatable(void);
extern size_t rust_offsetof_fdb_db_cur_file_sec(void);
extern size_t rust_offsetof_fdb_db_cur_file(void);
extern size_t rust_offsetof_fdb_db_cur_sec(void);
extern size_t rust_offsetof_fdb_db_lock(void);
extern size_t rust_offsetof_fdb_db_unlock(void);
extern size_t rust_offsetof_fdb_db_user_data(void);
extern size_t rust_sizeof_fdb_default_kv(void);
extern size_t rust_alignof_fdb_default_kv(void);
extern size_t rust_offsetof_fdb_default_kv_kvs(void);
extern size_t rust_offsetof_fdb_default_kv_num(void);
extern size_t rust_sizeof_fdb_default_kv_node(void);
extern size_t rust_alignof_fdb_default_kv_node(void);
extern size_t rust_offsetof_fdb_default_kv_node_key(void);
extern size_t rust_offsetof_fdb_default_kv_node_value(void);
extern size_t rust_offsetof_fdb_default_kv_node_value_len(void);
extern size_t rust_sizeof_fdb_kv(void);
extern size_t rust_alignof_fdb_kv(void);
extern size_t rust_offsetof_fdb_kv_status(void);
extern size_t rust_offsetof_fdb_kv_crc_is_ok(void);
extern size_t rust_offsetof_fdb_kv_name_len(void);
extern size_t rust_offsetof_fdb_kv_magic(void);
extern size_t rust_offsetof_fdb_kv_len(void);
extern size_t rust_offsetof_fdb_kv_value_len(void);
extern size_t rust_offsetof_fdb_kv_name(void);
extern size_t rust_offsetof_fdb_kv_addr(void);
extern size_t rust_sizeof_fdb_kv_iterator(void);
extern size_t rust_alignof_fdb_kv_iterator(void);
extern size_t rust_offsetof_fdb_kv_iterator_curr_kv(void);
extern size_t rust_offsetof_fdb_kv_iterator_iterated_cnt(void);
extern size_t rust_offsetof_fdb_kv_iterator_iterated_obj_bytes(void);
extern size_t rust_offsetof_fdb_kv_iterator_iterated_value_bytes(void);
extern size_t rust_offsetof_fdb_kv_iterator_sector_addr(void);
extern size_t rust_offsetof_fdb_kv_iterator_traversed_len(void);
extern size_t rust_sizeof_fdb_kvdb(void);
extern size_t rust_alignof_fdb_kvdb(void);
extern size_t rust_offsetof_fdb_kvdb_parent(void);
extern size_t rust_offsetof_fdb_kvdb_default_kvs(void);
extern size_t rust_offsetof_fdb_kvdb_gc_request(void);
extern size_t rust_offsetof_fdb_kvdb_in_recovery_check(void);
extern size_t rust_offsetof_fdb_kvdb_cur_kv(void);
extern size_t rust_offsetof_fdb_kvdb_cur_sector(void);
extern size_t rust_offsetof_fdb_kvdb_last_is_complete_del(void);
extern size_t rust_offsetof_fdb_kvdb_kv_cache_table(void);
extern size_t rust_offsetof_fdb_kvdb_sector_cache_table(void);
extern size_t rust_offsetof_fdb_kvdb_user_data(void);
extern size_t rust_sizeof_fdb_tsdb(void);
extern size_t rust_alignof_fdb_tsdb(void);
extern size_t rust_offsetof_fdb_tsdb_parent(void);
extern size_t rust_offsetof_fdb_tsdb_cur_sec(void);
extern size_t rust_offsetof_fdb_tsdb_last_time(void);
extern size_t rust_offsetof_fdb_tsdb_get_time(void);
extern size_t rust_offsetof_fdb_tsdb_max_len(void);
extern size_t rust_offsetof_fdb_tsdb_rollover(void);
extern size_t rust_offsetof_fdb_tsdb_user_data(void);
extern size_t rust_sizeof_fdb_tsl(void);
extern size_t rust_alignof_fdb_tsl(void);
extern size_t rust_offsetof_fdb_tsl_status(void);
extern size_t rust_offsetof_fdb_tsl_time(void);
extern size_t rust_offsetof_fdb_tsl_log_len(void);
extern size_t rust_offsetof_fdb_tsl_addr(void);
extern size_t rust_sizeof_kv_cache_node(void);
extern size_t rust_alignof_kv_cache_node(void);
extern size_t rust_offsetof_kv_cache_node_name_crc(void);
extern size_t rust_offsetof_kv_cache_node_active(void);
extern size_t rust_offsetof_kv_cache_node_addr(void);
extern size_t rust_sizeof_kvdb_sec_info(void);
extern size_t rust_alignof_kvdb_sec_info(void);
extern size_t rust_offsetof_kvdb_sec_info_check_ok(void);
extern size_t rust_offsetof_kvdb_sec_info_status(void);
extern size_t rust_offsetof_kvdb_sec_info_addr(void);
extern size_t rust_offsetof_kvdb_sec_info_magic(void);
extern size_t rust_offsetof_kvdb_sec_info_combined(void);
extern size_t rust_offsetof_kvdb_sec_info_remain(void);
extern size_t rust_offsetof_kvdb_sec_info_empty_kv(void);
extern size_t rust_sizeof_tsdb_sec_info(void);
extern size_t rust_alignof_tsdb_sec_info(void);
extern size_t rust_offsetof_tsdb_sec_info_check_ok(void);
extern size_t rust_offsetof_tsdb_sec_info_status(void);
extern size_t rust_offsetof_tsdb_sec_info_addr(void);
extern size_t rust_offsetof_tsdb_sec_info_magic(void);
extern size_t rust_offsetof_tsdb_sec_info_start_time(void);
extern size_t rust_offsetof_tsdb_sec_info_end_time(void);
extern size_t rust_offsetof_tsdb_sec_info_end_idx(void);
extern size_t rust_offsetof_tsdb_sec_info_end_info_stat(void);
extern size_t rust_offsetof_tsdb_sec_info_remain(void);
extern size_t rust_offsetof_tsdb_sec_info_empty_idx(void);
extern size_t rust_offsetof_tsdb_sec_info_empty_data(void);

int main(void) {
  int failures = 0;
  printf("[LAYOUT CHECK] start\n");
  if (sizeof(struct fdb_blob) != rust_sizeof_fdb_blob()) {
    printf("[LAYOUT MISMATCH] struct=fdb_blob sizeof c=%zu rust=%zu\n", sizeof(struct fdb_blob), rust_sizeof_fdb_blob());
    failures++;
  }
  if (_Alignof(struct fdb_blob) != rust_alignof_fdb_blob()) {
    printf("[LAYOUT MISMATCH] struct=fdb_blob alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_blob), rust_alignof_fdb_blob());
    failures++;
  }
  if (sizeof(struct fdb_blob) == rust_sizeof_fdb_blob() && _Alignof(struct fdb_blob) == rust_alignof_fdb_blob()) {
    printf("[LAYOUT OK] struct=fdb_blob sizeof=%zu alignof=%zu\n", sizeof(struct fdb_blob), (size_t)_Alignof(struct fdb_blob));
  }
  if (rust_offsetof_fdb_blob_buf() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_blob.buf offset c=%zu rust=missing\n", offsetof(struct fdb_blob, buf));
    printf("possible_reason=active macro added field buf that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_blob, buf) != rust_offsetof_fdb_blob_buf()) {
    printf("[LAYOUT MISMATCH] field=fdb_blob.buf offset c=%zu rust=%zu\n", offsetof(struct fdb_blob, buf), rust_offsetof_fdb_blob_buf());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_blob field=buf offset=%zu\n", offsetof(struct fdb_blob, buf));
  }
  if (rust_offsetof_fdb_blob_size() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_blob.size offset c=%zu rust=missing\n", offsetof(struct fdb_blob, size));
    printf("possible_reason=active macro added field size that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_blob, size) != rust_offsetof_fdb_blob_size()) {
    printf("[LAYOUT MISMATCH] field=fdb_blob.size offset c=%zu rust=%zu\n", offsetof(struct fdb_blob, size), rust_offsetof_fdb_blob_size());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_blob field=size offset=%zu\n", offsetof(struct fdb_blob, size));
  }
  if (rust_offsetof_fdb_blob_saved() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_blob.saved offset c=%zu rust=missing\n", offsetof(struct fdb_blob, saved));
    printf("possible_reason=active macro added field saved that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_blob, saved) != rust_offsetof_fdb_blob_saved()) {
    printf("[LAYOUT MISMATCH] field=fdb_blob.saved offset c=%zu rust=%zu\n", offsetof(struct fdb_blob, saved), rust_offsetof_fdb_blob_saved());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_blob field=saved offset=%zu\n", offsetof(struct fdb_blob, saved));
  }
  if (sizeof(struct fdb_db) != rust_sizeof_fdb_db()) {
    printf("[LAYOUT MISMATCH] struct=fdb_db sizeof c=%zu rust=%zu\n", sizeof(struct fdb_db), rust_sizeof_fdb_db());
    failures++;
  }
  if (_Alignof(struct fdb_db) != rust_alignof_fdb_db()) {
    printf("[LAYOUT MISMATCH] struct=fdb_db alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_db), rust_alignof_fdb_db());
    failures++;
  }
  if (sizeof(struct fdb_db) == rust_sizeof_fdb_db() && _Alignof(struct fdb_db) == rust_alignof_fdb_db()) {
    printf("[LAYOUT OK] struct=fdb_db sizeof=%zu alignof=%zu\n", sizeof(struct fdb_db), (size_t)_Alignof(struct fdb_db));
  }
  if (rust_offsetof_fdb_db_name() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.name offset c=%zu rust=missing\n", offsetof(struct fdb_db, name));
    printf("possible_reason=active macro added field name that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, name) != rust_offsetof_fdb_db_name()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.name offset c=%zu rust=%zu\n", offsetof(struct fdb_db, name), rust_offsetof_fdb_db_name());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=name offset=%zu\n", offsetof(struct fdb_db, name));
  }
  if (rust_offsetof_fdb_db_type() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.type offset c=%zu rust=missing\n", offsetof(struct fdb_db, type));
    printf("possible_reason=active macro added field type that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, type) != rust_offsetof_fdb_db_type()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.type offset c=%zu rust=%zu\n", offsetof(struct fdb_db, type), rust_offsetof_fdb_db_type());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=type offset=%zu\n", offsetof(struct fdb_db, type));
  }
  if (rust_offsetof_fdb_db_storage() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.storage offset c=%zu rust=missing\n", offsetof(struct fdb_db, storage));
    printf("possible_reason=active macro added field storage that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, storage) != rust_offsetof_fdb_db_storage()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.storage offset c=%zu rust=%zu\n", offsetof(struct fdb_db, storage), rust_offsetof_fdb_db_storage());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=storage offset=%zu\n", offsetof(struct fdb_db, storage));
  }
  if (rust_offsetof_fdb_db_sec_size() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.sec_size offset c=%zu rust=missing\n", offsetof(struct fdb_db, sec_size));
    printf("possible_reason=active macro added field sec_size that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, sec_size) != rust_offsetof_fdb_db_sec_size()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.sec_size offset c=%zu rust=%zu\n", offsetof(struct fdb_db, sec_size), rust_offsetof_fdb_db_sec_size());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=sec_size offset=%zu\n", offsetof(struct fdb_db, sec_size));
  }
  if (rust_offsetof_fdb_db_max_size() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.max_size offset c=%zu rust=missing\n", offsetof(struct fdb_db, max_size));
    printf("possible_reason=active macro added field max_size that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, max_size) != rust_offsetof_fdb_db_max_size()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.max_size offset c=%zu rust=%zu\n", offsetof(struct fdb_db, max_size), rust_offsetof_fdb_db_max_size());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=max_size offset=%zu\n", offsetof(struct fdb_db, max_size));
  }
  if (rust_offsetof_fdb_db_oldest_addr() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.oldest_addr offset c=%zu rust=missing\n", offsetof(struct fdb_db, oldest_addr));
    printf("possible_reason=active macro added field oldest_addr that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, oldest_addr) != rust_offsetof_fdb_db_oldest_addr()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.oldest_addr offset c=%zu rust=%zu\n", offsetof(struct fdb_db, oldest_addr), rust_offsetof_fdb_db_oldest_addr());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=oldest_addr offset=%zu\n", offsetof(struct fdb_db, oldest_addr));
  }
  if (rust_offsetof_fdb_db_init_ok() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.init_ok offset c=%zu rust=missing\n", offsetof(struct fdb_db, init_ok));
    printf("possible_reason=active macro added field init_ok that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, init_ok) != rust_offsetof_fdb_db_init_ok()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.init_ok offset c=%zu rust=%zu\n", offsetof(struct fdb_db, init_ok), rust_offsetof_fdb_db_init_ok());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=init_ok offset=%zu\n", offsetof(struct fdb_db, init_ok));
  }
  if (rust_offsetof_fdb_db_file_mode() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.file_mode offset c=%zu rust=missing\n", offsetof(struct fdb_db, file_mode));
    printf("possible_reason=active macro added field file_mode that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, file_mode) != rust_offsetof_fdb_db_file_mode()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.file_mode offset c=%zu rust=%zu\n", offsetof(struct fdb_db, file_mode), rust_offsetof_fdb_db_file_mode());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=file_mode offset=%zu\n", offsetof(struct fdb_db, file_mode));
  }
  if (rust_offsetof_fdb_db_not_formatable() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.not_formatable offset c=%zu rust=missing\n", offsetof(struct fdb_db, not_formatable));
    printf("possible_reason=active macro added field not_formatable that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, not_formatable) != rust_offsetof_fdb_db_not_formatable()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.not_formatable offset c=%zu rust=%zu\n", offsetof(struct fdb_db, not_formatable), rust_offsetof_fdb_db_not_formatable());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=not_formatable offset=%zu\n", offsetof(struct fdb_db, not_formatable));
  }
  if (rust_offsetof_fdb_db_cur_file_sec() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.cur_file_sec offset c=%zu rust=missing\n", offsetof(struct fdb_db, cur_file_sec));
    printf("possible_reason=active macro added field cur_file_sec that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, cur_file_sec) != rust_offsetof_fdb_db_cur_file_sec()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.cur_file_sec offset c=%zu rust=%zu\n", offsetof(struct fdb_db, cur_file_sec), rust_offsetof_fdb_db_cur_file_sec());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=cur_file_sec offset=%zu\n", offsetof(struct fdb_db, cur_file_sec));
  }
  if (rust_offsetof_fdb_db_cur_file() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.cur_file offset c=%zu rust=missing\n", offsetof(struct fdb_db, cur_file));
    printf("possible_reason=active macro added field cur_file that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, cur_file) != rust_offsetof_fdb_db_cur_file()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.cur_file offset c=%zu rust=%zu\n", offsetof(struct fdb_db, cur_file), rust_offsetof_fdb_db_cur_file());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=cur_file offset=%zu\n", offsetof(struct fdb_db, cur_file));
  }
  if (rust_offsetof_fdb_db_cur_sec() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.cur_sec offset c=%zu rust=missing\n", offsetof(struct fdb_db, cur_sec));
    printf("possible_reason=active macro added field cur_sec that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, cur_sec) != rust_offsetof_fdb_db_cur_sec()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.cur_sec offset c=%zu rust=%zu\n", offsetof(struct fdb_db, cur_sec), rust_offsetof_fdb_db_cur_sec());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=cur_sec offset=%zu\n", offsetof(struct fdb_db, cur_sec));
  }
  if (rust_offsetof_fdb_db_lock() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.lock offset c=%zu rust=missing\n", offsetof(struct fdb_db, lock));
    printf("possible_reason=active macro added field lock that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, lock) != rust_offsetof_fdb_db_lock()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.lock offset c=%zu rust=%zu\n", offsetof(struct fdb_db, lock), rust_offsetof_fdb_db_lock());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=lock offset=%zu\n", offsetof(struct fdb_db, lock));
  }
  if (rust_offsetof_fdb_db_unlock() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.unlock offset c=%zu rust=missing\n", offsetof(struct fdb_db, unlock));
    printf("possible_reason=active macro added field unlock that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, unlock) != rust_offsetof_fdb_db_unlock()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.unlock offset c=%zu rust=%zu\n", offsetof(struct fdb_db, unlock), rust_offsetof_fdb_db_unlock());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=unlock offset=%zu\n", offsetof(struct fdb_db, unlock));
  }
  if (rust_offsetof_fdb_db_user_data() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_db.user_data offset c=%zu rust=missing\n", offsetof(struct fdb_db, user_data));
    printf("possible_reason=active macro added field user_data that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_db, user_data) != rust_offsetof_fdb_db_user_data()) {
    printf("[LAYOUT MISMATCH] field=fdb_db.user_data offset c=%zu rust=%zu\n", offsetof(struct fdb_db, user_data), rust_offsetof_fdb_db_user_data());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_db field=user_data offset=%zu\n", offsetof(struct fdb_db, user_data));
  }
  if (sizeof(struct fdb_default_kv) != rust_sizeof_fdb_default_kv()) {
    printf("[LAYOUT MISMATCH] struct=fdb_default_kv sizeof c=%zu rust=%zu\n", sizeof(struct fdb_default_kv), rust_sizeof_fdb_default_kv());
    failures++;
  }
  if (_Alignof(struct fdb_default_kv) != rust_alignof_fdb_default_kv()) {
    printf("[LAYOUT MISMATCH] struct=fdb_default_kv alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_default_kv), rust_alignof_fdb_default_kv());
    failures++;
  }
  if (sizeof(struct fdb_default_kv) == rust_sizeof_fdb_default_kv() && _Alignof(struct fdb_default_kv) == rust_alignof_fdb_default_kv()) {
    printf("[LAYOUT OK] struct=fdb_default_kv sizeof=%zu alignof=%zu\n", sizeof(struct fdb_default_kv), (size_t)_Alignof(struct fdb_default_kv));
  }
  if (rust_offsetof_fdb_default_kv_kvs() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv.kvs offset c=%zu rust=missing\n", offsetof(struct fdb_default_kv, kvs));
    printf("possible_reason=active macro added field kvs that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_default_kv, kvs) != rust_offsetof_fdb_default_kv_kvs()) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv.kvs offset c=%zu rust=%zu\n", offsetof(struct fdb_default_kv, kvs), rust_offsetof_fdb_default_kv_kvs());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_default_kv field=kvs offset=%zu\n", offsetof(struct fdb_default_kv, kvs));
  }
  if (rust_offsetof_fdb_default_kv_num() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv.num offset c=%zu rust=missing\n", offsetof(struct fdb_default_kv, num));
    printf("possible_reason=active macro added field num that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_default_kv, num) != rust_offsetof_fdb_default_kv_num()) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv.num offset c=%zu rust=%zu\n", offsetof(struct fdb_default_kv, num), rust_offsetof_fdb_default_kv_num());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_default_kv field=num offset=%zu\n", offsetof(struct fdb_default_kv, num));
  }
  if (sizeof(struct fdb_default_kv_node) != rust_sizeof_fdb_default_kv_node()) {
    printf("[LAYOUT MISMATCH] struct=fdb_default_kv_node sizeof c=%zu rust=%zu\n", sizeof(struct fdb_default_kv_node), rust_sizeof_fdb_default_kv_node());
    failures++;
  }
  if (_Alignof(struct fdb_default_kv_node) != rust_alignof_fdb_default_kv_node()) {
    printf("[LAYOUT MISMATCH] struct=fdb_default_kv_node alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_default_kv_node), rust_alignof_fdb_default_kv_node());
    failures++;
  }
  if (sizeof(struct fdb_default_kv_node) == rust_sizeof_fdb_default_kv_node() && _Alignof(struct fdb_default_kv_node) == rust_alignof_fdb_default_kv_node()) {
    printf("[LAYOUT OK] struct=fdb_default_kv_node sizeof=%zu alignof=%zu\n", sizeof(struct fdb_default_kv_node), (size_t)_Alignof(struct fdb_default_kv_node));
  }
  if (rust_offsetof_fdb_default_kv_node_key() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv_node.key offset c=%zu rust=missing\n", offsetof(struct fdb_default_kv_node, key));
    printf("possible_reason=active macro added field key that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_default_kv_node, key) != rust_offsetof_fdb_default_kv_node_key()) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv_node.key offset c=%zu rust=%zu\n", offsetof(struct fdb_default_kv_node, key), rust_offsetof_fdb_default_kv_node_key());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_default_kv_node field=key offset=%zu\n", offsetof(struct fdb_default_kv_node, key));
  }
  if (rust_offsetof_fdb_default_kv_node_value() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv_node.value offset c=%zu rust=missing\n", offsetof(struct fdb_default_kv_node, value));
    printf("possible_reason=active macro added field value that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_default_kv_node, value) != rust_offsetof_fdb_default_kv_node_value()) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv_node.value offset c=%zu rust=%zu\n", offsetof(struct fdb_default_kv_node, value), rust_offsetof_fdb_default_kv_node_value());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_default_kv_node field=value offset=%zu\n", offsetof(struct fdb_default_kv_node, value));
  }
  if (rust_offsetof_fdb_default_kv_node_value_len() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv_node.value_len offset c=%zu rust=missing\n", offsetof(struct fdb_default_kv_node, value_len));
    printf("possible_reason=active macro added field value_len that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_default_kv_node, value_len) != rust_offsetof_fdb_default_kv_node_value_len()) {
    printf("[LAYOUT MISMATCH] field=fdb_default_kv_node.value_len offset c=%zu rust=%zu\n", offsetof(struct fdb_default_kv_node, value_len), rust_offsetof_fdb_default_kv_node_value_len());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_default_kv_node field=value_len offset=%zu\n", offsetof(struct fdb_default_kv_node, value_len));
  }
  if (sizeof(struct fdb_kv) != rust_sizeof_fdb_kv()) {
    printf("[LAYOUT MISMATCH] struct=fdb_kv sizeof c=%zu rust=%zu\n", sizeof(struct fdb_kv), rust_sizeof_fdb_kv());
    failures++;
  }
  if (_Alignof(struct fdb_kv) != rust_alignof_fdb_kv()) {
    printf("[LAYOUT MISMATCH] struct=fdb_kv alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_kv), rust_alignof_fdb_kv());
    failures++;
  }
  if (sizeof(struct fdb_kv) == rust_sizeof_fdb_kv() && _Alignof(struct fdb_kv) == rust_alignof_fdb_kv()) {
    printf("[LAYOUT OK] struct=fdb_kv sizeof=%zu alignof=%zu\n", sizeof(struct fdb_kv), (size_t)_Alignof(struct fdb_kv));
  }
  if (rust_offsetof_fdb_kv_status() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.status offset c=%zu rust=missing\n", offsetof(struct fdb_kv, status));
    printf("possible_reason=active macro added field status that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv, status) != rust_offsetof_fdb_kv_status()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.status offset c=%zu rust=%zu\n", offsetof(struct fdb_kv, status), rust_offsetof_fdb_kv_status());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv field=status offset=%zu\n", offsetof(struct fdb_kv, status));
  }
  if (rust_offsetof_fdb_kv_crc_is_ok() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.crc_is_ok offset c=%zu rust=missing\n", offsetof(struct fdb_kv, crc_is_ok));
    printf("possible_reason=active macro added field crc_is_ok that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv, crc_is_ok) != rust_offsetof_fdb_kv_crc_is_ok()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.crc_is_ok offset c=%zu rust=%zu\n", offsetof(struct fdb_kv, crc_is_ok), rust_offsetof_fdb_kv_crc_is_ok());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv field=crc_is_ok offset=%zu\n", offsetof(struct fdb_kv, crc_is_ok));
  }
  if (rust_offsetof_fdb_kv_name_len() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.name_len offset c=%zu rust=missing\n", offsetof(struct fdb_kv, name_len));
    printf("possible_reason=active macro added field name_len that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv, name_len) != rust_offsetof_fdb_kv_name_len()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.name_len offset c=%zu rust=%zu\n", offsetof(struct fdb_kv, name_len), rust_offsetof_fdb_kv_name_len());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv field=name_len offset=%zu\n", offsetof(struct fdb_kv, name_len));
  }
  if (rust_offsetof_fdb_kv_magic() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.magic offset c=%zu rust=missing\n", offsetof(struct fdb_kv, magic));
    printf("possible_reason=active macro added field magic that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv, magic) != rust_offsetof_fdb_kv_magic()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.magic offset c=%zu rust=%zu\n", offsetof(struct fdb_kv, magic), rust_offsetof_fdb_kv_magic());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv field=magic offset=%zu\n", offsetof(struct fdb_kv, magic));
  }
  if (rust_offsetof_fdb_kv_len() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.len offset c=%zu rust=missing\n", offsetof(struct fdb_kv, len));
    printf("possible_reason=active macro added field len that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv, len) != rust_offsetof_fdb_kv_len()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.len offset c=%zu rust=%zu\n", offsetof(struct fdb_kv, len), rust_offsetof_fdb_kv_len());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv field=len offset=%zu\n", offsetof(struct fdb_kv, len));
  }
  if (rust_offsetof_fdb_kv_value_len() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.value_len offset c=%zu rust=missing\n", offsetof(struct fdb_kv, value_len));
    printf("possible_reason=active macro added field value_len that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv, value_len) != rust_offsetof_fdb_kv_value_len()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.value_len offset c=%zu rust=%zu\n", offsetof(struct fdb_kv, value_len), rust_offsetof_fdb_kv_value_len());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv field=value_len offset=%zu\n", offsetof(struct fdb_kv, value_len));
  }
  if (rust_offsetof_fdb_kv_name() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.name offset c=%zu rust=missing\n", offsetof(struct fdb_kv, name));
    printf("possible_reason=active macro added field name that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv, name) != rust_offsetof_fdb_kv_name()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.name offset c=%zu rust=%zu\n", offsetof(struct fdb_kv, name), rust_offsetof_fdb_kv_name());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv field=name offset=%zu\n", offsetof(struct fdb_kv, name));
  }
  if (rust_offsetof_fdb_kv_addr() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.addr offset c=%zu rust=missing\n", offsetof(struct fdb_kv, addr));
    printf("possible_reason=active macro added field addr that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv, addr) != rust_offsetof_fdb_kv_addr()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv.addr offset c=%zu rust=%zu\n", offsetof(struct fdb_kv, addr), rust_offsetof_fdb_kv_addr());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv field=addr offset=%zu\n", offsetof(struct fdb_kv, addr));
  }
  if (sizeof(struct fdb_kv_iterator) != rust_sizeof_fdb_kv_iterator()) {
    printf("[LAYOUT MISMATCH] struct=fdb_kv_iterator sizeof c=%zu rust=%zu\n", sizeof(struct fdb_kv_iterator), rust_sizeof_fdb_kv_iterator());
    failures++;
  }
  if (_Alignof(struct fdb_kv_iterator) != rust_alignof_fdb_kv_iterator()) {
    printf("[LAYOUT MISMATCH] struct=fdb_kv_iterator alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_kv_iterator), rust_alignof_fdb_kv_iterator());
    failures++;
  }
  if (sizeof(struct fdb_kv_iterator) == rust_sizeof_fdb_kv_iterator() && _Alignof(struct fdb_kv_iterator) == rust_alignof_fdb_kv_iterator()) {
    printf("[LAYOUT OK] struct=fdb_kv_iterator sizeof=%zu alignof=%zu\n", sizeof(struct fdb_kv_iterator), (size_t)_Alignof(struct fdb_kv_iterator));
  }
  if (rust_offsetof_fdb_kv_iterator_curr_kv() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.curr_kv offset c=%zu rust=missing\n", offsetof(struct fdb_kv_iterator, curr_kv));
    printf("possible_reason=active macro added field curr_kv that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv_iterator, curr_kv) != rust_offsetof_fdb_kv_iterator_curr_kv()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.curr_kv offset c=%zu rust=%zu\n", offsetof(struct fdb_kv_iterator, curr_kv), rust_offsetof_fdb_kv_iterator_curr_kv());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv_iterator field=curr_kv offset=%zu\n", offsetof(struct fdb_kv_iterator, curr_kv));
  }
  if (rust_offsetof_fdb_kv_iterator_iterated_cnt() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.iterated_cnt offset c=%zu rust=missing\n", offsetof(struct fdb_kv_iterator, iterated_cnt));
    printf("possible_reason=active macro added field iterated_cnt that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv_iterator, iterated_cnt) != rust_offsetof_fdb_kv_iterator_iterated_cnt()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.iterated_cnt offset c=%zu rust=%zu\n", offsetof(struct fdb_kv_iterator, iterated_cnt), rust_offsetof_fdb_kv_iterator_iterated_cnt());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv_iterator field=iterated_cnt offset=%zu\n", offsetof(struct fdb_kv_iterator, iterated_cnt));
  }
  if (rust_offsetof_fdb_kv_iterator_iterated_obj_bytes() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.iterated_obj_bytes offset c=%zu rust=missing\n", offsetof(struct fdb_kv_iterator, iterated_obj_bytes));
    printf("possible_reason=active macro added field iterated_obj_bytes that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv_iterator, iterated_obj_bytes) != rust_offsetof_fdb_kv_iterator_iterated_obj_bytes()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.iterated_obj_bytes offset c=%zu rust=%zu\n", offsetof(struct fdb_kv_iterator, iterated_obj_bytes), rust_offsetof_fdb_kv_iterator_iterated_obj_bytes());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv_iterator field=iterated_obj_bytes offset=%zu\n", offsetof(struct fdb_kv_iterator, iterated_obj_bytes));
  }
  if (rust_offsetof_fdb_kv_iterator_iterated_value_bytes() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.iterated_value_bytes offset c=%zu rust=missing\n", offsetof(struct fdb_kv_iterator, iterated_value_bytes));
    printf("possible_reason=active macro added field iterated_value_bytes that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv_iterator, iterated_value_bytes) != rust_offsetof_fdb_kv_iterator_iterated_value_bytes()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.iterated_value_bytes offset c=%zu rust=%zu\n", offsetof(struct fdb_kv_iterator, iterated_value_bytes), rust_offsetof_fdb_kv_iterator_iterated_value_bytes());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv_iterator field=iterated_value_bytes offset=%zu\n", offsetof(struct fdb_kv_iterator, iterated_value_bytes));
  }
  if (rust_offsetof_fdb_kv_iterator_sector_addr() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.sector_addr offset c=%zu rust=missing\n", offsetof(struct fdb_kv_iterator, sector_addr));
    printf("possible_reason=active macro added field sector_addr that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv_iterator, sector_addr) != rust_offsetof_fdb_kv_iterator_sector_addr()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.sector_addr offset c=%zu rust=%zu\n", offsetof(struct fdb_kv_iterator, sector_addr), rust_offsetof_fdb_kv_iterator_sector_addr());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv_iterator field=sector_addr offset=%zu\n", offsetof(struct fdb_kv_iterator, sector_addr));
  }
  if (rust_offsetof_fdb_kv_iterator_traversed_len() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.traversed_len offset c=%zu rust=missing\n", offsetof(struct fdb_kv_iterator, traversed_len));
    printf("possible_reason=active macro added field traversed_len that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kv_iterator, traversed_len) != rust_offsetof_fdb_kv_iterator_traversed_len()) {
    printf("[LAYOUT MISMATCH] field=fdb_kv_iterator.traversed_len offset c=%zu rust=%zu\n", offsetof(struct fdb_kv_iterator, traversed_len), rust_offsetof_fdb_kv_iterator_traversed_len());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kv_iterator field=traversed_len offset=%zu\n", offsetof(struct fdb_kv_iterator, traversed_len));
  }
  if (sizeof(struct fdb_kvdb) != rust_sizeof_fdb_kvdb()) {
    printf("[LAYOUT MISMATCH] struct=fdb_kvdb sizeof c=%zu rust=%zu\n", sizeof(struct fdb_kvdb), rust_sizeof_fdb_kvdb());
    failures++;
  }
  if (_Alignof(struct fdb_kvdb) != rust_alignof_fdb_kvdb()) {
    printf("[LAYOUT MISMATCH] struct=fdb_kvdb alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_kvdb), rust_alignof_fdb_kvdb());
    failures++;
  }
  if (sizeof(struct fdb_kvdb) == rust_sizeof_fdb_kvdb() && _Alignof(struct fdb_kvdb) == rust_alignof_fdb_kvdb()) {
    printf("[LAYOUT OK] struct=fdb_kvdb sizeof=%zu alignof=%zu\n", sizeof(struct fdb_kvdb), (size_t)_Alignof(struct fdb_kvdb));
  }
  if (rust_offsetof_fdb_kvdb_parent() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.parent offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, parent));
    printf("possible_reason=active macro added field parent that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, parent) != rust_offsetof_fdb_kvdb_parent()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.parent offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, parent), rust_offsetof_fdb_kvdb_parent());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=parent offset=%zu\n", offsetof(struct fdb_kvdb, parent));
  }
  if (rust_offsetof_fdb_kvdb_default_kvs() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.default_kvs offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, default_kvs));
    printf("possible_reason=active macro added field default_kvs that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, default_kvs) != rust_offsetof_fdb_kvdb_default_kvs()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.default_kvs offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, default_kvs), rust_offsetof_fdb_kvdb_default_kvs());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=default_kvs offset=%zu\n", offsetof(struct fdb_kvdb, default_kvs));
  }
  if (rust_offsetof_fdb_kvdb_gc_request() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.gc_request offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, gc_request));
    printf("possible_reason=active macro added field gc_request that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, gc_request) != rust_offsetof_fdb_kvdb_gc_request()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.gc_request offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, gc_request), rust_offsetof_fdb_kvdb_gc_request());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=gc_request offset=%zu\n", offsetof(struct fdb_kvdb, gc_request));
  }
  if (rust_offsetof_fdb_kvdb_in_recovery_check() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.in_recovery_check offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, in_recovery_check));
    printf("possible_reason=active macro added field in_recovery_check that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, in_recovery_check) != rust_offsetof_fdb_kvdb_in_recovery_check()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.in_recovery_check offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, in_recovery_check), rust_offsetof_fdb_kvdb_in_recovery_check());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=in_recovery_check offset=%zu\n", offsetof(struct fdb_kvdb, in_recovery_check));
  }
  if (rust_offsetof_fdb_kvdb_cur_kv() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.cur_kv offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, cur_kv));
    printf("possible_reason=active macro added field cur_kv that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, cur_kv) != rust_offsetof_fdb_kvdb_cur_kv()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.cur_kv offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, cur_kv), rust_offsetof_fdb_kvdb_cur_kv());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=cur_kv offset=%zu\n", offsetof(struct fdb_kvdb, cur_kv));
  }
  if (rust_offsetof_fdb_kvdb_cur_sector() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.cur_sector offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, cur_sector));
    printf("possible_reason=active macro added field cur_sector that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, cur_sector) != rust_offsetof_fdb_kvdb_cur_sector()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.cur_sector offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, cur_sector), rust_offsetof_fdb_kvdb_cur_sector());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=cur_sector offset=%zu\n", offsetof(struct fdb_kvdb, cur_sector));
  }
  if (rust_offsetof_fdb_kvdb_last_is_complete_del() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.last_is_complete_del offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, last_is_complete_del));
    printf("possible_reason=active macro added field last_is_complete_del that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, last_is_complete_del) != rust_offsetof_fdb_kvdb_last_is_complete_del()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.last_is_complete_del offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, last_is_complete_del), rust_offsetof_fdb_kvdb_last_is_complete_del());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=last_is_complete_del offset=%zu\n", offsetof(struct fdb_kvdb, last_is_complete_del));
  }
  if (rust_offsetof_fdb_kvdb_kv_cache_table() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.kv_cache_table offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, kv_cache_table));
    printf("possible_reason=active macro added field kv_cache_table that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, kv_cache_table) != rust_offsetof_fdb_kvdb_kv_cache_table()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.kv_cache_table offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, kv_cache_table), rust_offsetof_fdb_kvdb_kv_cache_table());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=kv_cache_table offset=%zu\n", offsetof(struct fdb_kvdb, kv_cache_table));
  }
  if (rust_offsetof_fdb_kvdb_sector_cache_table() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.sector_cache_table offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, sector_cache_table));
    printf("possible_reason=active macro added field sector_cache_table that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, sector_cache_table) != rust_offsetof_fdb_kvdb_sector_cache_table()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.sector_cache_table offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, sector_cache_table), rust_offsetof_fdb_kvdb_sector_cache_table());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=sector_cache_table offset=%zu\n", offsetof(struct fdb_kvdb, sector_cache_table));
  }
  if (rust_offsetof_fdb_kvdb_user_data() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.user_data offset c=%zu rust=missing\n", offsetof(struct fdb_kvdb, user_data));
    printf("possible_reason=active macro added field user_data that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_kvdb, user_data) != rust_offsetof_fdb_kvdb_user_data()) {
    printf("[LAYOUT MISMATCH] field=fdb_kvdb.user_data offset c=%zu rust=%zu\n", offsetof(struct fdb_kvdb, user_data), rust_offsetof_fdb_kvdb_user_data());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_kvdb field=user_data offset=%zu\n", offsetof(struct fdb_kvdb, user_data));
  }
  if (sizeof(struct fdb_tsdb) != rust_sizeof_fdb_tsdb()) {
    printf("[LAYOUT MISMATCH] struct=fdb_tsdb sizeof c=%zu rust=%zu\n", sizeof(struct fdb_tsdb), rust_sizeof_fdb_tsdb());
    failures++;
  }
  if (_Alignof(struct fdb_tsdb) != rust_alignof_fdb_tsdb()) {
    printf("[LAYOUT MISMATCH] struct=fdb_tsdb alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_tsdb), rust_alignof_fdb_tsdb());
    failures++;
  }
  if (sizeof(struct fdb_tsdb) == rust_sizeof_fdb_tsdb() && _Alignof(struct fdb_tsdb) == rust_alignof_fdb_tsdb()) {
    printf("[LAYOUT OK] struct=fdb_tsdb sizeof=%zu alignof=%zu\n", sizeof(struct fdb_tsdb), (size_t)_Alignof(struct fdb_tsdb));
  }
  if (rust_offsetof_fdb_tsdb_parent() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.parent offset c=%zu rust=missing\n", offsetof(struct fdb_tsdb, parent));
    printf("possible_reason=active macro added field parent that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsdb, parent) != rust_offsetof_fdb_tsdb_parent()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.parent offset c=%zu rust=%zu\n", offsetof(struct fdb_tsdb, parent), rust_offsetof_fdb_tsdb_parent());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsdb field=parent offset=%zu\n", offsetof(struct fdb_tsdb, parent));
  }
  if (rust_offsetof_fdb_tsdb_cur_sec() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.cur_sec offset c=%zu rust=missing\n", offsetof(struct fdb_tsdb, cur_sec));
    printf("possible_reason=active macro added field cur_sec that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsdb, cur_sec) != rust_offsetof_fdb_tsdb_cur_sec()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.cur_sec offset c=%zu rust=%zu\n", offsetof(struct fdb_tsdb, cur_sec), rust_offsetof_fdb_tsdb_cur_sec());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsdb field=cur_sec offset=%zu\n", offsetof(struct fdb_tsdb, cur_sec));
  }
  if (rust_offsetof_fdb_tsdb_last_time() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.last_time offset c=%zu rust=missing\n", offsetof(struct fdb_tsdb, last_time));
    printf("possible_reason=active macro added field last_time that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsdb, last_time) != rust_offsetof_fdb_tsdb_last_time()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.last_time offset c=%zu rust=%zu\n", offsetof(struct fdb_tsdb, last_time), rust_offsetof_fdb_tsdb_last_time());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsdb field=last_time offset=%zu\n", offsetof(struct fdb_tsdb, last_time));
  }
  if (rust_offsetof_fdb_tsdb_get_time() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.get_time offset c=%zu rust=missing\n", offsetof(struct fdb_tsdb, get_time));
    printf("possible_reason=active macro added field get_time that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsdb, get_time) != rust_offsetof_fdb_tsdb_get_time()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.get_time offset c=%zu rust=%zu\n", offsetof(struct fdb_tsdb, get_time), rust_offsetof_fdb_tsdb_get_time());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsdb field=get_time offset=%zu\n", offsetof(struct fdb_tsdb, get_time));
  }
  if (rust_offsetof_fdb_tsdb_max_len() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.max_len offset c=%zu rust=missing\n", offsetof(struct fdb_tsdb, max_len));
    printf("possible_reason=active macro added field max_len that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsdb, max_len) != rust_offsetof_fdb_tsdb_max_len()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.max_len offset c=%zu rust=%zu\n", offsetof(struct fdb_tsdb, max_len), rust_offsetof_fdb_tsdb_max_len());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsdb field=max_len offset=%zu\n", offsetof(struct fdb_tsdb, max_len));
  }
  if (rust_offsetof_fdb_tsdb_rollover() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.rollover offset c=%zu rust=missing\n", offsetof(struct fdb_tsdb, rollover));
    printf("possible_reason=active macro added field rollover that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsdb, rollover) != rust_offsetof_fdb_tsdb_rollover()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.rollover offset c=%zu rust=%zu\n", offsetof(struct fdb_tsdb, rollover), rust_offsetof_fdb_tsdb_rollover());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsdb field=rollover offset=%zu\n", offsetof(struct fdb_tsdb, rollover));
  }
  if (rust_offsetof_fdb_tsdb_user_data() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.user_data offset c=%zu rust=missing\n", offsetof(struct fdb_tsdb, user_data));
    printf("possible_reason=active macro added field user_data that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsdb, user_data) != rust_offsetof_fdb_tsdb_user_data()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsdb.user_data offset c=%zu rust=%zu\n", offsetof(struct fdb_tsdb, user_data), rust_offsetof_fdb_tsdb_user_data());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsdb field=user_data offset=%zu\n", offsetof(struct fdb_tsdb, user_data));
  }
  if (sizeof(struct fdb_tsl) != rust_sizeof_fdb_tsl()) {
    printf("[LAYOUT MISMATCH] struct=fdb_tsl sizeof c=%zu rust=%zu\n", sizeof(struct fdb_tsl), rust_sizeof_fdb_tsl());
    failures++;
  }
  if (_Alignof(struct fdb_tsl) != rust_alignof_fdb_tsl()) {
    printf("[LAYOUT MISMATCH] struct=fdb_tsl alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct fdb_tsl), rust_alignof_fdb_tsl());
    failures++;
  }
  if (sizeof(struct fdb_tsl) == rust_sizeof_fdb_tsl() && _Alignof(struct fdb_tsl) == rust_alignof_fdb_tsl()) {
    printf("[LAYOUT OK] struct=fdb_tsl sizeof=%zu alignof=%zu\n", sizeof(struct fdb_tsl), (size_t)_Alignof(struct fdb_tsl));
  }
  if (rust_offsetof_fdb_tsl_status() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsl.status offset c=%zu rust=missing\n", offsetof(struct fdb_tsl, status));
    printf("possible_reason=active macro added field status that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsl, status) != rust_offsetof_fdb_tsl_status()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsl.status offset c=%zu rust=%zu\n", offsetof(struct fdb_tsl, status), rust_offsetof_fdb_tsl_status());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsl field=status offset=%zu\n", offsetof(struct fdb_tsl, status));
  }
  if (rust_offsetof_fdb_tsl_time() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsl.time offset c=%zu rust=missing\n", offsetof(struct fdb_tsl, time));
    printf("possible_reason=active macro added field time that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsl, time) != rust_offsetof_fdb_tsl_time()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsl.time offset c=%zu rust=%zu\n", offsetof(struct fdb_tsl, time), rust_offsetof_fdb_tsl_time());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsl field=time offset=%zu\n", offsetof(struct fdb_tsl, time));
  }
  if (rust_offsetof_fdb_tsl_log_len() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsl.log_len offset c=%zu rust=missing\n", offsetof(struct fdb_tsl, log_len));
    printf("possible_reason=active macro added field log_len that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsl, log_len) != rust_offsetof_fdb_tsl_log_len()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsl.log_len offset c=%zu rust=%zu\n", offsetof(struct fdb_tsl, log_len), rust_offsetof_fdb_tsl_log_len());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsl field=log_len offset=%zu\n", offsetof(struct fdb_tsl, log_len));
  }
  if (rust_offsetof_fdb_tsl_addr() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=fdb_tsl.addr offset c=%zu rust=missing\n", offsetof(struct fdb_tsl, addr));
    printf("possible_reason=active macro added field addr that Rust omitted\n");
    failures++;
  } else if (offsetof(struct fdb_tsl, addr) != rust_offsetof_fdb_tsl_addr()) {
    printf("[LAYOUT MISMATCH] field=fdb_tsl.addr offset c=%zu rust=%zu\n", offsetof(struct fdb_tsl, addr), rust_offsetof_fdb_tsl_addr());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=fdb_tsl field=addr offset=%zu\n", offsetof(struct fdb_tsl, addr));
  }
  if (sizeof(struct kv_cache_node) != rust_sizeof_kv_cache_node()) {
    printf("[LAYOUT MISMATCH] struct=kv_cache_node sizeof c=%zu rust=%zu\n", sizeof(struct kv_cache_node), rust_sizeof_kv_cache_node());
    failures++;
  }
  if (_Alignof(struct kv_cache_node) != rust_alignof_kv_cache_node()) {
    printf("[LAYOUT MISMATCH] struct=kv_cache_node alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct kv_cache_node), rust_alignof_kv_cache_node());
    failures++;
  }
  if (sizeof(struct kv_cache_node) == rust_sizeof_kv_cache_node() && _Alignof(struct kv_cache_node) == rust_alignof_kv_cache_node()) {
    printf("[LAYOUT OK] struct=kv_cache_node sizeof=%zu alignof=%zu\n", sizeof(struct kv_cache_node), (size_t)_Alignof(struct kv_cache_node));
  }
  if (rust_offsetof_kv_cache_node_name_crc() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kv_cache_node.name_crc offset c=%zu rust=missing\n", offsetof(struct kv_cache_node, name_crc));
    printf("possible_reason=active macro added field name_crc that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kv_cache_node, name_crc) != rust_offsetof_kv_cache_node_name_crc()) {
    printf("[LAYOUT MISMATCH] field=kv_cache_node.name_crc offset c=%zu rust=%zu\n", offsetof(struct kv_cache_node, name_crc), rust_offsetof_kv_cache_node_name_crc());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kv_cache_node field=name_crc offset=%zu\n", offsetof(struct kv_cache_node, name_crc));
  }
  if (rust_offsetof_kv_cache_node_active() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kv_cache_node.active offset c=%zu rust=missing\n", offsetof(struct kv_cache_node, active));
    printf("possible_reason=active macro added field active that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kv_cache_node, active) != rust_offsetof_kv_cache_node_active()) {
    printf("[LAYOUT MISMATCH] field=kv_cache_node.active offset c=%zu rust=%zu\n", offsetof(struct kv_cache_node, active), rust_offsetof_kv_cache_node_active());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kv_cache_node field=active offset=%zu\n", offsetof(struct kv_cache_node, active));
  }
  if (rust_offsetof_kv_cache_node_addr() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kv_cache_node.addr offset c=%zu rust=missing\n", offsetof(struct kv_cache_node, addr));
    printf("possible_reason=active macro added field addr that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kv_cache_node, addr) != rust_offsetof_kv_cache_node_addr()) {
    printf("[LAYOUT MISMATCH] field=kv_cache_node.addr offset c=%zu rust=%zu\n", offsetof(struct kv_cache_node, addr), rust_offsetof_kv_cache_node_addr());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kv_cache_node field=addr offset=%zu\n", offsetof(struct kv_cache_node, addr));
  }
  if (sizeof(struct kvdb_sec_info) != rust_sizeof_kvdb_sec_info()) {
    printf("[LAYOUT MISMATCH] struct=kvdb_sec_info sizeof c=%zu rust=%zu\n", sizeof(struct kvdb_sec_info), rust_sizeof_kvdb_sec_info());
    failures++;
  }
  if (_Alignof(struct kvdb_sec_info) != rust_alignof_kvdb_sec_info()) {
    printf("[LAYOUT MISMATCH] struct=kvdb_sec_info alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct kvdb_sec_info), rust_alignof_kvdb_sec_info());
    failures++;
  }
  if (sizeof(struct kvdb_sec_info) == rust_sizeof_kvdb_sec_info() && _Alignof(struct kvdb_sec_info) == rust_alignof_kvdb_sec_info()) {
    printf("[LAYOUT OK] struct=kvdb_sec_info sizeof=%zu alignof=%zu\n", sizeof(struct kvdb_sec_info), (size_t)_Alignof(struct kvdb_sec_info));
  }
  if (rust_offsetof_kvdb_sec_info_check_ok() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.check_ok offset c=%zu rust=missing\n", offsetof(struct kvdb_sec_info, check_ok));
    printf("possible_reason=active macro added field check_ok that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kvdb_sec_info, check_ok) != rust_offsetof_kvdb_sec_info_check_ok()) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.check_ok offset c=%zu rust=%zu\n", offsetof(struct kvdb_sec_info, check_ok), rust_offsetof_kvdb_sec_info_check_ok());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kvdb_sec_info field=check_ok offset=%zu\n", offsetof(struct kvdb_sec_info, check_ok));
  }
  if (rust_offsetof_kvdb_sec_info_status() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.status offset c=%zu rust=missing\n", offsetof(struct kvdb_sec_info, status));
    printf("possible_reason=active macro added field status that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kvdb_sec_info, status) != rust_offsetof_kvdb_sec_info_status()) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.status offset c=%zu rust=%zu\n", offsetof(struct kvdb_sec_info, status), rust_offsetof_kvdb_sec_info_status());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kvdb_sec_info field=status offset=%zu\n", offsetof(struct kvdb_sec_info, status));
  }
  if (rust_offsetof_kvdb_sec_info_addr() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.addr offset c=%zu rust=missing\n", offsetof(struct kvdb_sec_info, addr));
    printf("possible_reason=active macro added field addr that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kvdb_sec_info, addr) != rust_offsetof_kvdb_sec_info_addr()) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.addr offset c=%zu rust=%zu\n", offsetof(struct kvdb_sec_info, addr), rust_offsetof_kvdb_sec_info_addr());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kvdb_sec_info field=addr offset=%zu\n", offsetof(struct kvdb_sec_info, addr));
  }
  if (rust_offsetof_kvdb_sec_info_magic() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.magic offset c=%zu rust=missing\n", offsetof(struct kvdb_sec_info, magic));
    printf("possible_reason=active macro added field magic that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kvdb_sec_info, magic) != rust_offsetof_kvdb_sec_info_magic()) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.magic offset c=%zu rust=%zu\n", offsetof(struct kvdb_sec_info, magic), rust_offsetof_kvdb_sec_info_magic());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kvdb_sec_info field=magic offset=%zu\n", offsetof(struct kvdb_sec_info, magic));
  }
  if (rust_offsetof_kvdb_sec_info_combined() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.combined offset c=%zu rust=missing\n", offsetof(struct kvdb_sec_info, combined));
    printf("possible_reason=active macro added field combined that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kvdb_sec_info, combined) != rust_offsetof_kvdb_sec_info_combined()) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.combined offset c=%zu rust=%zu\n", offsetof(struct kvdb_sec_info, combined), rust_offsetof_kvdb_sec_info_combined());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kvdb_sec_info field=combined offset=%zu\n", offsetof(struct kvdb_sec_info, combined));
  }
  if (rust_offsetof_kvdb_sec_info_remain() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.remain offset c=%zu rust=missing\n", offsetof(struct kvdb_sec_info, remain));
    printf("possible_reason=active macro added field remain that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kvdb_sec_info, remain) != rust_offsetof_kvdb_sec_info_remain()) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.remain offset c=%zu rust=%zu\n", offsetof(struct kvdb_sec_info, remain), rust_offsetof_kvdb_sec_info_remain());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kvdb_sec_info field=remain offset=%zu\n", offsetof(struct kvdb_sec_info, remain));
  }
  if (rust_offsetof_kvdb_sec_info_empty_kv() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.empty_kv offset c=%zu rust=missing\n", offsetof(struct kvdb_sec_info, empty_kv));
    printf("possible_reason=active macro added field empty_kv that Rust omitted\n");
    failures++;
  } else if (offsetof(struct kvdb_sec_info, empty_kv) != rust_offsetof_kvdb_sec_info_empty_kv()) {
    printf("[LAYOUT MISMATCH] field=kvdb_sec_info.empty_kv offset c=%zu rust=%zu\n", offsetof(struct kvdb_sec_info, empty_kv), rust_offsetof_kvdb_sec_info_empty_kv());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=kvdb_sec_info field=empty_kv offset=%zu\n", offsetof(struct kvdb_sec_info, empty_kv));
  }
  if (sizeof(struct tsdb_sec_info) != rust_sizeof_tsdb_sec_info()) {
    printf("[LAYOUT MISMATCH] struct=tsdb_sec_info sizeof c=%zu rust=%zu\n", sizeof(struct tsdb_sec_info), rust_sizeof_tsdb_sec_info());
    failures++;
  }
  if (_Alignof(struct tsdb_sec_info) != rust_alignof_tsdb_sec_info()) {
    printf("[LAYOUT MISMATCH] struct=tsdb_sec_info alignof c=%zu rust=%zu\n", (size_t)_Alignof(struct tsdb_sec_info), rust_alignof_tsdb_sec_info());
    failures++;
  }
  if (sizeof(struct tsdb_sec_info) == rust_sizeof_tsdb_sec_info() && _Alignof(struct tsdb_sec_info) == rust_alignof_tsdb_sec_info()) {
    printf("[LAYOUT OK] struct=tsdb_sec_info sizeof=%zu alignof=%zu\n", sizeof(struct tsdb_sec_info), (size_t)_Alignof(struct tsdb_sec_info));
  }
  if (rust_offsetof_tsdb_sec_info_check_ok() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.check_ok offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, check_ok));
    printf("possible_reason=active macro added field check_ok that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, check_ok) != rust_offsetof_tsdb_sec_info_check_ok()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.check_ok offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, check_ok), rust_offsetof_tsdb_sec_info_check_ok());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=check_ok offset=%zu\n", offsetof(struct tsdb_sec_info, check_ok));
  }
  if (rust_offsetof_tsdb_sec_info_status() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.status offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, status));
    printf("possible_reason=active macro added field status that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, status) != rust_offsetof_tsdb_sec_info_status()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.status offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, status), rust_offsetof_tsdb_sec_info_status());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=status offset=%zu\n", offsetof(struct tsdb_sec_info, status));
  }
  if (rust_offsetof_tsdb_sec_info_addr() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.addr offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, addr));
    printf("possible_reason=active macro added field addr that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, addr) != rust_offsetof_tsdb_sec_info_addr()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.addr offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, addr), rust_offsetof_tsdb_sec_info_addr());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=addr offset=%zu\n", offsetof(struct tsdb_sec_info, addr));
  }
  if (rust_offsetof_tsdb_sec_info_magic() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.magic offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, magic));
    printf("possible_reason=active macro added field magic that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, magic) != rust_offsetof_tsdb_sec_info_magic()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.magic offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, magic), rust_offsetof_tsdb_sec_info_magic());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=magic offset=%zu\n", offsetof(struct tsdb_sec_info, magic));
  }
  if (rust_offsetof_tsdb_sec_info_start_time() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.start_time offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, start_time));
    printf("possible_reason=active macro added field start_time that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, start_time) != rust_offsetof_tsdb_sec_info_start_time()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.start_time offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, start_time), rust_offsetof_tsdb_sec_info_start_time());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=start_time offset=%zu\n", offsetof(struct tsdb_sec_info, start_time));
  }
  if (rust_offsetof_tsdb_sec_info_end_time() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.end_time offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, end_time));
    printf("possible_reason=active macro added field end_time that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, end_time) != rust_offsetof_tsdb_sec_info_end_time()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.end_time offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, end_time), rust_offsetof_tsdb_sec_info_end_time());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=end_time offset=%zu\n", offsetof(struct tsdb_sec_info, end_time));
  }
  if (rust_offsetof_tsdb_sec_info_end_idx() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.end_idx offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, end_idx));
    printf("possible_reason=active macro added field end_idx that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, end_idx) != rust_offsetof_tsdb_sec_info_end_idx()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.end_idx offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, end_idx), rust_offsetof_tsdb_sec_info_end_idx());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=end_idx offset=%zu\n", offsetof(struct tsdb_sec_info, end_idx));
  }
  if (rust_offsetof_tsdb_sec_info_end_info_stat() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.end_info_stat offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, end_info_stat));
    printf("possible_reason=active macro added field end_info_stat that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, end_info_stat) != rust_offsetof_tsdb_sec_info_end_info_stat()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.end_info_stat offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, end_info_stat), rust_offsetof_tsdb_sec_info_end_info_stat());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=end_info_stat offset=%zu\n", offsetof(struct tsdb_sec_info, end_info_stat));
  }
  if (rust_offsetof_tsdb_sec_info_remain() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.remain offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, remain));
    printf("possible_reason=active macro added field remain that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, remain) != rust_offsetof_tsdb_sec_info_remain()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.remain offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, remain), rust_offsetof_tsdb_sec_info_remain());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=remain offset=%zu\n", offsetof(struct tsdb_sec_info, remain));
  }
  if (rust_offsetof_tsdb_sec_info_empty_idx() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.empty_idx offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, empty_idx));
    printf("possible_reason=active macro added field empty_idx that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, empty_idx) != rust_offsetof_tsdb_sec_info_empty_idx()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.empty_idx offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, empty_idx), rust_offsetof_tsdb_sec_info_empty_idx());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=empty_idx offset=%zu\n", offsetof(struct tsdb_sec_info, empty_idx));
  }
  if (rust_offsetof_tsdb_sec_info_empty_data() == (size_t)-1) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.empty_data offset c=%zu rust=missing\n", offsetof(struct tsdb_sec_info, empty_data));
    printf("possible_reason=active macro added field empty_data that Rust omitted\n");
    failures++;
  } else if (offsetof(struct tsdb_sec_info, empty_data) != rust_offsetof_tsdb_sec_info_empty_data()) {
    printf("[LAYOUT MISMATCH] field=tsdb_sec_info.empty_data offset c=%zu rust=%zu\n", offsetof(struct tsdb_sec_info, empty_data), rust_offsetof_tsdb_sec_info_empty_data());
    failures++;
  } else {
    printf("[LAYOUT OK] struct=tsdb_sec_info field=empty_data offset=%zu\n", offsetof(struct tsdb_sec_info, empty_data));
  }
  if (failures) {
    printf("[LAYOUT CHECK] fail\n");
    return 1;
  }
  printf("[LAYOUT CHECK] pass\n");
  return 0;
}
