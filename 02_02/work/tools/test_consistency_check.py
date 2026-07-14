#!/usr/bin/env python3
"""Check Rust migrated tests against scorer-facing C semantic contracts."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def extract_rust_test_body(text: str, test_name: str) -> str:
    pattern = re.compile(r"#\s*\[\s*test\s*\]\s*fn\s+" + re.escape(test_name) + r"\s*\([^)]*\)\s*\{")
    match = pattern.search(text)
    if not match:
        return ""
    depth = 1
    cursor = match.end()
    while cursor < len(text) and depth:
        if text[cursor] == "{":
            depth += 1
        elif text[cursor] == "}":
            depth -= 1
        cursor += 1
    return text[match.end() : cursor - 1] if depth == 0 else ""


def rust_assertions(body: str) -> list[str]:
    assertions: list[str] = []
    for match in re.finditer(r"\bassert(?:_eq|_ne)?!\s*\((?P<expr>.*?)\)\s*;", body, flags=re.S):
        assertions.append(re.sub(r"\s+", " ", match.group("expr")).strip())
    return assertions


def important_obligations(obligations: list[str]) -> list[str]:
    return [
        item
        for item in obligations
        if item.startswith("verify_") or item.startswith("data_shape:") or item.startswith("scenario:")
    ]


def assertion_evidence_obligations(scenario: dict[str, Any]) -> set[str]:
    evidence = scenario.get("assertion_evidence", [])
    obligations: set[str] = set()
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and isinstance(item.get("validated_obligation"), str):
                obligations.add(item["validated_obligation"])
            elif isinstance(item, str):
                obligations.add(item)
    return obligations


def evidence_entries(scenario: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = scenario.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def evidence_matches_body(entries: list[dict[str, Any]], **expected: str) -> bool:
    for entry in entries:
        if any(entry.get(key) != value for key, value in expected.items()):
            continue
        expression = entry.get("rust_expression")
        body = entry.get("_body")
        if isinstance(expression, str) and expression.strip() and isinstance(body, str) and expression in body:
            return True
    return False


def rust_test_functions(root: Path, mapping: dict[str, Any]) -> set[str]:
    files = mapping.get("source_to_rust", {})
    paths = files.values() if isinstance(files, dict) else []
    found: set[str] = set()
    for relative in paths:
        if not isinstance(relative, str):
            continue
        path = root / relative.removeprefix("./")
        if not path.is_file():
            continue
        found.update(re.findall(r"#\s*\[\s*test\s*\]\s*fn\s+([A-Za-z_][A-Za-z0-9_]*)", path.read_text(encoding="utf-8", errors="ignore")))
    return found


def add_issue(issues: list[dict[str, Any]], code: str, scenario_id: str, message: str) -> None:
    issues.append({"code": code, "scenario_id": scenario_id, "message": message})


def analyze_consistency(root: Path) -> dict[str, Any]:
    root = root.resolve()
    trace = root / "logs" / "trace"
    test_model = load_json(trace / "c_test_model.json")
    mapping = load_json(trace / "rust_test_mapping.json")
    cases = test_model.get("scorer_standard_cases", [])
    scenarios = mapping.get("scenarios", [])
    case_by_id = {
        item.get("case_id"): item
        for item in cases
        if isinstance(item, dict) and isinstance(item.get("case_id"), str)
    } if isinstance(cases, list) else {}
    issues: list[dict[str, Any]] = []
    scenario_results: list[dict[str, Any]] = []

    if not isinstance(scenarios, list):
        add_issue(issues, "invalid_mapping", "<mapping>", "rust_test_mapping.json scenarios must be a list")
        scenarios = []

    mapped_case_ids = {
        item.get("scorer_case_id")
        for item in scenarios
        if isinstance(item, dict) and isinstance(item.get("scorer_case_id"), str)
    }
    c_only = sorted(case_id for case_id in case_by_id if case_id not in mapped_case_ids)
    for case_id in c_only:
        add_issue(issues, "c_only", case_id, "C scorer case has no Rust test mapping")

    rust_only_mappings = sorted(
        str(item.get("id", "<unknown>"))
        for item in scenarios
        if isinstance(item, dict) and item.get("scorer_case_id") not in case_by_id
    )
    for scenario_id in rust_only_mappings:
        add_issue(issues, "rust_only_mapping", scenario_id, "Rust mapping has no C scorer case")

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("id", scenario.get("rust_test", "<unknown>")))
        issue_start = len(issues)
        if scenario.get("implementation_status") not in {"implemented", "validated"}:
            add_issue(issues, "test_not_implemented", scenario_id, "mapped Rust test implementation is still pending")
        if scenario.get("coverage") != "semantic":
            add_issue(issues, "semantic_coverage_pending", scenario_id, "mapped Rust test is not marked semantic")
        obligations = scenario.get("semantic_obligations", [])
        obligations = [item for item in obligations if isinstance(item, str)] if isinstance(obligations, list) else []
        important = important_obligations(obligations)
        evidence_obligations = assertion_evidence_obligations(scenario)
        if important and not evidence_obligations:
            add_issue(
                issues,
                "missing_assertion_evidence",
                scenario_id,
                "semantic mapping for deep obligations must include assertion_evidence",
            )
        for obligation in [item for item in important if item.startswith("verify_")]:
            if obligation not in evidence_obligations:
                add_issue(
                    issues,
                    "missing_direct_verify_obligation",
                    scenario_id,
                    f"{obligation} must have direct assertion evidence",
                )

        rust_file = scenario.get("rust_file")
        rust_test = scenario.get("rust_test")
        body = ""
        if isinstance(rust_file, str) and isinstance(rust_test, str):
            path = root / rust_file.removeprefix("./")
            if path.is_file():
                body = extract_rust_test_body(path.read_text(encoding="utf-8", errors="ignore"), rust_test)
        assertions = rust_assertions(body)
        if not body:
            add_issue(issues, "missing_rust_test", scenario_id, "mapped Rust #[test] function was not found")
        elif not assertions:
            add_issue(issues, "missing_rust_assertion", scenario_id, "mapped Rust test has no assertion")

        case = case_by_id.get(scenario.get("scorer_case_id"))
        semantic_facts = case.get("semantic_facts") if isinstance(case, dict) else {}
        api_evidence = evidence_entries(scenario, "api_evidence")
        data_evidence = evidence_entries(scenario, "data_evidence")
        assertion_evidence = evidence_entries(scenario, "assertion_evidence")
        for entries in (api_evidence, data_evidence, assertion_evidence):
            for entry in entries:
                entry["_body"] = body

        c_calls = semantic_facts.get("public_api_calls", []) if isinstance(semantic_facts, dict) else []
        for c_api in [item for item in c_calls if isinstance(item, str)]:
            if not evidence_matches_body(api_evidence, c_api=c_api):
                add_issue(
                    issues,
                    "logic_mismatch_api",
                    scenario_id,
                    f"C API {c_api} lacks source-backed Rust API evidence",
                )
        data_shape = semantic_facts.get("data_shape") if isinstance(semantic_facts, dict) else None
        if data_shape and not any(evidence_matches_body([entry]) for entry in data_evidence):
            add_issue(
                issues,
                "logic_mismatch_data",
                scenario_id,
                "C test data shape lacks source-backed Rust data evidence",
            )
        if isinstance(semantic_facts, dict) and semantic_facts.get("assertion_count", 0) and not any(
            evidence_matches_body([entry]) for entry in assertion_evidence
        ):
            add_issue(
                issues,
                "logic_mismatch_assertion",
                scenario_id,
                "C assertions lack source-backed Rust assertion evidence",
            )
        c_assertion_count = semantic_facts.get("assertion_count") if isinstance(semantic_facts, dict) else 0
        if isinstance(c_assertion_count, int) and c_assertion_count > 0:
            minimum = max(1, math.ceil(c_assertion_count * 0.5))
            if len(assertions) < minimum:
                add_issue(
                    issues,
                    "rust_assertion_count_below_threshold",
                    scenario_id,
                    f"Rust test has {len(assertions)} assertions, below required minimum {minimum}",
                )

        if assertions:
            shallow = [
                expr
                for expr in assertions
                if re.fullmatch(r"true", expr)
                or re.search(r"\.is_(?:ok|some|none)\s*\(\s*\)", expr)
            ]
            if len(shallow) / len(assertions) > 0.70:
                add_issue(
                    issues,
                    "shallow_assertion_dominance",
                    scenario_id,
                    "More than 70% of Rust assertions are shallow status/presence checks",
                )

        validated = scenario.get("validated_obligations", [])
        validated_set = {item for item in validated if isinstance(item, str)} if isinstance(validated, list) else set()
        for obligation in obligations:
            if obligation not in validated_set:
                add_issue(issues, "unvalidated_obligation", scenario_id, f"{obligation} is not validated")
        scenario_issues = issues[issue_start:]
        scenario_results.append(
            {
                "scenario_id": scenario_id,
                "status": "pass" if not scenario_issues else "fail",
                "issue_codes": [item["code"] for item in scenario_issues],
                "obligation_evidence": [
                    item for item in scenario.get("assertion_evidence", []) if isinstance(item, dict)
                ] if isinstance(scenario.get("assertion_evidence"), list) else [],
            }
        )

    mapped_rust_tests = {
        item.get("rust_test")
        for item in scenarios
        if isinstance(item, dict) and isinstance(item.get("rust_test"), str)
    }
    rust_only = sorted(rust_test_functions(root, mapping) - mapped_rust_tests)
    logic_mismatch = [
        item for item in issues
        if isinstance(item, dict) and str(item.get("code", "")).startswith("logic_mismatch_")
    ]
    return {
        "stage": "TEST_CONSISTENCY_CHECK",
        "status": "pass" if not issues else "fail",
        "issue_count": len(issues),
        "issues": issues,
        "total_scenarios": len(scenario_results),
        "passed_scenarios": sum(item["status"] == "pass" for item in scenario_results),
        "failed_scenarios": sum(item["status"] == "fail" for item in scenario_results),
        "scenarios": scenario_results,
        "c_only": c_only,
        "rust_only": rust_only,
        "logic_mismatch": logic_mismatch,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check migrated Rust test consistency against C semantic contracts.")
    parser.add_argument("--root", default=".", help="Workbench root directory.")
    parser.add_argument("--out", help="Optional path to write test-consistency.json.")
    args = parser.parse_args(argv)

    report = analyze_consistency(Path(args.root))
    if args.out:
        write_json(Path(args.out), report)
    print("TEST_CONSISTENCY_CHECK: " + report["status"].upper())
    print(f"issues={report['issue_count']}")
    for issue in report["issues"]:
        print(f"- {issue['scenario_id']}: {issue['code']}: {issue['message']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
