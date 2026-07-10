# C-Cross Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Q4 revision so C-cross reports real per-test results, supports dynamic suite checkpoints, records convergence attempts and deferred failures, permits evidence-complete intermediate continuation, and remains strict at final verification.

**Architecture:** Keep `c_cross_validate.py` as the deterministic compile/layout/link/run engine. Add pure parsing and comparison helpers so runner output becomes per-test evidence and each execution can be compared with the prior matrix. Keep intermediate and final policy separate in `gate.py`: intermediate verification may complete only after failures are either resolved or backed by three no-progress attempts, while final reporting always requires a fresh all-suite full/pass matrix.

**Tech Stack:** Python 3 standard library, `unittest`, Cargo, system C compiler, Markdown contracts.

## Global Constraints

- Do not hardcode suite names, test counts, function names, or the five locally observed failures in workbench logic.
- Runtime agents may edit only their authorized `flashDB_rust/**`, `logs/**`, and `result/**` paths; they must not edit `INSTRUCTION.md`, `work/**`, `.opencode/**`, `tests/**`, `design_doc/**`, or platform C input.
- Preserve the existing real Rust staticlib, compiler-backed layout, C runner link, and runner execution chain.
- Intermediate C-cross may continue with evidence-complete deferred failures; final C-cross must be all-suite, full, fresh, parseable, and entirely pass.
- A failure fingerprint is `failure_layer + suite + source_test + normalized assertion/error`.
- A fingerprint becomes deferred only after three consecutive comparable no-progress repair attempts.
- Do not add wall-clock budget logic or a fixed pass-ratio threshold.
- Do not add Clang/libclang, network, Docker, or non-standard Python dependencies.
- Preserve pre-existing dirty work; do not stage, commit, or revert unrelated changes.

---

### Task 1: Parse Real Per-Test Runner Results

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/c_cross_validate.py`

**Interfaces:**
- Consumes: `registered_test_invocations`, suite runner combined output, runner exit code.
- Produces: `parse_runner_test_results(output: str, expected_tests: list[str], exit_code: int) -> dict[str, Any]` with `status`, `started`, `passed`, `failed`, `not_run`, `failures`, and `reason`.
- Produces: one scenario row per source test with a real `rust_impl_c_test` value instead of a copied suite value.

- [ ] **Step 1: Add failing parser tests**

Add tests covering:

```python
def test_c_cross_parses_partial_suite_results_per_test(self):
    result = cross.parse_runner_test_results(
        "Running: test_a ...\nRunning: test_b ...\nFAIL test_b: assertion (line 9)\n",
        ["test_a", "test_b", "test_c"],
        1,
    )
    self.assertEqual(["test_a"], result["passed"])
    self.assertEqual(["test_b"], result["failed"])
    self.assertEqual(["test_c"], result["not_run"])

def test_c_cross_rejects_unknown_or_ambiguous_test_output(self):
    result = cross.parse_runner_test_results(
        "Running: unknown_test ...\n",
        ["test_a"],
        1,
    )
    self.assertEqual("parse_failed", result["status"])
```

Also cover duplicate starts, a zero exit with missing expected tests, and a nonzero exit with no attributable failure.

- [ ] **Step 2: Run parser tests and verify RED**

Run the exact discovered unittest names. Expected: failure because `parse_runner_test_results` does not exist.

- [ ] **Step 3: Implement strict output parsing**

Implement regex-based parsing for current-input test names without fixed FlashDB names. Normalize whitespace in assertion text, retain exact raw failure text in evidence, and fail closed when expected/started/failed/not-run sets cannot be reconciled.

- [ ] **Step 4: Replace suite-wide runtime status copying**

Use parsed test results when building scenario rows. A suite runtime crash without attributable test evidence must create `c_runner_runtime_failed` at suite diagnostic level and `c_cross_result_parse_failed` for ambiguous case rows; it must not mark every case as a confirmed test failure.

- [ ] **Step 5: Run parser and existing harness tests**

Expected: real per-test tests pass; existing compile/layout/link harness tests remain green.

---

### Task 2: Add Dynamic Suite Checkpoints

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/c_cross_validate.py`

**Interfaces:**
- Consumes: suite values dynamically derived from `scorer_standard_cases` and registered invocations.
- Produces: `build_matrix(..., selected_suites: set[str] | None = None, attempt_kind: str = "checkpoint", trigger: str = "manual", changed_files: list[str] | None = None)`.
- CLI flags: repeatable `--suite`, `--attempt-kind`, `--trigger`, repeatable `--changed-file`.
- Matrix fields: `scope`, `selected_suites`, `attempt_kind`, `trigger`.

- [ ] **Step 1: Add failing suite-selection tests**

Create a fixture with two dynamically named suites and assert selecting one suite compiles/runs only its discovered runner and emits only its scenarios. Add a test proving an unknown requested suite is rejected rather than silently ignored.

