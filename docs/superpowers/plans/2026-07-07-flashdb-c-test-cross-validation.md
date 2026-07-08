# FlashDB C Test Cross Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `VERIFY_RUST_WITH_C_TESTS` stage between Rust core migration and Rust test migration, producing scenario-level cross-validation evidence from original C tests run against the Rust implementation.

**Architecture:** The workbench gains a new trace-producing validation tool, a new gate stage, and updated orchestrator/design docs. The validation tool writes `logs/trace/validation-matrix.json`; `gate.py` validates matrix completeness and blocks `MIGRATE_TESTS` on failed C-baseline evidence while keeping temporary C harness artifacts out of the final Rust project.

**Tech Stack:** Python 3 stdlib, Cargo, Rust `staticlib`, C compiler invoked by Python subprocess, existing JSON trace files, existing Markdown stage docs.

## Global Constraints

- Final Rust project must not contain C source files under `flashDB_rust/src/`.
- C cross-validation artifacts must live under `logs/trace/c-cross/` or another trace-owned temporary directory.
- `VERIFY_RUST_WITH_C_TESTS` must run after `REWRITE_CORE_MODULES` and before `MIGRATE_TESTS`.
- `MIGRATE_TESTS` remains responsible for Rust test semantic mapping through `rust_test_mapping.json`.
- `BUILD_TEST_REPAIR` remains responsible for final `cargo build` and `cargo test` pass/fail evidence.
- Unsupported C harness cases must be reported as `not_supported`, never silently treated as pass.
- Keep implementation stdlib-only unless an existing project dependency already provides the needed behavior.

---

## File Structure

- Create `02_02/work/tools/c_cross_validate.py`: builds a trace-owned validation matrix for C tests against Rust.
- Modify `02_02/work/tools/gate.py`: add `VERIFY_RUST_WITH_C_TESTS` required state keys and matrix validation.
- Modify `02_02/work/skills/flashdb-orchestrator.md`: insert the new stage in the primary workflow.
- Modify `design_doc/stages/README.md`: insert the new stage in the stage table and principles.
- Modify `design_doc/stages/06-rewrite-core-modules.md`: hand off to `VERIFY_RUST_WITH_C_TESTS`.
- Create `design_doc/stages/06-5-verify-rust-with-c-tests.md`: document the new stage.
- Modify `design_doc/stages/07-migrate-tests.md`: remove stale cargo-after-migrate requirements and make it depend on the new stage.
- Modify `design_doc/stages/08-build-test-repair.md`: make it depend on `MIGRATE_TESTS` after cross-validation.
- Modify `design_doc/stages/09-report-and-verify.md`: require matrix summary in final report evidence.
- Modify `design_doc/参赛工程设计文档.md`: update the full flow, stage numbering, mermaid diagram, and outputs.
- Modify `02_02/work/tools/report_writer.py`: include validation matrix summary in `result/output.md`.

### Task 1: Add Matrix Validation Gate

**Files:**
- Modify: `02_02/work/tools/gate.py`
- Test manually with fixture JSON under a temporary workbench directory.

**Interfaces:**
- Consumes: `logs/trace/c_test_model.json`, `logs/trace/validation-matrix.json`, `logs/trace/workflow_state.json`
- Produces: `gate.py --stage VERIFY_RUST_WITH_C_TESTS` pass/fail behavior

- [ ] **Step 1: Write a temporary failing fixture**

Create a temporary root outside the repo with only trace JSON needed by the gate:

