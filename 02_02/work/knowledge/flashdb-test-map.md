# FlashDB Test Map

## Purpose

This file records the stable target coverage for the later `MIGRATE_TESTS` checkpoint.

## Standard scenario counts

- KVDB: 13 scenarios
- TSDB: 11 scenarios
- Total: 24 scenarios

## Mapping principles

- Rust tests must preserve C test intent, not line-by-line syntax.
- Each migrated scenario must contain meaningful assertions.
- KVDB coverage must include init, set, get, update, delete, reload, and garbage collection behavior.
- TSDB coverage must include init, append, iteration, query, status, clean, reload, and deinit behavior.

The first framework checkpoint does not migrate tests.
