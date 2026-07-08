#!/usr/bin/env python3
"""Generate a safe Rust FlashDB project scaffold from rust_api_design.json."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def module_names(design: dict[str, Any]) -> list[str]:
    raw = design.get("modules") or ["error"]
    names = [safe_rust_ident(item) for item in raw if isinstance(item, str)]
    if "error" not in names:
        names.insert(0, "error")
    return list(dict.fromkeys(names))


def safe_rust_ident(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not ident:
        ident = "module"
    if ident[0].isdigit():
        ident = f"module_{ident}"
    return ident


def c_symbol_suffix(name: str) -> str:
    return safe_rust_ident(name)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def generate_layout_probe(design: dict[str, Any]) -> str:
    facade = design.get("c_abi_facade")
    structs = facade.get("structs") if isinstance(facade, dict) else []
    if not isinstance(structs, list):
        structs = []
    lines = [
        "//! C ABI layout probe exports used by VERIFY_RUST_WITH_C_TESTS.",
        "//!",
        "//! The scaffold initializes these from rust_api_design.json so the symbols",
        "//! exist early. rust-implementer must replace constants with actual",
        "//! core::mem::size_of/align_of and offset calculations once FFI structs",
        "//! are implemented.",
        "",
        "pub const RUST_MISSING_FIELD_OFFSET: usize = usize::MAX;",
        "",
    ]
    for struct in structs:
        if not isinstance(struct, dict) or not isinstance(struct.get("c_name"), str):
            continue
        c_name = struct["c_name"]
        suffix = c_symbol_suffix(c_name)
        sizeof = struct.get("sizeof")
        alignof = struct.get("alignof")
        sizeof_value = sizeof if isinstance(sizeof, int) and sizeof >= 0 else 0
        alignof_value = alignof if isinstance(alignof, int) and alignof >= 0 else 0
        lines.extend(
            [
                "#[no_mangle]",
                f"pub extern \"C\" fn rust_sizeof_{suffix}() -> usize {{ {sizeof_value} }}",
                "",
                "#[no_mangle]",
                f"pub extern \"C\" fn rust_alignof_{suffix}() -> usize {{ {alignof_value} }}",
                "",
            ]
        )
        fields = struct.get("fields", [])
        if not isinstance(fields, list):
            fields = []
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                continue
            field_suffix = c_symbol_suffix(field["name"])
            offset = field.get("offset")
            offset_value = offset if isinstance(offset, int) and offset >= 0 else "RUST_MISSING_FIELD_OFFSET"
            lines.extend(
                [
                    "#[no_mangle]",
                    f"pub extern \"C\" fn rust_offsetof_{suffix}_{field_suffix}() -> usize {{ {offset_value} }}",
                    "",
                ]
            )
    if len(lines) == 7:
        lines.extend(
            [
                "#[no_mangle]",
                "pub extern \"C\" fn rust_layout_probe_available() -> usize { 1 }",
                "",
            ]
        )
    return "\n".join(str(line) for line in lines)


def generate_project(design: dict[str, Any], project: Path) -> None:
    crate_name = design.get("crate_name", "flashdb_rust")
    modules = module_names(design)

    write(
        project / "Cargo.toml",
        f"""
[package]
name = "{crate_name}"
version = "0.1.0"
edition = "2021"

[lib]
name = "flashdb_rust"
path = "src/lib.rs"
crate-type = ["rlib", "staticlib"]
""",
    )
    lib_lines = [f"pub mod {name};" for name in modules]
    if "c_abi" not in modules:
        lib_lines.append("pub mod c_abi;")
    if "ffi" not in modules:
        lib_lines.append("pub mod ffi;")
    lib_lines.append("pub use error::{Error, Result};")
    write(project / "src" / "lib.rs", "\n".join(lib_lines))

    write(
        project / "src" / "error.rs",
        """
use std::fmt::{Display, Formatter};

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    InvalidInput(String),
    OperationFailed(String),
}

impl Display for Error {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidInput(message) => write!(f, "invalid input: {message}"),
            Self::OperationFailed(message) => write!(f, "operation failed: {message}"),
        }
    }
}

impl std::error::Error for Error {}
""",
    )

    for module in modules:
        module_path = project / "src" / f"{module}.rs"
        if not module_path.exists():
            function_name = f"{safe_rust_ident(module)}_module_available"
            write(
                module_path,
                f"""
//! Module generated from rust_api_design.json.

pub fn {function_name}() -> bool {{
    true
}}
""",
            )

    write(
        project / "src" / "c_abi.rs",
        """
//! Temporary C ABI facade used by VERIFY_RUST_WITH_C_TESTS.
//!
//! The functions are exported so original FlashDB C tests can link against the
//! Rust crate. The rust-implementer stage must replace these stubs with calls
//! into the safe Rust implementation before the C cross-validation gate passes.

use std::ffi::{c_char, c_void};

#[repr(C)]
pub struct FdbBlobSaved {
    pub meta_addr: u32,
    pub addr: u32,
    pub len: usize,
}

#[repr(C)]
pub struct FdbBlob {
    pub buf: *mut c_void,
    pub size: usize,
    pub saved: FdbBlobSaved,
}

