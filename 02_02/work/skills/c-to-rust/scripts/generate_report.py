#!/usr/bin/env python3
"""Render the final result from explicit verification-gate evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_GATES = (
    "c_baseline",
    "coverage",
    "unsafe",
    "cargo_build",
    "cargo_test",
    "cargo_fmt",
    "cargo_clippy",
    "no_c_linkage",
)


def gates_pass(gates: dict[str, dict[str, Any]]) -> bool:
    return all(name in gates and gates[name].get("passed") is True for name in REQUIRED_GATES)


def build_report(gates: dict[str, dict[str, Any]], rust_project: str) -> str:
    successful = gates_pass(gates)
    missing = [name for name in REQUIRED_GATES if name not in gates]
    lines = [
        "# 转换系统运行结果",
        "",
        f"STATUS: {'SUCCESS' if successful else 'FAILED'}",
        "",
        f"Rust 项目：`{rust_project}`",
        "",
        "## 验证门禁",
        "",
        "| 门禁 | 结果 | 退出码 | 命令 |",
        "|---|---|---:|---|",
    ]
    for name in REQUIRED_GATES:
        evidence = gates.get(name)
        if evidence is None:
            lines.append(f"| {name} | MISSING | - | - |")
            continue
        result = "PASS" if evidence.get("passed") is True else "FAIL"
        exit_code = evidence.get("exit_code", "-")
        command = str(evidence.get("command", "-")).replace("|", "\\|")
        lines.append(f"| {name} | {result} | {exit_code} | `{command}` |")
    lines.append("")
    if missing:
        lines.append("缺失证据：" + ", ".join(f"{name}: MISSING" for name in missing))
        lines.append("")
    lines.extend(["缺少证据与验证失败按同一规则处理。", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--rust-project", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    gates = json.loads(args.evidence.read_text(encoding="utf-8"))
    report = build_report(gates, args.rust_project)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report, end="")
    return 0 if gates_pass(gates) else 1


if __name__ == "__main__":
    raise SystemExit(main())
