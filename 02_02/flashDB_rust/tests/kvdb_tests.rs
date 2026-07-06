
use flashdb_rust::{KvDb, MemFlash};
use std::collections::HashMap;

const SEC_SIZE: u32 = 4096;
const SEC_COUNT: u32 = 4;

fn make_kvdb() -> KvDb {
    let flash = MemFlash::new(SEC_SIZE, SEC_COUNT);
    KvDb::open(Box::new(flash)).expect("open kvdb")
}

#[test]
fn kvdb_init_creates_empty_db() {
    let db = make_kvdb();
    assert_eq!(db.get("any_key").expect("get"), None);
}

#[test]
fn kvdb_create_and_get_kv() {
    let mut db = make_kvdb();
    db.set("key1", "value1").expect("set");
    let result = db.get("key1").expect("get");
    assert_eq!(result, Some("value1".to_string()));
}

#[test]
fn kvdb_change_kv() {
    let mut db = make_kvdb();
    db.set("key1", "value1").expect("set");
    assert_eq!(db.get("key1").expect("get"), Some("value1".to_string()));
    db.set("key1", "value2").expect("change");
    assert_eq!(db.get("key1").expect("get changed"), Some("value2".to_string()));
}

#[test]
fn kvdb_del_kv() {
    let mut db = make_kvdb();
    db.set("key1", "value1").expect("set");
    db.delete("key1").expect("delete");
    assert_eq!(db.get("key1").expect("get deleted"), None);
}

#[test]
fn kvdb_create_and_get_blob() {
    let mut db = make_kvdb();
    db.set_blob("blob1", &[1u8, 2, 3, 4]).expect("set blob");
    let result = db.get_blob("blob1").expect("get blob");
    assert_eq!(result, Some(vec![1, 2, 3, 4]));
}

#[test]
fn kvdb_change_blob() {
    let mut db = make_kvdb();
    db.set_blob("blob1", &[1u8, 2]).expect("set blob");
    assert_eq!(db.get_blob("blob1").expect("get blob"), Some(vec![1, 2]));
    db.set_blob("blob1", &[5u8, 6, 7]).expect("change blob");
    assert_eq!(db.get_blob("blob1").expect("get changed"), Some(vec![5, 6, 7]));
}

#[test]
fn kvdb_del_blob() {
    let mut db = make_kvdb();
    db.set_blob("blob1", &[1u8, 2]).expect("set blob");
    db.delete("blob1").expect("delete blob");
    assert_eq!(db.get_blob("blob1").expect("get deleted"), None);
}

#[test]
fn kvdb_iter_exposes_written_entries() {
    let mut db = make_kvdb();
    db.set("a", "1").expect("set a");
    db.set("b", "2").expect("set b");
    let pairs: HashMap<String, Vec<u8>> = db.iter().collect();
    assert_eq!(pairs.len(), 2);
    assert_eq!(pairs.get("a").unwrap(), &b"1".to_vec());
    assert_eq!(pairs.get("b").unwrap(), &b"2".to_vec());
}

#[test]
fn kvdb_gc_compacts_deleted_records() {
    let mut db = make_kvdb();
    for i in 0..20 {
        db.set(format!("key{}", i), format!("val{}", i)).expect("set");
    }
    for i in 0..10 {
        db.delete(format!("key{}", i)).expect("delete");
    }
    db.gc().expect("gc");
    for i in 10..20 {
        let val = db.get(format!("key{}", i)).expect("get after gc");
        assert_eq!(val, Some(format!("val{}", i)));
    }
    for i in 0..10 {
        assert_eq!(db.get(format!("key{}", i)).expect("get deleted"), None);
    }
}

#[test]
fn kvdb_set_default_stores_defaults() {
    let mut db = make_kvdb();
    db.set("key1", "default1").expect("set default 1");
    db.set("key2", "default2").expect("set default 2");
    assert_eq!(db.get("key1").expect("get default"), Some("default1".to_string()));
    assert_eq!(db.get("key2").expect("get default"), Some("default2".to_string()));
}

#[test]
fn kvdb_multiple_keys_stress() {
    let mut db = make_kvdb();
    for i in 0..30 {
        db.set(format!("k{}", i), format!("v{}", i)).expect("set");
    }
    for i in 0..30 {
        assert_eq!(db.get(format!("k{}", i)).expect("get"), Some(format!("v{}", i)));
    }
}

#[test]
fn kvdb_reload_preserves_data() {
    let flash = MemFlash::new(SEC_SIZE, SEC_COUNT);
    let mut db = KvDb::open(Box::new(flash)).expect("open");
    db.set("persistent", "data").expect("set");
    db.reload().expect("reload");
    assert_eq!(db.get("persistent").expect("get after reload"), Some("data".to_string()));
}