```bash
tmp=$(mktemp -d)
export tmp
mkdir -p "$tmp/logs/trace" "$tmp/flashDB_rust/src" "$tmp/result/issues"
cat > "$tmp/logs/trace/workflow_state.json" <<'JSON'
{
  "current_stage": "VERIFY_RUST_WITH_C_TESTS",
  "checkpoint": "VERIFY_RUST_WITH_C_TESTS",
  "completed_stages": [
    "BOOTSTRAP",
    "INIT_WORKSPACE",
    "READ_C_PROJECT",
    "BUILD_C_MODEL",
    "DESIGN_RUST_API",
    "GENERATE_RUST_SCAFFOLD",
    "REWRITE_CORE_MODULES",
    "VERIFY_RUST_WITH_C_TESTS"
  ],
  "rust_project_path": "flashDB_rust",
  "input_path_candidates": [],
  "build_status": "unknown",
  "test_status": "unknown",
  "unsafe_ratio": null,
  "repair_rounds": 0,
  "blocked_issues": [],
  "input_path": "FlashDB",
  "input_manifest": "logs/trace/input_manifest.json",
  "c_project_model": "logs/trace/c_project_model.json",
  "c_api_model": "logs/trace/c_api_model.json",
  "c_test_model": "logs/trace/c_test_model.json",
  "rust_api_design": "logs/trace/rust_api_design.json"
}
JSON
cat > "$tmp/logs/trace/c_test_model.json" <<'JSON'
{
  "standard_scenarios": [{"id": "test_fdb_kv_set"}],
  "scorer_standard_cases": [
    {"case_id": "1", "case_name": "kv_set", "scenario_id": "test_fdb_kv_set", "semantic_obligations": ["calls:fdb_kv_set"]}
  ]
}
JSON
cat > "$tmp/logs/trace/validation-matrix.json" <<'JSON'
{
  "stage": "VERIFY_RUST_WITH_C_TESTS",
  "total_scenarios": 1,
  "summary": {"rust_impl_c_test": {"fail": 1}},
  "scenarios": [
    {
      "scenario_id": "test_fdb_kv_set",
      "scorer_case_id": "1",
      "suite": "kvdb",
      "c_impl_c_test": "baseline",
      "rust_impl_c_test": "fail",
      "c_impl_rust_test": "not_run",
      "rust_impl_rust_test": "pending",
      "diagnosis": "rust_implementation_failed_c_baseline",
      "log": "logs/trace/c-cross/test_fdb_kv_set.log"
    }
  ]
}
JSON
python3 02_02/work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS --root "$tmp"
```

Expected before implementation:

```text
VERIFY_RUST_WITH_C_TESTS: FAIL
unsupported stage for this checkpoint: VERIFY_RUST_WITH_C_TESTS
```

- [ ] **Step 2: Add required state key set**

In `02_02/work/tools/gate.py`, add:

```python
REQUIRED_C_CROSS_STATE_KEYS = REQUIRED_DESIGN_STATE_KEYS
```

Do not include `rust_test_mapping` because Rust tests have not been migrated yet.

- [ ] **Step 3: Add `check_validation_matrix` helper**

Add a function with this exact interface:

```python
def check_validation_matrix(root: Path, *, allow_not_supported: bool = True) -> list[str]:
    ...
```

It must:

- load `logs/trace/validation-matrix.json`;
- load `logs/trace/c_test_model.json`;
- compare matrix scenario IDs with `scorer_standard_cases[*].scenario_id`;
- compare matrix scorer IDs with `scorer_standard_cases[*].case_id`;
- require `total_scenarios` to equal scorer case count;
- reject unknown cell values;
- reject any `rust_impl_c_test == "fail"`;
- reject `not_supported` when `allow_not_supported` is false;
- require `diagnosis` and `log` for `fail` and `not_supported` entries.

Use these value sets:

```python
VALID_MATRIX_VALUES = {"baseline", "pass", "fail", "not_run", "not_supported", "pending"}
VALID_DIAGNOSES = {
    "rust_implementation_matches_c_baseline_for_scenario",
    "rust_implementation_failed_c_baseline",
    "c_cross_harness_not_supported",
    "blocked_before_rust_test_migration",
    "rust_test_migration_pending",
}
```

- [ ] **Step 4: Add `check_verify_rust_with_c_tests`**

Add:

```python
def check_verify_rust_with_c_tests(root: Path) -> list[str]:
    errors = check_common_after_scaffold(root)
    required_stages = [
        "BOOTSTRAP",
        "INIT_WORKSPACE",
        "READ_C_PROJECT",
        "BUILD_C_MODEL",
        "DESIGN_RUST_API",
        "GENERATE_RUST_SCAFFOLD",
        "REWRITE_CORE_MODULES",
        "VERIFY_RUST_WITH_C_TESTS",
    ]
    state, state_errors = require_state(root, REQUIRED_C_CROSS_STATE_KEYS, "VERIFY_RUST_WITH_C_TESTS", required_stages)
    errors.extend(state_errors)
    if state is None:
        return errors
    errors.extend(check_validation_matrix(root, allow_not_supported=True))
    if not (root / "logs" / "trace" / "06-5-verify-rust-with-c-tests.md").exists():
        errors.append("missing logs/trace/06-5-verify-rust-with-c-tests.md")
    if list((root / "flashDB_rust" / "src").glob("*.c")):
        errors.append("flashDB_rust/src must not contain C source files")
    return errors
```

- [ ] **Step 5: Register the stage in `main`**

