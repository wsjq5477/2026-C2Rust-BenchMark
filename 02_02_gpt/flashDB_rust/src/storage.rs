//! In-process sidecar state for the C ABI facade.
//!
//! The C structs are caller-owned and intentionally remain ABI-shaped.  Rust
//! keeps ownership-sensitive values in this sidecar, keyed by the stable C
//! object address for the lifetime of an initialized database.

use std::collections::{BTreeMap, HashMap};
use std::sync::{Mutex, OnceLock};

#[derive(Clone, Default)]
pub struct KvRecord {
    pub value: Vec<u8>,
    pub addr: u32,
}

#[derive(Default)]
pub struct KvState {
    pub values: BTreeMap<String, KvRecord>,
    pub next_addr: u32,
    pub sec_size: u32,
    pub max_size: u32,
    pub scratch: HashMap<String, Vec<u8>>,
    pub writes: u32,
    pub oldest_addr: u32,
}

#[derive(Clone)]
pub struct TslRecord {
    pub status: i32,
    pub time: i32,
    pub value: Vec<u8>,
    pub index_addr: u32,
    pub log_addr: u32,
}

#[derive(Default)]
pub struct TsState {
    pub records: Vec<TslRecord>,
    pub next_addr: u32,
    pub sec_size: u32,
    pub max_size: u32,
}

#[derive(Default)]
pub struct Registry {
    pub kv: HashMap<usize, KvState>,
    pub ts: HashMap<usize, TsState>,
}

pub fn registry() -> &'static Mutex<Registry> {
    static REGISTRY: OnceLock<Mutex<Registry>> = OnceLock::new();
    REGISTRY.get_or_init(|| Mutex::new(Registry::default()))
}

pub fn with_registry<T>(f: impl FnOnce(&mut Registry) -> T) -> T {
    let mut guard = registry()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    f(&mut guard)
}
