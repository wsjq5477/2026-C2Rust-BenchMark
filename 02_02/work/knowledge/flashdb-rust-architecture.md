# FlashDB Rust Architecture

## Purpose

This file records the intended Rust architecture for later migration checkpoints.

## Target modules

```text
flashDB_rust/
├── Cargo.toml
├── src/
│   ├── lib.rs
│   ├── error.rs
│   ├── flash.rs
│   ├── kvdb.rs
│   └── tsdb.rs
└── tests/
    ├── kvdb_tests.rs
    ├── tsdb_tests.rs
    └── equivalence_tests.rs
```

## Core types

- `FlashStorage`
- `MemFlash`
- `FileFlash`
- `FdbError`
- `KvDb`
- `TsDb`
- `TslRecord`

## Semantic principles

- Prefer safe Rust.
- Use `HashMap` only as a runtime index.
- Preserve record append semantics.
- Represent delete as tombstone behavior.
- Reload must scan storage and rebuild state.
- Garbage collection must retain latest valid records.

The first framework checkpoint does not generate Rust source.