Add:

```python
elif stage == "VERIFY_RUST_WITH_C_TESTS":
    errors = check_verify_rust_with_c_tests(root)
```

- [ ] **Step 6: Verify fail fixture now fails for the right reason**

Run:

```bash
python3 02_02/work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS --root "$tmp"
```

Expected:

```text
VERIFY_RUST_WITH_C_TESTS: FAIL
- Rust implementation failed C baseline scenarios: test_fdb_kv_set
- missing logs/trace/06-5-verify-rust-with-c-tests.md
```

- [ ] **Step 7: Verify pass fixture**

Patch the temporary matrix:

```bash
python3 - <<'PY'
import json, os, pathlib
path = pathlib.Path(os.environ["tmp"]) / "logs/trace/validation-matrix.json"
data = json.loads(path.read_text())
data["summary"] = {"rust_impl_c_test": {"pass": 1}}
data["scenarios"][0]["rust_impl_c_test"] = "pass"
data["scenarios"][0]["diagnosis"] = "rust_implementation_matches_c_baseline_for_scenario"
path.write_text(json.dumps(data, indent=2) + "\n")
(pathlib.Path(os.environ["tmp"]) / "logs/trace/06-5-verify-rust-with-c-tests.md").write_text("验证通过\n")
PY
python3 02_02/work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS --root "$tmp"
```

Expected:

```text
VERIFY_RUST_WITH_C_TESTS: PASS
```

### Task 2: Add Cross-Validation Matrix Tool

**Files:**
- Create: `02_02/work/tools/c_cross_validate.py`

**Interfaces:**
- Consumes: `--root`, `--project`, `--out`
- Produces: `logs/trace/c-cross/cross-compile.log`, `logs/trace/c-cross/cross-test.log`, `logs/trace/validation-matrix.json`

- [ ] **Step 1: Create unsupported-first implementation**

Create `c_cross_validate.py` with:

```python
#!/usr/bin/env python3
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


def build_matrix(root: Path, out: Path) -> dict[str, Any]:
    trace = out
    c_cross = trace / "c-cross"
    c_cross.mkdir(parents=True, exist_ok=True)
    test_model = load_json(trace / "c_test_model.json")
    cases = test_model.get("scorer_standard_cases")
    if not isinstance(cases, list):
        raise ValueError("c_test_model.json scorer_standard_cases must be a list")

    scenarios = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        scenario_id = case.get("scenario_id")
        case_id = case.get("case_id")
        if not isinstance(scenario_id, str) or not isinstance(case_id, str):
            continue
        log = c_cross / f"{scenario_id}.log"
        log.write_text(
            "C cross-validation harness is not implemented for this scenario yet.\\n",
            encoding="utf-8",
        )
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "scorer_case_id": case_id,
                "suite": case.get("suite", "unknown"),
                "c_impl_c_test": "baseline",
                "rust_impl_c_test": "not_supported",
                "c_impl_rust_test": "not_run",
                "rust_impl_rust_test": "pending",
                "diagnosis": "c_cross_harness_not_supported",
                "reason": "initial harness does not yet compile this C test pattern",
                "log": log.relative_to(root).as_posix() if log.is_relative_to(root) else log.as_posix(),
            }
        )

    (c_cross / "cross-compile.log").write_text(
        "C cross-validation compile step not implemented in unsupported-first mode.\\n",
        encoding="utf-8",
    )
    (c_cross / "cross-test.log").write_text(
        "C cross-validation test step not implemented in unsupported-first mode.\\n",
        encoding="utf-8",
    )
    return {
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        "policy": "advisory",
        "total_scenarios": len(scenarios),
        "summary": {"rust_impl_c_test": {"not_supported": len(scenarios)}},
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FlashDB C tests against Rust validation facade.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--project", default="flashDB_rust", help="Rust project path, relative to root.")
    parser.add_argument("--out", default="logs/trace", help="Trace output directory, relative to root.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = (root / args.out).resolve()
    matrix = build_matrix(root, out)
    matrix_path = out / "validation-matrix.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    print("VERIFY_RUST_WITH_C_TESTS: MATRIX_WRITTEN")
    print(f"mapped_scenarios={matrix['total_scenarios']}")
    print("policy=advisory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the tool on current trace if available**

Run:

```bash
python3 02_02/work/tools/c_cross_validate.py --root 02_02 --project flashDB_rust --out logs/trace
```

Expected when `02_02/logs/trace/c_test_model.json` exists:

```text
VERIFY_RUST_WITH_C_TESTS: MATRIX_WRITTEN
mapped_scenarios=<number>
policy=advisory
```

- [ ] **Step 3: Inspect generated matrix**

Run:

```bash
python3 -m json.tool 02_02/logs/trace/validation-matrix.json | sed -n '1,80p'
```

Expected:

```text
"stage": "VERIFY_RUST_WITH_C_TESTS"
"rust_impl_c_test": "not_supported"
```

### Task 3: Update Orchestrator and Stage Docs

**Files:**
- Modify: `02_02/work/skills/flashdb-orchestrator.md`
- Modify: `design_doc/stages/README.md`
- Modify: `design_doc/stages/06-rewrite-core-modules.md`
- Create: `design_doc/stages/06-5-verify-rust-with-c-tests.md`
- Modify: `design_doc/stages/07-migrate-tests.md`
- Modify: `design_doc/stages/08-build-test-repair.md`
- Modify: `design_doc/stages/09-report-and-verify.md`
- Modify: `design_doc/参赛工程设计文档.md`

**Interfaces:**
- Consumes: design spec language
- Produces: consistent opencode-facing workflow docs

- [ ] **Step 1: Insert stage in orchestrator list**

Update the stage list in `02_02/work/skills/flashdb-orchestrator.md` to:

```text
7. `REWRITE_CORE_MODULES`
8. `VERIFY_RUST_WITH_C_TESTS`
9. `MIGRATE_TESTS`
10. `BUILD_TEST_REPAIR`
11. `REPORT_AND_VERIFY`
```

- [ ] **Step 2: Add orchestrator section**

Insert after `REWRITE_CORE_MODULES`:

```markdown
## VERIFY_RUST_WITH_C_TESTS

