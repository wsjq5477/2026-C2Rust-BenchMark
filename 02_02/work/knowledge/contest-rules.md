# Contest Rules

## Input

Primary platform input path:

```text
/app/code/judge-assets/02_02_c_to_rust/code/FlashDB
```

Local fallback candidates for development:

```text
judge-assets/code/FlashDB
../judge-assets/code/FlashDB
```

## Final output

The complete migration must eventually generate:

```text
flashDB_rust/
├── Cargo.toml
├── src/
└── tests/
```

The first framework checkpoint must not generate this directory.

## Hard constraints

- Do not modify platform-provided FlashDB source or tests.
- Do not submit only compiled binaries.
- Do not preinstall or prebuild a fake `flashDB_rust`.
- Final Rust project must build with `cargo build`.
- Final Rust tests must pass with `cargo test`.
- Unsafe ratio must stay below 10%.
