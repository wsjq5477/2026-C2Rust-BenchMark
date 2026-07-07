use flashdb_rust::{MemFlash, TsDb, TslStatus};

const SEC_SIZE: u32 = 4096;
const SECTORS: u32 = 16;
const MAX_LEN: u32 = 256;

fn make_tsdb() -> TsDb<MemFlash> {
    TsDb::open(MemFlash::new(SEC_SIZE, SECTORS), MAX_LEN).expect("open tsdb")
}

#[test]
fn tsdb_test_fdb_tsdb_init_ex() {
    let db = TsDb::open(MemFlash::new(SEC_SIZE, SECTORS), MAX_LEN);
    assert!(db.is_ok(), "tsdb init should succeed");
}

#[test]
fn tsdb_test_fdb_tsl_clean() {
    let mut db = make_tsdb();
    db.append(100, b"data1").expect("append 1");
    db.append(200, b"data2").expect("append 2");
    assert_eq!(db.iter().len(), 2, "should have 2 records before clean");
    db.clean().expect("clean");
    assert_eq!(db.iter().len(), 0, "should have 0 records after clean");
}

#[test]
fn tsdb_test_fdb_tsl_append() {
    let mut db = make_tsdb();
    db.append(100, b"tsl_data").expect("append");
    let records = db.iter();
    assert_eq!(records.len(), 1, "should have 1 record after append");
    assert_eq!(records[0].timestamp, 100, "timestamp should match");
    assert_eq!(records[0].payload, b"tsl_data".to_vec(), "payload should match");
}

#[test]
fn tsdb_test_fdb_tsl_iter() {
    let mut db = make_tsdb();
    db.append(10, b"first").expect("append first");
    db.append(20, b"second").expect("append second");
    db.append(30, b"third").expect("append third");
    let records = db.iter();
    assert_eq!(records.len(), 3, "iter should return 3 records");
    assert_eq!(records[0].timestamp, 10);
    assert_eq!(records[1].timestamp, 20);
    assert_eq!(records[2].timestamp, 30);
}

#[test]
fn tsdb_test_fdb_tsl_iter_by_time() {
    let mut db = make_tsdb();
    db.append(100, b"a").expect("append a");
    db.append(200, b"b").expect("append b");
    db.append(300, b"c").expect("append c");
    let queried = db.query_by_time(150, 250).expect("query by time");
    assert_eq!(queried.len(), 1, "time range 150-250 should match 1 record");
    assert_eq!(queried[0].payload, b"b".to_vec());
    let queried_all = db.query_by_time(0, 1000).expect("query all");
    assert_eq!(queried_all.len(), 3, "time range 0-1000 should match 3 records");
}

#[test]
fn tsdb_test_fdb_tsl_query_count() {
    let mut db = make_tsdb();
    db.append(100, b"x").expect("append 1");
    db.append(200, b"y").expect("append 2");
    db.append(300, b"z").expect("append 3");
    let count = db.count_by_time(0, 500).expect("count");
    assert_eq!(count, 3, "count in range 0-500 should be 3");
    let count2 = db.count_by_time(150, 250).expect("count");
    assert_eq!(count2, 1, "count in range 150-250 should be 1");
}

#[test]
fn tsdb_test_fdb_tsl_set_status() {
    let mut db = make_tsdb();
    db.append(100, b"status_data").expect("append");
    db.set_status(100, TslStatus::UserStatus1).expect("set status");
    let records = db.iter();
    assert_eq!(records[0].status, TslStatus::UserStatus1, "status should be UserStatus1");
    let count = db.count_by_time(100, 100).expect("count with status");
    assert_eq!(count, 1, "record should still be counted after status change");
}

#[test]
#[allow(non_snake_case)]
fn tsdb_test_fdb_tsl_clean__2() {
    let mut db = make_tsdb();
    db.append(10, b"d1").expect("append");
    db.append(20, b"d2").expect("append");
    db.clean().expect("clean");
    assert_eq!(db.iter().len(), 0, "should be empty after clean");
    db.append(30, b"d3").expect("append after clean");
    assert_eq!(db.iter().len(), 1, "should have 1 record after clean then append");
}

#[test]
fn tsdb_test_fdb_tsl_iter_by_time_1() {
    let mut db = make_tsdb();
    for i in 0..10u64 {
        let payload = format!("rec_{}", i);
        db.append(i * 100 + 50, payload.as_bytes()).expect("append");
    }
    let queried = db.query_by_time(150, 550).expect("query by time range");
    assert!(queried.len() > 0, "query should return records in range");
    for rec in &queried {
        assert!(rec.timestamp >= 150 && rec.timestamp <= 550, "record timestamp should be in range");
    }
    let all = db.iter();
    assert_eq!(all.len(), 10, "total records should be 10");
}

#[test]
fn tsdb_test_fdb_tsdb_deinit() {
    let db = TsDb::open(MemFlash::new(SEC_SIZE, SECTORS), MAX_LEN);
    assert!(db.is_ok(), "tsdb init for deinit should succeed");
}

#[test]
fn tsdb_test_fdb_github_issue_249() {
    let mut db = make_tsdb();
    let big_payload = vec![0xCD; 200];
    db.append(1000, &big_payload).expect("append big");
    let queried = db.query_by_time(1000, 1000).expect("query");
    assert_eq!(queried.len(), 1, "should find 1 record");
    assert_eq!(queried[0].payload.len(), 200, "payload size should match");
    assert_eq!(queried[0].payload, big_payload, "payload content should match");
    db.clean().expect("clean");
    let after_clean = db.query_by_time(0, 2000).expect("query after clean");
    assert_eq!(after_clean.len(), 0, "should be empty after clean");
}