读取：

- `logs/trace/c_test_model.json`
- `logs/trace/c_api_model.json`
- `logs/trace/rust_api_design.json`
- `flashDB_rust/`

运行：

```bash
python3 work/tools/c_cross_validate.py --root . --project flashDB_rust --out logs/trace
python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS
```

写入：

- `logs/trace/c-cross/cross-compile.log`
- `logs/trace/c-cross/cross-test.log`
- `logs/trace/validation-matrix.json`
- 中文 `logs/trace/06-5-verify-rust-with-c-tests.md`

本阶段用原始 C 测试证据验证 Rust 实现。临时 C harness 只能写入 trace 目录，不得进入 `flashDB_rust/src/`，不得让最终 Rust 项目依赖 FlashDB C 实现。
```

- [ ] **Step 3: Update `07-migrate-tests.md`**

Remove references to:

```text
logs/trace/cargo-test-after-migrate.log
logs/trace/test-after-migrate.json
```

Replace the opening dependency sentence with:

```markdown
本阶段必须在 `VERIFY_RUST_WITH_C_TESTS` gate 通过后执行。此时 Rust 核心实现已经用原始 C 测试证据做过基线验证，本阶段只负责把 C 测试语义迁移为 Rust 测试并维护 `rust_test_mapping.json`。
```

- [ ] **Step 4: Add new stage doc**

Create `design_doc/stages/06-5-verify-rust-with-c-tests.md` using the design spec's Stage Contract, Gate Behavior, and Failure Routing sections.

- [ ] **Step 5: Update stage README**

Add a table row:

```markdown
| 6.5 | VERIFY_RUST_WITH_C_TESTS | [06-5-verify-rust-with-c-tests.md](06-5-verify-rust-with-c-tests.md) | `validation-matrix.json` / C tests on Rust evidence |
```

Update the principles so test migration is no longer the first behavioral validation after core rewrite.

- [ ] **Step 6: Update main Chinese design doc**

In `design_doc/参赛工程设计文档.md`, update:

- stage list;
- mermaid flow;
- `6.7 REWRITE_CORE_MODULES` handoff;
- add `6.8 VERIFY_RUST_WITH_C_TESTS`;
- renumber later sections or explicitly name the inserted 6.8.5-style stage;
- remove stale `cargo-test-after-migrate` requirement from the MIGRATE_TESTS section;
- add `validation-matrix.json` to final report evidence.

- [ ] **Step 7: Verify docs no longer contain stale migrate-test cargo files**

Run:

```bash
rg -n "cargo-test-after-migrate|test-after-migrate" design_doc 02_02/work
```

Expected:

```text
```

No matches.

### Task 4: Update Report Writer

**Files:**
- Modify: `02_02/work/tools/report_writer.py`

**Interfaces:**
- Consumes: `logs/trace/validation-matrix.json`
- Produces: validation matrix summary in `result/output.md`

- [ ] **Step 1: Inspect report writer structure**

Run:

```bash
sed -n '1,180p' 02_02/work/tools/report_writer.py
```

Expected: identify where `rust_test_mapping.json` is loaded and where test coverage is written.

- [ ] **Step 2: Load validation matrix**

Add:

```python
matrix = load_json(trace / "validation-matrix.json")
```

next to the existing trace JSON loads.

- [ ] **Step 3: Add summary renderer**

Add:

```python
def validation_matrix_summary(matrix: dict[str, Any]) -> list[str]:
    if not matrix:
        return ["- C cross-validation: missing"]
    summary = matrix.get("summary", {})
    rust_impl = summary.get("rust_impl_c_test", {}) if isinstance(summary, dict) else {}
    if not isinstance(rust_impl, dict):
        rust_impl = {}
    parts = [f"{key}={value}" for key, value in sorted(rust_impl.items())]
    return [
        f"- C tests on Rust: {', '.join(parts) if parts else 'no summary'}",
        f"- Validation matrix scenarios: {matrix.get('total_scenarios', 0)}",
    ]
