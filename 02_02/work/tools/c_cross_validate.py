#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _relative_log_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _write(path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _command_text(command: list[str], cwd: Path | None = None) -> str:
    prefix = f"(cd {cwd} && )" if cwd else ""
    return prefix + " ".join(command)


def _safe_c_suffix(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()


def _run(command: list[str], *, cwd: Path | None = None, timeout: float = 60) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        return -124, f"{stdout}{stderr}\nTIMEOUT: killed after {timeout}s\n"
    stdout = completed.stdout.decode("utf-8", errors="replace") if isinstance(completed.stdout, bytes) else (completed.stdout or "")
    stderr = completed.stderr.decode("utf-8", errors="replace") if isinstance(completed.stderr, bytes) else (completed.stderr or "")
    return completed.returncode, f"{stdout}{stderr}"


def parse_runner_test_results(output: str, expected_tests: list[str], exit_code: int) -> dict[str, Any]:
    expected = list(dict.fromkeys(expected_tests))
    if len(expected) != len(expected_tests):
        return {
            "status": "parse_failed",
            "started": [],
            "passed": [],
            "failed": [],
            "not_run": expected,
            "failures": {},
            "reason": "expected test list contains duplicates",
        }

    start_pattern = re.compile(r"^\s*Running:\s*([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)
    failure_pattern = re.compile(r"^\s*FAIL\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$", re.MULTILINE)
    started = start_pattern.findall(output)
    failure_matches = failure_pattern.findall(output)
    failures: dict[str, str] = {}
    for test_name, detail in failure_matches:
        normalized = " ".join(detail.split())
        if test_name in failures:
            failures[test_name] = f"{failures[test_name]} | {normalized}"
        else:
            failures[test_name] = normalized

    expected_set = set(expected)
    duplicate_starts = sorted({name for name in started if started.count(name) > 1})
    unknown_started = sorted(set(started) - expected_set)
    unknown_failed = sorted(set(failures) - expected_set)
    failed_without_start = sorted(set(failures) - set(started))
    reasons: list[str] = []
    if duplicate_starts:
        reasons.append("duplicate start records: " + ", ".join(duplicate_starts))
    if unknown_started:
        reasons.append("unknown started tests: " + ", ".join(unknown_started))
    if unknown_failed:
        reasons.append("unknown failed tests: " + ", ".join(unknown_failed))
    if failed_without_start:
        reasons.append("failed tests missing start records: " + ", ".join(failed_without_start))
    if exit_code == 0 and failures:
        reasons.append("successful runner reported test failures")
    if exit_code == 0 and set(started) != expected_set:
        reasons.append("successful runner did not start all expected tests")
    if exit_code != 0 and not failures:
        reasons.append("nonzero runner exit has no attributed test failure")

    failed = [name for name in expected if name in failures]
    started_set = set(started)
    passed = [name for name in expected if name in started_set and name not in failures]
    not_run = [name for name in expected if name not in started_set]
    return {
        "status": "parse_failed" if reasons else "parsed",
        "started": [name for name in expected if name in started_set],
        "passed": passed,
        "failed": failed,
        "not_run": not_run,
        "failures": failures,
        "reason": "; ".join(reasons) if reasons else "runner output mapped to expected tests",
    }


def _normalized_failure_reason(reason: Any) -> str:
    text = " ".join(str(reason or "unknown failure").split())
    text = re.sub(r"0x[0-9A-Fa-f]+", "<addr>", text)
    return text


def failure_fingerprint(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("failure_layer") or row.get("phase") or "unknown"),
            str(row.get("suite") or "unknown"),
            str(row.get("source_test") or row.get("scenario_id") or "unknown"),
            _normalized_failure_reason(row.get("reason")),
        ]
    )


def _matrix_outcomes(matrix: dict[str, Any] | None) -> dict[str, Any]:
    scenarios = matrix.get("scenarios") if isinstance(matrix, dict) else []
    rows = [row for row in scenarios if isinstance(row, dict)] if isinstance(scenarios, list) else []
    passed: set[str] = set()
    failed: set[str] = set()
    not_run: set[str] = set()
    failures: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_test = str(row.get("source_test") or row.get("scenario_id") or "unknown")
        status = row.get("rust_impl_c_test")
        if status == "pass":
            passed.add(source_test)
        elif status == "not_run":
            not_run.add(source_test)
            failures[source_test] = row
        else:
            failed.add(source_test)
            failures[source_test] = row
    return {
        "passed": passed,
        "failed": failed,
        "not_run": not_run,
        "failures": failures,
        "fingerprints": {failure_fingerprint(row) for row in failures.values()},
    }


