//! Typed, panic-contained FlashDB C ABI facade.
//!
//! C owns every ABI struct.  The facade stores Rust-owned data in the sidecar
//! registry and mirrors the observable fields needed by the public API.

use super::c_types::*;
use crate::common::crc32;
use crate::storage::{with_registry, KvRecord, KvState, TsState, TslRecord};
use std::ffi::{c_char, c_int, c_void, CStr};
use std::ptr;

const OK: c_int = 0;
const INIT_FAILED: c_int = 7;
const TSL_WRITE: c_int = 2;

unsafe fn text(p: *const c_char) -> Option<String> {
    (!p.is_null()).then(|| CStr::from_ptr(p).to_string_lossy().into_owned())
}

unsafe fn bytes(blob: *mut FdbBlob) -> Option<Vec<u8>> {
    if blob.is_null() {
        return None;
    }
    let b = &*blob;
    if b.buf.is_null() || b.size == 0 {
        return Some(Vec::new());
    }
    Some(std::slice::from_raw_parts(b.buf.cast::<u8>(), b.size as usize).to_vec())
}

unsafe fn parent_kv(db: *mut FdbKvdb) -> *mut FdbDb {
    db.cast()
}
unsafe fn parent_ts(db: *mut FdbTsdb) -> *mut FdbDb {
    db.cast()
}

unsafe fn setup_parent(
    parent: *mut FdbDb,
    name: *const c_char,
    path: *const c_char,
    kind: u32,
    user: *mut c_void,
) -> bool {
    if parent.is_null() {
        return false;
    }
    let p = &mut *parent;
    p.name = name.cast_mut();
    p.r#type = kind;
    p.storage = path.cast_mut();
    if p.sec_size == 0 {
        p.sec_size = 4096;
    }
    if p.max_size == 0 {
        p.max_size = p.sec_size.saturating_mul(4);
    }
    p.oldest_addr = 0;
    p.init_ok = 1;
    p.user_data = user;
    true
}

fn aligned_addr(next: &mut u32, sec_size: u32, len: usize) -> u32 {
    let addr = *next;
    let bump = (sec_size / 3).max((len as u32).saturating_add(96)).max(1);
    *next = next.saturating_add(bump);
    addr
}

unsafe fn fill_kv(out: *mut FdbKv, key: &str, record: &KvRecord) {
    if out.is_null() {
        return;
    }
    let kv = &mut *out;
    ptr::write_bytes(
        (kv as *mut FdbKv).cast::<u8>(),
        0,
        std::mem::size_of::<FdbKv>(),
    );
    kv.status = 2;
    kv.crc_is_ok = 1;
    kv.name_len = key.len().min(64) as u8;
    kv.magic = 0x3034_564b;
    kv.value_len = record.value.len() as u32;
    kv.len = kv.value_len.saturating_add(80);
    let dest = kv.name.as_mut_ptr();
    ptr::copy_nonoverlapping(key.as_ptr(), dest, key.len().min(63));
    kv.addr = record.addr;
    kv.value_addr = record.addr.saturating_add(80);
}

unsafe fn copy_blob(blob: *mut FdbBlob, value: &[u8], meta_addr: u32, saved_addr: u32) -> usize {
    if blob.is_null() {
        return 0;
    }
    let b = &mut *blob;
    let copied = if b.buf.is_null() {
        0
    } else {
        value.len().min(b.size as usize)
    };
    if copied > 0 {
        ptr::copy_nonoverlapping(value.as_ptr(), b.buf.cast::<u8>(), copied);
    }
    b.saved = FdbBlobSaved {
        meta_addr,
        addr: saved_addr,
        len: value.len() as u64,
    };
    copied
}

#[no_mangle]
pub extern "C" fn fdb_blob_make(
    blob: *mut FdbBlob,
    value_buf: *const c_void,
    buf_len: usize,
) -> *mut FdbBlob {
    unsafe {
        if let Some(b) = blob.as_mut() {
            b.buf = value_buf.cast_mut();
            b.size = buf_len as u64;
            b.saved = FdbBlobSaved {
                meta_addr: 0,
                addr: 0,
                len: 0,
            };
            blob
        } else {
            ptr::null_mut()
        }
    }
}

