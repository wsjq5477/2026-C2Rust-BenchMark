#!/usr/bin/env python3
"""Generate a safe Rust FlashDB project scaffold from rust_api_design.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def module_names(design: dict[str, Any]) -> list[str]:
    raw = design.get("modules") or ["error", "flash", "kvdb", "tsdb"]
    names = [item for item in raw if isinstance(item, str)]
    for required in ["error", "flash", "kvdb", "tsdb"]:
        if required not in names:
            names.append(required)
    return list(dict.fromkeys(names))


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
    lib_lines.extend(
        [
            "pub use error::{FdbError, Result};",
            "pub use flash::{FileFlash, FlashStorage, MemFlash};",
            "pub use kvdb::KvDb;",
            "pub use tsdb::{TsDb, TslRecord};",
        ]
    )
    write(project / "src" / "lib.rs", "\n".join(lib_lines))

    write(
        project / "src" / "error.rs",
        """
use std::fmt::{Display, Formatter};

pub type Result<T> = std::result::Result<T, FdbError>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FdbError {
    NotFound,
    InvalidInput(String),
    Io(String),
}

impl Display for FdbError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotFound => write!(f, "not found"),
            Self::InvalidInput(message) => write!(f, "invalid input: {message}"),
            Self::Io(message) => write!(f, "io error: {message}"),
        }
    }
}

impl std::error::Error for FdbError {}
""",
    )

    write(
        project / "src" / "flash.rs",
        """
use crate::{FdbError, Result};
use std::fs;
use std::path::{Path, PathBuf};

pub trait FlashStorage {
    fn read_all(&self) -> Result<Vec<u8>>;
    fn write_all(&mut self, bytes: &[u8]) -> Result<()>;
    fn erase(&mut self) -> Result<()>;
}

#[derive(Debug, Clone, Default)]
pub struct MemFlash {
    data: Vec<u8>,
}

impl MemFlash {
    pub fn new() -> Self {
        Self { data: Vec::new() }
    }
}

impl FlashStorage for MemFlash {
    fn read_all(&self) -> Result<Vec<u8>> {
        Ok(self.data.clone())
    }

    fn write_all(&mut self, bytes: &[u8]) -> Result<()> {
        self.data.extend_from_slice(bytes);
        Ok(())
    }

    fn erase(&mut self) -> Result<()> {
        self.data.clear();
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct FileFlash {
    path: PathBuf,
}

impl FileFlash {
    pub fn new(path: impl AsRef<Path>) -> Self {
        Self { path: path.as_ref().to_path_buf() }
    }
}

impl FlashStorage for FileFlash {
    fn read_all(&self) -> Result<Vec<u8>> {
        match fs::read(&self.path) {
            Ok(bytes) => Ok(bytes),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
            Err(error) => Err(FdbError::Io(error.to_string())),
        }
    }

    fn write_all(&mut self, bytes: &[u8]) -> Result<()> {
        fs::write(&self.path, bytes).map_err(|error| FdbError::Io(error.to_string()))
    }

    fn erase(&mut self) -> Result<()> {
        fs::write(&self.path, []).map_err(|error| FdbError::Io(error.to_string()))
    }
}
""",
    )

    write(
        project / "src" / "kvdb.rs",
        """
use crate::{FlashStorage, Result};
use std::collections::HashMap;

#[derive(Debug, Default)]
pub struct KvDb {
    values: HashMap<String, Vec<u8>>,
}

impl KvDb {
    pub fn open<S: FlashStorage>(_storage: S) -> Result<Self> {
        Ok(Self { values: HashMap::new() })
    }

    pub fn set(&mut self, key: impl Into<String>, value: impl Into<String>) -> Result<()> {
        self.values.insert(key.into(), value.into().into_bytes());
        Ok(())
    }

    pub fn get(&self, key: &str) -> Result<Option<String>> {
        Ok(self.values.get(key).map(|bytes| String::from_utf8_lossy(bytes).into_owned()))
    }

    pub fn set_blob(&mut self, key: impl Into<String>, value: impl AsRef<[u8]>) -> Result<()> {
        self.values.insert(key.into(), value.as_ref().to_vec());
        Ok(())
    }

    pub fn get_blob(&self, key: &str) -> Result<Option<Vec<u8>>> {
        Ok(self.values.get(key).cloned())
    }

    pub fn delete(&mut self, key: &str) -> Result<()> {
        self.values.remove(key);
        Ok(())
    }

    pub fn reload(&mut self) -> Result<()> {
        Ok(())
    }

    pub fn gc(&mut self) -> Result<()> {
        Ok(())
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &[u8])> {
        self.values.iter().map(|(key, value)| (key.as_str(), value.as_slice()))
    }
}
""",
    )

    write(
        project / "src" / "tsdb.rs",
        """
use crate::Result;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TslRecord {
    pub timestamp: u64,
    pub payload: Vec<u8>,
    pub status: u8,
}

#[derive(Debug, Default)]
pub struct TsDb {
    records: Vec<TslRecord>,
}

impl TsDb {
    pub fn open() -> Result<Self> {
        Ok(Self { records: Vec::new() })
    }

    pub fn append(&mut self, timestamp: u64, payload: impl AsRef<[u8]>) -> Result<()> {
        self.records.push(TslRecord {
            timestamp,
            payload: payload.as_ref().to_vec(),
            status: 0,
        });
        Ok(())
    }

    pub fn iter(&self) -> impl Iterator<Item = &TslRecord> {
        self.records.iter()
    }

    pub fn query_by_time(&self, from: u64, to: u64) -> Result<Vec<TslRecord>> {
        Ok(self.records.iter().filter(|item| item.timestamp >= from && item.timestamp <= to).cloned().collect())
    }

    pub fn set_status(&mut self, timestamp: u64, status: u8) -> Result<()> {
        for record in &mut self.records {
            if record.timestamp == timestamp {
                record.status = status;
            }
        }
        Ok(())
    }

    pub fn clean(&mut self) -> Result<()> {
        self.records.retain(|record| record.status == 0);
        Ok(())
    }

    pub fn reload(&mut self) -> Result<()> {
        Ok(())
    }
}
""",
    )

    for module in modules:
        module_path = project / "src" / f"{module}.rs"
        if not module_path.exists():
            write(module_path, "//! Support module generated from rust_api_design.json.\n")

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
