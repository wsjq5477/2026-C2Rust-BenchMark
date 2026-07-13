//! Cross-module observable invariants for the generated C ABI facade.

use flashdb_rust::common::crc32;
use flashdb_rust::ffi::c_abi::{fdb_blob_make, fdb_calc_crc32};
use flashdb_rust::ffi::c_types::FdbBlob;

#[test]
fn crc32_c_abi_matches_safe_incremental_calculation() {
    let bytes = b"FlashDB migration equivalence";
    let safe = crc32(0, bytes);
    let ffi = fdb_calc_crc32(0, bytes.as_ptr().cast(), bytes.len());
    assert_eq!(ffi, safe);
    assert_eq!(
        fdb_calc_crc32(0, bytes[..8].as_ptr().cast(), 8),
        crc32(0, &bytes[..8])
    );
}

#[test]
fn blob_make_preserves_the_caller_buffer_shape() {
    let mut data = b"opaque bytes".to_vec();
    let mut blob: FdbBlob = unsafe { std::mem::zeroed() };
    assert_eq!(
        fdb_blob_make(&mut blob, data.as_mut_ptr().cast(), data.len()),
        &mut blob as *mut FdbBlob
    );
    assert_eq!(blob.size as usize, data.len());
    assert_eq!(blob.buf.cast::<u8>(), data.as_mut_ptr());
}