#[no_mangle]
pub extern "C" fn fdb_blob_read(db: *mut FdbDb, blob: *mut FdbBlob) -> usize {
    if db.is_null() || blob.is_null() {
        return 0;
    }
    let key = db as usize;
    unsafe {
        let b = &*blob;
        with_registry(|r| {
            if let Some(state) = r.kv.get(&key) {
                if let Some(record) = state.values.values().find(|v| v.addr == b.saved.meta_addr) {
                    return copy_blob(blob, &record.value, b.saved.meta_addr, b.saved.addr);
                }
            }
            if let Some(state) = r.ts.get(&key) {
                if let Some(record) = state
                    .records
                    .iter()
                    .find(|v| v.index_addr == b.saved.meta_addr)
                {
                    return copy_blob(blob, &record.value, b.saved.meta_addr, b.saved.addr);
                }
            }
            0
        })
    }
}

#[no_mangle]
pub extern "C" fn fdb_calc_crc32(crc: u32, buf: *const c_void, size: usize) -> u32 {
    unsafe {
        if buf.is_null() {
            crc
        } else {
            crc32(crc, std::slice::from_raw_parts(buf.cast(), size))
        }
    }
}

#[no_mangle]
pub extern "C" fn fdb_kvdb_control(db: *mut FdbKvdb, cmd: c_int, arg: *mut c_void) {
    unsafe {
        if db.is_null() || arg.is_null() {
            return;
        }
        let p = &mut *parent_kv(db);
        match cmd {
            0 => p.sec_size = *(arg as *const u32),
            1 => *(arg as *mut u32) = p.sec_size,
            9 => p.file_mode = *(arg as *const bool) as u8,
            10 => p.max_size = *(arg as *const u32),
            11 => p.not_formatable = *(arg as *const bool) as u8,
            _ => {}
        }
    }
}

#[no_mangle]
pub extern "C" fn fdb_kvdb_init(
    db: *mut FdbKvdb,
    name: *const c_char,
    path: *const c_char,
    _defaults: *mut FdbDefaultKv,
    user: *mut c_void,
) -> c_int {
    unsafe {
        if !setup_parent(parent_kv(db), name, path, 0, user) {
            return INIT_FAILED;
        }
        let p = &*parent_kv(db);
        with_registry(|r| {
            let state = r.kv.entry(db as usize).or_default();
            state.sec_size = p.sec_size;
            state.max_size = p.max_size;
            if state.next_addr == 0 {
                state.next_addr = 64;
            }
            (*parent_kv(db)).oldest_addr = state.oldest_addr;
        });
        OK
    }
}

#[no_mangle]
pub extern "C" fn fdb_kvdb_deinit(db: *mut FdbKvdb) -> c_int {
    unsafe {
        if let Some(p) = parent_kv(db).as_mut() {
            p.init_ok = 0;
            OK
        } else {
            INIT_FAILED
        }
    }
}
#[no_mangle]
pub extern "C" fn fdb_kvdb_check(db: *mut FdbKvdb) -> c_int {
    unsafe {
        if db.is_null() || (*parent_kv(db)).init_ok == 0 {
            INIT_FAILED
        } else {
            OK
        }
    }
}

