---
name: flashdb-report
description: Use when FlashDB migration reports must summarize staged evidence, cargo results, unsafe ratio, output paths, and known issues.
---

# FlashDB Report

## Scope

Use this Skill only after the orchestrator enters `REPORT_AND_VERIFY`.

## REPORT_AND_VERIFY contract

Produce:

- `result/output.md`;
- `result/issues/00-summary.md`;
- `logs/trace/final-verification.md`.

Reports must summarize:

- input path and output path;
- C model evidence;
- Rust API design evidence;
- extension/unknown/unmapped coverage;
- cargo build and test status;
- unsafe ratio;
- known issues.

Reports must distinguish checkpoint progress from complete migration success. Do not write `STATUS: SUCCESS` until every final gate has fresh evidence and `python3 work/tools/gate.py --stage REPORT_AND_VERIFY` passes.