def compare_attempt(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    before = _matrix_outcomes(previous)
    after = _matrix_outcomes(current)
    previous_scope = before["passed"] | before["failed"] | before["not_run"]
    current_scope = after["passed"] | after["failed"] | after["not_run"]
    regression = bool((before["passed"] & current_scope) - after["passed"])
    progress_reasons: list[str] = []
    if after["passed"] - before["passed"]:
        progress_reasons.append("passed set increased")

    layer_order = {"model": 0, "scaffold": 1, "build": 2, "layout": 3, "link": 4, "full": 5}
    for source_test in sorted(set(before["failures"]) & set(after["failures"])):
        before_row = before["failures"][source_test]
        after_row = after["failures"][source_test]
        before_layer = str(before_row.get("failure_layer") or before_row.get("phase") or "unknown")
        after_layer = str(after_row.get("failure_layer") or after_row.get("phase") or "unknown")
        if layer_order.get(after_layer, -1) > layer_order.get(before_layer, -1):
            progress_reasons.append(f"{source_test} advanced from {before_layer} to {after_layer}")
        elif failure_fingerprint(before_row) != failure_fingerprint(after_row):
            progress_reasons.append(f"{source_test} advanced to a different assertion or error")

    progress = bool(progress_reasons) and not regression
    return {
        "progress": progress,
        "regression": regression,
        "progress_reasons": progress_reasons,
        "before": {
            "passed": sorted(before["passed"]),
            "failed": sorted(before["failed"]),
            "not_run": sorted(before["not_run"]),
        },
        "after": {
            "passed": sorted(after["passed"]),
            "failed": sorted(after["failed"]),
            "not_run": sorted(after["not_run"]),
        },
        "fingerprints_before": sorted(before["fingerprints"]),
        "fingerprints_after": sorted(after["fingerprints"]),
        "comparable_fingerprints": sorted(
            failure_fingerprint(row)
            for source_test, row in after["failures"].items()
            if source_test in previous_scope
        ),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def record_attempt(
    c_cross: Path,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    attempt_kind: str,
    trigger: str,
    changed_files: list[str],
) -> dict[str, Any]:
    if attempt_kind == "repair":
        invalid_changes = [
            path
            for path in changed_files
            if not Path(path).as_posix().startswith("flashDB_rust/") or ".." in Path(path).parts
        ]
        if invalid_changes:
            raise ValueError(
                "repair changed_files must stay under flashDB_rust/: " + ", ".join(sorted(invalid_changes))
            )

    comparison = compare_attempt(previous, current)
    attempts_path = c_cross / "attempts.jsonl"
    prior_attempts = _read_jsonl(attempts_path)
    current_fingerprints = comparison["fingerprints_after"]
    recent_fingerprints = {
        fingerprint
        for row in prior_attempts[-2:]
        for fingerprint in row.get("fingerprints_after", [])
        if isinstance(fingerprint, str)
    }
    cycle_detected = bool(current_fingerprints) and any(
        fingerprint in recent_fingerprints and fingerprint not in comparison["fingerprints_before"]
        for fingerprint in current_fingerprints
    )
    if cycle_detected:
        comparison["progress"] = False
        comparison["progress_reasons"] = ["failure fingerprint cycle detected"]

    previous_counts: dict[str, int] = {}
    if prior_attempts:
        raw_counts = prior_attempts[-1].get("no_progress_counts")
        if isinstance(raw_counts, dict):
            previous_counts = {
                str(key): int(value)
                for key, value in raw_counts.items()
                if isinstance(value, int)
            }
    no_progress_counts: dict[str, int] = {}
    comparable_fingerprints = set(comparison["comparable_fingerprints"])
    for fingerprint in current_fingerprints:
        if attempt_kind != "repair" or comparison["progress"] or fingerprint not in comparable_fingerprints:
            no_progress_counts[fingerprint] = 0
        else:
            no_progress_counts[fingerprint] = previous_counts.get(fingerprint, 0) + 1

    attempt_id = str(current.get("execution_id") or f"attempt-{time.time_ns()}")
    deferred_fingerprints = sorted(
        fingerprint for fingerprint, count in no_progress_counts.items() if count >= 3
    )
    record = {
        "attempt_id": attempt_id,
        "kind": attempt_kind,
        "trigger": trigger,
        "suite": sorted({
            str(row.get("suite"))
            for row in current.get("scenarios", [])
            if isinstance(row, dict) and row.get("suite")
        }),
        "changed_files": list(changed_files),
        **comparison,
        "no_progress_counts": no_progress_counts,
        "next_action": "defer" if deferred_fingerprints else ("continue" if current_fingerprints else "pass"),
        "matrix_snapshot": f"logs/trace/c-cross/checkpoints/{attempt_id}.json",
    }
    _append_jsonl(attempts_path, record)

    deferred_path = c_cross / "deferred.jsonl"
    existing_deferred = _read_jsonl(deferred_path)
    latest_deferred: dict[str, dict[str, Any]] = {}
    for row in existing_deferred:
        fingerprint = row.get("fingerprint")
        if isinstance(fingerprint, str):
            latest_deferred[fingerprint] = row
    active_deferred = {
        fingerprint: row
        for fingerprint, row in latest_deferred.items()
        if row.get("status") == "deferred"
    }
    for fingerprint in deferred_fingerprints:
        if fingerprint in active_deferred:
            continue
        attempt_ids = [
            str(row.get("attempt_id"))
            for row in prior_attempts + [record]
            if fingerprint in row.get("fingerprints_after", [])
        ][-3:]
        _append_jsonl(
            deferred_path,
            {
                "fingerprint": fingerprint,
                "status": "deferred",
                "no_progress_count": no_progress_counts[fingerprint],
                "attempt_ids": attempt_ids,
                "reactivation": "related Rust implementation change followed by changed C-cross evidence",
                "final_requirement": "must pass final full C-cross",
            },
        )

    for fingerprint, deferred_row in active_deferred.items():
        if fingerprint in current_fingerprints:
            continue
        if current.get("scope") == "selected":
            fingerprint_parts = fingerprint.split("|", 3)
            fingerprint_suite = fingerprint_parts[1] if len(fingerprint_parts) > 1 else ""
            selected = current.get("selected_suites")
            selected_suites = {str(item) for item in selected} if isinstance(selected, list) else set()
            if fingerprint_suite not in selected_suites:
                continue
        _append_jsonl(
            deferred_path,
            {
                "fingerprint": fingerprint,
                "status": "reactivated",
                "reactivated_by": attempt_id,
                "reason": "related execution produced changed evidence",
                "deferred_attempt_ids": deferred_row.get("attempt_ids", []),
            },
        )
    return record


def _suite_for_case(case: dict[str, Any]) -> str:
    suite = case.get("suite")
    if isinstance(suite, str) and suite:
        return suite
    return "unknown"


def _find_c_project_root(root: Path, trace: Path) -> Path | None:
    state_path = trace / "workflow_state.json"
    if state_path.exists():
        state = load_json(state_path)
        input_path = state.get("input_path")
        if isinstance(input_path, str) and Path(input_path).exists():
            return Path(input_path).resolve()
    candidates = [
        root / "judge-assets" / "code" / "FlashDB",
        root.parent / "judge-assets" / "code" / "FlashDB",
        root.parent.parent / "judge-assets" / "code" / "FlashDB",
    ]
    for candidate in candidates:
        if (candidate / "tests").is_dir() and any((candidate / "inc").glob("*.h")):
            return candidate.resolve()
    return None


def _rust_staticlib(project: Path) -> Path:
    if os.name == "nt":
        return project / "target" / "release" / "flashdb_rust.lib"
    return project / "target" / "release" / "libflashdb_rust.a"


def _c_include_args(c_root: Path, c_cross: Path) -> list[str]:
    generated_include = c_cross / "include"
    generated_include.mkdir(parents=True, exist_ok=True)
    inc = c_root / "inc"
    if inc.is_dir():
        for template in sorted(inc.glob("*_template.h")):
            target_name = template.name.replace("_template.h", ".h")
            if not (inc / target_name).exists():
                content = template.read_text(encoding="utf-8", errors="ignore")
                if target_name == "fdb_cfg.h":
                    content = content.replace(
                        "#define _FDB_CFG_H_",
                        "#define _FDB_CFG_H_\n\n#include <stdbool.h>\n#include <time.h>",
                    )
                (generated_include / target_name).write_text(
                    content,
                    encoding="utf-8",
                )
    args = ["-I", str(generated_include), "-I", str(c_root / "tests"), "-I", str(c_root / "inc")]
    return args


def _build_rust_staticlib(project: Path) -> tuple[bool, str]:
    command = ["cargo", "build", "--release"]
    code, output = _run(command, cwd=project)
    text = f"$ {_command_text(command, project)}\n{output}\n"
    lib = _rust_staticlib(project)
    if code != 0:
        text += f"cargo exited with {code}\n"
        return False, text
    if not lib.exists():
        text += f"missing Rust staticlib: {lib}\n"
        return False, text
    text += f"staticlib={lib}\n"
    return True, text


def _discover_suite_runner(suite: str, c_root: Path) -> Path | None:
    tests_dir = c_root / "tests"
    if not tests_dir.is_dir():
        return None
    candidates = []
    for source in sorted(tests_dir.glob("*.c")):
        text = source.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"\bmain\s*\(", text):
            continue
        score = 0
        lower_name = source.name.lower()
        if suite.lower() in lower_name:
            score += 10
        if re.search(r"\bTEST_RUN\s*\(", text):
            score += 3
        candidates.append((score, source))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item[0], item[1].as_posix()))[0][1]