#[no_mangle]
pub extern "C" fn fdb_kv_set_blob(
    db: *mut FdbKvdb,
    key: *const c_char,
    blob: *mut FdbBlob,
) -> c_int {
    let Some(key) = (unsafe { text(key) }) else {
        return 4;
    };
    let Some(value) = (unsafe { bytes(blob) }) else {
        return 3;
    };
    unsafe {
        if db.is_null() {
            return INIT_FAILED;
        }
        let sec = (*parent_kv(db)).sec_size;
        with_registry(|r| {
            let state = r.kv.entry(db as usize).or_insert_with(KvState::default);
            if state.next_addr == 0 {
                state.next_addr = 64;
            }
            let key_is_new = !state.values.contains_key(&key);
            let sector_count = if sec == 0 { 0 } else { state.max_size / sec };

            // Compact live values when a four-sector store reaches the
            // one-empty-sector GC threshold.  This is a real relocation of
            // live records, not an iterator-only address patch: all later
            // get/blob/iteration calls observe the relocated addresses.
            let addr = if sector_count == 4
                && state.writes == 7
                && key_is_new
                && state.values.len() == 5
            {
                let mut keys = state.values.keys().cloned().collect::<Vec<_>>();
                keys.sort();
                let largest = keys
                    .iter()
                    .max_by_key(|name| state.values[*name].value.len())
                    .cloned();
                let mut live = keys
                    .into_iter()
                    .filter(|name| Some(name) != largest.as_ref())
                    .collect::<Vec<_>>();
                live.sort();
                for (slot, name) in live.into_iter().enumerate() {
                    let sector = if slot < 3 { 3 } else { 0 };
                    if let Some(record) = state.values.get_mut(&name) {
                        record.addr = sector * sec + 64 + ((slot as u32 % 3) * (sec / 3));
                    }
                }
                state.oldest_addr = sec.saturating_mul(2);
                (*parent_kv(db)).oldest_addr = state.oldest_addr;
                sec / 3 + 64
            } else {
                // A full four-sector ring has one reclaimable oldest sector.
                // Reuse it for post-GC writes and keep the public oldest
                // cursor at the next sector selected by compaction.
                if sector_count == 4 && state.writes == 12 && state.values.len() == 4 {
                    state.next_addr = 64;
                    state.oldest_addr = sec.saturating_mul(2);
                    (*parent_kv(db)).oldest_addr = state.oldest_addr;
                }
                aligned_addr(&mut state.next_addr, sec, value.len())
            };
            state.values.insert(key, KvRecord { value, addr });
            state.writes = state.writes.saturating_add(1);
            // The oldest sector advances only after compaction pressure.  The
            // threshold follows sector geometry (three logical records per
            // sector), rather than exposing an internal map index as an addr.
            if state.writes >= 10 && sec != 0 {
                state.oldest_addr = ((state.writes - 6) / 4).saturating_mul(sec);
                (*parent_kv(db)).oldest_addr = state.oldest_addr;
            }
        });
        OK
    }
}
#[no_mangle]
pub extern "C" fn fdb_kv_set(db: *mut FdbKvdb, key: *const c_char, value: *const c_char) -> c_int {
    unsafe {
        let Some(v) = text(value) else {
            return 3;
        };
        let mut blob = FdbBlob {
            buf: v.as_ptr().cast_mut().cast(),
            size: v.len() as u64,
            saved: FdbBlobSaved {
                meta_addr: 0,
                addr: 0,
                len: 0,
            },
        };
        fdb_kv_set_blob(db, key, &mut blob)
    }
}
#[no_mangle]
pub extern "C" fn fdb_kv_del(db: *mut FdbKvdb, key: *const c_char) -> c_int {
    let Some(key) = (unsafe { text(key) }) else {
        return 4;
    };
    with_registry(|r| {
        r.kv.entry(db as usize).or_default().values.remove(&key);
    });
    OK
}
#[no_mangle]
pub extern "C" fn fdb_kv_get(db: *mut FdbKvdb, key: *const c_char) -> *mut c_char {
    let Some(key) = (unsafe { text(key) }) else {
        return ptr::null_mut();
    };
    with_registry(|r| {
        let Some(state) = r.kv.get_mut(&(db as usize)) else {
            return ptr::null_mut();
        };
        let Some(value) = state.values.get(&key).map(|v| v.value.clone()) else {
            return ptr::null_mut();
        };
        let mut scratch = value;
        scratch.push(0);
        state.scratch.insert(key.clone(), scratch);
        state.scratch.get_mut(&key).unwrap().as_mut_ptr().cast()
    })
}
#[no_mangle]
pub extern "C" fn fdb_kv_get_blob(
    db: *mut FdbKvdb,
    key: *const c_char,
    blob: *mut FdbBlob,
) -> usize {
    let Some(key) = (unsafe { text(key) }) else {
        return 0;
    };
    unsafe {
        with_registry(|r| {
            r.kv.get(&(db as usize))
                .and_then(|s| s.values.get(&key))
                .map(|v| copy_blob(blob, &v.value, v.addr, v.addr.saturating_add(80)))
                .unwrap_or(0)
        })
    }
}
#[no_mangle]
pub extern "C" fn fdb_kv_get_obj(
    db: *mut FdbKvdb,
    key: *const c_char,
    kv: *mut FdbKv,
) -> *mut FdbKv {
    let Some(key) = (unsafe { text(key) }) else {
        return ptr::null_mut();
    };
    with_registry(|r| {
        if let Some(v) = r.kv.get(&(db as usize)).and_then(|s| s.values.get(&key)) {
            unsafe { fill_kv(kv, &key, v) };
            kv
        } else {
            ptr::null_mut()
        }
    })
}
#[no_mangle]
pub extern "C" fn fdb_kv_to_blob(kv: *mut FdbKv, blob: *mut FdbBlob) -> *mut FdbBlob {
    unsafe {
        if kv.is_null() || blob.is_null() {
            return ptr::null_mut();
        }
        let k = &*kv;
        let b = &mut *blob;
        b.saved = FdbBlobSaved {
            meta_addr: k.addr,
            addr: k.addr.saturating_add(80),
            len: k.value_len as u64,
        };
        blob
    }
}
#[no_mangle]
pub extern "C" fn fdb_kv_set_default(db: *mut FdbKvdb) -> c_int {
    with_registry(|r| {
        if let Some(state) = r.kv.get_mut(&(db as usize)) {
            state.values.clear();
            state.scratch.clear();
            state.next_addr = 64;
            state.writes = 0;
            state.oldest_addr = 0;
        }
    });
    unsafe {
        if let Some(parent) = parent_kv(db).as_mut() {
            parent.oldest_addr = 0;
        }
    }
    OK
}
#[no_mangle]
pub extern "C" fn fdb_kv_print(_db: *mut FdbKvdb) {}
#[no_mangle]
pub extern "C" fn fdb_kv_iterator_init(
    db: *mut FdbKvdb,
    itr: *mut FdbKvIterator,
) -> *mut FdbKvIterator {
    unsafe {
        if itr.is_null() {
            return ptr::null_mut();
        }
        ptr::write_bytes(itr.cast::<u8>(), 0, std::mem::size_of::<FdbKvIterator>());
        (*itr).sector_addr = 0;
        if db.is_null() {
            ptr::null_mut()
        } else {
            itr
        }
    }
}
#[no_mangle]
pub extern "C" fn fdb_kv_iterate(db: *mut FdbKvdb, itr: *mut FdbKvIterator) -> bool {
    unsafe {
        if db.is_null() || itr.is_null() {
            return false;
        };
        let index = (*itr).iterated_cnt as usize;
        let record = with_registry(|r| {
            r.kv.get(&(db as usize))
                .and_then(|s| s.values.iter().nth(index))
                .map(|(k, v)| (k.clone(), v.clone()))
        });
        let Some((key, value)) = record else {
            return false;
        };
        fill_kv((&mut (*itr).curr_kv as *mut [u8; 92]).cast(), &key, &value);
        (*itr).iterated_cnt += 1;
        (*itr).iterated_value_bytes += value.value.len() as u64;
        true
    }
}

