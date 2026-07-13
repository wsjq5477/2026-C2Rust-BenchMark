//! KVDB semantic integration tests derived from the current C scorer cases.

use flashdb_rust::ffi::c_abi::*;
use flashdb_rust::ffi::c_types::*;
use std::ffi::CStr;
use std::os::raw::c_void;

const OK: i32 = 0;

fn new_db() -> FdbKvdb {
    // The public facade intentionally accepts caller-owned, ABI-shaped C objects.
    unsafe { std::mem::zeroed() }
}

fn init(db: &mut FdbKvdb, sectors: u32) {
    let mut sector_size = 1024_u32;
    fdb_kvdb_control(db, 0, (&mut sector_size as *mut u32).cast::<c_void>());
    let mut max_size = sector_size * sectors;
    fdb_kvdb_control(db, 10, (&mut max_size as *mut u32).cast::<c_void>());
    assert_eq!(
        fdb_kvdb_init(
            db,
            c"kv-test".as_ptr(),
            c"memory".as_ptr(),
            std::ptr::null_mut(),
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

fn read_blob(db: &mut FdbKvdb, key: &std::ffi::CStr, length: usize) -> (usize, Vec<u8>, FdbBlob) {
    let mut bytes = vec![0_u8; length];
    let mut blob = blob_for(&mut bytes);
    let read = fdb_kv_get_blob(db, key.as_ptr(), &mut blob);
    (read, bytes, blob)
}

fn set_text(db: &mut FdbKvdb, key: &std::ffi::CStr, value: &std::ffi::CStr) {
    assert_eq!(fdb_kv_set(db, key.as_ptr(), value.as_ptr()), OK);
}

#[test]
fn kvdb_test_fdb_kvdb_init() {
    let mut db = new_db();
    init(&mut db, 4);
    assert_eq!(fdb_kvdb_check(&mut db), OK);
    let mut sector_size = 0_u32;
    fdb_kvdb_control(&mut db, 1, (&mut sector_size as *mut u32).cast::<c_void>());
    assert_eq!(sector_size, 1024);
}

#[test]
fn kvdb_test_fdb_kvdb_init_check() {
    let mut db = new_db();
    init(&mut db, 4);
    assert_eq!(fdb_kvdb_check(&mut db), OK);
    let parent = unsafe { &*((&db as *const FdbKvdb).cast::<FdbDb>()) };
    assert_eq!(parent.oldest_addr % parent.sec_size, 0);
}

#[test]
fn kvdb_test_fdb_create_kv_blob() {
    let mut db = new_db();
    init(&mut db, 4);
    let key = c"blob-create";
    let mut written = b"0123456789".to_vec();
    let mut input = blob_for(&mut written);
    assert_eq!(fdb_kv_set_blob(&mut db, key.as_ptr(), &mut input), OK);
    let (read, bytes, saved) = read_blob(&mut db, key, 32);
    assert_eq!(read, written.len());
    assert_eq!(&bytes[..read], written.as_slice());
    assert_eq!(saved.saved.len as usize, written.len());
    let mut object: FdbKv = unsafe { std::mem::zeroed() };
    assert_eq!(
        fdb_kv_get_obj(&mut db, key.as_ptr(), &mut object),
        &mut object as *mut FdbKv
    );
    assert_eq!(object.value_len as usize, written.len());
    let mut object_bytes = vec![0_u8; 32];
    let mut via_object = blob_for(&mut object_bytes);
    assert_eq!(
        fdb_kv_to_blob(&mut object, &mut via_object),
        &mut via_object as *mut FdbBlob
    );
    assert_eq!(
        fdb_blob_read((&mut db as *mut FdbKvdb).cast(), &mut via_object),
        written.len()
    );
    assert_eq!(&object_bytes[..written.len()], written.as_slice());
}

#[test]
fn kvdb_test_fdb_change_kv_blob() {
    let mut db = new_db();
    init(&mut db, 4);
    let key = c"blob-change";
    let mut first = b"old-value".to_vec();
    let mut first_blob = blob_for(&mut first);
    assert_eq!(fdb_kv_set_blob(&mut db, key.as_ptr(), &mut first_blob), OK);
    let mut second = b"new-longer-value".to_vec();
    let mut second_blob = blob_for(&mut second);
    assert_eq!(fdb_kv_set_blob(&mut db, key.as_ptr(), &mut second_blob), OK);
    let (read, bytes, saved) = read_blob(&mut db, key, 64);
    assert_eq!(read, second.len());
    assert_eq!(&bytes[..read], second.as_slice());
    assert_ne!(&bytes[..read], first.as_slice());
    assert_eq!(saved.saved.len as usize, second.len());
}

#[test]
fn kvdb_test_fdb_del_kv_blob() {
    let mut db = new_db();
    init(&mut db, 4);
    let key = c"blob-delete";
    let mut payload = b"remove-me".to_vec();
    let mut blob = blob_for(&mut payload);
    assert_eq!(fdb_kv_set_blob(&mut db, key.as_ptr(), &mut blob), OK);
    let (before, _, _) = read_blob(&mut db, key, 32);
    assert_eq!(before, payload.len());
    assert_eq!(fdb_kv_del(&mut db, key.as_ptr()), OK);
    let (after, bytes, saved) = read_blob(&mut db, key, 32);
    assert_eq!(after, 0);
    assert_eq!(saved.saved.len, 0);
    assert_eq!(bytes, vec![0; 32]);
}

#[test]
fn kvdb_test_fdb_create_kv() {
    let mut db = new_db();
    init(&mut db, 4);
    set_text(&mut db, c"plain-create", c"101");
    let value = fdb_kv_get(&mut db, c"plain-create".as_ptr());
    assert!(!value.is_null());
    assert_eq!(unsafe { CStr::from_ptr(value) }.to_bytes(), b"101");
}

#[test]
fn kvdb_test_fdb_change_kv() {
    let mut db = new_db();
    init(&mut db, 4);
    set_text(&mut db, c"plain-change", c"101");
    let before = unsafe { CStr::from_ptr(fdb_kv_get(&mut db, c"plain-change".as_ptr())) }
        .to_bytes()
        .to_vec();
    set_text(&mut db, c"plain-change", c"202");
    let after = unsafe { CStr::from_ptr(fdb_kv_get(&mut db, c"plain-change".as_ptr())) }
        .to_bytes()
        .to_vec();
    assert_ne!(before, after);
    assert_eq!(after, b"202");
    assert_eq!(after.len(), 3);
}

#[test]
fn kvdb_test_fdb_del_kv() {
    let mut db = new_db();
    init(&mut db, 4);
    set_text(&mut db, c"plain-delete", c"303");
    assert!(!fdb_kv_get(&mut db, c"plain-delete".as_ptr()).is_null());
    assert_eq!(fdb_kv_del(&mut db, c"plain-delete".as_ptr()), OK);
    assert!(fdb_kv_get(&mut db, c"plain-delete".as_ptr()).is_null());
    assert_eq!(fdb_kvdb_check(&mut db), OK);
}

fn put_many(db: &mut FdbKvdb, count: usize, width: usize) -> Vec<(std::ffi::CString, Vec<u8>)> {
    (0..count)
        .map(|i| {
            let key = std::ffi::CString::new(format!("key-{i}")).unwrap();
            let mut value = vec![i as u8; width + i];
            let mut blob = blob_for(&mut value);
            assert_eq!(fdb_kv_set_blob(db, key.as_ptr(), &mut blob), OK);
            (key, value)
        })
        .collect()
}

#[test]
fn kvdb_test_fdb_gc() {
    let mut db = new_db();
    init(&mut db, 4);
    let records = put_many(&mut db, 4, 180);
    let mut itr: FdbKvIterator = unsafe { std::mem::zeroed() };
    assert_eq!(
        fdb_kv_iterator_init(&mut db, &mut itr),
        &mut itr as *mut FdbKvIterator
    );
    for (key, expected) in &records {
        let (n, got, saved) = read_blob(&mut db, key, 512);
        assert_eq!(n, expected.len());
        assert_eq!(&got[..n], expected.as_slice());
        assert_eq!(saved.saved.len as usize, expected.len());
    }
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(!fdb_kv_iterate(&mut db, &mut itr));
    assert_eq!(itr.iterated_cnt, 4);
    assert_eq!(fdb_kv_set_default(&mut db), OK);
}

#[test]
fn kvdb_test_fdb_gc2() {
    let mut db = new_db();
    init(&mut db, 8);
    let records = put_many(&mut db, 6, 1500);
    let mut itr: FdbKvIterator = unsafe { std::mem::zeroed() };
    assert_eq!(
        fdb_kv_iterator_init(&mut db, &mut itr),
        &mut itr as *mut FdbKvIterator
    );
    for (key, expected) in &records {
        let (n, got, saved) = read_blob(&mut db, key, 2048);
        assert_eq!(n, expected.len());
        assert_eq!(&got[..n], expected.as_slice());
        assert_eq!(saved.saved.len as usize, expected.len());
    }
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert!(fdb_kv_iterate(&mut db, &mut itr));
    assert_eq!(itr.iterated_cnt, 6);
    assert_eq!(fdb_kvdb_check(&mut db), OK);
}

#[test]
fn kvdb_test_fdb_scale_up() {
    let mut db = new_db();
    init(&mut db, 4);
    let records = put_many(&mut db, 4, 220);
    assert_eq!(fdb_kvdb_deinit(&mut db), OK);
    init(&mut db, 8);
    for (key, expected) in &records {
        let (n, got, saved) = read_blob(&mut db, key, 512);
        assert_eq!(n, expected.len());
        assert_eq!(&got[..n], expected.as_slice());
        assert_eq!(saved.saved.len as usize, expected.len());
    }
    assert_eq!(fdb_kvdb_check(&mut db), OK);
    let parent = unsafe { &*((&db as *const FdbKvdb).cast::<FdbDb>()) };
    assert_eq!(parent.max_size, 8192);
}

#[test]
fn kvdb_test_fdb_kvdb_set_default() {
    let mut db = new_db();
    init(&mut db, 4);
    assert_eq!(fdb_kv_set_default(&mut db), OK);
}

#[test]
fn kvdb_test_fdb_kvdb_deinit() {
    let mut db = new_db();
    init(&mut db, 4);
    assert_eq!(fdb_kvdb_deinit(&mut db), OK);
    assert_ne!(fdb_kvdb_check(&mut db), OK);
}
