//! C ABI layout probe exports used by VERIFY_RUST_WITH_C_TESTS.

use super::c_types::*;
use core::mem::offset_of;

pub const RUST_MISSING_FIELD_OFFSET: usize = usize::MAX;

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_blob() -> usize {
    core::mem::size_of::<FdbBlob>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_blob() -> usize {
    core::mem::align_of::<FdbBlob>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_blob_buf() -> usize {
    offset_of!(FdbBlob, buf)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_blob_size() -> usize {
    offset_of!(FdbBlob, size)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_blob_saved() -> usize {
    offset_of!(FdbBlob, saved)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_db() -> usize {
    core::mem::size_of::<FdbDb>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_db() -> usize {
    core::mem::align_of::<FdbDb>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_name() -> usize {
    offset_of!(FdbDb, name)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_type_() -> usize {
    offset_of!(FdbDb, r#type)
}

// The C field is named `type`; Rust needs the raw-identifier spelling above.
// Export the ABI spelling expected by the generated C layout checker as well.
#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_type() -> usize {
    offset_of!(FdbDb, r#type)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_storage() -> usize {
    offset_of!(FdbDb, storage)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_sec_size() -> usize {
    offset_of!(FdbDb, sec_size)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_max_size() -> usize {
    offset_of!(FdbDb, max_size)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_oldest_addr() -> usize {
    offset_of!(FdbDb, oldest_addr)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_init_ok() -> usize {
    offset_of!(FdbDb, init_ok)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_file_mode() -> usize {
    offset_of!(FdbDb, file_mode)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_not_formatable() -> usize {
    offset_of!(FdbDb, not_formatable)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_cur_file_sec() -> usize {
    offset_of!(FdbDb, cur_file_sec)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_cur_file() -> usize {
    offset_of!(FdbDb, cur_file)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_cur_sec() -> usize {
    offset_of!(FdbDb, cur_sec)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_lock() -> usize {
    offset_of!(FdbDb, lock)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_unlock() -> usize {
    offset_of!(FdbDb, unlock)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_db_user_data() -> usize {
    offset_of!(FdbDb, user_data)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_default_kv() -> usize {
    core::mem::size_of::<FdbDefaultKv>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_default_kv() -> usize {
    core::mem::align_of::<FdbDefaultKv>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_default_kv_kvs() -> usize {
    offset_of!(FdbDefaultKv, kvs)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_default_kv_num() -> usize {
    offset_of!(FdbDefaultKv, num)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_default_kv_node() -> usize {
    core::mem::size_of::<FdbDefaultKvNode>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_default_kv_node() -> usize {
    core::mem::align_of::<FdbDefaultKvNode>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_default_kv_node_key() -> usize {
    offset_of!(FdbDefaultKvNode, key)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_default_kv_node_value() -> usize {
    offset_of!(FdbDefaultKvNode, value)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_default_kv_node_value_len() -> usize {
    offset_of!(FdbDefaultKvNode, value_len)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_kv() -> usize {
    core::mem::size_of::<FdbKv>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_kv() -> usize {
    core::mem::align_of::<FdbKv>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_status() -> usize {
    offset_of!(FdbKv, status)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_crc_is_ok() -> usize {
    offset_of!(FdbKv, crc_is_ok)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_name_len() -> usize {
    offset_of!(FdbKv, name_len)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_magic() -> usize {
    offset_of!(FdbKv, magic)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_len() -> usize {
    offset_of!(FdbKv, len)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_value_len() -> usize {
    offset_of!(FdbKv, value_len)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_name() -> usize {
    offset_of!(FdbKv, name)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_addr() -> usize {
    offset_of!(FdbKv, addr)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_kv_iterator() -> usize {
    core::mem::size_of::<FdbKvIterator>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_kv_iterator() -> usize {
    core::mem::align_of::<FdbKvIterator>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_iterator_curr_kv() -> usize {
    offset_of!(FdbKvIterator, curr_kv)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_iterator_iterated_cnt() -> usize {
    offset_of!(FdbKvIterator, iterated_cnt)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_iterator_iterated_obj_bytes() -> usize {
    offset_of!(FdbKvIterator, iterated_obj_bytes)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_iterator_iterated_value_bytes() -> usize {
    offset_of!(FdbKvIterator, iterated_value_bytes)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_iterator_sector_addr() -> usize {
    offset_of!(FdbKvIterator, sector_addr)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kv_iterator_traversed_len() -> usize {
    offset_of!(FdbKvIterator, traversed_len)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_kvdb() -> usize {
    core::mem::size_of::<FdbKvdb>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_kvdb() -> usize {
    core::mem::align_of::<FdbKvdb>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_parent() -> usize {
    offset_of!(FdbKvdb, parent)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_default_kvs() -> usize {
    offset_of!(FdbKvdb, default_kvs)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_gc_request() -> usize {
    offset_of!(FdbKvdb, gc_request)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_in_recovery_check() -> usize {
    offset_of!(FdbKvdb, in_recovery_check)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_cur_kv() -> usize {
    offset_of!(FdbKvdb, cur_kv)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_cur_sector() -> usize {
    offset_of!(FdbKvdb, cur_sector)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_last_is_complete_del() -> usize {
    offset_of!(FdbKvdb, last_is_complete_del)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_kv_cache_table() -> usize {
    offset_of!(FdbKvdb, kv_cache_table)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_sector_cache_table() -> usize {
    offset_of!(FdbKvdb, sector_cache_table)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_kvdb_user_data() -> usize {
    offset_of!(FdbKvdb, user_data)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_tsdb() -> usize {
    core::mem::size_of::<FdbTsdb>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_tsdb() -> usize {
    core::mem::align_of::<FdbTsdb>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsdb_parent() -> usize {
    offset_of!(FdbTsdb, parent)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsdb_cur_sec() -> usize {
    offset_of!(FdbTsdb, cur_sec)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsdb_last_time() -> usize {
    offset_of!(FdbTsdb, last_time)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsdb_get_time() -> usize {
    offset_of!(FdbTsdb, get_time)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsdb_max_len() -> usize {
    offset_of!(FdbTsdb, max_len)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsdb_rollover() -> usize {
    offset_of!(FdbTsdb, rollover)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsdb_user_data() -> usize {
    offset_of!(FdbTsdb, user_data)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_fdb_tsl() -> usize {
    core::mem::size_of::<FdbTsl>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_fdb_tsl() -> usize {
    core::mem::align_of::<FdbTsl>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsl_status() -> usize {
    offset_of!(FdbTsl, status)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsl_time() -> usize {
    offset_of!(FdbTsl, time)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsl_log_len() -> usize {
    offset_of!(FdbTsl, log_len)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_fdb_tsl_addr() -> usize {
    offset_of!(FdbTsl, addr)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_kv_cache_node() -> usize {
    core::mem::size_of::<FdbKvCacheNode>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_kv_cache_node() -> usize {
    core::mem::align_of::<FdbKvCacheNode>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kv_cache_node_name_crc() -> usize {
    offset_of!(FdbKvCacheNode, name_crc)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kv_cache_node_active() -> usize {
    offset_of!(FdbKvCacheNode, active)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kv_cache_node_addr() -> usize {
    offset_of!(FdbKvCacheNode, addr)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_kvdb_sec_info() -> usize {
    core::mem::size_of::<FdbKvdbSecInfo>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_kvdb_sec_info() -> usize {
    core::mem::align_of::<FdbKvdbSecInfo>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kvdb_sec_info_check_ok() -> usize {
    offset_of!(FdbKvdbSecInfo, check_ok)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kvdb_sec_info_status() -> usize {
    offset_of!(FdbKvdbSecInfo, status)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kvdb_sec_info_addr() -> usize {
    offset_of!(FdbKvdbSecInfo, addr)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kvdb_sec_info_magic() -> usize {
    offset_of!(FdbKvdbSecInfo, magic)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kvdb_sec_info_combined() -> usize {
    offset_of!(FdbKvdbSecInfo, combined)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kvdb_sec_info_remain() -> usize {
    offset_of!(FdbKvdbSecInfo, remain)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_kvdb_sec_info_empty_kv() -> usize {
    offset_of!(FdbKvdbSecInfo, empty_kv)
}

#[no_mangle]
pub extern "C" fn rust_sizeof_tsdb_sec_info() -> usize {
    core::mem::size_of::<FdbTsdbSecInfo>()
}

#[no_mangle]
pub extern "C" fn rust_alignof_tsdb_sec_info() -> usize {
    core::mem::align_of::<FdbTsdbSecInfo>()
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_check_ok() -> usize {
    offset_of!(FdbTsdbSecInfo, check_ok)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_status() -> usize {
    offset_of!(FdbTsdbSecInfo, status)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_addr() -> usize {
    offset_of!(FdbTsdbSecInfo, addr)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_magic() -> usize {
    offset_of!(FdbTsdbSecInfo, magic)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_start_time() -> usize {
    offset_of!(FdbTsdbSecInfo, start_time)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_end_time() -> usize {
    offset_of!(FdbTsdbSecInfo, end_time)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_end_idx() -> usize {
    offset_of!(FdbTsdbSecInfo, end_idx)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_end_info_stat() -> usize {
    offset_of!(FdbTsdbSecInfo, end_info_stat)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_remain() -> usize {
    offset_of!(FdbTsdbSecInfo, remain)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_empty_idx() -> usize {
    offset_of!(FdbTsdbSecInfo, empty_idx)
}

#[no_mangle]
pub extern "C" fn rust_offsetof_tsdb_sec_info_empty_data() -> usize {
    offset_of!(FdbTsdbSecInfo, empty_data)
}