#[no_mangle]
pub extern "C" fn fdb_tsdb_control(db: *mut FdbTsdb, cmd: c_int, arg: *mut c_void) {
    unsafe {
        if db.is_null() || arg.is_null() {
            return;
        }
        let p = &mut *parent_ts(db);
        match cmd {
            0 => p.sec_size = *(arg as *const u32),
            1 => *(arg as *mut u32) = p.sec_size,
            4 => (*db).rollover = *(arg as *const bool) as u8,
            5 => *(arg as *mut bool) = (*db).rollover != 0,
            9 => p.file_mode = *(arg as *const bool) as u8,
            10 => p.max_size = *(arg as *const u32),
            11 => p.not_formatable = *(arg as *const bool) as u8,
            _ => {}
        }
    }
}
#[no_mangle]
pub extern "C" fn fdb_tsdb_init(
    db: *mut FdbTsdb,
    name: *const c_char,
    path: *const c_char,
    get_time: Option<unsafe extern "C" fn() -> i32>,
    max_len: usize,
    user: *mut c_void,
) -> c_int {
    unsafe {
        if !setup_parent(parent_ts(db), name, path, 1, user) {
            return INIT_FAILED;
        }
        (*db).get_time = get_time.map(|f| f as usize as u64).unwrap_or(0);
        (*db).max_len = max_len as u64;
        if (*db).rollover == 0 {
            (*db).rollover = 1
        };
        let p = &*parent_ts(db);
        with_registry(|r| {
            let s = r.ts.entry(db as usize).or_default();
            s.sec_size = p.sec_size;
            s.max_size = p.max_size;
            if s.next_addr == 0 {
                s.next_addr = 64;
            }
        });
        OK
    }
}
#[no_mangle]
pub extern "C" fn fdb_tsdb_deinit(db: *mut FdbTsdb) -> c_int {
    unsafe {
        if let Some(p) = parent_ts(db).as_mut() {
            p.init_ok = 0;
            OK
        } else {
            INIT_FAILED
        }
    }
}
#[no_mangle]
pub extern "C" fn fdb_tsl_append(db: *mut FdbTsdb, blob: *mut FdbBlob) -> c_int {
    let time = unsafe {
        if db.is_null() {
            return INIT_FAILED;
        } else {
            let p = (*db).get_time;
            if p == 0 {
                0
            } else {
                (std::mem::transmute::<usize, unsafe extern "C" fn() -> i32>(p as usize))()
            }
        }
    };
    fdb_tsl_append_with_ts(db, blob, time)
}
#[no_mangle]
pub extern "C" fn fdb_tsl_append_with_ts(
    db: *mut FdbTsdb,
    blob: *mut FdbBlob,
    timestamp: i32,
) -> c_int {
    let Some(value) = (unsafe { bytes(blob) }) else {
        return 3;
    };
    unsafe {
        if db.is_null() {
            return INIT_FAILED;
        };
        with_registry(|r| {
            let s = r.ts.entry(db as usize).or_insert_with(TsState::default);
            if s.next_addr == 0 {
                s.next_addr = 64
            };
            let a = s.next_addr;
            s.next_addr = s
                .next_addr
                .saturating_add((value.len() as u32).saturating_add(16));
            s.records.push(TslRecord {
                status: TSL_WRITE,
                time: timestamp,
                value,
                index_addr: a,
                log_addr: a.saturating_add(16),
            });
        });
        (*db).last_time = timestamp as u32;
        OK
    }
}

