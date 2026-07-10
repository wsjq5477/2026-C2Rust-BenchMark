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


RUST_STRICT_KEYWORDS = frozenset({
    "as", "break", "const", "continue", "crate", "else", "enum", "extern",
    "false", "fn", "for", "if", "impl", "in", "let", "loop", "match", "mod",
    "move", "mut", "pub", "ref", "return", "self", "static", "struct",
    "super", "trait", "true", "type", "unsafe", "use", "where", "while",
    "async", "await", "dyn",
})


def safe_rust_ident(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not ident:
        ident = "module"
    if ident[0].isdigit():
        ident = f"module_{ident}"
    if ident in RUST_STRICT_KEYWORDS:
        ident = f"r#{ident}"
    return ident


def safe_external_ident(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not ident:
        ident = "item"
    if ident[0].isdigit():
        ident = f"item_{ident}"
    if ident in RUST_STRICT_KEYWORDS:
        ident = f"{ident}_"
    return ident


def c_symbol_suffix(name: str) -> str:
    return safe_external_ident(name)


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


def rust_field_type(field: dict[str, Any]) -> str:
    ctype = str(field.get("ctype", "")).strip()
    size = field.get("sizeof")
    name = str(field.get("name", "")).lower()
    if "void" in ctype and "*" in ctype:
        return "*mut std::ffi::c_void"
    if "char" in ctype and "*" in ctype:
        return "*mut std::ffi::c_char"
    if "bool" in ctype:
        return "bool"
    if "uint8_t" in ctype:
        return "u8"
    if "uint16_t" in ctype:
        return "u16"
    if "uint32_t" in ctype:
        return "u32"
    if "uint64_t" in ctype:
        return "u64"
    if "int8_t" in ctype:
        return "i8"
    if "int16_t" in ctype:
        return "i16"
    if "int32_t" in ctype or ctype == "int":
        return "i32"
    if "int64_t" in ctype:
        return "i64"
    if "storage" in name and size == 8:
        return "*mut std::ffi::c_void"
    if size == 1:
        return "u8"
    if size == 2:
        return "u16"
    if size == 4:
        return "u32"
    if size == 8:
        return "u64"
    return f"[u8; {size if isinstance(size, int) and size > 0 else 1}]"


def generate_c_types(design: dict[str, Any]) -> str:
    lines = [
        "//! Typed C ABI structs generated from rust_api_design.json.",
        "",
        "#![allow(non_camel_case_types)]",
        "",
    ]
    type_alias_lines = collect_type_aliases(design)
    for alias_line in type_alias_lines:
        lines.append(alias_line)
    if type_alias_lines:
        lines.append("")
    for struct in facade_structs(design):
        rust_name = safe_rust_type(str(struct.get("rust_name") or struct["c_name"]), "CAbiStruct")
        fields = struct.get("fields", [])
        if not isinstance(fields, list):
            fields = []
        sorted_fields = sorted(
            [
                field
                for field in fields
                if isinstance(field, dict)
                and isinstance(field.get("name"), str)
                and isinstance(field.get("offset"), int)
                and isinstance(field.get("sizeof"), int)
            ],
            key=lambda field: (field["offset"], field["name"]),
        )
        lines.extend(["#[repr(C)]", f"pub struct {rust_name} {{"])
        cursor = 0
        pad_index = 0
        for field in sorted_fields:
            offset = int(field["offset"])
            size = int(field["sizeof"])
            if offset > cursor:
                lines.append(f"    pub _pad_{pad_index}: [u8; {offset - cursor}],")
                pad_index += 1
                cursor = offset
            field_name = safe_rust_ident(field["name"])
            lines.append(f"    pub {field_name}: {rust_field_type(field)},")
            cursor = max(cursor, offset + max(size, 0))
        sizeof = struct.get("sizeof")
        if isinstance(sizeof, int) and sizeof > cursor:
            lines.append(f"    pub _pad_{pad_index}: [u8; {sizeof - cursor}],")
        if not sorted_fields:
            lines.append("    pub _layout_unresolved: [u8; 1],")
        lines.extend(["}", ""])
    if len(lines) == 4:
        lines.extend(["#[repr(C)]", "pub struct CAbiUnavailable {", "    pub _unused: u8,", "}", ""])
    return "\n".join(lines)


def collect_type_aliases(design: dict[str, Any]) -> list[str]:
    struct_names = {safe_rust_type(str(s.get("rust_name") or s.get("c_name", "")), "CAbiStruct") for s in facade_structs(design)}
    facade = design.get("c_abi_facade")
    type_map = facade.get("c_type_map") if isinstance(facade, dict) else None
    resolved = type_map.get("resolved") if isinstance(type_map, dict) else None
    needed: dict[str, str] = {}
    if isinstance(resolved, dict):
        for key, entry in resolved.items():
            if not isinstance(entry, dict):
                continue
            rust_ffi_type = str(entry.get("rust_ffi_type") or "").strip()
            category = str(entry.get("category") or "")
            if not rust_ffi_type or rust_ffi_type in struct_names:
                continue
            if rust_ffi_type.startswith("*") or rust_ffi_type in ("()", "bool", "i32", "i64", "u32", "u64", "u8", "u16", "usize", "std::ffi::c_int", "std::ffi::c_char", "std::ffi::c_void"):
                continue
            if "alias:" in category or "enum:" in category or "status_code" in category:
                underlying = "u32"
                if "status_code" in category:
                    underlying = "i32"
                elif "i64" in rust_ffi_type.lower():
                    underlying = "i64"
                elif "u64" in rust_ffi_type.lower():
                    underlying = "u64"
                needed[rust_ffi_type] = underlying
    functions = facade.get("functions") if isinstance(facade, dict) else []
    if isinstance(functions, list):
        for func in functions:
            if not isinstance(func, dict):
                continue
            return_info = func.get("return")
            if isinstance(return_info, dict):
                rt = str(return_info.get("rust_ffi_type") or "").strip()
                if rt and rt not in struct_names and rt not in ("()", "bool", "i32", "i64", "u32", "u64", "u8", "u16", "usize", "std::ffi::c_int", "*mut std::ffi::c_void", "*const std::ffi::c_void", "*mut std::ffi::c_char", "*const std::ffi::c_char") and not rt.startswith("*"):
                    if rt not in needed:
                        needed[rt] = "u32"
            params = func.get("params")
            if isinstance(params, list):
                for param in params:
                    if not isinstance(param, dict):
                        continue
                    pt = str(param.get("rust_ffi_type") or "").strip()
                    if pt and pt not in struct_names and pt not in ("()", "bool", "i32", "i64", "u32", "u64", "u8", "u16", "usize", "std::ffi::c_int", "*mut std::ffi::c_void", "*const std::ffi::c_void", "*mut std::ffi::c_char", "*const std::ffi::c_char") and not pt.startswith("*"):
                        if pt not in needed:
                            needed[pt] = "u32"
    alias_lines: list[str] = []
    for alias_name in sorted(needed):
        alias_lines.append(f"pub type {alias_name} = {needed[alias_name]};")
    return alias_lines


def facade_functions(design: dict[str, Any]) -> list[dict[str, Any]]:
    facade = design.get("c_abi_facade")
    functions = facade.get("functions") if isinstance(facade, dict) else []
    return [
        item
        for item in functions
        if isinstance(item, dict) and isinstance(item.get("rust_export"), str)
    ] if isinstance(functions, list) else []


def neutral_return(rust_type: str, struct_names: set[str] | None = None) -> str:
    stripped = rust_type.strip()
    if stripped == "()":
        return ""
    if stripped == "bool":
        return "false"
    if stripped.startswith("*const"):
        return "std::ptr::null()"
    if stripped.startswith("*mut"):
        return "std::ptr::null_mut()"
    if struct_names and stripped in struct_names:
        return f"unsafe {{ core::mem::zeroed::<{stripped}>() }}"
    if stripped in ("i32", "std::ffi::c_int"):
        return "0"
    if stripped in ("usize", "u32", "u64", "i64", "u8", "u16", "i8", "i16"):
        return "0"
    return "0"


def generate_typed_c_abi(design: dict[str, Any]) -> str:
    lines = [
        "//! Typed C ABI facade generated from rust_api_design.json.",
        "",
        "#![allow(unused_variables)]",
        "",
        "use super::c_types::*;",
        "",
    ]
    struct_names = {safe_rust_type(str(s.get("rust_name") or s.get("c_name", "")), "CAbiStruct") for s in facade_structs(design)}
    type_aliases = collect_type_aliases(design)
    for alias_line in type_aliases:
        lines.append(alias_line)
    if type_aliases:
        lines.append("")
    functions = facade_functions(design)
    if not functions:
        lines.extend(["#[no_mangle]", "pub extern \"C\" fn rust_c_abi_facade_available() -> usize { 1 }", ""])
        return "\n".join(lines)
    for function in functions:
        export = safe_external_ident(function["rust_export"])
        raw_params = function.get("params", [])
        params: list[str] = []
        if isinstance(raw_params, list):
            for index, param in enumerate(raw_params):
                if not isinstance(param, dict):
                    continue
                name = safe_rust_ident(str(param.get("name") or f"arg{index}"))
                rust_type = str(param.get("rust_ffi_type") or "*mut std::ffi::c_void")
                params.append(f"{name}: {rust_type}")
        return_info = function.get("return")
        return_type = str(return_info.get("rust_ffi_type", "()")) if isinstance(return_info, dict) else "()"
        value = neutral_return(return_type, struct_names)
        lines.extend(["#[no_mangle]"])
        if return_type == "()":
            lines.extend([f"pub extern \"C\" fn {export}({', '.join(params)}) {{", "}"])
        else:
            lines.extend([f"pub extern \"C\" fn {export}({', '.join(params)}) -> {return_type} {{", f"    {value}", "}"])
        lines.append("")
    return "\n".join(lines)


def generate_c_abi_facade(design: dict[str, Any]) -> str:
    lines = [
        "//! Compatibility re-export for the typed C ABI facade.",
        "",
        "pub use crate::ffi::c_abi::*;",
        "",
    ]
    return "\n".join(lines)


def generate_layout_probe(design: dict[str, Any]) -> str:
    facade = design.get("c_abi_facade")
    structs = facade.get("structs") if isinstance(facade, dict) else []
    if not isinstance(structs, list):
        structs = []
    lines = [
        "//! C ABI layout probe exports used by VERIFY_RUST_WITH_C_TESTS.",
        "",
        "use super::c_types::*;",
        "use core::mem::offset_of;",
        "",
        "pub const RUST_MISSING_FIELD_OFFSET: usize = usize::MAX;",
        "",
    ]
    for struct in structs:
        if not isinstance(struct, dict) or not isinstance(struct.get("c_name"), str):
            continue
        c_name = struct["c_name"]
        suffix = c_symbol_suffix(c_name)
        rust_name = safe_rust_type(str(struct.get("rust_name") or c_name), "CAbiStruct")
        lines.extend(
            [
                "#[no_mangle]",
                f"pub extern \"C\" fn rust_sizeof_{suffix}() -> usize {{ core::mem::size_of::<{rust_name}>() }}",
                "",
                "#[no_mangle]",
                f"pub extern \"C\" fn rust_alignof_{suffix}() -> usize {{ core::mem::align_of::<{rust_name}>() }}",
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
            field_name = safe_rust_ident(field["name"])
            lines.extend(
                [
                    "#[no_mangle]",
                    f"pub extern \"C\" fn rust_offsetof_{suffix}_{field_suffix}() -> usize {{ offset_of!({rust_name}, {field_name}) }}",
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

    write(project / "src" / "ffi" / "mod.rs", "pub mod c_types;\npub mod c_abi;\npub mod layout_probe;\n")
    write(project / "src" / "ffi" / "c_types.rs", generate_c_types(design))
    write(project / "src" / "ffi" / "c_abi.rs", generate_typed_c_abi(design))
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
