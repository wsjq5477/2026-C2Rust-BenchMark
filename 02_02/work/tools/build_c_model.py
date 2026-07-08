#!/usr/bin/env python3
"""Build deterministic C project, API, and test models from the FlashDB input manifest."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
CONTROL_WORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "defined",
}

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//.*", " ", text)
    return text


def classify_path(path: str) -> str:
    lower = path.lower()
    if lower.startswith("tests/"):
        return "tests"
    if "kvdb" in lower or "_kv" in lower:
        return "kvdb"
    if "tsdb" in lower or "_tsl" in lower or "tsdb" in lower:
        return "tsdb"
    if "file" in lower:
        return "file"
    if "utils" in lower:
        return "utils"
    return "common"


def extract_includes(text: str) -> list[str]:
    return sorted(dict.fromkeys(re.findall(r"^\s*#\s*include\s+[<\"]([^>\"]+)[>\"]", text, flags=re.M)))


def extract_macros(text: str) -> list[str]:
    names = re.findall(r"^\s*#\s*define\s+(" + IDENT + r")\b", text, flags=re.M)
    return sorted(dict.fromkeys(names))


def extract_structs(text: str, file_name: str) -> list[dict[str, str]]:
    clean = strip_comments(text)
    names: list[str] = []
    for match in re.finditer(r"\bstruct\s+(" + IDENT + r")\b", clean):
        names.append(match.group(1))
    return [{"name": name, "file": file_name} for name in sorted(dict.fromkeys(names))]


def extract_typedefs(text: str, file_name: str) -> list[dict[str, str]]:
    clean = strip_comments(text)
    names: list[str] = []
    for statement in re.findall(r"\btypedef\b[^;]+;", clean, flags=re.S):
        match = re.search(r"(" + IDENT + r")\s*(?:\[[^\]]*\])?\s*;\s*$", statement)
        if match:
            names.append(match.group(1))
    return [{"name": name, "file": file_name} for name in sorted(dict.fromkeys(names))]


def extract_enum_blocks(text: str, file_name: str) -> tuple[list[dict[str, str]], list[str]]:
    clean = strip_comments(text)
    enums: list[dict[str, str]] = []
    values: list[str] = []
    for match in re.finditer(r"(?:typedef\s+)?enum(?:\s+(" + IDENT + r"))?\s*\{(?P<body>.*?)\}\s*(?P<alias>" + IDENT + r")?\s*;", clean, flags=re.S):
        name = match.group(1) or match.group("alias") or "anonymous"
        enums.append({"name": name, "file": file_name})
        body = match.group("body")
        for raw in body.split(","):
            token = raw.split("=", 1)[0].strip()
            if re.fullmatch(IDENT, token):
                values.append(token)
    return sorted(enums, key=lambda item: (item["file"], item["name"])), sorted(dict.fromkeys(values))


def collapse_function_lines(text: str) -> str:
    clean = strip_comments(text)
    clean = re.sub(r"\\\n", " ", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean


def extract_functions(text: str, file_name: str) -> list[dict[str, str]]:
    one_line = collapse_function_lines(text)
    pattern = re.compile(
        r"(?P<signature>\b(?:static\s+)?(?:inline\s+)?(?:const\s+)?(?:struct\s+)?" + IDENT
        + r"(?:\s*[*]\s*|\s+)+(?P<name>" + IDENT + r")\s*\([^;{}]*\)\s*(?P<end>[;{]))"
    )
    functions: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in pattern.finditer(one_line):
        name = match.group("name")
        if name in CONTROL_WORDS:
            continue
        kind = "definition" if match.group("end") == "{" else "prototype"
        key = (file_name, name)
        if key in seen:
            continue
        seen.add(key)
        functions.append({"name": name, "file": file_name, "kind": kind})
    return sorted(functions, key=lambda item: (item["file"], item["name"]))


def extract_registered_tests(text: str) -> list[str]:
    return re.findall(r"\bTEST_RUN\s*\(\s*(" + IDENT + r")\s*\)", text)


def extract_function_bodies(text: str) -> dict[str, str]:
    clean = strip_comments(text)
    pattern = re.compile(r"\b(test_[A-Za-z0-9_]+)\s*\([^;{}]*\)\s*\{")
    bodies: dict[str, str] = {}
    for match in pattern.finditer(clean):
        depth = 1
        cursor = match.end()
        while cursor < len(clean) and depth:
            if clean[cursor] == "{":
                depth += 1
            elif clean[cursor] == "}":
                depth -= 1
            cursor += 1
        if depth == 0:
            bodies[match.group(1)] = clean[match.end() : cursor - 1]
    return bodies


def extract_assertion_details(body: str) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    pattern = re.compile(r"\b(?P<macro>(?:TEST_ASSERT|test_assert)[A-Za-z0-9_]*)\s*\((?P<expr>[^;]*)\)\s*;", re.S)
    for match in pattern.finditer(body):
        expr = re.sub(r"\s+", " ", match.group("expr")).strip()
        tokens = sorted(
            dict.fromkeys(
                token
                for token in re.findall(IDENT, expr)
                if token not in CONTROL_WORDS
            )
        )
        details.append(
            {
                "macro": match.group("macro"),
                "expression": expr,
                "targets": tokens,
            }
        )
    return details


def semantic_markers_from_body(body: str, assertion_targets: list[str]) -> list[str]:
    markers: list[str] = []
    lower = body.lower()
    target_set = set(assertion_targets)
    if {"addr", "oldest_addr"} & target_set or re.search(r"\boldest_addr\b[^;]*(?:%|sec_size|sector)", body):
        markers.append("verify_addr_alignment")
    if re.search(r"\bfdb_(?:kvdb|tsdb)_control\s*\(", body):
        markers.append("use_control_interface")
    if re.search(r"\bfdb_reboot\s*\(", body):
        markers.append("verify_persistence_after_reboot")
    elif re.search(r"\bfdb_(?:kvdb|tsdb)_deinit\s*\(", body) and re.search(r"\bfdb_(?:kvdb|tsdb)_init\s*\(", body):
        markers.append("verify_persistence_after_reboot")
    if "init_ok" in lower:
        markers.append("verify_init_state")
    return sorted(dict.fromkeys(markers))


def data_shape_from_body(body: str) -> dict[str, Any]:
    kv_set_count = len(re.findall(r"\bfdb_kv_set\s*\(", body))
    blob_multiplier = 0
    for table in re.finditer(r"\bstruct\s+test_kv\s+\w+\s*\[\s*\]\s*=\s*\{(?P<body>.*?)\}\s*;", body, flags=re.S):
        kv_set_count = max(kv_set_count, len(re.findall(r"\{\s*\"kv", table.group("body"))))
        for match in re.finditer(r"(?:\bTEST_KV_VALUE_LEN\b\s*[*]\s*(\d+)|(\d+)\s*[*]\s*\bTEST_KV_VALUE_LEN\b)", table.group("body")):
            blob_multiplier = max(blob_multiplier, int(match.group(1) or match.group(2)))
    blob_calls = re.findall(r"\bfdb_kv_set_blob\s*\((?P<args>[^;]*)\)", body, flags=re.S)
    for args in blob_calls:
        match = re.search(r"(?:\b(?:sec_size|sector_size|FDB_SECTOR_SIZE|TEST_KV_VALUE_LEN)\b\s*[*]\s*(\d+)|(\d+)\s*[*]\s*\b(?:sec_size|sector_size|FDB_SECTOR_SIZE|TEST_KV_VALUE_LEN)\b)", args)
        if match:
            blob_multiplier = max(blob_multiplier, int(match.group(1) or match.group(2)))
    tsl_append_count = len(re.findall(r"\bfdb_tsl_append\s*\(", body))
    sector_bound_calls = len(re.findall(r"\btest_fdb_tsl_sector_bound_test\s*\(", body))
    return {
        "kv_set_count": kv_set_count,
        "blob_write_count": len(blob_calls),
        "blob_multiplier": blob_multiplier,
        "tsl_append_count": tsl_append_count,
        "sector_bound_query_count": sector_bound_calls,
    }


def scenario_features_from_body(body: str, data_shape: dict[str, Any]) -> list[str]:
    features: list[str] = []
    if re.search(r"\bfdb_tsl_iter_reverse\s*\(", body):
        features.append("iter_reverse")
    if re.search(r"\bfdb_tsl_iter_by_time\s*\(", body):
        features.append("iter_by_time")
    if (
        re.search(r"\bfdb_tsl_set_status\s*\([^;]*USER_STATUS", body)
        and re.search(r"\bfdb_tsl_set_status\s*\([^;]*DELETED", body)
    ) or (
        re.search(r"\bfdb_tsl_query_count\s*\([^;]*USER_STATUS", body)
        and re.search(r"\bfdb_tsl_query_count\s*\([^;]*DELETED", body)
    ):
        features.append("multi_status_filter")
    if data_shape.get("blob_multiplier", 0) >= 2:
        features.append("large_blob_persistence")
    if data_shape.get("kv_set_count", 0) >= 4:
        features.append("multi_kv_gc_pressure")
    if data_shape.get("tsl_append_count", 0) >= 5 or data_shape.get("sector_bound_query_count", 0) >= 2 or re.search(r"\bsector\b", body, flags=re.I):
        features.append("cross_sector_tsl")
    return sorted(dict.fromkeys(features))


def extract_control_usage(body: str) -> list[dict[str, str]]:
    usage: list[dict[str, str]] = []
    for match in re.finditer(r"\b(?P<function>fdb_(?:kvdb|tsdb)_control)\s*\((?P<args>[^;]*)\)", body, flags=re.S):
        args = [part.strip() for part in match.group("args").split(",")]
        usage.append(
            {
                "function": match.group("function"),
                "command": args[1] if len(args) > 1 else "",
            }
        )
    return usage


def extract_test_semantics(body: str) -> dict[str, Any]:
    calls = sorted(
        dict.fromkeys(
            name
            for name in re.findall(r"\b(" + IDENT + r")\s*\(", body)
            if name not in CONTROL_WORDS
        )
    )
    assertions = sorted(name for name in calls if "assert" in name.lower())
    observed_symbols = sorted(name for name in calls if name.startswith("fdb_"))
    helper_calls = sorted(
        name
        for name in calls
        if name.startswith("test_") and name not in assertions
    )
    assertion_details = extract_assertion_details(body)
    assertion_targets = sorted(
        dict.fromkeys(
            target
            for detail in assertion_details
            for target in detail.get("targets", [])
            if isinstance(target, str)
        )
    )
    data_shape = data_shape_from_body(body)
    scenario_features = scenario_features_from_body(body, data_shape)
    semantic_markers = semantic_markers_from_body(body, assertion_targets)
    return {
        "called_functions": calls,
        "observed_c_symbols": observed_symbols,
        "helper_calls": helper_calls,
        "assertion_macros": assertions,
        "assertion_count": sum(len(re.findall(r"\b" + re.escape(name) + r"\s*\(", body)) for name in assertions),
        "assertion_details": assertion_details,
        "assertion_targets": assertion_targets,
        "control_usage": extract_control_usage(body),
        "data_shape": data_shape,
        "scenario_features": scenario_features,
        "semantic_markers": semantic_markers,
    }


def tag_test(name: str) -> list[str]:
    lower = name.lower()
    tags: list[str] = []
    if "kv" in lower or "kvdb" in lower or "gc" in lower or "scale" in lower:
        tags.append("kvdb")
    if "tsl" in lower or "tsdb" in lower or "github_issue" in lower:
        tags.append("tsdb")
    for keyword in ["init", "deinit", "append", "iter", "query", "status", "clean", "gc", "del", "change", "set", "create"]:
        if keyword in lower:
            tags.append(keyword)
    return sorted(dict.fromkeys(tags))


def scenario_suite(name: str, tags: list[str]) -> str:
    if "kvdb" in tags:
        return "kvdb"
    if "tsdb" in tags:
        return "tsdb"
    lower = name.lower()
    if "kv" in lower or "gc" in lower or "scale" in lower:
        return "kvdb"
    if "tsl" in lower or "tsdb" in lower:
        return "tsdb"
    return "extension"


def build_standard_scenarios(
    registered_invocations: list[dict[str, Any]],
    scenario_tags: dict[str, list[str]],
    test_semantics: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    occurrences: dict[str, int] = {}
    for index, invocation in enumerate(registered_invocations, start=1):
        name = str(invocation["name"])
        occurrences[name] = occurrences.get(name, 0) + 1
        scenario_id = name if occurrences[name] == 1 else f"{name}__{occurrences[name]}"
        tags = scenario_tags.get(name, tag_test(name))
        suite = scenario_suite(name, tags)
        scenarios.append(
            {
                "id": scenario_id,
                "name": name,
                "parent_test": name,
                "suite": suite,
                "source": "registered",
                "source_file": invocation.get("source_file"),
                "order": index,
                "tags": tags,
                "semantic_facts": test_semantics.get(
                    name,
                    {
                        "called_functions": [],
                        "observed_c_symbols": [],
                        "helper_calls": [],
                        "assertion_macros": [],
                        "assertion_count": 0,
                    },
                ),
            }
        )
    return scenarios


def empty_semantic_facts() -> dict[str, Any]:
    return {
        "called_functions": [],
        "observed_c_symbols": [],
        "helper_calls": [],
        "assertion_macros": [],
        "assertion_count": 0,
        "assertion_details": [],
        "assertion_targets": [],
        "control_usage": [],
        "data_shape": {
            "kv_set_count": 0,
            "blob_write_count": 0,
            "blob_multiplier": 0,
            "tsl_append_count": 0,
            "sector_bound_query_count": 0,
        },
        "scenario_features": [],
        "semantic_markers": [],
    }


def merge_semantic_facts(names: list[str], test_semantics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    merged = empty_semantic_facts()
    for name in names:
        facts = test_semantics.get(name)
        if not isinstance(facts, dict):
            continue
        for key in ["called_functions", "observed_c_symbols", "helper_calls", "assertion_macros", "assertion_details", "assertion_targets", "control_usage", "scenario_features", "semantic_markers"]:
            values = facts.get(key)
            if isinstance(values, list):
                merged[key].extend(item for item in values if isinstance(item, str))
                if key in {"assertion_details", "control_usage"}:
                    merged[key].extend(item for item in values if isinstance(item, dict))
        count = facts.get("assertion_count")
        if isinstance(count, int):
            merged["assertion_count"] += count
        data_shape = facts.get("data_shape")
        if isinstance(data_shape, dict):
            for shape_key in ["kv_set_count", "blob_write_count", "blob_multiplier", "tsl_append_count", "sector_bound_query_count"]:
                value = data_shape.get(shape_key)
                if isinstance(value, int):
                    if shape_key == "blob_multiplier":
                        merged["data_shape"][shape_key] = max(merged["data_shape"][shape_key], value)
                    else:
                        merged["data_shape"][shape_key] += value
    for key in ["called_functions", "observed_c_symbols", "helper_calls", "assertion_macros", "assertion_targets", "scenario_features", "semantic_markers"]:
        merged[key] = sorted(dict.fromkeys(merged[key]))
    return merged


def scorer_case_name(test_name: str) -> str:
    name = re.sub(r"^test_", "", test_name)
    name = re.sub(r"^fdb_", "", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or test_name


def semantic_obligations_from_facts(tags: list[str], facts: dict[str, Any]) -> list[str]:
    obligations: list[str] = []
    obligations.extend(tag for tag in tags if tag not in {"kvdb", "tsdb"})

    observed = facts.get("observed_c_symbols")
    if isinstance(observed, list):
        obligations.extend(f"calls:{symbol}" for symbol in observed if isinstance(symbol, str))

    helpers = facts.get("helper_calls")
    if isinstance(helpers, list):
        obligations.extend(f"helper:{helper}" for helper in helpers if isinstance(helper, str))

    markers = facts.get("semantic_markers")
    if isinstance(markers, list):
        obligations.extend(marker for marker in markers if isinstance(marker, str))

    data_shape = facts.get("data_shape")
    if isinstance(data_shape, dict):
        kv_set_count = data_shape.get("kv_set_count")
        if isinstance(kv_set_count, int) and kv_set_count >= 2:
            obligations.append(f"data_shape:multi_kv_count:{kv_set_count}")
        if isinstance(data_shape.get("blob_multiplier"), int) and data_shape["blob_multiplier"] >= 2:
            obligations.append("data_shape:cross_sector_blob")
        tsl_append_count = data_shape.get("tsl_append_count")
        if isinstance(tsl_append_count, int) and tsl_append_count >= 5:
            obligations.append(f"data_shape:cross_sector_tsl_count:{tsl_append_count}")
        sector_bound_query_count = data_shape.get("sector_bound_query_count")
        if isinstance(sector_bound_query_count, int) and sector_bound_query_count >= 2:
            obligations.append(f"data_shape:sector_bound_queries:{sector_bound_query_count}")

    features = facts.get("scenario_features")
    if isinstance(features, list):
        obligations.extend(f"scenario:{feature}" for feature in features if isinstance(feature, str))

    assertions = facts.get("assertion_macros")
    if isinstance(assertions, list) and assertions:
        obligations.append("assertion_intent")
    if isinstance(facts.get("assertion_count"), int) and facts["assertion_count"] > 0:
        obligations.append("assertion_count")

    return sorted(dict.fromkeys(obligations or ["registered_scenario"]))


def related_test_names(name: str, test_semantics: dict[str, dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(current: str) -> None:
        if current in seen:
            return
        seen.add(current)
        ordered.append(current)
        facts = test_semantics.get(current, {})
        helpers = facts.get("helper_calls")
        if isinstance(helpers, list):
            for helper in helpers:
                if isinstance(helper, str) and helper in test_semantics:
                    visit(helper)

    visit(name)
    return ordered


def build_scorer_standard_cases(
    registered_invocations: list[dict[str, Any]],
    scenario_tags: dict[str, list[str]],
    test_semantics: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    occurrences: dict[str, int] = {}
    for index, invocation in enumerate(registered_invocations, start=1):
        name = str(invocation["name"])
        occurrences[name] = occurrences.get(name, 0) + 1
        scenario_id = name if occurrences[name] == 1 else f"{name}__{occurrences[name]}"
        tags = scenario_tags.get(name, tag_test(name))
        facts = merge_semantic_facts(related_test_names(name, test_semantics), test_semantics)
        cases.append(
            {
                "case_id": str(index),
                "case_name": scorer_case_name(scenario_id),
                "scenario_id": scenario_id,
                "suite": scenario_suite(name, tags),
                "required_c_tests": [name],
                "order": index,
                "source": "registered_c_tests",
                "present_c_tests": [name],
                "missing_c_tests": [],
                "semantic_facts": facts,
                "semantic_obligations": semantic_obligations_from_facts(tags, facts),
                "tags": tags,
                "source_file": invocation.get("source_file"),
            }
        )
    return cases


def build_models(manifest: dict[str, Any]) -> dict[str, Any]:
    root = Path(manifest["source_root"]).resolve()
    source_files = list(manifest.get("core_sources", []))
    headers = list(manifest.get("headers", []))
    test_files = list(manifest.get("test_sources", []))

    include_graph: dict[str, list[str]] = {}
    modules: dict[str, list[str]] = {
        "common": [],
        "kvdb": [],
        "tsdb": [],
        "file": [],
        "utils": [],
        "tests": [],
    }
    for file_name in source_files + test_files:
        modules.setdefault(classify_path(file_name), []).append(file_name)
    for key in modules:
        modules[key] = sorted(dict.fromkeys(modules[key]))

    public_headers = sorted([name for name in headers if name.startswith("inc/")])
    all_functions: list[dict[str, str]] = []
    structs: list[dict[str, str]] = []
    typedefs: list[dict[str, str]] = []
    enum_blocks: list[dict[str, str]] = []
    enum_values: list[str] = []
    macros: list[str] = []

    for file_name in sorted(dict.fromkeys(headers + source_files + test_files)):
        path = root / file_name
        if not path.is_file():
            continue
        text = read_text(path)
        include_graph[file_name] = extract_includes(text)
        macros.extend(extract_macros(text))
        structs.extend(extract_structs(text, file_name))
        typedefs.extend(extract_typedefs(text, file_name))
        enums, values = extract_enum_blocks(text, file_name)
        enum_blocks.extend(enums)
        enum_values.extend(values)
        all_functions.extend(extract_functions(text, file_name))

    public_functions = sorted(
        dict.fromkeys(
            item["name"]
            for item in all_functions
            if item["file"].startswith("inc/") or item["name"].startswith("fdb_")
        )
    )
    kvdb_symbols = sorted([name for name in public_functions if "kv" in name or "kvdb" in name])
    tsdb_symbols = sorted([name for name in public_functions if "tsl" in name or "tsdb" in name])

    test_functions: list[str] = []
    registered_tests: list[str] = []
    registered_invocations: list[dict[str, Any]] = []
    scenario_tags: dict[str, list[str]] = {}
    test_semantics: dict[str, dict[str, Any]] = {}
    for file_name in test_files:
        path = root / file_name
        if not path.is_file():
            continue
        text = read_text(path)
        funcs = [item["name"] for item in extract_functions(text, file_name) if item["name"].startswith("test_")]
        bodies = extract_function_bodies(text)
        test_functions.extend(funcs)
        registered = extract_registered_tests(text)
        registered_tests.extend(registered)
        registered_invocations.extend(
            {"name": name, "source_file": file_name, "source_index": index}
            for index, name in enumerate(registered, start=1)
        )
        for name in funcs + registered:
            scenario_tags[name] = tag_test(name)
        for name, body in bodies.items():
            test_semantics[name] = extract_test_semantics(body)

    test_functions = sorted(dict.fromkeys(test_functions))
    registered_tests = sorted(dict.fromkeys(registered_tests))
    kvdb_tests = sorted([name for name in registered_tests if "kvdb" in tag_test(name)])
    tsdb_tests = sorted([name for name in registered_tests if "tsdb" in tag_test(name)])
    standard_scenarios = build_standard_scenarios(registered_invocations, scenario_tags, test_semantics)
    scorer_standard_cases = build_scorer_standard_cases(registered_invocations, scenario_tags, test_semantics)

    c_project_model = {
        "source_root": str(root),
        "modules": modules,
        "source_files": source_files,
        "headers": headers,
        "test_files": test_files,
        "include_graph": include_graph,
        "build_files": list(manifest.get("build_files", [])),
        "counts": {
            "source_files": len(source_files),
            "headers": len(headers),
            "test_files": len(test_files),
            "includes": sum(len(items) for items in include_graph.values()),
        },
    }

    c_api_model = {
        "public_headers": public_headers,
        "public_functions": public_functions,
        "all_functions": all_functions,
        "structs": sorted({(item["file"], item["name"]) for item in structs}),
        "typedefs": sorted({(item["file"], item["name"]) for item in typedefs}),
        "macros": sorted(dict.fromkeys(macros)),
        "enums": sorted({(item["file"], item["name"]) for item in enum_blocks}),
        "enum_values": sorted(dict.fromkeys(enum_values)),
        "kvdb_symbols": kvdb_symbols,
        "tsdb_symbols": tsdb_symbols,
    }
    c_api_model["structs"] = [{"file": file, "name": name} for file, name in c_api_model["structs"]]
    c_api_model["typedefs"] = [{"file": file, "name": name} for file, name in c_api_model["typedefs"]]
    c_api_model["enums"] = [{"file": file, "name": name} for file, name in c_api_model["enums"]]

    c_test_model = {
        "test_files": test_files,
        "test_functions": test_functions,
        "registered_tests": registered_tests,
        "registered_test_invocations": registered_invocations,
        "standard_scenarios": standard_scenarios,
        "scorer_standard_cases": scorer_standard_cases,
        "test_semantics": test_semantics,
        "kvdb_tests": kvdb_tests,
        "tsdb_tests": tsdb_tests,
        "scenario_tags": scenario_tags,
    }

    return {
        "c_project_model": c_project_model,
        "c_api_model": c_api_model,
        "c_test_model": c_test_model,
    }


def write_models(models: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, model in models.items():
        (output_dir / f"{name}.json").write_text(
            json.dumps(model, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build FlashDB C project/API/test models.")
    parser.add_argument("--manifest", required=True, help="logs/trace/input_manifest.json path.")
    parser.add_argument("--output-dir", required=True, help="Directory for c_*_model.json outputs.")
    args = parser.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    models = build_models(manifest)
    write_models(models, Path(args.output_dir))
    print("BUILD_C_MODEL: MODELS_WRITTEN")
    print(f"public_functions={len(models['c_api_model']['public_functions'])}")
    print(f"registered_tests={len(models['c_test_model']['registered_tests'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
