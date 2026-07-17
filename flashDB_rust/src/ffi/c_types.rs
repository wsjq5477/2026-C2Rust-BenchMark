//! Typed C ABI structs generated from rust_api_design.json.

#![allow(non_camel_case_types)]

#[repr(C)]
#[repr(align(8))]
pub struct FdbBlob {
    pub buf: *mut std::ffi::c_void,
    pub size: usize,
    pub saved: [u8; 16],
}

#[repr(C)]
#[repr(align(8))]
pub struct FdbDb {
    pub name: *const std::ffi::c_char,
    pub r#type: [u8; 4],
    pub _pad_0: [u8; 4],
    pub storage: [u8; 8],
    pub sec_size: u32,
    pub max_size: u32,
    pub oldest_addr: u32,
    pub init_ok: u8,
    pub file_mode: u8,
    pub not_formatable: u8,
    pub _pad_1: [u8; 1],
    pub cur_file_sec: [u32; 2],
    pub cur_file: [std::ffi::c_int; 2],
    pub cur_sec: u32,
    pub _pad_2: [u8; 4],
    pub lock: [u8; 8],
    pub unlock: [u8; 8],
    pub user_data: *mut std::ffi::c_void,
}

#[repr(C)]
#[repr(align(8))]
pub struct FdbDefaultKv {
    pub kvs: *mut FdbDefaultKvNode,
    pub num: usize,
}

#[repr(C)]
#[repr(align(8))]
pub struct FdbDefaultKvNode {
    pub key: *mut std::ffi::c_char,
    pub value: *mut std::ffi::c_void,
    pub value_len: usize,
}

#[repr(C)]
#[repr(align(4))]
pub struct FdbKv {
    pub status: [u8; 4],
    pub crc_is_ok: u8,
    pub name_len: u8,
    pub _pad_0: [u8; 2],
    pub magic: u32,
    pub len: u32,
    pub value_len: u32,
    pub name: [u8; 64],
    pub addr: [u8; 8],
}

#[repr(C)]
#[repr(align(8))]
pub struct FdbKvIterator {
    pub curr_kv: FdbKv,
    pub iterated_cnt: u32,
    pub iterated_obj_bytes: usize,
    pub iterated_value_bytes: usize,
    pub sector_addr: u32,
    pub traversed_len: u32,
}

#[repr(C)]
#[repr(align(8))]
pub struct FdbKvdb {
    pub parent: FdbDb,
    pub default_kvs: FdbDefaultKv,
    pub gc_request: u8,
    pub in_recovery_check: u8,
    pub _pad_0: [u8; 2],
    pub cur_kv: FdbKv,
    pub cur_sector: FdbKvdbSecInfo,
    pub last_is_complete_del: u8,
    pub _pad_1: [u8; 3],
    pub kv_cache_table: [u8; 512],
    pub _pad_2: [u8; 4],
    pub sector_cache_table: [u8; 320],
    pub user_data: *mut std::ffi::c_void,
}

#[repr(C)]
#[repr(align(8))]
pub struct FdbTsdb {
    pub parent: FdbDb,
    pub cur_sec: FdbTsdbSecInfo,
    pub last_time: i32,
    pub _pad_0: [u8; 4],
    pub get_time: [u8; 8],
    pub max_len: usize,
    pub rollover: u8,
    pub _pad_1: [u8; 7],
    pub user_data: *mut std::ffi::c_void,
}

#[repr(C)]
#[repr(align(4))]
pub struct FdbTsl {
    pub status: std::ffi::c_int,
    pub time: i32,
    pub log_len: u32,
    pub addr: [u8; 8],
}

#[repr(C)]
#[repr(align(4))]
pub struct FdbKvCacheNode {
    pub name_crc: u16,
    pub active: u16,
    pub addr: u32,
}

#[repr(C)]
#[repr(align(8))]
pub struct FdbKvdbSecInfo {
    pub check_ok: u8,
    pub _pad_0: [u8; 3],
    pub status: [u8; 8],
    pub addr: u32,
    pub magic: u32,
    pub combined: u32,
    pub remain: usize,
    pub empty_kv: u32,
    pub _pad_1: [u8; 4],
}

#[repr(C)]
#[repr(align(8))]
pub struct FdbTsdbSecInfo {
    pub check_ok: u8,
    pub _pad_0: [u8; 3],
    pub status: [u8; 4],
    pub addr: u32,
    pub magic: u32,
    pub start_time: i32,
    pub end_time: i32,
    pub end_idx: u32,
    pub end_info_stat: [std::ffi::c_int; 2],
    pub _pad_1: [u8; 4],
    pub remain: usize,
    pub empty_idx: u32,
    pub empty_data: u32,
}
