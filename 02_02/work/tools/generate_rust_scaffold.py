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


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


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
""",
    )
    lib_lines = [f"pub mod {name};" for name in modules]
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
