#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
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


def _command_text(command: list[str], cwd: Path | None = None) -> str:
    prefix = f"(cd {cwd} && )" if cwd else ""
    return prefix + " ".join(command)


def _safe_c_suffix(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()


def _run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.returncode, completed.stdout


def _suite_for_case(case: dict[str, Any]) -> str:
    suite = case.get("suite")
    if isinstance(suite, str) and suite:
        return suite
    scenario = str(case.get("scenario_id", "")).lower()
    if "tsl" in scenario or "tsdb" in scenario or "github_issue" in scenario:
        return "tsdb"
    if "kv" in scenario or "gc" in scenario or "scale" in scenario:
        return "kvdb"
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


def _run_suite_runner(suite: str, binary: Path, c_cross: Path) -> tuple[bool, str]:
    run_dir = c_cross / f"{suite}-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    command = [str(binary.resolve())]
    code, output = _run(command, cwd=run_dir)
    text = f"$ {_command_text(command, run_dir)}\n{output}\n"
    if code != 0:
        text += f"runner exited with {code}\n"
        return False, text
    return True, text


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
        reason = f"malformed scorer_standard_cases entry at index {index}: missing or non-string {', '.join(missing_fields)}"
    else:
        reason = f"malformed scorer_standard_cases entry at index {index}: expected object, got {type(case).__name__}"
    _write(log, reason + "\n")
    return {
        "scenario_id": scenario_id,
        "scorer_case_id": scenario_id,
        "suite": "unknown",
        "c_impl_c_test": "baseline",
        "rust_impl_c_test": "not_supported",
        "c_impl_rust_test": "not_run",
        "rust_impl_rust_test": "pending",
        "diagnosis": "c_cross_harness_not_supported",
        "reason": reason,
        "log": _relative_log_path(log, root),
    }


def _suite_result_rows(
    cases: list[dict[str, Any]],
    suite_results: dict[str, tuple[str, str]],
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
        if status == "pass":
            diagnosis = "rust_implementation_matches_c_baseline_for_scenario"
        elif status == "fail":
            diagnosis = "rust_implementation_failed_c_baseline"
        else:
            diagnosis = "c_cross_harness_not_supported"
        _write(log, f"suite={suite}\nstatus={status}\nreason={reason}\n")
        rows.append(
            {
                "scenario_id": scenario_id,
                "scorer_case_id": str(case["case_id"]),
                "suite": suite,
                "c_impl_c_test": "baseline",
                "rust_impl_c_test": status,
                "c_impl_rust_test": "not_run",
                "rust_impl_rust_test": "pending",
                "diagnosis": diagnosis,
                "reason": reason,
                "log": _relative_log_path(log, root),
            }
        )
    return rows


def build_matrix(root: Path, out: Path, project_name: str = "flashDB_rust") -> dict[str, Any]:
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
        ):
            malformed.append(_malformed_row(index, case, c_cross, root))
        else:
            valid_cases.append(case)

    compile_log = []
    test_log = []
    suite_results: dict[str, tuple[str, str]] = {}
    c_root = _find_c_project_root(root, trace)
    project = (root / project_name).resolve()

    if c_root is None:
        reason = "FlashDB C project root not found"
        compile_log.append(reason + "\n")
        for suite in sorted({_suite_for_case(case) for case in valid_cases}):
            suite_results[suite] = ("not_supported", reason)
    elif not project.exists():
        reason = f"Rust project not found: {project}"
        compile_log.append(reason + "\n")
        for suite in sorted({_suite_for_case(case) for case in valid_cases}):
            suite_results[suite] = ("fail", reason)
    else:
        rust_ok, rust_output = _build_rust_staticlib(project)
        compile_log.append(rust_output)
        if not rust_ok:
            reason = "Rust staticlib build failed"
            for suite in sorted({_suite_for_case(case) for case in valid_cases}):
                suite_results[suite] = ("fail", reason)
        else:
            rust_lib = _rust_staticlib(project)
            layout_ok, layout_output = _run_layout_checker(c_root, c_cross, rust_lib, trace)
            compile_log.append(layout_output)
            if not layout_ok:
                reason = "layout mismatch or layout checker failure; see logs/trace/c-cross/layout-check.log"
                for suite in sorted({_suite_for_case(case) for case in valid_cases}):
                    suite_results[suite] = ("fail", reason)
            else:
                for suite in sorted({_suite_for_case(case) for case in valid_cases}):
                    ok, binary, output = _compile_suite_runner(suite, c_root, c_cross, rust_lib)
                    compile_log.append(output)
                    if not ok or binary is None:
                        suite_results[suite] = ("fail", f"{suite} original C runner failed to compile")
                        continue
                    run_ok, run_output = _run_suite_runner(suite, binary, c_cross)
                    test_log.append(run_output)
                    suite_results[suite] = (
                        "pass" if run_ok else "fail",
                        f"{suite} original C runner {'passed' if run_ok else 'failed'}",
                    )

    _write(c_cross / "cross-compile.log", "\n".join(compile_log))
    _write(c_cross / "cross-test.log", "\n".join(test_log) if test_log else "No C runner executed.\n")

    scenarios = malformed + _suite_result_rows(valid_cases, suite_results, c_cross, root)
    summary = Counter(item["rust_impl_c_test"] for item in scenarios)
    return {
        "stage": "VERIFY_RUST_WITH_C_TESTS",
        "policy": "strict",
        "total_scenarios": len(scenarios),
        "summary": {"rust_impl_c_test": dict(sorted(summary.items()))},
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FlashDB original C tests against the Rust C ABI staticlib.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--project", default="flashDB_rust", help="Rust project path, relative to root.")
    parser.add_argument("--out", default="logs/trace", help="Trace output directory, relative to root.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = (root / args.out).resolve()
    matrix = build_matrix(root, out, project_name=args.project)
    matrix_path = out / "validation-matrix.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = matrix["summary"]["rust_impl_c_test"]
    print("VERIFY_RUST_WITH_C_TESTS: MATRIX_WRITTEN")
    print(f"mapped_scenarios={matrix['total_scenarios']}")
    print(f"policy={matrix['policy']}")
    print("rust_impl_c_test=" + ",".join(f"{key}:{value}" for key, value in sorted(counts.items())))
    return 1 if counts.get("fail") or counts.get("not_supported") else 0


if __name__ == "__main__":
    raise SystemExit(main())
