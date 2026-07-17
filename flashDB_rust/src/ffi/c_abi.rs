//! Typed C ABI facade generated from rust_api_design.json.

#![allow(unused_variables)]

use super::c_types::*;

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_blob_make
#[no_mangle]
pub extern "C" fn fdb_blob_make(
    blob: *mut FdbBlob,
    value_buf: *const std::ffi::c_void,
    buf_len: usize,
) -> *mut FdbBlob {
    std::ptr::null_mut()
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_blob_read
#[no_mangle]
pub extern "C" fn fdb_blob_read(db: *mut FdbDb, blob: *mut FdbBlob) -> usize {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_calc_crc32
#[no_mangle]
pub extern "C" fn fdb_calc_crc32(crc: u32, buf: *const std::ffi::c_void, size: usize) -> u32 {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_del
#[no_mangle]
pub extern "C" fn fdb_kv_del(db: *mut FdbKvdb, key: *const std::ffi::c_char) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_get
#[no_mangle]
pub extern "C" fn fdb_kv_get(
    db: *mut FdbKvdb,
    key: *const std::ffi::c_char,
) -> *mut std::ffi::c_char {
    std::ptr::null_mut()
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_get_blob
#[no_mangle]
pub extern "C" fn fdb_kv_get_blob(
    db: *mut FdbKvdb,
    key: *const std::ffi::c_char,
    blob: *mut FdbBlob,
) -> usize {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_get_obj
#[no_mangle]
pub extern "C" fn fdb_kv_get_obj(
    db: *mut FdbKvdb,
    key: *const std::ffi::c_char,
    kv: *mut FdbKv,
) -> *mut FdbKv {
    std::ptr::null_mut()
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_iterate
#[no_mangle]
pub extern "C" fn fdb_kv_iterate(db: *mut FdbKvdb, itr: *mut FdbKvIterator) -> bool {
    false
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_iterator_init
#[no_mangle]
pub extern "C" fn fdb_kv_iterator_init(
    db: *mut FdbKvdb,
    itr: *mut FdbKvIterator,
) -> *mut FdbKvIterator {
    std::ptr::null_mut()
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_print
#[no_mangle]
pub extern "C" fn fdb_kv_print(db: *mut FdbKvdb) {}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_set
#[no_mangle]
pub extern "C" fn fdb_kv_set(
    db: *mut FdbKvdb,
    key: *const std::ffi::c_char,
    value: *const std::ffi::c_char,
) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_set_blob
#[no_mangle]
pub extern "C" fn fdb_kv_set_blob(
    db: *mut FdbKvdb,
    key: *const std::ffi::c_char,
    blob: *mut FdbBlob,
) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_set_default
#[no_mangle]
pub extern "C" fn fdb_kv_set_default(db: *mut FdbKvdb) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kv_to_blob
#[no_mangle]
pub extern "C" fn fdb_kv_to_blob(kv: *mut FdbKv, blob: *mut FdbBlob) -> *mut FdbBlob {
    std::ptr::null_mut()
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kvdb_check
#[no_mangle]
pub extern "C" fn fdb_kvdb_check(db: *mut FdbKvdb) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kvdb_control
#[no_mangle]
pub extern "C" fn fdb_kvdb_control(
    db: *mut FdbKvdb,
    cmd: std::ffi::c_int,
    arg: *mut std::ffi::c_void,
) {
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kvdb_deinit
#[no_mangle]
pub extern "C" fn fdb_kvdb_deinit(db: *mut FdbKvdb) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_kvdb_init
#[no_mangle]
pub extern "C" fn fdb_kvdb_init(
    db: *mut FdbKvdb,
    name: *const std::ffi::c_char,
    path: *const std::ffi::c_char,
    default_kv: *mut FdbDefaultKv,
    user_data: *mut std::ffi::c_void,
) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsdb_control
#[no_mangle]
pub extern "C" fn fdb_tsdb_control(
    db: *mut FdbTsdb,
    cmd: std::ffi::c_int,
    arg: *mut std::ffi::c_void,
) {
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsdb_deinit
#[no_mangle]
pub extern "C" fn fdb_tsdb_deinit(db: *mut FdbTsdb) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsdb_init
#[no_mangle]
pub extern "C" fn fdb_tsdb_init(
    db: *mut FdbTsdb,
    name: *const std::ffi::c_char,
    path: *const std::ffi::c_char,
    get_time: Option<unsafe extern "C" fn() -> i32>,
    max_len: usize,
    user_data: *mut std::ffi::c_void,
) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_append
#[no_mangle]
pub extern "C" fn fdb_tsl_append(db: *mut FdbTsdb, blob: *mut FdbBlob) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_append_with_ts
#[no_mangle]
pub extern "C" fn fdb_tsl_append_with_ts(
    db: *mut FdbTsdb,
    blob: *mut FdbBlob,
    timestamp: i32,
) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_clean
#[no_mangle]
pub extern "C" fn fdb_tsl_clean(db: *mut FdbTsdb) {}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_iter
#[no_mangle]
pub extern "C" fn fdb_tsl_iter(
    db: *mut FdbTsdb,
    cb: Option<unsafe extern "C" fn(*mut FdbTsl, *mut std::ffi::c_void) -> bool>,
    cb_arg: *mut std::ffi::c_void,
) {
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_iter_by_time
#[no_mangle]
pub extern "C" fn fdb_tsl_iter_by_time(
    db: *mut FdbTsdb,
    from: i32,
    to: i32,
    cb: Option<unsafe extern "C" fn(*mut FdbTsl, *mut std::ffi::c_void) -> bool>,
    cb_arg: *mut std::ffi::c_void,
) {
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_iter_reverse
#[no_mangle]
pub extern "C" fn fdb_tsl_iter_reverse(
    db: *mut FdbTsdb,
    cb: Option<unsafe extern "C" fn(*mut FdbTsl, *mut std::ffi::c_void) -> bool>,
    cb_arg: *mut std::ffi::c_void,
) {
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_max_blob_count
#[no_mangle]
pub extern "C" fn fdb_tsl_max_blob_count(db: *mut FdbTsdb) -> usize {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_query_count
#[no_mangle]
pub extern "C" fn fdb_tsl_query_count(
    db: *mut FdbTsdb,
    from: i32,
    to: i32,
    status: std::ffi::c_int,
) -> usize {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_set_status
#[no_mangle]
pub extern "C" fn fdb_tsl_set_status(
    db: *mut FdbTsdb,
    tsl: *mut FdbTsl,
    status: std::ffi::c_int,
) -> std::ffi::c_int {
    0
}

// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_tsl_to_blob
#[no_mangle]
pub extern "C" fn fdb_tsl_to_blob(tsl: *mut FdbTsl, blob: *mut FdbBlob) -> *mut FdbBlob {
    std::ptr::null_mut()
}