```

- [ ] **Step 4: Include in final output**

Add a section:

```markdown
## Cross Validation Matrix
```

and append the lines from `validation_matrix_summary(matrix)`.

- [ ] **Step 5: Run report writer with current trace**

Run:

```bash
python3 02_02/work/tools/report_writer.py --root 02_02 --output /tmp/flashdb-output.md --issues /tmp/flashdb-issues.md
rg -n "Cross Validation Matrix|C tests on Rust|Validation matrix scenarios" /tmp/flashdb-output.md
```

Expected:

```text
Cross Validation Matrix
C tests on Rust
Validation matrix scenarios
```

### Task 5: Full Verification

**Files:**
- Verify all modified files.

**Interfaces:**
- Consumes: completed Tasks 1-4
- Produces: evidence that the new stage contract is internally consistent

- [ ] **Step 1: Run Python syntax checks**

Run:

```bash
python3 -m py_compile 02_02/work/tools/gate.py 02_02/work/tools/c_cross_validate.py 02_02/work/tools/report_writer.py
```

Expected: no output and exit code 0.

- [ ] **Step 2: Generate advisory matrix on current workbench trace**

Run:

```bash
python3 02_02/work/tools/c_cross_validate.py --root 02_02 --project flashDB_rust --out logs/trace
```

Expected:

```text
VERIFY_RUST_WITH_C_TESTS: MATRIX_WRITTEN
```

- [ ] **Step 3: Create stage log for local gate smoke test**

Run:

```bash
printf 'C 测试交叉验证矩阵已生成。\\n' > 02_02/logs/trace/06-5-verify-rust-with-c-tests.md
```

- [ ] **Step 4: Run new gate if workflow state is at the new stage**

If `02_02/logs/trace/workflow_state.json` has `current_stage` set to `VERIFY_RUST_WITH_C_TESTS`, run:

```bash
python3 02_02/work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS --root 02_02
```

Expected:

```text
VERIFY_RUST_WITH_C_TESTS: PASS
```

If workflow state is currently at another stage, do not rewrite user trace just to force a pass. Use the temporary fixture from Task 1 instead.

- [ ] **Step 5: Run existing gate smoke tests that do not depend on current dirty generated output**

Run:

```bash
python3 02_02/work/tools/gate.py --stage MIGRATE_TESTS --root 02_02
```

Expected depends on current generated migration output. If it fails, verify the failure is not from Python exceptions or missing new symbols.

- [ ] **Step 6: Check doc consistency**

Run active workflow doc check:

```bash
rg -n "VERIFY_RUST_WITH_C_TESTS|validation-matrix" design_doc 02_02/work docs/superpowers
```

Run stale active workflow doc check:

```bash
rg -n "cargo-test-after-migrate|test-after-migrate" design_doc 02_02/work
```

Expected:

- `VERIFY_RUST_WITH_C_TESTS` appears in orchestrator, stage docs, main design doc, spec, and plan.
- `validation-matrix` appears in new stage docs, final report docs, spec, and plan.
- `cargo-test-after-migrate` and `test-after-migrate` do not appear in active workflow docs.

- [ ] **Step 7: Review worktree scope**

Run:

```bash
git status --short docs/superpowers design_doc 02_02/work
```

Expected: only planned files are modified or added.
