//! TSDB semantic integration tests derived from the current C scorer cases.

use flashdb_rust::ffi::c_abi::*;
use flashdb_rust::ffi::c_types::*;
use std::os::raw::c_void;

const OK: i32 = 0;
const WRITE: i32 = 2;
const USER_STATUS1: i32 = 3;
const DELETED: i32 = 1;

unsafe extern "C" fn fixed_time() -> i32 {
    42
}

fn new_db() -> FdbTsdb {
    unsafe { std::mem::zeroed() }
}

fn init(db: &mut FdbTsdb, sectors: u32) {
    let mut sec_size = 1024_u32;
    fdb_tsdb_control(db, 0, (&mut sec_size as *mut u32).cast::<c_void>());
    let mut max_size = sec_size * sectors;
    fdb_tsdb_control(db, 10, (&mut max_size as *mut u32).cast::<c_void>());
    assert_eq!(
        fdb_tsdb_init(
            db,
            c"ts-test".as_ptr(),
            c"memory".as_ptr(),
            Some(fixed_time),
            128,
            std::ptr::null_mut()
        ),
        OK
    );
}

fn blob_for(bytes: &mut [u8]) -> FdbBlob {
    let mut blob: FdbBlob = unsafe { std::mem::zeroed() };
    assert_eq!(
        fdb_blob_make(&mut blob, bytes.as_mut_ptr().cast(), bytes.len()),
        &mut blob as *mut FdbBlob
    );
    blob
}

fn append(db: &mut FdbTsdb, time: i32, text: &[u8]) {
    let mut payload = text.to_vec();
    let mut blob = blob_for(&mut payload);
    assert_eq!(fdb_tsl_append_with_ts(db, &mut blob, time), OK);
}

struct PayloadCtx {
    db: *mut FdbTsdb,
    rows: Vec<(i32, Vec<u8>)>,
}

unsafe extern "C" fn collect_payload(tsl: *mut FdbTsl, raw: *mut c_void) -> bool {
    let ctx = &mut *raw.cast::<PayloadCtx>();
    let mut bytes = vec![0_u8; (*tsl).log_len as usize];
    let mut blob = blob_for(&mut bytes);
    fdb_tsl_to_blob(tsl, &mut blob);
    let read = fdb_blob_read(ctx.db.cast::<FdbDb>(), &mut blob);
    bytes.truncate(read);
    ctx.rows.push(((*tsl).time as i32, bytes));
    false
}

struct StatusCtx {
    db: *mut FdbTsdb,
    changed: usize,
}

unsafe extern "C" fn set_user_status(tsl: *mut FdbTsl, raw: *mut c_void) -> bool {
    let ctx = &mut *raw.cast::<StatusCtx>();
    if (*tsl).time % 2 == 0 {
        assert_eq!(fdb_tsl_set_status(ctx.db, tsl, USER_STATUS1), OK);
        ctx.changed += 1;
    } else {
        assert_eq!(fdb_tsl_set_status(ctx.db, tsl, DELETED), OK);
        ctx.changed += 1;
    }
    false
}

#[test]
fn tsdb_test_fdb_tsdb_init_ex() {
    let mut db = new_db();
    init(&mut db, 4);
    let parent = unsafe { &*((&db as *const FdbTsdb).cast::<FdbDb>()) };
    assert_eq!(parent.sec_size, 1024);
    assert_eq!(parent.max_size, 4096);
}

#[test]
fn tsdb_test_fdb_tsl_clean() {
    let mut db = new_db();
    init(&mut db, 4);
    append(&mut db, 10, b"before-clean");
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 20, WRITE), 1);
    fdb_tsl_clean(&mut db);
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 20, WRITE), 0);
}

#[test]
fn tsdb_test_fdb_tsl_append() {
    let mut db = new_db();
    init(&mut db, 4);
    append(&mut db, 42, b"append-payload");
    assert_eq!(fdb_tsl_query_count(&mut db, 42, 42, WRITE), 1);
}

#[test]
fn tsdb_test_fdb_tsl_iter() {
    let mut db = new_db();
    init(&mut db, 4);
    append(&mut db, 10, b"10");
    append(&mut db, 20, b"20");
    append(&mut db, 30, b"30");
    let mut ctx = PayloadCtx {
        db: &mut db,
        rows: Vec::new(),
    };
    fdb_tsl_iter(
        &mut db,
        Some(collect_payload),
        (&mut ctx as *mut PayloadCtx).cast(),
    );
    assert_eq!(ctx.rows.len(), 3);
    assert_eq!(ctx.rows[0], (10, b"10".to_vec()));
    assert_eq!(ctx.rows[1], (20, b"20".to_vec()));
    assert_eq!(ctx.rows[2], (30, b"30".to_vec()));
}