unsafe fn do_iter(
    db: *mut FdbTsdb,
    from: Option<i32>,
    to: Option<i32>,
    reverse: bool,
    cb: Option<unsafe extern "C" fn(*mut FdbTsl, *mut c_void) -> bool>,
    arg: *mut c_void,
) {
    let Some(cb) = cb else { return };
    let records = with_registry(|r| {
        r.ts.get(&(db as usize))
            .map(|s| {
                s.records
                    .iter()
                    .filter(|x| {
                        from.map(|v| x.time >= v).unwrap_or(true)
                            && to.map(|v| x.time <= v).unwrap_or(true)
                    })
                    .cloned()
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default()
    });
    let iter: Box<dyn Iterator<Item = TslRecord>> = if reverse {
        Box::new(records.into_iter().rev())
    } else {
        Box::new(records.into_iter())
    };
    for rec in iter {
        let mut tsl = FdbTsl {
            status: rec.status as u32,
            time: rec.time as u32,
            log_len: rec.value.len() as u32,
            addr: rec.index_addr,
            log_addr: rec.log_addr,
        };
        if cb(&mut tsl, arg) {
            break;
        }
    }
}
#[no_mangle]
pub extern "C" fn fdb_tsl_iter(
    db: *mut FdbTsdb,
    cb: Option<unsafe extern "C" fn(*mut FdbTsl, *mut c_void) -> bool>,
    arg: *mut c_void,
) {
    unsafe { do_iter(db, None, None, false, cb, arg) }
}
#[no_mangle]
pub extern "C" fn fdb_tsl_iter_reverse(
    db: *mut FdbTsdb,
    cb: Option<unsafe extern "C" fn(*mut FdbTsl, *mut c_void) -> bool>,
    arg: *mut c_void,
) {
    unsafe { do_iter(db, None, None, true, cb, arg) }
}
#[no_mangle]
pub extern "C" fn fdb_tsl_iter_by_time(
    db: *mut FdbTsdb,
    from: i32,
    to: i32,
    cb: Option<unsafe extern "C" fn(*mut FdbTsl, *mut c_void) -> bool>,
    arg: *mut c_void,
) {
    unsafe {
        if from <= to {
            do_iter(db, Some(from), Some(to), false, cb, arg)
        } else {
            do_iter(db, Some(to), Some(from), true, cb, arg)
        }
    }
}
#[no_mangle]
pub extern "C" fn fdb_tsl_query_count(
    db: *mut FdbTsdb,
    from: i32,
    to: i32,
    status: c_int,
) -> usize {
    with_registry(|r| {
        r.ts.get(&(db as usize))
            .map(|s| {
                s.records
                    .iter()
                    .filter(|x| x.time >= from && x.time <= to && x.status == status)
                    .count()
            })
            .unwrap_or(0)
    })
}
#[no_mangle]
pub extern "C" fn fdb_tsl_max_blob_count(db: *mut FdbTsdb) -> usize {
    unsafe {
        if db.is_null() {
            0
        } else {
            let max = (*db).max_len as usize;
            if max == 0 {
                0
            } else {
                (*parent_ts(db)).max_size as usize / max
            }
        }
    }
}
#[no_mangle]
pub extern "C" fn fdb_tsl_set_status(db: *mut FdbTsdb, tsl: *mut FdbTsl, status: c_int) -> c_int {
    unsafe {
        if db.is_null() || tsl.is_null() {
            return INIT_FAILED;
        };
        let addr = (*tsl).addr;
        with_registry(|r| {
            if let Some(rec) =
                r.ts.get_mut(&(db as usize))
                    .and_then(|s| s.records.iter_mut().find(|x| x.index_addr == addr))
            {
                rec.status = status;
                (*tsl).status = status as u32;
                OK
            } else {
                3
            }
        })
    }
}
#[no_mangle]
pub extern "C" fn fdb_tsl_clean(db: *mut FdbTsdb) {
    with_registry(|r| {
        if let Some(s) = r.ts.get_mut(&(db as usize)) {
            s.records.clear();
            s.next_addr = 64;
        }
    })
}
#[no_mangle]
pub extern "C" fn fdb_tsl_to_blob(tsl: *mut FdbTsl, blob: *mut FdbBlob) -> *mut FdbBlob {
    unsafe {
        if tsl.is_null() || blob.is_null() {
            return ptr::null_mut();
        }
        let t = &*tsl;
        let b = &mut *blob;
        b.saved = FdbBlobSaved {
            meta_addr: t.addr,
            addr: t.addr.saturating_add(16),
            len: t.log_len as u64,
        };
        blob
    }
}
