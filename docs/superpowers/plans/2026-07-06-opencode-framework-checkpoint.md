# Opencode Framework Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build only the first verifiable checkpoint for the FlashDB C-to-Rust opencode workbench.

**Architecture:** `02_02/INSTRUCTION.md` boots into `work/agents/flashdb-orchestrator.md`. The orchestrator executes only `BOOTSTRAP` and `INIT_WORKSPACE` for this checkpoint, validates them through `work/tools/gate.py`, writes `workflow_state.json`, and stops before reading FlashDB or generating `flashDB_rust`.

**Tech Stack:** Markdown instructions, project-local Codex/OpenCode-style agents and skills, Python standard library tools, `unittest`.

---

### Task 1: Framework and INIT_WORKSPACE checkpoint

**Files:**
- Modify: `/home/nv_test/777/flashdb2rust/02_02/INSTRUCTION.md`
- Modify: `/home/nv_test/777/flashdb2rust/02_02/tests/test_conversion_system.py`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/agents/flashdb-orchestrator.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/skills/test-migrator.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/skills/repairer.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/skills/flashdb-migration/SKILL.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/skills/flashdb-test-migration/SKILL.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/skills/rust-compile-repair/SKILL.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/skills/flashdb-report/SKILL.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/knowledge/contest-rules.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/knowledge/flashdb-test-map.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/knowledge/flashdb-rust-architecture.md`
- Create: `/home/nv_test/777/flashdb2rust/02_02/work/tools/gate.py`

- [ ] **Step 1: Write the failing contract tests**

Replace `/home/nv_test/777/flashdb2rust/02_02/tests/test_conversion_system.py` with tests that require the new `work/agents`, `work/skills`, `work/knowledge`, and `work/tools` layout, and require `gate.py --stage INIT_WORKSPACE` to pass only after `workflow_state.json` exists.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s 02_02/tests -v
```

Expected: fail because the new agent, skill, knowledge, and tool files do not exist yet.

- [ ] **Step 3: Implement minimal checkpoint framework**

Create the new files with concise responsibilities. `INSTRUCTION.md` must explicitly say this development checkpoint stops after `INIT_WORKSPACE`; no C project read and no `flashDB_rust` generation in this slice.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s 02_02/tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Validate project-local skills**

Run:

```bash
python3 /mnt/c/Users/nv_test/.codex/skills/.system/skill-creator/scripts/quick_validate.py 02_02/work/skills/flashdb-migration
python3 /mnt/c/Users/nv_test/.codex/skills/.system/skill-creator/scripts/quick_validate.py 02_02/work/skills/flashdb-test-migration
python3 /mnt/c/Users/nv_test/.codex/skills/.system/skill-creator/scripts/quick_validate.py 02_02/work/skills/rust-compile-repair
python3 /mnt/c/Users/nv_test/.codex/skills/.system/skill-creator/scripts/quick_validate.py 02_02/work/skills/flashdb-report
```

Expected: every skill is valid.

- [ ] **Step 6: Stop for opencode verification**

Report the exact files changed and ask the user to run opencode against this checkpoint before implementing `READ_C_PROJECT`.