#[test]
fn tsdb_test_fdb_tsl_iter_by_time() {
    let mut db = new_db();
    init(&mut db, 4);
    for time in [10, 20, 30, 40, 50] {
        append(&mut db, time, time.to_string().as_bytes());
    }
    let mut ctx = PayloadCtx {
        db: &mut db,
        rows: Vec::new(),
    };
    fdb_tsl_iter_by_time(
        &mut db,
        20,
        40,
        Some(collect_payload),
        (&mut ctx as *mut PayloadCtx).cast(),
    );
    assert_eq!(
        ctx.rows.iter().map(|(time, _)| *time).collect::<Vec<_>>(),
        vec![20, 30, 40]
    );
    assert_eq!(
        ctx.rows
            .iter()
            .map(|(_, value)| value.clone())
            .collect::<Vec<_>>(),
        vec![b"20".to_vec(), b"30".to_vec(), b"40".to_vec()]
    );
}

#[test]
fn tsdb_test_fdb_tsl_query_count() {
    let mut db = new_db();
    init(&mut db, 4);
    for time in 0..512 {
        append(&mut db, time, b"sample");
    }
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 511, WRITE), 512);
    assert_eq!(fdb_tsl_query_count(&mut db, 100, 355, WRITE), 256);
}

#[test]
fn tsdb_test_fdb_tsl_set_status() {
    let mut db = new_db();
    init(&mut db, 4);
    for time in 0..8 {
        append(&mut db, time, b"stateful");
    }
    let mut ctx = StatusCtx {
        db: &mut db,
        changed: 0,
    };
    fdb_tsl_iter_by_time(
        &mut db,
        0,
        7,
        Some(set_user_status),
        (&mut ctx as *mut StatusCtx).cast(),
    );
    assert_eq!(ctx.changed, 8);
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 7, USER_STATUS1), 4);
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 7, DELETED), 4);
}

#[test]
fn tsdb_test_fdb_tsl_clean__2() {
    let mut db = new_db();
    init(&mut db, 4);
    for time in 0..32 {
        append(&mut db, time, b"clear");
    }
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 31, WRITE), 32);
    fdb_tsl_clean(&mut db);
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 31, WRITE), 0);
}

#[test]
fn tsdb_test_fdb_tsl_iter_by_time_1() {
    let mut db = new_db();
    init(&mut db, 8);
    for time in (0..70).map(|v| v * 10) {
        append(&mut db, time, format!("event-{time}").as_bytes());
    }
    let mut ctx = PayloadCtx {
        db: &mut db,
        rows: Vec::new(),
    };
    fdb_tsl_iter_by_time(
        &mut db,
        120,
        180,
        Some(collect_payload),
        (&mut ctx as *mut PayloadCtx).cast(),
    );
    assert_eq!(ctx.rows.len(), 7);
    assert_eq!(ctx.rows.first().unwrap().0, 120);
    assert_eq!(ctx.rows.last().unwrap().0, 180);
    assert_eq!(ctx.rows[0].1, b"event-120");
    assert_eq!(ctx.rows[3].1, b"event-150");
    assert_eq!(ctx.rows[6].1, b"event-180");
    assert!(ctx.rows.windows(2).all(|pair| pair[0].0 < pair[1].0));
}

#[test]
fn tsdb_test_fdb_tsdb_deinit() {
    let mut db = new_db();
    init(&mut db, 4);
    assert_eq!(fdb_tsdb_deinit(&mut db), OK);
    let parent = unsafe { &*((&db as *const FdbTsdb).cast::<FdbDb>()) };
    assert_eq!(parent.init_ok, 0);
}

#[test]
fn tsdb_test_fdb_github_issue_249() {
    let mut db = new_db();
    init(&mut db, 16);
    for time in 0..16 {
        append(&mut db, time, vec![time as u8; 600].as_slice());
    }
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 15, WRITE), 16);
    assert_eq!(fdb_tsl_max_blob_count(&mut db), 128);
    let mut ctx = PayloadCtx {
        db: &mut db,
        rows: Vec::new(),
    };
    fdb_tsl_iter_by_time(
        &mut db,
        5,
        8,
        Some(collect_payload),
        (&mut ctx as *mut PayloadCtx).cast(),
    );
    assert_eq!(ctx.rows.len(), 4);
    assert_eq!(ctx.rows[0].0, 5);
    assert_eq!(ctx.rows[3].0, 8);
    assert_eq!(ctx.rows[0].1.len(), 600);
    assert_eq!(ctx.rows[3].1, vec![8; 600]);
    fdb_tsl_clean(&mut db);
    assert_eq!(fdb_tsl_query_count(&mut db, 0, 15, WRITE), 0);
}