- [ ] **Step 2: Run suite-selection tests and verify RED**

Expected: failure because `selected_suites` and CLI flags are unsupported.

- [ ] **Step 3: Implement suite filtering**

Filter cases only after validating requested suite names against suites derived from the current model. Set `scope` to `selected` when a suite filter is present and `all` otherwise. Keep default behavior backward-compatible as all suites.

- [ ] **Step 4: Preserve checkpoint evidence**

Write an immutable snapshot of each matrix under `logs/trace/c-cross/checkpoints/` using a stable execution id before replacing the latest `validation-matrix.json`. Do not use suite or test names as fixed filenames without identifier sanitization.

- [ ] **Step 5: Run suite and harness tests**

Expected: selected-suite tests pass; default full run still covers every scorer case.

---

### Task 3: Record Fingerprints, Progress, and Deferred Failures

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/c_cross_validate.py`

**Interfaces:**
- Produces: `failure_fingerprint(row: dict[str, Any]) -> str`.
- Produces: `compare_attempt(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]`.
- Writes: `logs/trace/c-cross/attempts.jsonl` and `logs/trace/c-cross/deferred.jsonl`.
- Attempt fields: `attempt_id`, `kind`, `trigger`, `suite`, `changed_files`, `before`, `after`, `fingerprints_before`, `fingerprints_after`, `progress`, `no_progress_counts`, `next_action`, `matrix_snapshot`.

- [ ] **Step 1: Add failing convergence tests**

Cover these transitions:

```text
same assertion after repair -> no_progress_count increments
fail -> later assertion -> progress and old fingerprint count resets
fail -> pass -> progress
A -> B -> A cycle -> no progress for recurring A
third consecutive no-progress -> deferred
related implementation change plus new evidence -> deferred reactivated
```

Also assert a `repair` attempt rejects `changed_files` outside `flashDB_rust/**`.

- [ ] **Step 2: Run convergence tests and verify RED**

Expected: failure because fingerprint and attempt APIs do not exist.

- [ ] **Step 3: Implement normalized fingerprints**

Normalize volatile paths, addresses, and whitespace without deleting the test name, failure layer, or assertion identity. Keep raw text beside the normalized fingerprint for diagnosis.

- [ ] **Step 4: Implement attempt comparison**

Treat pass-set growth, later failure layer, or changed assertion within the same source test as progress. Treat regression, unchanged fingerprint, and A/B/A recurrence as no progress. A confirmation run is recorded but does not consume a repair count.

- [ ] **Step 5: Implement deferred persistence and reactivation**

Append/update JSONL records without fixed case totals. Deferred entries must contain three attempt evidence paths and a reactivation reason. A changed relevant Rust file alone is not enough; the next comparable run must provide changed evidence before clearing deferred.

- [ ] **Step 6: Run convergence tests**

Expected: all transition and path-scope tests pass.

---

### Task 4: Separate Intermediate and Final Gate Semantics

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/gate.py`

**Interfaces:**
- Produces: `check_c_cross_intermediate_evidence(root: Path) -> list[str]`.
- Produces: `check_c_cross_final_evidence(root: Path) -> list[str]`.
- `VERIFY_RUST_WITH_C_TESTS` uses intermediate semantics.
- `REPORT_AND_VERIFY` uses final semantics.

- [ ] **Step 1: Add failing gate tests**

Test that intermediate verification accepts:

```text
all pass
failures with valid three-attempt deferred evidence
recorded parse failure with actionable evidence
```

Test that it rejects an ordinary unresolved fail with fewer than three no-progress attempts, missing attempts/deferred files, `not_supported`, malformed fingerprints, and a repair attempt outside `flashDB_rust/**`.

Test that final verification rejects every `fail`, `not_run`, `deferred`, `not_supported`, parse failure, selected-suite scope, non-final attempt kind, and stale/non-full matrix.

- [ ] **Step 2: Run gate tests and verify RED**

Expected: current gate rejects all intermediate failures and lacks final freshness/scope checks.

- [ ] **Step 3: Implement intermediate gate**

Require real build/layout/link evidence where reached, valid per-test sets, failure fingerprints, and either pass or valid deferred/parse-failure evidence. Do not interpret intermediate acceptance as C baseline success.

- [ ] **Step 4: Implement final gate**

Require `scope == "all"`, `mode == "full"`, `attempt_kind == "final"`, all layered checks pass, every expected scenario pass, no active deferred rows, and case-results matching the final matrix.

- [ ] **Step 5: Wire stage gates**

Keep `MIGRATE_TESTS` reachable after evidence-complete intermediate verification. Add final C-cross validation directly to `REPORT_AND_VERIFY`, independent of the earlier stage state.

- [ ] **Step 6: Run gate tests**

Expected: intermediate/final policy tests pass and existing malformed-evidence tests remain green.

---

### Task 5: Surface Convergence in Reports

**Files:**
- Modify: `02_02/tests/test_conversion_system.py`
- Modify: `02_02/work/tools/report_writer.py`

**Interfaces:**
- Consumes: latest matrix, `attempts.jsonl`, `deferred.jsonl`, `workbench-issues.jsonl`.
- Produces: report summaries for per-test pass/fail/not-run, progress attempts, active deferred fingerprints, and workbench issues.

- [ ] **Step 1: Add failing report tests**

Create mixed per-test, attempt, deferred, and workbench issue fixtures. Assert the report distinguishes actual failed tests from suite diagnostics and clearly says intermediate acceptance is not final success.

- [ ] **Step 2: Run report tests and verify RED**

Expected: current report has layered diagnostics but no convergence/deferred summary.

- [ ] **Step 3: Implement report summaries**

Keep machine identifiers English and prose concise. Do not count deferred as pass. Show actual per-test totals derived from the matrix rather than fixed numbers.

- [ ] **Step 4: Run report tests**

Expected: new and existing report tests pass.

---

### Task 6: Update Runtime Contracts and Mirrors

**Files:**
- Modify: `02_02/INSTRUCTION.md`
- Modify: `02_02/work/skills/flashdb-orchestrator.md`
- Modify: `02_02/work/skills/rust-implementer.md`
- Modify: `02_02/work/skills/test-migrator.md`
- Modify: `02_02/work/skills/repairer.md`
- Modify: `02_02/work/skills/flashdb-migration/SKILL.md`
- Modify: `02_02/.opencode/skills/flashdb-migration/SKILL.md`
- Modify: matching files under `02_02/.opencode/skills/` when present
- Modify: `design_doc/stages/05-generate-rust-scaffold.md`
- Modify: `design_doc/stages/06-rewrite-core-modules.md`
- Modify: `design_doc/stages/06-5-verify-rust-with-c-tests.md`
- Modify: `design_doc/stages/08-build-test-repair.md`
- Modify: `02_02/tests/test_conversion_system.py`

**Interfaces:**
- Defines runtime edit scopes, incremental checkpoint commands, three-no-progress behavior, deferred handoff, and final strict rerun.
- Keeps `work/skills` authoritative and `.opencode` mirrors byte-identical where required.

- [ ] **Step 1: Add failing contract-text tests**

Assert authoritative documents contain:

```text
runtime agents must not modify workbench files
suite checkpoints are dynamic
three consecutive no-progress attempts cause deferred
intermediate deferred does not block test migration
final full C-cross must pass
workbench issues are recorded, not repaired during competition
```

Also assert obsolete text claiming C-cross must be all-pass before `MIGRATE_TESTS` is absent.

- [ ] **Step 2: Run contract tests and verify RED**

Expected: current docs still require strict all-pass before test migration and lack write-scope rules.

- [ ] **Step 3: Update authoritative contracts**

Use short operational rules in skills and keep design rationale in stage/Q4 docs. Do not copy the whole design into dispatch prompts.

- [ ] **Step 4: Synchronize mirrors**

Update matching `.opencode/skills` files from authoritative `work/skills` content only where the repository currently maintains a mirror.

- [ ] **Step 5: Run contract and parity tests**

Expected: wording assertions and mirror comparisons pass.

---

### Task 7: End-to-End Verification and Completion Audit

**Files:**
- Verify all files above.
- Do not modify generated local migration output merely to make contract tests pass.

**Interfaces:**
- Proves the implementation matches every requirement in the Q4 secondary optimization design.

- [ ] **Step 1: Run focused C-cross and gate tests**

Run discovered unittest names for parser, suite selection, attempts/deferred, gates, reports, and contract text. Expected: all pass.

- [ ] **Step 2: Run the full conversion-system test module**

Run:

```bash
python3 -B -m unittest 02_02.tests.test_conversion_system
```

Expected: all tests pass except documented environment skips.

- [ ] **Step 3: Run static verification**

Run:

```bash
python3 -B -m py_compile 02_02/work/tools/c_cross_validate.py 02_02/work/tools/gate.py 02_02/work/tools/report_writer.py
git diff --check
```

Expected: exit 0.

- [ ] **Step 4: Run a fresh local C-cross smoke execution**

Run the current local Rust output against the original C runners and verify the matrix reports real partial results rather than suite-wide failure. This smoke may correctly return nonzero because the local Rust implementation still has known semantic failures; success criterion is accurate per-test evidence and bounded execution.

- [ ] **Step 5: Audit requirement coverage**

Check every item in `design_doc/Q4-C-cross错误.md` sections 4 through 13 against code, tests, docs, and fresh artifacts. Do not mark complete while any explicit artifact, gate rule, runtime scope, or final strict condition is unverified.
