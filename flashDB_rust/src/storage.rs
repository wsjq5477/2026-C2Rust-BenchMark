//! Generated sidecar registry for caller-owned C objects.
//!
//! Domain modules define their own state values. The registry only fixes the
//! ownership boundary: a non-null C object address identifies Rust-owned state
//! until the matching deinit removes it.

use std::collections::HashMap;

#[derive(Debug, Default)]
pub struct SidecarRegistry<T> {
    entries: HashMap<usize, T>,
}

impl<T> SidecarRegistry<T> {
    pub fn new() -> Self {
        Self {
            entries: HashMap::new(),
        }
    }

    pub fn key_for<C>(object: *const C) -> Option<usize> {
        (!object.is_null()).then_some(object as usize)
    }

    pub fn insert<C>(&mut self, object: *const C, state: T) -> Option<T> {
        Self::key_for(object).and_then(|key| self.entries.insert(key, state))
    }

    pub fn get<C>(&self, object: *const C) -> Option<&T> {
        Self::key_for(object).and_then(|key| self.entries.get(&key))
    }

    pub fn get_mut<C>(&mut self, object: *const C) -> Option<&mut T> {
        Self::key_for(object).and_then(|key| self.entries.get_mut(&key))
    }

    pub fn remove<C>(&mut self, object: *const C) -> Option<T> {
        Self::key_for(object).and_then(|key| self.entries.remove(&key))
    }
}
