
use flashdb_rust::{KvDb, MemFlash, TsDb, TslStatus};

#[test]
fn kvdb_and_tsdb_coexist_independently() {
    let mut kv = KvDb::open(Box::new(MemFlash::new(4096, 4))).expect("open kvdb");
    kv.set("env", "test").expect("set kv");
    assert_eq!(kv.get("env").expect("get kv"), Some("test".to_string()));
    kv.delete("env").expect("delete kv");
    assert_eq!(kv.get("env").expect("get deleted"), None);

    let mut ts = TsDb::open(4096, 16, 128).expect("open tsdb");
    ts.append(10, b"event").expect("append");
    ts.append(20, b"event2").expect("append");
    let queried = ts.query_by_time(0, 30).expect("query");
    assert_eq!(queried.len(), 2);
}

#[test]
fn kvdb_blob_string_interop() {
    let mut kv = KvDb::open(Box::new(MemFlash::new(4096, 4))).expect("open kvdb");
    kv.set("text_key", "hello").expect("set string");
    kv.set_blob("bin_key", &[0xDE, 0xAD]).expect("set blob");
    assert_eq!(kv.get("text_key").expect("get string"), Some("hello".to_string()));
    assert_eq!(kv.get_blob("bin_key").expect("get blob"), Some(vec![0xDE, 0xAD]));
}

#[test]
fn tsdb_status_then_query() {
    let mut ts = TsDb::open(4096, 16, 128).expect("open tsdb");
    ts.append(2, b"r1").expect("append");
    ts.append(4, b"r2").expect("append");
    ts.append(6, b"r3").expect("append");
    ts.set_status(2, TslStatus::UserStatus1).expect("set status");
    ts.set_status(6, TslStatus::Deleted).expect("set status");
    assert_eq!(ts.count_by_time(0, 10, TslStatus::Write), 1);
    assert_eq!(ts.count_by_time(0, 10, TslStatus::UserStatus1), 1);
    assert_eq!(ts.count_by_time(0, 10, TslStatus::Deleted), 1);
}

#[test]
fn kvdb_gc_retains_latest_values() {
    let mut kv = KvDb::open(Box::new(MemFlash::new(4096, 4))).expect("open kvdb");
    kv.set("a", "1").expect("set a=1");
    kv.set("a", "2").expect("set a=2");
    kv.set("a", "3").expect("set a=3");
    kv.gc().expect("gc");
    assert_eq!(kv.get("a").expect("get after gc"), Some("3".to_string()));
}
