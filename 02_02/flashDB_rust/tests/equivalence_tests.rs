use flashdb_rust::{KvDb, MemFlash, TsDb, TslStatus};

#[test]
fn core_flashdb_apis_are_available_to_tests() {
    let mut kv = KvDb::open(MemFlash::new(4096, 4)).expect("open kv");
    kv.set("mode", "safe").expect("set");
    assert_eq!(kv.get("mode").expect("get"), Some("safe".to_string()));
    kv.delete("mode").expect("delete");
    assert_eq!(kv.get("mode").expect("get after delete"), None);

    let mut ts = TsDb::open(MemFlash::new(4096, 16), 256).expect("open ts");
    ts.append(100, b"event").expect("append");
    assert_eq!(ts.query_by_time(0, 200).expect("query").len(), 1);
    ts.set_status(100, TslStatus::UserStatus1).expect("set status");
    let queried = ts.query_by_time(0, 200).expect("query");
    assert_eq!(queried[0].status, TslStatus::UserStatus1);
    ts.clean().expect("clean");
    assert_eq!(ts.iter().len(), 0);
}
