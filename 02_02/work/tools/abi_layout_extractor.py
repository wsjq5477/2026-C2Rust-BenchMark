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
        if not target.exists():
            target.write_text(source.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        if source.name != target_name:
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


def _active_macros(project_root: Path, include_dirs: list[str], config_headers: list[str], tmp: Path) -> dict[str, str]:
    cc = _cc()
    if cc is None:
        return {}
    _prepare_config_alias(project_root, config_headers, tmp)
    source = tmp / "abi_macros.c"
    source.write_text(_discovered_header_includes(project_root, include_dirs), encoding="utf-8")
    command = [cc, "-dM", "-E", *_include_args(project_root, include_dirs, tmp), str(source)]
    code, output = _run(command, cwd=project_root)
    if code != 0:
        return {}
    macros: dict[str, str] = {}
    for line in output.splitlines():
        match = re.match(r"#define\s+(" + IDENT + r")\b(?:\s+(.*))?$", line)
        if match and match.group(1).startswith("FDB_"):
            macros[match.group(1)] = (match.group(2) or "1").strip()
    return dict(sorted(macros.items()))


def _referenced_structs(fields: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for field in fields:
        ctype = field.get("ctype")
        if isinstance(ctype, str):
            names.update(re.findall(r"\bstruct\s+(" + IDENT + r")\b", ctype))
    return names


def _split_top_level_commas(text: str) -> list[str]:
    """Split a C parameter list without splitting nested declarators."""
    parts: list[str] = []
    start = 0
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    for index, char in enumerate(text):
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "," and paren_depth == bracket_depth == brace_depth == 0:
            part = text[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
    final = text[start:].strip()
    if final:
        parts.append(final)
    return parts


def _array_extents(declarator: str, name_end: int) -> list[str]:
    suffix = declarator[name_end:]
    return [match.group(1).strip() for match in re.finditer(r"\[([^\]]*)\]", suffix)]


def _pointer_target(ctype: str) -> str | None:
    if "*" not in ctype:
        return None
    target = ctype.rsplit("*", 1)[0]
    target = re.sub(r"\s+", " ", target).strip()
    return target or None


def _field_contract(
    *,
    statement: str,
    name: str,
    ctype: str,
    name_end: int,
    callback_signature: dict[str, Any] | None = None,
    explicit_array_extents: list[str] | None = None,
) -> dict[str, Any]:
    extents = explicit_array_extents if explicit_array_extents is not None else _array_extents(statement, name_end)
    compact_type = re.sub(r"\s+", " ", ctype).strip()
    if callback_signature is not None and extents:
        kind = "function_pointer_array"
    elif callback_signature is not None:
        kind = "function_pointer"
    elif extents:
        kind = "array"
    elif re.match(r"^(?:struct|union)\s*\{", compact_type):
        kind = "anonymous_union" if compact_type.startswith("union") else "anonymous_struct"
    elif "*" in compact_type:
        kind = "pointer"
    elif re.match(r"^struct\s+" + IDENT + r"\b", compact_type):
        kind = "named_struct"
    elif re.match(r"^union\s+" + IDENT + r"\b", compact_type):
        kind = "named_union"
    elif re.search(r":\s*\d+\s*$", statement):
        kind = "bitfield"
    else:
        kind = "scalar_or_typedef"
    pointee = _pointer_target(compact_type) if kind in {"pointer", "array"} else None
    return {
        "name": name,
        "ctype": compact_type,
        "raw_declarator": statement,
        "kind": kind,
        "array_extents": extents,
        "pointee": pointee,
        "callback_signature": callback_signature,
        "condition": None,
    }


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
    function_pointer = re.search(
        r"^(?P<return>.*?)\(\s*\*\s*(?P<name>" + IDENT
        + r")(?P<arrays>(?:\s*\[[^\]]*\])*)\s*\)\s*\((?P<params>.*)\)\s*$",
        statement,
    )
    if function_pointer:
        name = function_pointer.group("name")
        raw_params = function_pointer.group("params").strip()
        callback_signature = {
            "return_type": function_pointer.group("return").strip(),
            "parameters": [] if raw_params in {"", "void"} else _split_top_level_commas(raw_params),
            "raw": statement,
        }
        return _field_contract(
            statement=statement,
            name=name,
            ctype=statement,
            name_end=function_pointer.end("name"),
            callback_signature=callback_signature,
            explicit_array_extents=[
                match.group(1).strip()
                for match in re.finditer(r"\[([^\]]*)\]", function_pointer.group("arrays"))
            ],
        )
    nested = re.search(r"\}\s*(" + IDENT + r")\s*(?:\[[^\]]*\]\s*)*$", statement)
    if nested:
        return _field_contract(
            statement=statement,
            name=nested.group(1),
            ctype=statement[: nested.start() + 1].strip(),
            name_end=nested.end(1),
        )
    match = re.search(r"(" + IDENT + r")\s*(?:\[[^\]]*\]\s*)*(?::\s*\d+)?\s*$", statement)
    if not match:
        return None
    name = match.group(1)
    ctype = statement[: match.start(1)].strip()
    if not ctype:
        return None
    return _field_contract(
        statement=statement,
        name=name,
        ctype=ctype,
        name_end=match.end(1),
    )


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
            if field.get("kind") == "bitfield":
                # Standard C does not permit offsetof/sizeof on a bit-field.
                # Preserve its declarator contract, but leave probe values
                # absent so downstream generators cannot pretend it is safe.
                continue
            lines.append(
                f'  printf("FIELD|{struct_name}|{field_name}|%zu|%zu|%zu\\n", '
                f"offsetof(struct {struct_name}, {field_name}), "
                f"sizeof(((struct {struct_name} *)0)->{field_name}), "
                f"(size_t)__alignof__(((struct {struct_name} *)0)->{field_name}));"
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
        elif len(parts) == 6 and parts[0] == "FIELD":
            field_values[(parts[1], parts[2])] = {
                "offset": int(parts[3]),
                "sizeof": int(parts[4]),
                "alignof": int(parts[5]),
            }
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
        # ABI correctness includes named structs embedded by value or pointer
        # in public structs.  Probe their complete transitive closure, rather
        # than silently omitting private-named implementation nodes.
        queue = [(name, name) for name in names]
        fields_by_struct: dict[str, list[dict[str, Any]]] = {}
        dependency_of: dict[str, set[str]] = {name: {name} for name in names}
        expanded_pairs: set[tuple[str, str]] = set()
        while queue:
            name, root_name = queue.pop(0)
            dependency_of.setdefault(name, set()).add(root_name)
            if (name, root_name) in expanded_pairs:
                continue
            expanded_pairs.add((name, root_name))
            if _find_struct_body(preprocessed, name) is None:
                continue
            fields = fields_by_struct.setdefault(name, _parse_fields(preprocessed, name))
            for dependency in sorted(_referenced_structs(fields)):
                dependency_of.setdefault(dependency, set()).add(root_name)
                queue.append((dependency, root_name))
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
                "dependency_of": sorted(dependency_of.get(name, {name})),
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