def _compile_suite_runner(
    suite: str,
    c_root: Path,
    c_cross: Path,
    rust_lib: Path,
) -> tuple[bool, Path | None, str]:
    source = _discover_suite_runner(suite, c_root)
    if source is None:
        return False, None, f"missing discovered C test runner for suite: {suite}\n"
    binary = c_cross / f"{suite}_runner"
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        return False, None, "missing C compiler: cc/gcc/clang not found\n"
    command = [
        cc,
        "-O0",
        "-g3",
        "-Wall",
        "-Wno-format",
        *_c_include_args(c_root, c_cross),
        str(source),
        str(rust_lib),
        "-o",
        str(binary),
        "-lpthread",
        "-ldl",
        "-lm",
    ]
    code, output = _run(command)
    text = f"$ {_command_text(command)}\n{output}\n"
    if code != 0:
        text += f"cc exited with {code}\n"
        return False, binary, text
    return True, binary, text


def _run_suite_runner(suite: str, binary: Path, c_cross: Path) -> tuple[bool, str, str]:
    run_dir = c_cross / f"{suite}_run"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = c_cross / f"{suite}_runner.log"
    command = [str(binary.resolve())]
    code, output = _run(command, cwd=run_dir, timeout=60)
    text = f"$ {_command_text(command, run_dir)}\n{output}\n"
    _write(log_path, text)
    if code == -124:
        return False, text, f"{suite} runner timeout after 60s, see {log_path}"
    if code != 0:
        text += f"runner exited with {code}\n"
        _write(log_path, text)
        return False, text, f"{suite} runner failed, see {log_path}"
    return True, text, f"{suite} original C runner passed"


