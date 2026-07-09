#!/usr/bin/env python3
"""Extract C compiler-confirmed ABI layouts for FlashDB structs."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def _run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.returncode, completed.stdout


def _cc() -> str | None:
    return shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//.*", " ", text)
    return text


def _prepare_config_alias(project_root: Path, config_headers: list[str], tmp: Path) -> list[str]:
    alias_dir = tmp / "config"
    alias_dir.mkdir(parents=True, exist_ok=True)
    aliases: list[str] = []
    for header in config_headers:
        source = (project_root / header).resolve()
        if not source.is_file():
            continue
        aliases.append(header)
        if source.name.endswith("_template.h"):
            target_name = source.name.replace("_template.h", ".h")
        else:
            target_name = source.name
        target = alias_dir / target_name
        if not target.exists() and source.name != target_name:
            target.write_text(source.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
            aliases.append(target_name)
    return aliases


def _include_args(project_root: Path, include_dirs: list[str], tmp: Path) -> list[str]:
    args = ["-I", str(tmp / "config")]
    for include_dir in include_dirs:
        args.extend(["-I", str((project_root / include_dir).resolve())])
    return args


def _discovered_header_includes(project_root: Path, include_dirs: list[str]) -> str:
    headers: list[str] = []
    for include_dir in include_dirs:
        root = project_root / include_dir
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.h")):
            headers.append(path.relative_to(root).as_posix())
    standard_headers = [
        "#include <stdbool.h>",
        "#include <stddef.h>",
        "#include <stdint.h>",
    ]
    project_headers = [f'#include "{header}"' for header in sorted(dict.fromkeys(headers))]
    return "\n".join(standard_headers + project_headers) + "\n"


def _preprocess(project_root: Path, include_dirs: list[str], config_headers: list[str], tmp: Path) -> str:
    cc = _cc()
    if cc is None:
        raise RuntimeError("missing C compiler: cc/gcc/clang not found")
    _prepare_config_alias(project_root, config_headers, tmp)
    source = tmp / "abi_preprocess.c"
    source.write_text(_discovered_header_includes(project_root, include_dirs), encoding="utf-8")
    command = [cc, "-E", "-P", *_include_args(project_root, include_dirs, tmp), str(source)]
    code, output = _run(command, cwd=project_root)
    if code != 0:
        raise RuntimeError(f"C preprocessing failed:\n{output}")
    return output


def _active_macros(project_root: Path, include_dirs: list[str], config_headers: list[str], tmp: Path) -> list[str]:
    cc = _cc()
    if cc is None:
        return []
    _prepare_config_alias(project_root, config_headers, tmp)
    source = tmp / "abi_macros.c"
    source.write_text(_discovered_header_includes(project_root, include_dirs), encoding="utf-8")
    command = [cc, "-dM", "-E", *_include_args(project_root, include_dirs, tmp), str(source)]
    code, output = _run(command, cwd=project_root)
    if code != 0:
        return []
    names = []
    for line in output.splitlines():
        match = re.match(r"#define\s+(" + IDENT + r")\b", line)
        if match and match.group(1).startswith("FDB_"):
            names.append(match.group(1))
    return sorted(dict.fromkeys(names))


def _find_struct_body(preprocessed: str, struct_name: str) -> str | None:
    match = re.search(r"\bstruct\s+" + re.escape(struct_name) + r"\s*\{", preprocessed)
    if not match:
        return None
    depth = 1
    cursor = match.end()
    while cursor < len(preprocessed) and depth:
        char = preprocessed[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        cursor += 1
    if depth != 0:
        return None
    return preprocessed[match.end() : cursor - 1]


def _split_top_level_fields(body: str) -> list[str]:
    fields: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(body):
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            statement = body[start:index].strip()
            start = index + 1
            if statement:
                fields.append(statement)
    return fields


def _field_from_statement(statement: str) -> dict[str, Any] | None:
    statement = re.sub(r"\s+", " ", statement.strip())
    if not statement or statement.startswith("typedef "):
        return None
    function_pointer = re.search(r"\(\s*\*\s*(" + IDENT + r")\s*\)", statement)
    if function_pointer:
        return {"name": function_pointer.group(1), "ctype": statement, "condition": None}
    nested = re.search(r"\}\s*(" + IDENT + r")\s*(?:\[[^\]]+\])?\s*$", statement)
    if nested:
        return {"name": nested.group(1), "ctype": statement[: nested.start() + 1].strip(), "condition": None}
    match = re.search(r"(" + IDENT + r")\s*(?:\[[^\]]+\])?\s*(?::\s*\d+)?\s*$", statement)
    if not match:
        return None
    name = match.group(1)
    ctype = statement[: match.start(1)].strip()
    if not ctype:
        return None
    return {"name": name, "ctype": ctype, "condition": None}


def _parse_fields(preprocessed: str, struct_name: str) -> list[dict[str, Any]]:
    body = _find_struct_body(preprocessed, struct_name)
    if body is None:
        return []
    fields: list[dict[str, Any]] = []
    for statement in _split_top_level_fields(_strip_comments(body)):
        field = _field_from_statement(statement)
        if field is not None:
            fields.append(field)
    return fields


def _probe_source(project_root: Path, include_dirs: list[str], fields_by_struct: dict[str, list[dict[str, Any]]]) -> str:
    lines = [
        "#include <stddef.h>",
        "#include <stdio.h>",
    ]
    lines.extend(_discovered_header_includes(project_root, include_dirs).splitlines())
    lines.append("int main(void) {")
    for struct_name, fields in fields_by_struct.items():
        lines.append(
            f'  printf("STRUCT|{struct_name}|%zu|%zu\\n", '
            f"sizeof(struct {struct_name}), _Alignof(struct {struct_name}));"
        )
        for field in fields:
            field_name = field["name"]
            lines.append(
                f'  printf("FIELD|{struct_name}|{field_name}|%zu|%zu\\n", '
                f"offsetof(struct {struct_name}, {field_name}), "
                f"sizeof(((struct {struct_name} *)0)->{field_name}));"
            )
    lines.append("  return 0;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _run_probe(
    project_root: Path,
    include_dirs: list[str],
    config_headers: list[str],
    fields_by_struct: dict[str, list[dict[str, Any]]],
    tmp: Path,
) -> dict[str, dict[str, Any]]:
    cc = _cc()
    if cc is None:
        raise RuntimeError("missing C compiler: cc/gcc/clang not found")
    _prepare_config_alias(project_root, config_headers, tmp)
    source = tmp / "abi_probe.c"
    binary = tmp / "abi_probe"
    source.write_text(_probe_source(project_root, include_dirs, fields_by_struct), encoding="utf-8")
    command = [cc, "-std=c11", *_include_args(project_root, include_dirs, tmp), str(source), "-o", str(binary)]
    code, output = _run(command, cwd=project_root)
    if code != 0:
        raise RuntimeError(f"ABI probe compile failed:\n{output}")
    code, output = _run([str(binary)], cwd=project_root)
    if code != 0:
        raise RuntimeError(f"ABI probe run failed:\n{output}")
    layouts: dict[str, dict[str, Any]] = {}
    field_values: dict[tuple[str, str], dict[str, int]] = {}
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) == 4 and parts[0] == "STRUCT":
            layouts[parts[1]] = {"sizeof": int(parts[2]), "alignof": int(parts[3])}
        elif len(parts) == 5 and parts[0] == "FIELD":
            field_values[(parts[1], parts[2])] = {"offset": int(parts[3]), "sizeof": int(parts[4])}
    for struct_name, fields in fields_by_struct.items():
        for field in fields:
            values = field_values.get((struct_name, field["name"]))
            if values:
                field.update(values)
    return layouts


def _header_for_struct(project_root: Path, include_dirs: list[str], struct_name: str) -> str:
    pattern = re.compile(r"\bstruct\s+" + re.escape(struct_name) + r"\b")
    for include_dir in include_dirs:
        root = project_root / include_dir
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.h")):
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                return path.relative_to(project_root).as_posix()
    return ""


def extract_layouts(
    project_root: str | Path,
    include_dirs: list[str],
    config_headers: list[str],
    struct_names: list[str],
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    names = sorted(dict.fromkeys(name for name in struct_names if re.fullmatch(IDENT, name)))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        preprocessed = _preprocess(root, include_dirs, config_headers, tmp)
        active_macros = _active_macros(root, include_dirs, config_headers, tmp)
        fields_by_struct = {
            name: _parse_fields(preprocessed, name)
            for name in names
            if _find_struct_body(preprocessed, name) is not None
        }
        probed = _run_probe(root, include_dirs, config_headers, fields_by_struct, tmp) if fields_by_struct else {}
    layouts: list[dict[str, Any]] = []
    for name, fields in fields_by_struct.items():
        values = probed.get(name)
        if values is None:
            continue
        layouts.append(
            {
                "name": name,
                "header": _header_for_struct(root, include_dirs, name),
                "sizeof": values["sizeof"],
                "alignof": values["alignof"],
                "active_macros": active_macros,
                "fields": fields,
            }
        )
    return {"abi_layouts": layouts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract C ABI layouts with a compiler probe.")
    parser.add_argument("--root", required=True, help="C project root.")
    parser.add_argument("--include-dir", action="append", default=[], help="Include directory relative to root.")
    parser.add_argument("--config-header", action="append", default=[], help="Config header relative to root.")
    parser.add_argument("--struct", action="append", default=[], help="Struct name without the struct keyword.")
    parser.add_argument("--output", required=True, help="Path to write layout JSON.")
    args = parser.parse_args(argv)
    result = extract_layouts(
        project_root=Path(args.root),
        include_dirs=args.include_dir or ["inc"],
        config_headers=args.config_header,
        struct_names=args.struct,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("ABI_LAYOUT_EXTRACTOR: LAYOUTS_WRITTEN")
    print(f"abi_layouts={len(result['abi_layouts'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
