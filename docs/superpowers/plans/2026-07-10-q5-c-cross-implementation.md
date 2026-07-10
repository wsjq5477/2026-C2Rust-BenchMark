# Q5 C-CROSS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute every registered original-C test invocation against the Rust staticlib, retain partial results, and continue the contest workflow when C-CROSS cannot fully pass.

**Architecture:** `build_c_model.py` becomes the authoritative producer of runner-aware invocation records. `c_cross_validate.py` consumes those records to build all test-side objects, infer required exported APIs from partial-link undefined symbols, execute each discovered runner, and write partial evidence. `gate.py` distinguishes evidence validity from the contest continuation decision; reports consume the same matrix without treating partial evidence as pass.

**Tech Stack:** Python 3 standard library, `unittest`, Cargo, system C compiler/linker, Markdown.

## Global Constraints

- Do not hardcode suite names, runner names, test counts, C API names, or exclusions.
- C-CROSS must never link a FlashDB C core implementation; only test-side objects, Rust staticlib, and required system libraries may link.
- Runtime agents may modify only `flashDB_rust/**`; platform failures are written by the controller to `logs/trace/c-cross/workbench-issues.jsonl`.
- All temporary C-CROSS files live under `logs/trace/c-cross/`.
- `CONTINUE_WITH_FAILURES` permits later contest stages but is never C-CROSS success.
- Preserve unrelated dirty files and do not stage or commit them.

---

### Task 1: Produce canonical runner-aware invocations

**Files:**
- Modify: `02_02/work/tools/build_c_model.py`
- Modify: `02_02/tests/test_conversion_system.py`

**Interfaces:**
- Produces `registered_test_invocations[]` with `suite`, `runner`, `test_function`, `invocation_index`, `runner_order`, `scenario_id`, `source_file`, and `source_line`.
- `runner` is the C file containing `TEST_RUN`, while `source_file` identifies the test implementation when known.

- [ ] **Step 1: Write failing model tests**

```python
record = model["registered_test_invocations"][0]
self.assertEqual("tests/main.c", record["runner"])
self.assertEqual("test_a", record["test_function"])
self.assertEqual(1, record["runner_order"])
self.assertEqual(17, record["source_line"])
self.assertNotIn("source_index", record)
```

- [ ] **Step 2: Run the exact model test and verify RED**

Run: `python3 -m unittest 02_02.tests.test_conversion_system.FrameworkCheckpointTests.<new_test> -v`

Expected: FAIL because the producer still emits `name`, `source_index`, and `scenarios`.

- [ ] **Step 3: Implement canonical extraction**

Replace the old record construction with a scanner over runner source text that records each `TEST_RUN` call’s physical line number and order. Resolve the function body’s source file from the scanned test-source index; retain a deterministic fallback to the runner file when it is local to the runner.

- [ ] **Step 4: Run the model test and full conversion test suite**

Run: `python3 -m unittest 02_02.tests.test_conversion_system -v`

Expected: PASS.

### Task 2: Execute all invocations and preserve partial outcomes

**Files:**
- Modify: `02_02/work/tools/c_cross_validate.py`
- Modify: `02_02/tests/test_conversion_system.py`

**Interfaces:**
- `build_matrix()` consumes `registered_test_invocations`, not `scorer_standard_cases`.
- A scenario row has `pass`, `fail`, `not_run`, `parse_failed`, or `unresolved`; `scorer_case_id` is optional.
- `parse_runner_test_results()` retains parsed pass/fail entries before a runner exit or timeout.

- [ ] **Step 1: Write failing validator tests**

```python
matrix = cross.build_matrix(root, trace)
self.assertEqual({"test_a", "test_b", "test_c"}, {row["scenario_id"] for row in matrix["scenarios"]})
self.assertEqual("pass", row_by_id["test_a"]["rust_impl_c_test"])
self.assertEqual("fail", row_by_id["test_b"]["rust_impl_c_test"])
self.assertEqual("not_run", row_by_id["test_c"]["rust_impl_c_test"])
self.assertNotIn("scorer_case_id", row_by_id["test_c"])
```

- [ ] **Step 2: Run the exact validator tests and verify RED**

Run: `python3 -m unittest 02_02.tests.test_conversion_system.FrameworkCheckpointTests.<new_test> -v`

Expected: FAIL because matrix construction reads `scorer_standard_cases` and requires `case_id`.

- [ ] **Step 3: Implement all-invocation matrix construction**

Build suite groups directly from canonical invocation records. Carry a lookup from scorer cases only to attach an optional association. Update runner parsing to use `test_function` plus `invocation_index`, preserving already-started pass/fail records when the process exits nonzero.

- [ ] **Step 4: Run the validator tests and full conversion test suite**

Run: `python3 -m unittest 02_02.tests.test_conversion_system -v`

Expected: PASS.

### Task 3: Build test-side closure and derive FFI manifest