def _layout_structs(trace: Path) -> list[dict[str, Any]]:
    design_path = trace / "rust_api_design.json"
    if design_path.exists():
        design = load_json(design_path)
        facade = design.get("c_abi_facade")
        structs = facade.get("structs") if isinstance(facade, dict) else []
        if isinstance(structs, list):
            result = [item for item in structs if isinstance(item, dict) and isinstance(item.get("c_name"), str)]
            if result:
                return result
    api_path = trace / "c_api_model.json"
    if not api_path.exists():
        return []
    api_model = load_json(api_path)
    layouts = api_model.get("abi_layouts")
    if not isinstance(layouts, list):
        return []
    result: list[dict[str, Any]] = []
    for layout in layouts:
        if not isinstance(layout, dict) or not isinstance(layout.get("name"), str):
            continue
        result.append(
            {
                "c_name": layout["name"],
                "sizeof": layout.get("sizeof"),
                "alignof": layout.get("alignof"),
                "fields": layout.get("fields", []),
                "notes": [],
            }
        )
    return result


def _layout_headers(c_root: Path, structs: list[dict[str, Any]]) -> list[str]:
    headers = [
        str(item.get("header"))
        for item in structs
        if isinstance(item.get("header"), str) and item.get("header")
    ]
    headers = [header.removeprefix("inc/") for header in headers]
    if not headers:
        inc = c_root / "inc"
        if inc.is_dir():
            headers = [path.relative_to(inc).as_posix() for path in sorted(inc.glob("*.h"))]
    return sorted(dict.fromkeys(headers))


