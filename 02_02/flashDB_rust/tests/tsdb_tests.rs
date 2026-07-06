
use flashdb_rust::{TsDb, TslStatus};

const SEC_SIZE: u32 = 4096;
const SEC_COUNT: u32 = 16;
const MAX_LEN: u32 = 128;

fn make_tsdb() -> TsDb {
    TsDb::open(SEC_SIZE, SEC_COUNT, MAX_LEN).expect("open tsdb")
}

#[test]
fn tsdb_init_creates_empty_db() {
    let db = make_tsdb();
    let count = db.iter().count();
    assert_eq!(count, 0);
}

#[test]
fn tsdb_append_and_iter() {
    let mut db = make_tsdb();
    db.append(2, b"record1").expect("append 1");
    db.append(4, b"record2").expect("append 2");
    db.append(6, b"record3").expect("append 3");
    let records: Vec<_> = db.iter().cloned().collect();
    assert_eq!(records.len(), 3);
    assert_eq!(records[0].timestamp, 2);
    assert_eq!(records[1].timestamp, 4);
    assert_eq!(records[2].timestamp, 6);
}

#[test]
fn tsdb_query_by_time() {
    let mut db = make_tsdb();
    for ts in [2u64, 4, 6, 8, 10] {
        db.append(ts, format!("data{}", ts).as_bytes()).expect("append");
    }
    let queried = db.query_by_time(4, 8).expect("query");
    assert_eq!(queried.len(), 3);
    assert_eq!(queried[0].timestamp, 4);
    assert_eq!(queried[1].timestamp, 6);
    assert_eq!(queried[2].timestamp, 8);
}

#[test]
fn tsdb_query_count() {
    let mut db = make_tsdb();
    for i in 1..=5 {
        db.append(i * 2, b"data").expect("append");
    }
    let count = db.count_by_time(2, 10, TslStatus::Write);
    assert_eq!(count, 5);
}

#[test]
fn tsdb_set_status() {
    let mut db = make_tsdb();
    db.append(2, b"r1").expect("append 1");
    db.append(4, b"r2").expect("append 2");
    db.append(6, b"r3").expect("append 3");
    db.set_status(4, TslStatus::Deleted).expect("set status");
    let write_count = db.count_by_time(2, 6, TslStatus::Write);
    assert_eq!(write_count, 2);
    let deleted_count = db.count_by_time(2, 6, TslStatus::Deleted);
    assert_eq!(deleted_count, 1);
}

#[test]
fn tsdb_set_user_status() {
    let mut db = make_tsdb();
    for i in 1..=6 {
        db.append(i * 2, b"data").expect("append");
    }
    db.set_status(2, TslStatus::UserStatus1).expect("set user1");
    db.set_status(4, TslStatus::UserStatus1).expect("set user1");
    db.set_status(6, TslStatus::Deleted).expect("set deleted");
    let user1_count = db.count_by_time(2, 12, TslStatus::UserStatus1);
    assert_eq!(user1_count, 2);
    let deleted_count = db.count_by_time(2, 12, TslStatus::Deleted);
    assert_eq!(deleted_count, 1);
}

#[test]
fn tsdb_clean_removes_all() {
    let mut db = make_tsdb();
    db.append(2, b"data").expect("append");
    db.append(4, b"data2").expect("append");
    db.clean().expect("clean");
    let count = db.iter().count();
    assert_eq!(count, 0);
}

#[test]
fn tsdb_clean_and_reuse() {
    let mut db = make_tsdb();
    db.append(2, b"data").expect("append");
    db.clean().expect("clean");
    db.append(4, b"new_data").expect("append after clean");
    let records: Vec<_> = db.iter().cloned().collect();
    assert_eq!(records.len(), 1);
    assert_eq!(records[0].timestamp, 4);
}

#[test]
fn tsdb_iter_reverse() {
    let mut db = make_tsdb();
    db.append(2, b"a").expect("append");
    db.append(4, b"b").expect("append");
    db.append(6, b"c").expect("append");
    let records: Vec<_> = db.iter_reverse().cloned().collect();
    assert_eq!(records.len(), 3);
    assert_eq!(records[0].timestamp, 6);
    assert_eq!(records[1].timestamp, 4);
    assert_eq!(records[2].timestamp, 2);
}

#[test]
fn tsdb_reload_preserves_data() {
    let mut db = make_tsdb();
    db.append(2, b"data").expect("append");
    db.append(4, b"data2").expect("append");
    db.reload().expect("reload");
    let records: Vec<_> = db.iter().cloned().collect();
    assert_eq!(records.len(), 2);
}

#[test]
fn tsdb_multi_sector() {
    let mut db = TsDb::open(SEC_SIZE, 16, 16).expect("open");
    for i in 1..=80 {
        db.append(i as u64 * 2, b"d").expect("append");
    }
    let count = db.count_by_time(2, 160, TslStatus::Write);
    assert_eq!(count, 80);
}
