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
    names = re.findall(r"\bTEST_RUN\s*\(\s*(" + IDENT + r")\s*\)", text)
    return sorted(dict.fromkeys(names))


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
    scenario_tags: dict[str, list[str]] = {}
    for file_name in test_files:
        path = root / file_name
        if not path.is_file():
            continue
        text = read_text(path)
        funcs = [item["name"] for item in extract_functions(text, file_name) if item["name"].startswith("test_")]
        test_functions.extend(funcs)
        registered = extract_registered_tests(text)
        registered_tests.extend(registered)
        for name in funcs + registered:
            scenario_tags[name] = tag_test(name)

    test_functions = sorted(dict.fromkeys(test_functions))
    registered_tests = sorted(dict.fromkeys(registered_tests))
    kvdb_tests = sorted([name for name in registered_tests if "kvdb" in tag_test(name)])
    tsdb_tests = sorted([name for name in registered_tests if "tsdb" in tag_test(name)])

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
