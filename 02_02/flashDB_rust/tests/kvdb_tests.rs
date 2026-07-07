use flashdb_rust::{KvDb, MemFlash};

const SEC_SIZE: u32 = 4096;
const SECTORS: u32 = 4;

fn make_kvdb() -> KvDb<MemFlash> {
    KvDb::open(MemFlash::new(SEC_SIZE, SECTORS)).expect("open kvdb")
}

#[test]
fn kvdb_test_fdb_kvdb_init() {
    let db = KvDb::open(MemFlash::new(SEC_SIZE, SECTORS));
    assert!(db.is_ok(), "KVDB init should succeed");
}

#[test]
fn kvdb_test_fdb_kvdb_init_check() {
    let mut db = make_kvdb();
    db.set("key_check", "value_check").expect("set");
    let result = db.get("key_check").expect("get");
    assert!(result.is_some(), "init check: value should exist after set");
}

#[test]
fn kvdb_test_fdb_create_kv_blob() {
    let mut db = make_kvdb();
    let blob: Vec<u8> = vec![0x01, 0x02, 0x03, 0x04, 0x05];
    db.set_blob("blob_key", &blob).expect("set blob");
    let got = db.get_blob("blob_key").expect("get blob");
    assert!(got.is_some(), "blob should exist after create");
    assert_eq!(got.unwrap(), blob, "blob content should match");
    let blob2: Vec<u8> = vec![0xAA, 0xBB];
    db.set_blob("blob_key2", &blob2).expect("set blob2");
    assert_eq!(db.get_blob("blob_key2").expect("get blob2").unwrap(), blob2);
}

#[test]
fn kvdb_test_fdb_change_kv_blob() {
    let mut db = make_kvdb();
    let blob1: Vec<u8> = vec![0x10, 0x20, 0x30];
    db.set_blob("change_key", &blob1).expect("set blob initial");
    let got1 = db.get_blob("change_key").expect("get blob initial");
    assert_eq!(got1.unwrap(), blob1, "initial blob should match");
    let blob2: Vec<u8> = vec![0x40, 0x50, 0x60, 0x70];
    db.set_blob("change_key", &blob2).expect("set blob changed");
    let got2 = db.get_blob("change_key").expect("get blob changed");
    assert_ne!(got2.unwrap(), blob1, "changed blob should differ from initial");
    assert_eq!(db.get_blob("change_key").expect("get").unwrap(), blob2, "changed blob content should match new value");
}

#[test]
fn kvdb_test_fdb_del_kv_blob() {
    let mut db = make_kvdb();
    let blob: Vec<u8> = vec![0xFF, 0xFE, 0xFD];
    db.set_blob("del_key", &blob).expect("set blob");
    assert!(db.get_blob("del_key").expect("get blob before del").is_some(), "blob should exist before delete");
    db.delete("del_key").expect("delete");
    let got = db.get_blob("del_key").expect("get blob after del");
    assert!(got.is_none(), "blob should not exist after delete");
}

#[test]
fn kvdb_test_fdb_create_kv() {
    let mut db = make_kvdb();
    db.set("str_key", "str_value").expect("set string");
    let got = db.get("str_key").expect("get string");
    assert!(got.is_some(), "string value should exist after create");
    assert_eq!(got.unwrap(), "str_value", "string content should match");
    db.set("key_num", "42").expect("set numeric string");
    assert_eq!(db.get("key_num").expect("get").unwrap(), "42");
}

#[test]
fn kvdb_test_fdb_change_kv() {
    let mut db = make_kvdb();
    db.set("change_str", "v1").expect("set initial");
    assert_eq!(db.get("change_str").expect("get").unwrap(), "v1", "initial value should be v1");
    db.set("change_str", "v2").expect("set changed");
    let got = db.get("change_str").expect("get changed");
    assert_ne!(got.as_deref(), Some("v1"), "changed value should differ from initial");
    assert_eq!(got.unwrap(), "v2", "changed value should be v2");
}

#[test]
fn kvdb_test_fdb_del_kv() {
    let mut db = make_kvdb();
    db.set("del_str", "to_delete").expect("set");
    assert!(db.get("del_str").expect("get before del").is_some(), "value should exist before delete");
    db.delete("del_str").expect("delete");
    assert!(db.get("del_str").expect("get after del").is_none(), "value should not exist after delete");
    db.set("del2", "also_delete").expect("set second");
    db.delete("del2").expect("delete second");
    assert!(db.get("del2").expect("get").is_none());
}

#[test]
fn kvdb_test_fdb_gc() {
    let mut db = make_kvdb();
    db.set("gc_key1", "gc_val1").expect("set 1");
    db.set("gc_key2", "gc_val2").expect("set 2");
    db.set("gc_key3", "gc_val3").expect("set 3");
    db.set("gc_key1", "gc_val1_new").expect("change key1");
    db.gc().expect("gc should succeed");
    assert_eq!(db.get("gc_key1").expect("get key1 after gc").unwrap(), "gc_val1_new", "gc should retain latest value for key1");
    assert_eq!(db.get("gc_key2").expect("get key2 after gc").unwrap(), "gc_val2", "gc should retain unchanged key2");
    assert_eq!(db.get("gc_key3").expect("get key3 after gc").unwrap(), "gc_val3", "gc should retain unchanged key3");
}

#[test]
fn kvdb_test_fdb_gc2() {
    let mut db = make_kvdb();
    let big_val = vec![0xAB; 100];
    db.set_blob("big_key", &big_val).expect("set big blob");
    db.set("small_key", "small_val").expect("set small");
    db.set_blob("big_key", &big_val).expect("change big blob");
    db.gc().expect("gc should succeed");
    assert_eq!(db.get_blob("big_key").expect("get big after gc").unwrap(), big_val, "gc should retain latest big value");
    assert_eq!(db.get("small_key").expect("get small after gc").unwrap(), "small_val", "gc should retain small value");
}

#[test]
fn kvdb_test_fdb_scale_up() {
    let db8 = KvDb::open(MemFlash::new(SEC_SIZE, 8));
    assert!(db8.is_ok(), "kvdb init with 8 sectors should succeed");
    let mut db8 = db8.unwrap();
    db8.set("scale_key", "scale_val").expect("set");
    assert_eq!(db8.get("scale_key").expect("get").unwrap(), "scale_val");
}

#[test]
fn kvdb_test_fdb_kvdb_set_default() {
    let mut db = make_kvdb();
    let defaults = [
        ("default1", b"val1" as &[u8]),
        ("default2", b"val2" as &[u8]),
    ];
    db.set_default(&defaults).expect("set default");
    assert_eq!(db.get("default1").expect("get default1").unwrap(), "val1");
    assert_eq!(db.get("default2").expect("get default2").unwrap(), "val2");
}

#[test]
fn kvdb_test_fdb_kvdb_deinit() {
    let db = KvDb::open(MemFlash::new(SEC_SIZE, SECTORS));
    assert!(db.is_ok(), "kvdb init for deinit should succeed");
}
