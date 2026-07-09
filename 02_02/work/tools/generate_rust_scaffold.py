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


def safe_rust_type(name: str, fallback: str = "GeneratedType") -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    value = "".join(part[:1].upper() + part[1:] for part in parts)
    if not value:
        value = fallback
    if value[0].isdigit():
        value = f"{fallback}{value}"
    return value


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def error_variants(design: dict[str, Any]) -> list[str]:
    model = design.get("error_model")
    variants: list[str] = []
    if isinstance(model, dict):
        raw_variants = model.get("variants")
        if isinstance(raw_variants, list):
            for item in raw_variants:
                if isinstance(item, str):
                    variants.append(safe_rust_type(item, "ErrorVariant"))
                elif isinstance(item, dict) and isinstance(item.get("name"), str):
                    variants.append(safe_rust_type(item["name"], "ErrorVariant"))
        raw_statuses = model.get("status_values") or model.get("enum_values")
        if isinstance(raw_statuses, list):
            for item in raw_statuses:
                if isinstance(item, str):
                    variants.append(safe_rust_type(item, "Status"))
    if not variants:
        variants.append("Message")
    return list(dict.fromkeys(variants))


def generate_error_module(design: dict[str, Any]) -> str:
    variants = error_variants(design)
    variant_lines = "\n".join(f"    {variant}(String)," for variant in variants)
    match_lines = "\n".join(
        f'            Self::{variant}(message) => write!(f, "{safe_rust_ident(variant)}: {{message}}"),'
        for variant in variants
    )
    return f"""
use std::fmt::{{Display, Formatter}};

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {{
{variant_lines}
}}

impl Display for Error {{
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {{
        match self {{
{match_lines}
        }}
    }}
}}

impl std::error::Error for Error {{}}
"""


def facade_structs(design: dict[str, Any]) -> list[dict[str, Any]]:
    facade = design.get("c_abi_facade")
    structs = facade.get("structs") if isinstance(facade, dict) else []
    if not isinstance(structs, list):
        return []
    return [
        item
        for item in structs
        if isinstance(item, dict) and isinstance(item.get("c_name"), str)
    ]


def c_abi_symbols(design: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    mapping = design.get("c_to_rust_symbol_map")
    if isinstance(mapping, dict):
        symbols.extend(key for key in mapping if isinstance(key, str))
    for key, value in design.items():
        if not key.endswith("_api") or not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            raw_symbols = item.get("c_symbols")
            if isinstance(raw_symbols, list):
                symbols.extend(symbol for symbol in raw_symbols if isinstance(symbol, str))
    return [
        symbol
        for symbol in sorted(dict.fromkeys(symbols))
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol)
    ]


def generate_c_abi_facade(design: dict[str, Any]) -> str:
    lines = [
        "//! Temporary C ABI facade used by VERIFY_RUST_WITH_C_TESTS.",
        "//!",
        "//! Exports are derived from rust_api_design.json. The rust-implementer",
        "//! stage must replace these generic placeholders with typed ABI wrappers",
        "//! backed by the safe Rust implementation before the C cross-validation",
        "//! gate can pass.",
        "",
        "use std::ffi::c_void;",
        "",
    ]
    for struct in facade_structs(design):
        rust_name = safe_rust_type(str(struct.get("rust_name") or struct["c_name"]), "CAbiStruct")
        sizeof = struct.get("sizeof")
        size = sizeof if isinstance(sizeof, int) and sizeof > 0 else 1
        lines.extend(
            [
                "#[repr(C)]",
                f"pub struct {rust_name} {{",
                f"    _opaque: [u8; {size}],",
                "}",
                "",
            ]
        )
    symbols = c_abi_symbols(design)
    if not symbols:
        lines.extend(
            [
                "#[no_mangle]",
                "pub extern \"C\" fn rust_c_abi_facade_available() -> usize { 1 }",
                "",
            ]
        )
    for symbol in symbols:
        lines.extend(
            [
                "#[no_mangle]",
                f"pub extern \"C\" fn {symbol}() -> *mut c_void {{",
                "    std::ptr::null_mut()",
                "}",
                "",
            ]
        )
    return "\n".join(lines)


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

    write(project / "src" / "error.rs", generate_error_module(design))

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

    write(project / "src" / "c_abi.rs", generate_c_abi_facade(design))

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
