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

    if not isinstance(scenarios, list):
        add_issue(issues, "invalid_mapping", "<mapping>", "rust_test_mapping.json scenarios must be a list")
        scenarios = []

    for scenario in scenarios:
        if not isinstance(scenario, dict) or scenario.get("coverage") != "semantic":
            continue
        scenario_id = str(scenario.get("id", scenario.get("rust_test", "<unknown>")))
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

        case = case_by_id.get(scenario.get("scorer_case_id"))
        semantic_facts = case.get("semantic_facts") if isinstance(case, dict) else {}
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

    return {
        "stage": "TEST_CONSISTENCY_CHECK",
        "status": "pass" if not issues else "fail",
        "issue_count": len(issues),
        "issues": issues,
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