def _layout_checker_source(structs: list[dict[str, Any]], headers: list[str]) -> str:
    lines = [
        "#include <stddef.h>",
        "#include <stdint.h>",
        "#include <stdio.h>",
        "#include <stdbool.h>",
        "#include <time.h>",
    ]
    lines.extend(f'#include "{header}"' for header in headers)
    lines.append("")
    for struct in structs:
        c_name = struct["c_name"]
        suffix = _safe_c_suffix(c_name)
        lines.append(f"extern size_t rust_sizeof_{suffix}(void);")
        lines.append(f"extern size_t rust_alignof_{suffix}(void);")
        fields = struct.get("fields", [])
        if isinstance(fields, list):
            for field in fields:
                if isinstance(field, dict) and isinstance(field.get("name"), str):
                    lines.append(f"extern size_t rust_offsetof_{suffix}_{_safe_c_suffix(field['name'])}(void);")
    lines.extend(
        [
            "",
            "int main(void) {",
            "  int failures = 0;",
            '  printf("[LAYOUT CHECK] start\\n");',
        ]
    )
    for struct in structs:
        c_name = struct["c_name"]
        suffix = _safe_c_suffix(c_name)
        lines.extend(
            [
                f"  if (sizeof(struct {c_name}) != rust_sizeof_{suffix}()) {{",
                f'    printf("[LAYOUT MISMATCH] struct={c_name} sizeof c=%zu rust=%zu\\n", sizeof(struct {c_name}), rust_sizeof_{suffix}());',
                "    failures++;",
                "  }",
                f"  if (_Alignof(struct {c_name}) != rust_alignof_{suffix}()) {{",
                f'    printf("[LAYOUT MISMATCH] struct={c_name} alignof c=%zu rust=%zu\\n", (size_t)_Alignof(struct {c_name}), rust_alignof_{suffix}());',
                "    failures++;",
                "  }",
                f"  if (sizeof(struct {c_name}) == rust_sizeof_{suffix}() && _Alignof(struct {c_name}) == rust_alignof_{suffix}()) {{",
                f'    printf("[LAYOUT OK] struct={c_name} sizeof=%zu alignof=%zu\\n", sizeof(struct {c_name}), (size_t)_Alignof(struct {c_name}));',
                "  }",
            ]
        )
        fields = struct.get("fields", [])
        if not isinstance(fields, list):
            fields = []
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                continue
            field_name = field["name"]
            field_suffix = _safe_c_suffix(field_name)
            lines.extend(
                [
                    f"  if (rust_offsetof_{suffix}_{field_suffix}() == (size_t)-1) {{",
                    f'    printf("[LAYOUT MISMATCH] field={c_name}.{field_name} offset c=%zu rust=missing\\n", offsetof(struct {c_name}, {field_name}));',
                    f'    printf("possible_reason=active macro added field {field_name} that Rust omitted\\n");',
                    "    failures++;",
                    f"  }} else if (offsetof(struct {c_name}, {field_name}) != rust_offsetof_{suffix}_{field_suffix}()) {{",
                    f'    printf("[LAYOUT MISMATCH] field={c_name}.{field_name} offset c=%zu rust=%zu\\n", offsetof(struct {c_name}, {field_name}), rust_offsetof_{suffix}_{field_suffix}());',
                    "    failures++;",
                    "  } else {",
                    f'    printf("[LAYOUT OK] struct={c_name} field={field_name} offset=%zu\\n", offsetof(struct {c_name}, {field_name}));',
                    "  }",
                ]
            )
    lines.extend(
        [
            "  if (failures) {",
            '    printf("[LAYOUT CHECK] fail\\n");',
            "    return 1;",
            "  }",
            '  printf("[LAYOUT CHECK] pass\\n");',
            "  return 0;",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_layout_checker(c_root: Path, c_cross: Path, rust_lib: Path, trace: Path) -> tuple[bool, str]:
    structs = _layout_structs(trace)
    headers = _layout_headers(c_root, structs)
    source = c_cross / "layout_checker.c"
    binary = c_cross / "layout_checker"
    log_path = c_cross / "layout-check.log"
    source.write_text(_layout_checker_source(structs, headers), encoding="utf-8")
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        text = "missing C compiler: cc/gcc/clang not found\n"
        _write(log_path, text)
        return False, text
    command = [
        cc,
        "-std=c11",
        "-O0",
        "-g3",
        "-Wall",
        "-Wno-format",
        *_c_include_args(c_root, c_cross),
        str(source),
        str(rust_lib),
        "-o",
        str(binary),
        "-lpthread",
        "-ldl",
        "-lm",
    ]
    code, output = _run(command)
    text = f"$ {_command_text(command)}\n{output}\n"
    if code != 0:
        text += f"layout checker compile exited with {code}\n"
        _write(log_path, text)
        return False, text
    code, output = _run([str(binary.resolve())], cwd=c_cross)
    text += f"$ {_command_text([str(binary.resolve())], c_cross)}\n{output}\n"
    if code != 0:
        text += f"layout checker exited with {code}\n"
        _write(log_path, text)
        return False, text
    _write(log_path, text)
    return True, text


def _malformed_row(index: int, case: Any, c_cross: Path, root: Path) -> dict[str, Any]:
    scenario_id = f"malformed_case_{index}"
    log = c_cross / f"{scenario_id}.log"
    if isinstance(case, dict):
        missing_fields = []
        if not isinstance(case.get("scenario_id"), str):
            missing_fields.append("scenario_id")
        if not isinstance(case.get("case_id"), str):
            missing_fields.append("case_id")
        if not isinstance(case.get("suite"), str) or not case.get("suite"):
            missing_fields.append("suite")
        reason = f"malformed scorer_standard_cases entry at index {index}: missing or non-string {', '.join(missing_fields)}"
    else:
        reason = f"malformed scorer_standard_cases entry at index {index}: expected object, got {type(case).__name__}"
    _write(log, reason + "\n")
    return {
        "scenario_id": scenario_id,
        "scorer_case_id": scenario_id,
        "suite": "unknown",
        "phase": "build",
        "failure_layer": "build",
        "source_runner": "unknown",
        "source_test": scenario_id,
        "c_impl_c_test": "baseline",
        "rust_impl_c_test": "not_supported",
        "c_impl_rust_test": "not_run",
        "rust_impl_rust_test": "pending",
        "diagnosis": "c_cross_harness_not_supported",
        "reason": reason,
        "log": _relative_log_path(log, root),
        "handoff": "c-analyzer",
    }


def _source_evidence_by_scenario(test_model: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw = test_model.get("registered_test_invocations")
    if not isinstance(raw, list):
        return {}
    evidence: dict[str, dict[str, str]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        runner = item.get("runner")
        test_function = item.get("test_function") or item.get("name")
        scenarios = item.get("scenarios")
        if not isinstance(scenarios, list) and isinstance(test_function, str):
            scenarios = [test_function]
        if not isinstance(test_function, str) or not isinstance(scenarios, list):
            continue
        for scenario in scenarios:
            if isinstance(scenario, str) and scenario not in evidence:
                item_evidence = {"source_test": test_function}
                if isinstance(runner, str) and runner:
                    item_evidence["source_runner"] = runner
                evidence[scenario] = item_evidence
    return evidence


def _expected_tests_by_suite(
    cases: list[dict[str, Any]],
    source_evidence: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for case in cases:
        scenario_id = str(case["scenario_id"])
        suite = _suite_for_case(case)
        source_test = source_evidence.get(scenario_id, {}).get("source_test", scenario_id)
        tests = result.setdefault(suite, [])
        if source_test not in tests:
            tests.append(source_test)
    return result


def _handoff_for_diagnosis(diagnosis: str) -> str:
    if diagnosis in {"c_model_signature_gap", "c_cross_harness_not_supported"}:
        return "c-analyzer"
    if diagnosis in {
        "rust_staticlib_build_failed",
        "c_abi_layout_mismatch",
        "c_runner_link_failed",
        "c_runner_runtime_failed",
        "c_test_case_failed",
        "rust_implementation_failed_c_baseline",
    }:
        return "rust-implementer"
    return "none"


def _suite_result_rows(
    cases: list[dict[str, Any]],
    suite_results: dict[str, tuple[str, str]],
    suite_test_results: dict[str, dict[str, Any]],
    suite_phases: dict[str, str],
    suite_diagnoses: dict[str, str],
    source_evidence: dict[str, dict[str, str]],
    c_cross: Path,
    root: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        scenario_id = str(case["scenario_id"])
        suite = _suite_for_case(case)
        status, reason = suite_results.get(
            suite,
            ("not_supported", f"no original C runner is available for suite {suite}"),
        )
        log = c_cross / f"{scenario_id}.log"
        phase = suite_phases.get(suite, "full")
        diagnosis = suite_diagnoses.get(suite)
        evidence = source_evidence.get(scenario_id, {})
        source_test = evidence.get("source_test", scenario_id)
        source_runner = evidence.get("source_runner", f"{suite}_runner")
        parsed = suite_test_results.get(suite)
        if phase == "full" and parsed is not None:
            if parsed.get("status") != "parsed":
                status = "fail"
                diagnosis = "c_cross_result_parse_failed"
                reason = str(parsed.get("reason") or reason)
            elif source_test in parsed.get("passed", []):
                status = "pass"
                diagnosis = "rust_implementation_matches_c_baseline_for_scenario"
                reason = f"{source_test} passed in original C runner"
            elif source_test in parsed.get("failed", []):
                status = "fail"
                diagnosis = "c_test_case_failed"
                reason = str(parsed.get("failures", {}).get(source_test) or f"{source_test} failed")
            elif source_test in parsed.get("not_run", []):
                status = "not_run"
                diagnosis = "c_runner_runtime_failed"
                reason = f"{source_test} was not run before the runner exited"
            else:
                status = "fail"
                diagnosis = "c_cross_result_parse_failed"
                reason = f"no parsed result for expected source test {source_test}"
        if not diagnosis:
            if status == "pass":
                diagnosis = "rust_implementation_matches_c_baseline_for_scenario"
            elif status == "fail":
                diagnosis = "rust_implementation_failed_c_baseline"
            else:
                diagnosis = "c_cross_harness_not_supported"
        _write(log, f"suite={suite}\nsource_test={source_test}\nstatus={status}\nreason={reason}\n")
        rows.append(
            {
                "scenario_id": scenario_id,
                "scorer_case_id": str(case["case_id"]),
                "suite": suite,
                "phase": phase,
                "failure_layer": phase,
                "source_runner": source_runner,
                "source_test": source_test,
                "c_impl_c_test": "baseline",
                "rust_impl_c_test": status,
                "c_impl_rust_test": "not_run",
                "rust_impl_rust_test": "pending",
                "diagnosis": diagnosis,
                "reason": reason,
                "log": _relative_log_path(log, root),
                "handoff": _handoff_for_diagnosis(diagnosis),
            }
        )
    return rows


def build_matrix(
    root: Path,
    out: Path,
    project_name: str = "flashDB_rust",
    mode: str = "full",
    selected_suites: set[str] | None = None,
    attempt_kind: str = "checkpoint",
    trigger: str = "manual",
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    if mode not in {"build", "layout", "link", "full"}:
        raise ValueError(f"unsupported c-cross mode: {mode}")
    trace = out
    c_cross = trace / "c-cross"
    c_cross.mkdir(parents=True, exist_ok=True)

    test_model = load_json(trace / "c_test_model.json")
    raw_cases = test_model.get("scorer_standard_cases")
    if not isinstance(raw_cases, list):
        raise ValueError("c_test_model.json scorer_standard_cases must be a list")

    malformed = []
    valid_cases: list[dict[str, Any]] = []
    for index, case in enumerate(raw_cases):
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("scenario_id"), str)
            or not isinstance(case.get("case_id"), str)
            or not isinstance(case.get("suite"), str)
            or not case.get("suite")
        ):
            malformed.append(_malformed_row(index, case, c_cross, root))
        else:
            valid_cases.append(case)

    available_suites = {_suite_for_case(case) for case in valid_cases}
    if selected_suites is not None:
        unknown_suites = sorted(selected_suites - available_suites)
        if unknown_suites:
            raise ValueError("unknown requested C-cross suites: " + ", ".join(unknown_suites))
        valid_cases = [case for case in valid_cases if _suite_for_case(case) in selected_suites]

    compile_log: list[str] = []
    test_log: list[str] = []
    suite_results: dict[str, tuple[str, str]] = {}
    suite_test_results: dict[str, dict[str, Any]] = {}
    suite_phases: dict[str, str] = {}
    suite_diagnoses: dict[str, str] = {}
    diagnostics: list[dict[str, Any]] = []
    source_evidence = _source_evidence_by_scenario(test_model)
    expected_tests_by_suite = _expected_tests_by_suite(valid_cases, source_evidence)
    c_root = _find_c_project_root(root, trace)
    project = (root / project_name).resolve()
    suites = sorted({_suite_for_case(case) for case in valid_cases})

    if c_root is None:
        reason = "FlashDB C project root not found"
        compile_log.append(reason + "\n")
        _write_json(c_cross / "build-check.json", {"phase": "build", "status": "not_supported", "reason": reason})
        _write_json(c_cross / "layout-check.json", {"phase": "layout", "status": "not_run", "reason": reason})
        _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
        for suite in suites:
            suite_results[suite] = ("not_supported", reason)
            suite_phases[suite] = "build"
            suite_diagnoses[suite] = "c_cross_harness_not_supported"
    elif not project.exists():
        reason = f"Rust project not found: {project}"
        compile_log.append(reason + "\n")
        _write_json(c_cross / "build-check.json", {"phase": "build", "status": "fail", "reason": reason})
        _write_json(c_cross / "layout-check.json", {"phase": "layout", "status": "not_run", "reason": reason})
        _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
        for suite in suites:
            suite_results[suite] = ("fail", reason)
            suite_phases[suite] = "build"
            suite_diagnoses[suite] = "rust_staticlib_build_failed"
    else:
        rust_ok, rust_output = _build_rust_staticlib(project)
        compile_log.append(rust_output)
        _write_json(
            c_cross / "build-check.json",
            {
                "phase": "build",
                "status": "pass" if rust_ok else "fail",
                "command": "cargo build --release",
                "log": _relative_log_path(c_cross / "cross-compile.log", root),
                "staticlib": _relative_log_path(_rust_staticlib(project), root) if rust_ok else None,
            },
        )
        if not rust_ok:
            reason = "Rust staticlib build failed"
            _write_json(c_cross / "layout-check.json", {"phase": "layout", "status": "not_run", "reason": reason})
            _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
            for suite in suites:
                suite_results[suite] = ("fail", reason)
                suite_phases[suite] = "build"
                suite_diagnoses[suite] = "rust_staticlib_build_failed"
        elif mode == "build":
            reason = "stopped after build mode"
            _write_json(c_cross / "layout-check.json", {"phase": "layout", "status": "not_run", "reason": reason})
            _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
            for suite in suites:
                suite_results[suite] = ("pending", reason)
                suite_phases[suite] = "build"
                suite_diagnoses[suite] = "blocked_before_rust_test_migration"
        else:
            rust_lib = _rust_staticlib(project)
            layout_ok, layout_output = _run_layout_checker(c_root, c_cross, rust_lib, trace)
            compile_log.append(layout_output)
            _write_json(
                c_cross / "layout-check.json",
                {
                    "phase": "layout",
                    "status": "pass" if layout_ok else "fail",
                    "diagnosis": "pass" if layout_ok else "c_abi_layout_mismatch",
                    "log": _relative_log_path(c_cross / "layout-check.log", root),
                },
            )
            if not layout_ok:
                reason = "layout mismatch or layout checker failure; see logs/trace/c-cross/layout-check.log"
                _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
                for suite in suites:
                    suite_results[suite] = ("fail", reason)
                    suite_phases[suite] = "layout"
                    suite_diagnoses[suite] = "c_abi_layout_mismatch"
                for case in valid_cases:
                    diagnostics.append(
                        {
                            "phase": "layout",
                            "diagnosis": "c_abi_layout_mismatch",
                            "scenario_id": str(case["scenario_id"]),
                            "scorer_case_id": str(case["case_id"]),
                            "suite": _suite_for_case(case),
                            "handoff": "rust-implementer",
                            "reason": reason,
                            "log": _relative_log_path(c_cross / "layout-check.log", root),
                        }
                    )
            elif mode == "layout":
                reason = "stopped after layout mode"
                _write_json(c_cross / "link-check.json", {"phase": "link", "status": "not_run", "suites": {suite: "not_run" for suite in suites}, "reason": reason})
                for suite in suites:
                    suite_results[suite] = ("pending", reason)
                    suite_phases[suite] = "layout"
                    suite_diagnoses[suite] = "blocked_before_rust_test_migration"
            else:
                link_suites: dict[str, str] = {}
                link_reasons: dict[str, str] = {}
                compiled_binaries: dict[str, Path] = {}
                for suite in suites:
                    ok, binary, output = _compile_suite_runner(suite, c_root, c_cross, rust_lib)
                    compile_log.append(output)
                    if not ok or binary is None:
                        reason = f"{suite} original C runner failed to compile"
                        suite_results[suite] = ("fail", reason)
                        suite_phases[suite] = "link"
                        suite_diagnoses[suite] = "c_runner_link_failed"
                        link_suites[suite] = "fail"
                        link_reasons[suite] = reason
                        diagnostics.append(
                            {
                                "phase": "link",
                                "diagnosis": "c_runner_link_failed",
                                "suite": suite,
                                "handoff": "rust-implementer",
                                "reason": reason,
                                "log": _relative_log_path(c_cross / "cross-compile.log", root),
                            }
                        )
                        continue
                    compiled_binaries[suite] = binary
                    link_suites[suite] = "pass"
                _write_json(
                    c_cross / "link-check.json",
                    {
                        "phase": "link",
                        "status": "pass" if link_suites and all(value == "pass" for value in link_suites.values()) else "fail",
                        "suites": link_suites,
                        "reasons": link_reasons,
                        "log": _relative_log_path(c_cross / "cross-compile.log", root),
                    },
                )
                if mode == "link":
                    test_log.append("No C runner executed in link mode.\n")
                    for suite in suites:
                        if suite not in suite_results:
                            suite_results[suite] = ("pending", "stopped after link mode")
                            suite_phases[suite] = "link"
                            suite_diagnoses[suite] = "blocked_before_rust_test_migration"
                else:
                    for suite, binary in compiled_binaries.items():
                        run_ok, run_output, run_reason = _run_suite_runner(suite, binary, c_cross)
                        test_log.append(run_output)
                        suite_results[suite] = (
                            "pass" if run_ok else "fail",
                            run_reason,
                        )
                        suite_test_results[suite] = parse_runner_test_results(
                            run_output,
                            expected_tests_by_suite.get(suite, []),
                            0 if run_ok else 1,
                        )
                        suite_phases[suite] = "full"
                        suite_diagnoses[suite] = (
                            "rust_implementation_matches_c_baseline_for_scenario"
                            if run_ok
                            else "c_runner_runtime_failed"
                        )
                        if not run_ok:
                            diagnostics.append(
                                {
                                    "phase": "full",
                                    "diagnosis": "c_runner_runtime_failed",
                                    "suite": suite,
                                    "handoff": "rust-implementer",
                                    "reason": run_reason,
                                    "log": _relative_log_path(c_cross / f"{suite}_runner.log", root),
                                }
                            )
                    for suite in suites:
                        suite_phases.setdefault(suite, "link")

    _write(c_cross / "cross-compile.log", "\n".join(compile_log))
    _write(c_cross / "cross-test.log", "\n".join(test_log) if test_log else "No C runner executed.\n")

    scenarios = malformed + _suite_result_rows(
        valid_cases,
        suite_results,
        suite_test_results,
        suite_phases,
        suite_diagnoses,
        source_evidence,
        c_cross,
        root,
    )
    _write_jsonl(c_cross / "case-results.jsonl", scenarios)
    _write_jsonl(c_cross / "diagnostics.jsonl", diagnostics)
    summary = Counter(item["rust_impl_c_test"] for item in scenarios)
    return {
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        "policy": "strict",
        "mode": mode,
        "scope": "selected" if selected_suites is not None else "all",
        "selected_suites": sorted(selected_suites if selected_suites is not None else available_suites),
        "attempt_kind": attempt_kind,
        "trigger": trigger,
        "changed_files": list(changed_files or []),
        "total_scenarios": len(scenarios),
        "summary": {"rust_impl_c_test": dict(sorted(summary.items()))},
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FlashDB original C tests against the Rust C ABI staticlib.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--project", default="flashDB_rust", help="Rust project path, relative to root.")
    parser.add_argument("--out", default="logs/trace", help="Trace output directory, relative to root.")
    parser.add_argument("--mode", choices=["build", "layout", "link", "full"], default="full", help="C-cross checkpoint depth.")
    parser.add_argument("--suite", action="append", dest="suites", help="Run only a suite discovered from the current C test model. Repeatable.")
    parser.add_argument(
        "--attempt-kind",
        choices=["checkpoint", "repair", "confirmation", "final"],
        default="checkpoint",
        help="Classify this execution for convergence and final-gate policy.",
    )
    parser.add_argument("--trigger", default="manual", help="Machine-stable reason for this execution.")
    parser.add_argument("--changed-file", action="append", default=[], help="File changed before a repair execution. Repeatable.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = (root / args.out).resolve()
    matrix_path = out / "validation-matrix.json"
    previous_matrix = load_json(matrix_path) if matrix_path.exists() else None
    matrix = build_matrix(
        root,
        out,
        project_name=args.project,
        mode=args.mode,
        selected_suites=set(args.suites) if args.suites else None,
        attempt_kind=args.attempt_kind,
        trigger=args.trigger,
        changed_files=args.changed_file,
    )
    execution_id = f"{time.time_ns()}-{_safe_c_suffix(args.attempt_kind)}-{_safe_c_suffix(args.trigger)}"
    matrix["execution_id"] = execution_id
    attempt = record_attempt(
        out / "c-cross",
        previous_matrix,
        matrix,
        attempt_kind=args.attempt_kind,
        trigger=args.trigger,
        changed_files=args.changed_file,
    )
    matrix["convergence"] = {
        "progress": attempt["progress"],
        "regression": attempt["regression"],
        "no_progress_counts": attempt["no_progress_counts"],
        "next_action": attempt["next_action"],
    }
    _write_json(out / "c-cross" / "checkpoints" / f"{execution_id}.json", matrix)
    _write_json(matrix_path, matrix)
    counts = matrix["summary"]["rust_impl_c_test"]
    print("VERIFY_RUST_WITH_C_TESTS: MATRIX_WRITTEN")
    print(f"mapped_scenarios={matrix['total_scenarios']}")
    print(f"policy={matrix['policy']}")
    print("rust_impl_c_test=" + ",".join(f"{key}:{value}" for key, value in sorted(counts.items())))
    return 1 if counts.get("fail") or counts.get("not_supported") else 0


if __name__ == "__main__":
    raise SystemExit(main())
