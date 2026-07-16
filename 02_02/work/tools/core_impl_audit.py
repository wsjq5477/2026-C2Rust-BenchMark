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
import time
from pathlib import Path
from typing import Any


AUDIT_SCHEMA_VERSION = 2
MAX_IMPLEMENTATION_REPAIR_ATTEMPTS = 1
IMPLEMENTATION_ATTEMPT_KINDS = {"checkpoint", "repair", "confirmation"}


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


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def current_source_manifest(project: Path) -> dict[str, str]:
    """Hash current Rust implementation inputs without including build output."""
    project = project.resolve()
    files: set[Path] = set()
    src = project / "src"
    if src.is_dir():
        files.update(
            path
            for path in src.rglob("*.rs")
            if path.is_file() and not path.is_symlink()
        )
    cargo = project / "Cargo.toml"
    if cargo.is_file() and not cargo.is_symlink():
        files.add(cargo)
    return {
        path.relative_to(project).as_posix(): _file_sha256(path)
        for path in sorted(files)
    }


def _baseline_fingerprint(manifest_path: Path, design_path: Path) -> str:
    payload = {
        "manifest_sha256": _file_sha256(manifest_path) if manifest_path.is_file() else "missing",
        "design_sha256": _file_sha256(design_path) if design_path.is_file() else "missing",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + _sha256_bytes(encoded)


def audit_input_fingerprint(
    manifest_path: Path,
    design_path: Path,
    source_manifest: dict[str, str],
) -> str:
    payload = {
        "baseline_fingerprint": _baseline_fingerprint(manifest_path, design_path),
        "source_manifest": source_manifest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + _sha256_bytes(encoded)


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


def _matching_paren(source: str, opening: int) -> int | None:
    depth = 0
    cursor = opening
    state = "code"
    block_depth = 0
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
        if char == "/" and nxt == "/":
            state = "line_comment"
            cursor += 2
            continue
        if char == "/" and nxt == "*":
            state = "block_comment"
            block_depth = 1
            cursor += 2
            continue
        if char == '"':
            state = "string"
            cursor += 1
            continue
        if char == "'":
            close = source.find("'", cursor + 1, min(len(source), cursor + 8))
            if close >= 0:
                state = "char"
            cursor += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return None


def _split_top_level_params(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    closing = {")": "(", "]": "[", "}": "{", ">": "<"}
    for index, char in enumerate(value):
        if char in depths:
            depths[char] += 1
        elif char in closing and depths[closing[char]] > 0:
            depths[closing[char]] -= 1
        elif char == "," and all(depth == 0 for depth in depths.values()):
            part = value[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _function_signature(source: str, symbol: str) -> str | None:
    pattern = re.compile(
        r'\b(?:pub\s+)?(?:unsafe\s+)?extern\s+"C"\s+fn\s+'
        + re.escape(symbol)
        + r"\s*\("
    )
    match = pattern.search(source)
    if match is None:
        return None
    opening = source.rfind("(", match.start(), match.end())
    if opening < 0:
        return None
    closing = _matching_paren(source, opening)
    if closing is None:
        return None
    body_opening = _find_open_brace(source, closing + 1)
    if body_opening is None:
        return None
    params = ",".join(_split_top_level_params(source[opening + 1 : closing]))
    suffix = source[closing + 1 : body_opening].strip()
    return_type = suffix[2:].strip() if suffix.startswith("->") else "()"
    return f"{symbol}({params})->{return_type}"


def _normalized_signature(value: str) -> str:
    return _normalized_rust_source(value).replace(",)", ")")


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
    source_manifest = current_source_manifest(project)
    input_fingerprint = audit_input_fingerprint(manifest_path, design_path, source_manifest)
    baseline_fingerprint = _baseline_fingerprint(manifest_path, design_path)
    try:
        manifest = _load_object(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append(_finding("manifest_unavailable", "scaffold manifest cannot be loaded", path=str(manifest_path), detail=str(exc)))
        return _result(
            root, project, manifest_path, design_path, findings, 0, 0, 0,
            source_manifest, input_fingerprint, baseline_fingerprint,
        )
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
    stub_symbols = manifest.get("stub_symbols")
    if (
        not isinstance(stub_symbols, list)
        or any(not isinstance(item, str) for item in stub_symbols)
        or sorted(stub_symbols) != sorted(ffi_entries)
    ):
        findings.append(
            _finding(
                "invalid_manifest",
                "manifest stub_symbols must exactly match ffi_functions",
            )
        )
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
        marker = entry.get("marker")
        if isinstance(marker, str) and marker and f"{marker} symbol={symbol}" in source:
            findings.append(
                _finding(
                    "ffi_scaffold_marker",
                    "FFI export still carries its generated scaffold marker",
                    symbol=symbol,
                    path=relative,
                )
            )
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

    ownership = manifest.get("rewrite_ownership")
    frozen_symbols = ownership.get("frozen_contract_symbols") if isinstance(ownership, dict) else []
    if not isinstance(frozen_symbols, list):
        frozen_symbols = []
        findings.append(_finding("invalid_manifest", "rewrite_ownership frozen_contract_symbols must be a list"))
    checked_frozen_signatures = 0
    for item in frozen_symbols:
        if not isinstance(item, dict):
            findings.append(_finding("invalid_manifest", "invalid frozen_contract_symbols entry"))
            continue
        symbol = item.get("symbol")
        relative = item.get("path")
        expected = item.get("signature")
        if not all(isinstance(value, str) and value for value in (symbol, relative, expected)):
            findings.append(_finding("invalid_manifest", "frozen ABI symbol entry is incomplete", entry=item))
            continue
        expected_hash = item.get("signature_sha256")
        if expected_hash != _sha256_bytes(expected.encode("utf-8")):
            findings.append(
                _finding(
                    "invalid_manifest",
                    "frozen ABI signature hash does not match its contract text",
                    symbol=symbol,
                    path=relative,
                )
            )
            continue
        path = project / relative
        try:
            source = source_cache.setdefault(path, path.read_text(encoding="utf-8"))
        except OSError as exc:
            findings.append(
                _finding(
                    "ffi_source_unavailable",
                    "frozen ABI source cannot be read",
                    symbol=symbol,
                    path=relative,
                    detail=str(exc),
                )
            )
            continue
        actual = _function_signature(source, symbol)
        if actual is None:
            findings.append(
                _finding(
                    "missing_frozen_ffi_signature",
                    "frozen ABI export is missing or its signature cannot be parsed",
                    symbol=symbol,
                    path=relative,
                )
            )
            continue
        checked_frozen_signatures += 1
        if _normalized_signature(actual) != _normalized_signature(expected):
            findings.append(
                _finding(
                    "changed_frozen_ffi_signature",
                    "FFI signature differs from the scaffold ABI contract",
                    symbol=symbol,
                    path=relative,
                    expected=expected,
                    actual=actual,
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
        checked_frozen_signatures,
        source_manifest,
        input_fingerprint,
        baseline_fingerprint,
    )


def audit_workspace(
    root: Path,
    project_name: str = "flashDB_rust",
    manifest_name: str = "logs/trace/scaffold-manifest.json",
    design_name: str = "logs/trace/rust_api_design.json",
) -> dict[str, Any]:
    root = root.resolve()
    return audit(
        root=root,
        project=_resolve(root, project_name, "flashDB_rust"),
        manifest_path=_resolve(root, manifest_name, "logs/trace/scaffold-manifest.json"),
        design_path=_resolve(root, design_name, "logs/trace/rust_api_design.json"),
    )


def _result(
    root: Path,
    project: Path,
    manifest_path: Path,
    design_path: Path,
    findings: list[dict[str, Any]],
    checked_functions: int,
    checked_placeholders: int,
    checked_frozen_signatures: int,
    source_manifest: dict[str, str],
    input_fingerprint: str,
    baseline_fingerprint: str,
) -> dict[str, Any]:
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "fail" if findings else "pass",
        "root": str(root.resolve()),
        "project": str(project.resolve()),
        "manifest": str(manifest_path.resolve()),
        "design": str(design_path.resolve()),
        "baseline_fingerprint": baseline_fingerprint,
        "input_fingerprint": input_fingerprint,
        "source_manifest": source_manifest,
        "summary": {
            "findings": len(findings),
            "checked_ffi_functions": checked_functions,
            "checked_placeholder_modules": checked_placeholders,
            "checked_frozen_signatures": checked_frozen_signatures,
        },
        "findings": findings,
    }


def load_attempts(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError("implementation-attempts.jsonl rows must be objects")
        rows.append(item)
    return rows


def _manifest_changed_files(before: Any, after: Any) -> list[str]:
    old = before if isinstance(before, dict) else {}
    new = after if isinstance(after, dict) else {}
    return sorted(
        path
        for path in set(old) | set(new)
        if old.get(path) != new.get(path)
    )


def _current_baseline_attempts(
    attempts: list[dict[str, Any]],
    baseline_fingerprint: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in attempts
        if row.get("baseline_fingerprint") == baseline_fingerprint
    ]


def implementation_evidence(
    result: dict[str, Any],
    attempts: list[dict[str, Any]],
    layout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = result.get("baseline_fingerprint")
    scoped = _current_baseline_attempts(attempts, str(baseline)) if isinstance(baseline, str) else []
    errors: list[str] = []
    repairs_used = sum(row.get("kind") == "repair" for row in scoped)
    latest = scoped[-1] if scoped else {}
    layout = layout if isinstance(layout, dict) else {}
    layout_current = layout.get("source_manifest") == result.get("source_manifest")
    layout_pass = bool(
        layout_current
        and layout.get("status") == "pass"
        and layout.get("build_status") == "pass"
        and layout.get("layout_status") == "pass"
    )
    if not layout_current:
        errors.append("current implementation build/layout evidence is missing or stale")
    if not scoped:
        errors.append("missing current implementation audit attempt")
    else:
        if latest.get("input_fingerprint") != result.get("input_fingerprint"):
            errors.append("latest implementation attempt is stale for current Rust sources")
        if latest.get("source_manifest") != result.get("source_manifest"):
            errors.append("latest implementation attempt source manifest is stale")
        if latest.get("audit_status") != result.get("status"):
            errors.append("latest implementation attempt status does not match current audit")
        if latest.get("repair_attempts_used") != repairs_used:
            errors.append("latest implementation attempt repair count is inconsistent")
        if latest.get("max_repair_attempts") != MAX_IMPLEMENTATION_REPAIR_ATTEMPTS:
            errors.append("implementation repair budget is inconsistent")
    if repairs_used > MAX_IMPLEMENTATION_REPAIR_ATTEMPTS:
        errors.append("implementation repair budget exceeded")
    if scoped:
        checkpoints = sum(row.get("kind") == "checkpoint" for row in scoped)
        if checkpoints != 1 or scoped[0].get("kind") != "checkpoint":
            errors.append("implementation evidence requires exactly one leading checkpoint")

    previous: dict[str, Any] | None = None
    for row in scoped:
        kind = row.get("kind")
        if kind not in IMPLEMENTATION_ATTEMPT_KINDS:
            errors.append("implementation attempt has invalid kind")
            previous = row
            continue
        if kind == "repair":
            if not isinstance(previous, dict) or previous.get("kind") != "checkpoint":
                errors.append("implementation repair must immediately follow the checkpoint")
            actual = _manifest_changed_files(
                previous.get("source_manifest") if isinstance(previous, dict) else {},
                row.get("source_manifest"),
            )
            if not actual or row.get("actual_changed_files") != actual:
                errors.append("implementation repair must record real current Rust source changes")
        if kind == "confirmation":
            if not isinstance(previous, dict) or previous.get("kind") != "repair":
                errors.append("implementation confirmation must immediately follow a repair")
            elif _manifest_changed_files(previous.get("source_manifest"), row.get("source_manifest")):
                errors.append("implementation confirmation must not change Rust sources")
        previous = row

    valid = not errors
    if result.get("status") == "pass" and layout_pass and valid:
        status = "ready_for_verify"
        terminal = False
        next_action = "run_c_cross_checkpoint"
    elif (
        valid
        and latest.get("kind") == "confirmation"
        and repairs_used >= MAX_IMPLEMENTATION_REPAIR_ATTEMPTS
        and (result.get("status") != "pass" or not layout_pass)
    ):
        status = "failed_final"
        terminal = True
        next_action = "report_implementation_failure"
    else:
        status = "implementation_required"
        terminal = False
        next_action = (
            "run_fresh_implementation_confirmation"
            if valid and latest.get("kind") == "repair" and repairs_used >= MAX_IMPLEMENTATION_REPAIR_ATTEMPTS
            else "repair_scaffold_residue"
        )
    return {
        "status": status,
        "terminal": terminal,
        "next_action": next_action,
        "valid": valid,
        "errors": errors,
        "attempt_id": latest.get("attempt_id"),
        "attempt_kind": latest.get("kind"),
        "repair_attempts_used": repairs_used,
        "max_repair_attempts": MAX_IMPLEMENTATION_REPAIR_ATTEMPTS,
        "remaining_repair_attempts": max(0, MAX_IMPLEMENTATION_REPAIR_ATTEMPTS - repairs_used),
        "input_fingerprint": result.get("input_fingerprint"),
        "source_manifest": result.get("source_manifest"),
        "layout_current": layout_current,
        "layout_pass": layout_pass,
    }


def record_attempt(
    path: Path,
    result: dict[str, Any],
    *,
    kind: str,
    layout: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if kind not in IMPLEMENTATION_ATTEMPT_KINDS:
        raise ValueError(f"invalid implementation attempt kind: {kind}")
    attempts = load_attempts(path)
    baseline = str(result.get("baseline_fingerprint"))
    scoped = _current_baseline_attempts(attempts, baseline)
    repairs_used = sum(row.get("kind") == "repair" for row in scoped)
    previous = scoped[-1] if scoped else None
    current_manifest = result.get("source_manifest") if isinstance(result.get("source_manifest"), dict) else {}
    actual_changed_files: list[str] = []
    if kind == "checkpoint":
        if scoped:
            raise ValueError("current scaffold baseline already has an implementation checkpoint")
    elif kind == "repair":
        if previous is None:
            raise ValueError("implementation repair requires a checkpoint")
        if previous.get("audit_status") == "pass":
            raise ValueError("implementation repair is not allowed after a passing audit")
        if repairs_used >= MAX_IMPLEMENTATION_REPAIR_ATTEMPTS:
            raise ValueError("implementation repair budget is exhausted")
        actual_changed_files = _manifest_changed_files(previous.get("source_manifest"), current_manifest)
        if not actual_changed_files:
            raise ValueError("implementation repair requires real Rust source changes")
        repairs_used += 1
    elif kind == "confirmation":
        if previous is None or previous.get("kind") != "repair":
            raise ValueError("implementation confirmation must immediately follow a repair")
        if repairs_used < MAX_IMPLEMENTATION_REPAIR_ATTEMPTS:
            raise ValueError("implementation confirmation requires the repair budget to be consumed")
        if _manifest_changed_files(previous.get("source_manifest"), current_manifest):
            raise ValueError("implementation confirmation must not change Rust sources")

    row = {
        "attempt_id": f"{time.time_ns()}-{kind}",
        "kind": kind,
        "baseline_fingerprint": baseline,
        "input_fingerprint": result.get("input_fingerprint"),
        "source_manifest": current_manifest,
        "audit_status": result.get("status"),
        "finding_codes": sorted({
            str(item.get("code"))
            for item in result.get("findings", [])
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        }),
        "finding_count": result.get("summary", {}).get("findings"),
        "actual_changed_files": actual_changed_files,
        "repair_attempts_used": repairs_used,
        "max_repair_attempts": MAX_IMPLEMENTATION_REPAIR_ATTEMPTS,
        "layout_status": layout.get("status") if isinstance(layout, dict) else None,
        "layout_source_manifest": layout.get("source_manifest") if isinstance(layout, dict) else None,
    }
    evidence = implementation_evidence(result, attempts + [row], layout)
    row["convergence"] = {
        key: evidence[key]
        for key in (
            "status", "terminal", "next_action", "repair_attempts_used",
            "max_repair_attempts", "remaining_repair_attempts",
        )
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row, evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Rust code for unchanged scaffold implementations.")
    parser.add_argument("--root", default=".", help="Conversion workspace root.")
    parser.add_argument("--project", help="Rust project path, relative to --root.")
    parser.add_argument("--manifest", help="Scaffold manifest path, relative to --root.")
    parser.add_argument("--design", help="Rust API design path, relative to --root.")
    parser.add_argument("--output", help="Audit JSON path, relative to --root.")
    parser.add_argument(
        "--attempt-kind",
        choices=sorted(IMPLEMENTATION_ATTEMPT_KINDS),
        help="Record a bounded implementation checkpoint, repair, or fresh confirmation.",
    )
    parser.add_argument(
        "--attempts",
        help="Implementation attempt JSONL path, relative to --root.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    project = _resolve(root, args.project, "flashDB_rust")
    manifest_path = _resolve(root, args.manifest, "logs/trace/scaffold-manifest.json")
    design_path = _resolve(root, args.design, "logs/trace/rust_api_design.json")
    output = _resolve(root, args.output, "logs/trace/implementation-audit.json")
    attempts_path = _resolve(root, args.attempts, "logs/trace/implementation-attempts.jsonl")
    result = audit(root=root, project=project, manifest_path=manifest_path, design_path=design_path)
    layout_path = root / "logs" / "trace" / "c-cross" / "scaffold-layout-check.json"
    try:
        layout = _load_object(layout_path)
    except (OSError, ValueError, json.JSONDecodeError):
        layout = {}
    evidence = implementation_evidence(result, load_attempts(attempts_path), layout)
    if args.attempt_kind:
        try:
            _, evidence = record_attempt(
                attempts_path,
                result,
                kind=args.attempt_kind,
                layout=layout,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
    result["convergence"] = evidence
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = "FAILED_FINAL" if evidence["status"] == "failed_final" else str(result["status"]).upper()
    print(f"CORE_IMPL_AUDIT: {status}")
    print(f"findings={result['summary']['findings']}")
    print(f"output={output}")
    print(f"next_action={evidence['next_action']}")
    return 0 if result["status"] == "pass" or evidence["status"] == "failed_final" else 1


if __name__ == "__main__":
    raise SystemExit(main())
