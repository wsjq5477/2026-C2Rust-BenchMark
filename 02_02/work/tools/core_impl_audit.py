#!/usr/bin/env python3
"""Reject scaffold-only Rust implementations before functional verification.

The audit consumes the baseline written by generate_rust_scaffold.py.  It is
deliberately conservative: it rejects byte-for-byte/semantic scaffold bodies
and direct neutral constants, but does not try to judge real stateful Rust
implementations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_rust_source(text: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    without_comments = re.sub(r"//[^\n]*", "", without_blocks)
    return re.sub(r"\s+", "", without_comments)


def _normalized_rust_hash(text: str) -> str:
    return _sha256_bytes(_normalized_rust_source(text).encode("utf-8"))


def _load_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _resolve(root: Path, value: str | None, default: str) -> Path:
    path = Path(value or default)
    return path if path.is_absolute() else root / path


def _safe_external_ident(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower() or "item"
    if ident[0].isdigit():
        ident = f"item_{ident}"
    if ident in {
        "as", "break", "const", "continue", "crate", "else", "enum", "extern",
        "false", "fn", "for", "if", "impl", "in", "let", "loop", "match",
        "mod", "move", "mut", "pub", "ref", "return", "self", "static",
        "struct", "super", "trait", "true", "type", "unsafe", "use", "where",
        "while", "async", "await", "dyn",
    }:
        ident += "_"
    return ident


def _required_exports(design: dict[str, Any]) -> set[str]:
    facade = design.get("c_abi_facade")
    functions = facade.get("functions") if isinstance(facade, dict) else []
    if not isinstance(functions, list):
        return set()
    return {
        _safe_external_ident(str(item["rust_export"]))
        for item in functions
        if isinstance(item, dict) and isinstance(item.get("rust_export"), str)
    }


def _find_open_brace(source: str, start: int) -> int | None:
    # Function signatures generated from the design contain parentheses and
    # generic angle brackets but no braces, so the first non-comment brace is
    # the body opener.
    cursor = start
    while cursor < len(source):
        if source.startswith("//", cursor):
            newline = source.find("\n", cursor + 2)
            cursor = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", cursor):
            end = source.find("*/", cursor + 2)
            if end < 0:
                return None
            cursor = end + 2
            continue
        if source[cursor] == "{":
            return cursor
        cursor += 1
    return None


def _matching_brace(source: str, opening: int) -> int | None:
    depth = 0
    cursor = opening
    state = "code"
    block_depth = 0
    raw_terminator = ""
    while cursor < len(source):
        char = source[cursor]
        nxt = source[cursor + 1] if cursor + 1 < len(source) else ""
        if state == "line_comment":
            if char == "\n":
                state = "code"
            cursor += 1
            continue
        if state == "block_comment":
            if char == "/" and nxt == "*":
                block_depth += 1
                cursor += 2
            elif char == "*" and nxt == "/":
                block_depth -= 1
                cursor += 2
                if block_depth == 0:
                    state = "code"
            else:
                cursor += 1
            continue
        if state == "string":
            if char == "\\":
                cursor += 2
            else:
                cursor += 1
                if char == '"':
                    state = "code"
            continue
        if state == "char":
            if char == "\\":
                cursor += 2
            else:
                cursor += 1
                if char == "'":
                    state = "code"
            continue
        if state == "raw_string":
            if source.startswith(raw_terminator, cursor):
                cursor += len(raw_terminator)
                state = "code"
            else:
                cursor += 1
            continue

        if char == "/" and nxt == "/":
            state = "line_comment"
            cursor += 2
            continue
        if char == "/" and nxt == "*":
            state = "block_comment"
            block_depth = 1
            cursor += 2
            continue
        raw_match = re.match(r'r(#{0,16})"', source[cursor:])
        if raw_match:
            hashes = raw_match.group(1)
            raw_terminator = '"' + hashes
            state = "raw_string"
            cursor += raw_match.end()
            continue
        if char == '"':
            state = "string"
            cursor += 1
            continue
        if char == "'":
            # Treat only a syntactically short quoted value as a char literal;
            # lifetimes such as 'a must remain ordinary code.
            close = source.find("'", cursor + 1, min(len(source), cursor + 8))
            if close >= 0:
                state = "char"
            cursor += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return None


def _function_body(source: str, symbol: str) -> str | None:
    pattern = re.compile(
        r'\b(?:pub\s+)?(?:unsafe\s+)?extern\s+"C"\s+fn\s+'
        + re.escape(symbol)
        + r"\s*\("
    )
    match = pattern.search(source)
    if match is None:
        return None
    opening = _find_open_brace(source, match.end())
    if opening is None:
        return None
    closing = _matching_brace(source, opening)
    return None if closing is None else source[opening + 1 : closing]


def _is_direct_neutral_body(body: str) -> bool:
    value = _normalized_rust_source(body).rstrip(";")
    if value.startswith("return"):
        value = value[len("return") :].rstrip(";")
    if value in {
        "", "false", "true", "None", "std::ptr::null()", "std::ptr::null_mut()",
        "core::ptr::null()", "core::ptr::null_mut()",
    }:
        return True
    if re.fullmatch(r"[+-]?(?:0|1)(?:_?[iu](?:8|16|32|64|128|size))?", value):
        return True
    return bool(
        re.fullmatch(
            r"unsafe\{(?:core|std)::mem::zeroed(?:::[^()]*)?\(\)\}",
            value,
        )
    )


def _finding(code: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "severity": "error", "message": message, "evidence": evidence}


def audit(
    *,
    root: Path,
    project: Path,
    manifest_path: Path,
    design_path: Path,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    try:
        manifest = _load_object(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append(_finding("manifest_unavailable", "scaffold manifest cannot be loaded", path=str(manifest_path), detail=str(exc)))
        return _result(root, project, manifest_path, design_path, findings, 0, 0)
    try:
        design = _load_object(design_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append(_finding("design_unavailable", "Rust API design cannot be loaded", path=str(design_path), detail=str(exc)))
        design = {}

    if design_path.is_file():
        actual_design_hash = _sha256_bytes(design_path.read_bytes())
        if manifest.get("design_sha256") != actual_design_hash:
            findings.append(
                _finding(
                    "stale_scaffold_manifest",
                    "design changed after scaffold baseline was generated",
                    expected=manifest.get("design_sha256"),
                    actual=actual_design_hash,
                )
            )

    ffi_entries = manifest.get("ffi_functions")
    if not isinstance(ffi_entries, dict):
        ffi_entries = {}
        findings.append(_finding("invalid_manifest", "manifest ffi_functions must be an object"))
    required = _required_exports(design)
    missing_from_manifest = sorted(required - set(ffi_entries))
    for symbol in missing_from_manifest:
        findings.append(
            _finding(
                "manifest_missing_symbol",
                "required FFI export has no scaffold baseline",
                symbol=symbol,
            )
        )

    source_cache: dict[Path, str] = {}
    checked_functions = 0
    for symbol, entry in sorted(ffi_entries.items()):
        if not isinstance(symbol, str) or not isinstance(entry, dict):
            findings.append(_finding("invalid_manifest", "invalid ffi_functions entry", symbol=str(symbol)))
            continue
        relative = entry.get("path")
        if not isinstance(relative, str):
            findings.append(_finding("invalid_manifest", "FFI entry has no source path", symbol=symbol))
            continue
        path = project / relative
        try:
            source = source_cache.setdefault(path, path.read_text(encoding="utf-8"))
        except OSError as exc:
            findings.append(_finding("ffi_source_unavailable", "FFI source cannot be read", symbol=symbol, path=str(path), detail=str(exc)))
            continue
        body = _function_body(source, symbol)
        if body is None:
            findings.append(_finding("missing_ffi_symbol", "scaffold FFI export is missing or unparsable", symbol=symbol, path=relative))
            continue
        checked_functions += 1
        body_hash = _normalized_rust_hash(body)
        if body_hash == entry.get("body_normalized_sha256"):
            findings.append(
                _finding(
                    "unchanged_scaffold_body",
                    "FFI body is semantically identical to its generated scaffold",
                    symbol=symbol,
                    path=relative,
                    body_normalized_sha256=body_hash,
                )
            )
        if _is_direct_neutral_body(body):
            findings.append(
                _finding(
                    "constant_only_neutral_body",
                    "FFI body is only an empty/constant/null neutral result",
                    symbol=symbol,
                    path=relative,
                )
            )

    files = manifest.get("files")
    if isinstance(files, dict):
        for relative, baseline in sorted(files.items()):
            if not isinstance(relative, str) or not isinstance(baseline, dict):
                continue
            path = project / relative
            if not path.is_file():
                continue
            data = path.read_bytes()
            if _sha256_bytes(data) == baseline.get("sha256") or path.suffix != ".rs":
                continue
            current_normalized = _normalized_rust_hash(data.decode("utf-8"))
            if current_normalized == baseline.get("normalized_sha256"):
                findings.append(
                    _finding(
                        "cosmetic_only_file_change",
                        "file differs from scaffold only by comments/markers/whitespace",
                        path=relative,
                        normalized_sha256=current_normalized,
                    )
                )

    placeholders = manifest.get("placeholder_modules")
    if not isinstance(placeholders, dict):
        placeholders = {}
    checked_placeholders = 0
    for module, entry in sorted(placeholders.items()):
        if not isinstance(module, str) or not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            findings.append(_finding("invalid_manifest", "invalid placeholder_modules entry", module=str(module)))
            continue
        relative = entry["path"]
        path = project / relative
        if not path.is_file():
            findings.append(_finding("missing_core_module", "generated core module was deleted", module=module, path=relative))
            continue
        checked_placeholders += 1
        source = path.read_text(encoding="utf-8")
        sha = _sha256_bytes(source.encode("utf-8"))
        normalized = _normalized_rust_hash(source)
        marker = str(entry.get("marker") or "")
        if marker in source or sha == entry.get("sha256") or normalized == entry.get("normalized_sha256"):
            findings.append(
                _finding(
                    "placeholder_module",
                    "core module still carries the generated availability placeholder",
                    module=module,
                    path=relative,
                    marker_present=bool(marker and marker in source),
                )
            )

    return _result(
        root,
        project,
        manifest_path,
        design_path,
        findings,
        checked_functions,
        checked_placeholders,
    )


def _result(
    root: Path,
    project: Path,
    manifest_path: Path,
    design_path: Path,
    findings: list[dict[str, Any]],
    checked_functions: int,
    checked_placeholders: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "fail" if findings else "pass",
        "root": str(root.resolve()),
        "project": str(project.resolve()),
        "manifest": str(manifest_path.resolve()),
        "design": str(design_path.resolve()),
        "summary": {
            "findings": len(findings),
            "checked_ffi_functions": checked_functions,
            "checked_placeholder_modules": checked_placeholders,
        },
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Rust code for unchanged scaffold implementations.")
    parser.add_argument("--root", default=".", help="Conversion workspace root.")
    parser.add_argument("--project", help="Rust project path, relative to --root.")
    parser.add_argument("--manifest", help="Scaffold manifest path, relative to --root.")
    parser.add_argument("--design", help="Rust API design path, relative to --root.")
    parser.add_argument("--output", help="Audit JSON path, relative to --root.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    project = _resolve(root, args.project, "flashDB_rust")
    manifest_path = _resolve(root, args.manifest, "logs/trace/scaffold-manifest.json")
    design_path = _resolve(root, args.design, "logs/trace/rust_api_design.json")
    output = _resolve(root, args.output, "logs/trace/implementation-audit.json")
    result = audit(root=root, project=project, manifest_path=manifest_path, design_path=design_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = str(result["status"]).upper()
    print(f"CORE_IMPL_AUDIT: {status}")
    print(f"findings={result['summary']['findings']}")
    print(f"output={output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
