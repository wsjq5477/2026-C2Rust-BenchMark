---
name: rust-compile-repair
description: Use when Rust build or test failures occur during staged FlashDB migration and the repair must be minimal and evidence-driven.
---

# Rust Compile Repair

## Scope

Use this Skill only after the orchestrator enters `BUILD_TEST_REPAIR`.

## BUILD_TEST_REPAIR contract

- classify compiler or test failures from captured cargo logs;
- make the smallest patch that addresses the observed error;
- rerun the failing command after each patch;
- record each repair attempt in `result/issues/repair_trace.jsonl`.

Required evidence:

- `logs/trace/cargo-build.log`;
- `logs/trace/cargo-test.log`;
- `logs/trace/cargo-results.json`;
- `logs/trace/08-build-test-repair.md`.

Do not remove tests, weaken assertions, hide errors, return constant success, or rewrite unrelated modules.
