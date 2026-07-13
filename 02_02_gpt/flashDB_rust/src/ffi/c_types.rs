//! Typed C ABI structs generated from rust_api_design.json.

#![allow(non_camel_case_types)]

#[repr(C)]
pub struct FdbBlobSaved {
    pub meta_addr: u32,
    pub addr: u32,
    pub len: u64,
}

#[repr(C)]
pub struct FdbBlob {
    pub buf: *mut std::ffi::c_void,
    pub size: u64,
    pub saved: FdbBlobSaved,
}

#[repr(C)]
pub struct FdbDb {
    pub name: *mut std::ffi::c_char,
    pub r#type: u32,
    pub _pad_0: [u8; 4],
    pub storage: *mut std::ffi::c_char,
    pub sec_size: u32,
    pub max_size: u32,
    pub oldest_addr: u32,
    pub init_ok: u8,
    pub file_mode: u8,
    pub not_formatable: u8,
    pub _pad_1: [u8; 1],
    pub cur_file_sec: u32,
    pub _pad_cur_file: [u8; 4],
    pub cur_file: *mut std::ffi::c_void,
    pub cur_sec: u32,
    pub _pad_2: [u8; 4],
    pub lock: *mut std::ffi::c_void,
    pub unlock: *mut std::ffi::c_void,
    pub user_data: *mut std::ffi::c_void,
}

#[repr(C)]
pub struct FdbDefaultKv {
    pub kvs: u64,
    pub num: u64,
}

#[repr(C)]
pub struct FdbDefaultKvNode {
    pub key: *mut std::ffi::c_char,
    pub value: *mut std::ffi::c_void,
    pub value_len: u64,
}

#[repr(C)]
pub struct FdbKv {
    pub status: u32,
    pub crc_is_ok: u8,
    pub name_len: u8,
    pub _pad_0: [u8; 2],
    pub magic: u32,
    pub len: u32,
    pub value_len: u32,
    pub name: [u8; 64],
    pub addr: u32,
    pub value_addr: u32,
}

#[repr(C)]
pub struct FdbKvIterator {
    pub curr_kv: [u8; 92],
    pub iterated_cnt: u32,
    pub iterated_obj_bytes: u64,
    pub iterated_value_bytes: u64,
    pub sector_addr: u32,
    pub traversed_len: u32,
}

#[repr(C)]
pub struct FdbKvdb {
    pub parent: [u8; 88],
    pub default_kvs: [u8; 16],
    pub gc_request: u8,
    pub in_recovery_check: u8,
    pub _pad_0: [u8; 2],
    pub cur_kv: [u8; 92],
    pub cur_sector: [u8; 40],
    pub last_is_complete_del: u8,
    pub _pad_1: [u8; 3],
    pub kv_cache_table: [u8; 512],
    pub _pad_2: [u8; 4],
    pub sector_cache_table: [u8; 320],
    pub user_data: *mut std::ffi::c_void,
}

#[repr(C)]
pub struct FdbTsdb {
    pub parent: [u8; 88],
    pub cur_sec: [u8; 56],
    pub last_time: u32,
    pub _pad_0: [u8; 4],
    pub get_time: u64,
    pub max_len: u64,
    pub rollover: u8,
    pub _pad_1: [u8; 7],
    pub user_data: *mut std::ffi::c_void,
}

#[repr(C)]
pub struct FdbTsl {
    pub status: u32,
    pub time: u32,
    pub log_len: u32,
    pub addr: u32,
    pub log_addr: u32,
}

#[repr(C)]
pub struct FdbKvCacheNode {
    pub name_crc: u16,
    pub active: u16,
    pub addr: u32,
}

#[repr(C)]
pub struct FdbKvdbSecInfo {
    pub check_ok: u8,
    pub _pad_0: [u8; 3],
    pub status: [u8; 8],
    pub addr: u32,
    pub magic: u32,
    pub combined: u32,
    pub remain: u64,
    pub empty_kv: u32,
}

#[repr(C)]
pub struct FdbTsdbSecInfo {
    pub check_ok: u8,
    pub _pad_0: [u8; 3],
    pub status: u32,
    pub addr: u32,
    pub magic: u32,
    pub start_time: u32,
    pub end_time: u32,
    pub end_idx: u32,
    pub end_info_stat: [u8; 8],
    pub remain: u64,
    pub empty_idx: u32,
    pub empty_data: u32,
}
