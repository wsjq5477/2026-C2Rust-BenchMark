# FlashDB Test Map

## Purpose

This file records the stable target coverage for the later `MIGRATE_TESTS` checkpoint.

## Scenario source of truth

- Do not hardcode a fixed KVDB, TSDB, or total scenario count.
- `BUILD_C_MODEL` extracts the executable scenario set from the current C input.
- `logs/trace/c_test_model.json.standard_scenarios` is the source of truth for the current run.
- Rust tests and `rust_test_mapping.json.scenarios` must match those extracted scenario IDs one-to-one.

## Mapping principles

- Rust tests must preserve C test intent, not line-by-line syntax.
- Each migrated scenario must contain meaningful assertions.
- Generated baseline tests are marked `MIGRATION_PENDING` and do not count as semantic coverage.
- A scenario may use `coverage: semantic` only after its C calls and assertions in `semantic_facts` are reflected in the Rust test.
- KVDB coverage must include init, set, get, update, delete, reload, and garbage collection behavior.
- TSDB coverage must include init, append, iteration, query, status, clean, reload, and deinit behavior.

The first framework checkpoint does not migrate tests.