**Files:**
- Modify: `02_02/work/tools/c_cross_validate.py`
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/generate_rust_scaffold.py` only if its manifest consumer needs the canonical fields

**Interfaces:**
- Produces `logs/trace/ffi_manifest.json` with `required_ffi_apis` derived from partial-link undefined symbols intersected with `c_api_model.json.public_api_symbols`.
- Runner linking consumes test-side objects plus Rust staticlib, never a C core source/object/library.

- [ ] **Step 1: Write failing closure/manifest tests**

```python
manifest = json.loads((trace / "ffi_manifest.json").read_text())
self.assertEqual(["fdb_api"], manifest["required_ffi_apis"])
self.assertIn("tests/test_impl.c", compile_log)
self.assertNotIn("src/fdb.c", link_command)
```

- [ ] **Step 2: Run the exact manifest test and verify RED**

Run: `python3 -m unittest 02_02.tests.test_conversion_system.FrameworkCheckpointTests.<new_test> -v`

Expected: FAIL because the current runner compiler accepts only a runner source and no undefined-symbol manifest is emitted.

- [ ] **Step 3: Implement test-side object closure**

Compile the runner, invocation source files, and discovered helper/framework sources to `logs/trace/c-cross/runners/<runner-id>/`. Perform `ld -r` or the platform-compatible linker equivalent, collect undefined symbols using an available system symbol tool, intersect them with public API symbols, and write the manifest. Link the same test-side object set against Rust staticlib.

- [ ] **Step 4: Run focused and full tests**

Run: `python3 -m unittest 02_02.tests.test_conversion_system -v`

Expected: PASS.

### Task 4: Implement continuation gate and platform issue evidence

**Files:**
- Modify: `02_02/work/tools/c_cross_validate.py`
- Modify: `02_02/work/tools/gate.py`
- Modify: `02_02/work/tools/report_writer.py`
- Modify: `02_02/tests/test_conversion_system.py`

**Interfaces:**
- Matrix fields: `stage_result` (`PASS` or `CONTINUE_WITH_FAILURES`) and `verification_result` (`pass`, `partial`, `failed`, `unresolved`).
- `check_verify_rust_with_c_tests()` validates evidence and accepts both stage results.
- Platform failures append records with `owner: "controller"` to `workbench-issues.jsonl`.

- [ ] **Step 1: Write failing continuation tests**

```python
errors = gate.check_verify_rust_with_c_tests(root)
self.assertEqual([], errors)
matrix = json.loads((trace / "validation-matrix.json").read_text())
self.assertEqual("CONTINUE_WITH_FAILURES", matrix["stage_result"])
self.assertEqual("partial", matrix["verification_result"])
issue = json.loads((trace / "c-cross" / "workbench-issues.jsonl").read_text().splitlines()[0])
self.assertEqual("controller", issue["owner"])
```

- [ ] **Step 2: Run the exact continuation test and verify RED**

Run: `python3 -m unittest 02_02.tests.test_conversion_system.FrameworkCheckpointTests.<new_test> -v`

Expected: FAIL because the current gate rejects any non-pass C-CROSS case and uses deferred evidence as a prerequisite.

- [ ] **Step 3: Implement soft continuation semantics**

Remove deferred/fingerprint gating from C-CROSS. Require complete scenario coverage and actionable non-pass evidence, calculate stage/verification results, and make parser/model/tool exceptions append a controller-owned issue. Keep `REPORT_AND_VERIFY` strict about reporting actual status, not about suppressing contest output.

- [ ] **Step 4: Run focused and full tests**

Run: `python3 -m unittest 02_02.tests.test_conversion_system -v`

Expected: PASS.

### Task 5: Synchronize workbench contracts and validate a real run

**Files:**
- Modify: `02_02/INSTRUCTION.md`
- Modify: `02_02/work/skills/flashdb-orchestrator.md`
- Modify: `02_02/work/skills/rust-implementer.md`
- Modify: `02_02/work/skills/test-migrator.md`
- Modify: `02_02/work/skills/repairer.md`
- Modify: matching `02_02/.opencode/skills/` mirrors
- Modify: `02_02/work/tools/report_writer.py`
- Modify: `02_02/tests/test_conversion_system.py`

**Interfaces:**
- Contracts say full invocation C-CROSS, trace-only C harnesses, controller-owned platform issues, and continuation after `CONTINUE_WITH_FAILURES`.

- [ ] **Step 1: Write failing contract tests**

```python
for path in contract_paths:
    text = path.read_text(encoding="utf-8")
    self.assertIn("CONTINUE_WITH_FAILURES", text)
    self.assertIn("workbench-issues.jsonl", text)
    self.assertNotIn("deferred.jsonl", text)
```

- [ ] **Step 2: Run contract tests and verify RED**

Run: `python3 -m unittest 02_02.tests.test_conversion_system.FrameworkCheckpointTests.<new_test> -v`

Expected: FAIL because the old contracts still require deferred evidence and block `MIGRATE_TESTS`.

- [ ] **Step 3: Update contracts and report wording**

Update every authoritative skill and its mirror in one change. State that partial C-CROSS is evidence, never proof of success, while subsequent contest stages still run. Report totals by result status and include controller platform issues.

- [ ] **Step 4: Run the complete unit suite and a fresh real C-CROSS command**

Run: `python3 -m unittest 02_02.tests.test_conversion_system -v`

Run: `cd 02_02 && python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace --mode full --attempt-kind checkpoint --trigger q5_validation`

Expected: unit suite passes; real command writes fresh compile/test logs, a full-invocation matrix, and an honest `PASS` or `CONTINUE_WITH_FAILURES` result.