#[no_mangle]
pub extern "C" fn fdb_kvdb_init(
    _db: *mut c_void,
    _name: *const c_char,
    _path: *const c_char,
    _default_kv: *mut c_void,
    _user_data: *mut c_void,
) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_kvdb_control(_db: *mut c_void, _cmd: i32, _arg: *mut c_void) {}

#[no_mangle]
pub extern "C" fn fdb_kvdb_check(_db: *mut c_void) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_kvdb_deinit(_db: *mut c_void) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_tsdb_init(
    _db: *mut c_void,
    _name: *const c_char,
    _path: *const c_char,
    _get_time: *mut c_void,
    _max_len: usize,
    _user_data: *mut c_void,
) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_tsdb_control(_db: *mut c_void, _cmd: i32, _arg: *mut c_void) {}

#[no_mangle]
pub extern "C" fn fdb_tsdb_deinit(_db: *mut c_void) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_blob_make(blob: *mut FdbBlob, value_buf: *const c_void, buf_len: usize) -> *mut FdbBlob {
    if !blob.is_null() {
        unsafe {
            (*blob).buf = value_buf as *mut c_void;
            (*blob).size = buf_len;
            (*blob).saved.len = buf_len;
        }
    }
    blob
}

#[no_mangle]
pub extern "C" fn fdb_blob_read(_db: *mut c_void, _blob: *mut FdbBlob) -> usize {
    0
}

#[no_mangle]
pub extern "C" fn fdb_kv_set(_db: *mut c_void, _key: *const c_char, _value: *const c_char) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_kv_get(_db: *mut c_void, _key: *const c_char) -> *mut c_char {
    std::ptr::null_mut()
}

#[no_mangle]
pub extern "C" fn fdb_kv_set_blob(_db: *mut c_void, _key: *const c_char, _blob: *mut FdbBlob) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_kv_get_blob(_db: *mut c_void, _key: *const c_char, _blob: *mut FdbBlob) -> usize {
    0
}

#[no_mangle]
pub extern "C" fn fdb_kv_del(_db: *mut c_void, _key: *const c_char) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_kv_get_obj(_db: *mut c_void, _key: *const c_char, _kv: *mut c_void) -> *mut c_void {
    std::ptr::null_mut()
}

#[no_mangle]
pub extern "C" fn fdb_kv_to_blob(_kv: *mut c_void, blob: *mut FdbBlob) -> *mut FdbBlob {
    blob
}

#[no_mangle]
pub extern "C" fn fdb_kv_set_default(_db: *mut c_void) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_kv_print(_db: *mut c_void) {}

#[no_mangle]
pub extern "C" fn fdb_kv_iterator_init(_db: *mut c_void, itr: *mut c_void) -> *mut c_void {
    itr
}

#[no_mangle]
pub extern "C" fn fdb_kv_iterate(_db: *mut c_void, _itr: *mut c_void) -> bool {
    false
}

#[no_mangle]
pub extern "C" fn fdb_tsl_append(_db: *mut c_void, _blob: *mut FdbBlob) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_tsl_append_with_ts(_db: *mut c_void, _blob: *mut FdbBlob, _timestamp: i32) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_tsl_iter(_db: *mut c_void, _cb: *mut c_void, _cb_arg: *mut c_void) {}

#[no_mangle]
pub extern "C" fn fdb_tsl_iter_reverse(_db: *mut c_void, _cb: *mut c_void, _cb_arg: *mut c_void) {}

#[no_mangle]
pub extern "C" fn fdb_tsl_iter_by_time(
    _db: *mut c_void,
    _from: i32,
    _to: i32,
    _cb: *mut c_void,
    _cb_arg: *mut c_void,
) {
}

#[no_mangle]
pub extern "C" fn fdb_tsl_query_count(_db: *mut c_void, _from: i32, _to: i32, _status: i32) -> usize {
    0
}

#[no_mangle]
pub extern "C" fn fdb_tsl_max_blob_count(_db: *mut c_void) -> usize {
    0
}

#[no_mangle]
pub extern "C" fn fdb_tsl_set_status(_db: *mut c_void, _tsl: *mut c_void, _status: i32) -> i32 {
    0
}

#[no_mangle]
pub extern "C" fn fdb_tsl_clean(_db: *mut c_void) {}

#[no_mangle]
pub extern "C" fn fdb_tsl_to_blob(_tsl: *mut c_void, blob: *mut FdbBlob) -> *mut FdbBlob {
    blob
}

#[no_mangle]
pub extern "C" fn fdb_calc_crc32(crc: u32, _buf: *const c_void, _size: usize) -> u32 {
    crc
}
""",
    )

    write(project / "src" / "ffi" / "mod.rs", "pub mod layout_probe;\n")
    write(project / "src" / "ffi" / "layout_probe.rs", generate_layout_probe(design))

    (project / "tests").mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate flashDB_rust scaffold from rust_api_design.json.")
    parser.add_argument("--design", required=True, help="Path to rust_api_design.json.")
    parser.add_argument("--project", required=True, help="Path to output flashDB_rust directory.")
    args = parser.parse_args(argv)

    generate_project(load_json(Path(args.design)), Path(args.project))
    print("GENERATE_RUST_SCAFFOLD: SCAFFOLD_WRITTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
