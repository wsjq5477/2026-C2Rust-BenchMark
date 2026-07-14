import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "work" / "tools"


def load_tool(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location("simplified_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPORT = load_tool("report_writer.py")


class ResultEvidenceTests(unittest.TestCase):
    def test_final_c_cross_requires_fresh_full_final_attempt(self):
        passing = {
            "mode": "full",
            "scope": "all",
            "attempt_kind": "final",
            "execution_id": "final-1",
            "scenarios": [{"rust_impl_c_test": "pass"}],
        }
        self.assertTrue(REPORT.final_c_cross_verified(passing, [{"attempt_id": "final-1", "kind": "final"}]))
        self.assertFalse(REPORT.final_c_cross_verified(passing, [{"attempt_id": "older", "kind": "final"}]))

    def test_report_status_uses_results_not_workflow_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "logs" / "trace"
            (root / "result" / "issues").mkdir(parents=True)
            (root / "logs").mkdir(exist_ok=True)
            (trace / "c-cross").mkdir(parents=True)
            payloads = {
                "cargo-results.json": {"build_status": "pass", "test_status": "pass", "build": {"returncode": 0}, "test": {"returncode": 0}},
                "unsafe-ratio.json": {"unsafe_ratio": 0.0, "unsafe_lines": 0},
                "rust_api_design.json": {"crate_name": "fixture", "modules": []},
                "validation-matrix.json": {"mode": "full", "scope": "all", "attempt_kind": "final", "execution_id": "final-1", "total_scenarios": 1, "summary": {"rust_impl_c_test": {"pass": 1}}, "scenarios": [{"rust_impl_c_test": "pass"}]},
                "rust_test_mapping.json": {"total_scenarios": 1, "extension": [], "unmapped": []},
                "test-placeholder-check.json": {"status": "pass", "issue_count": 0},
                "test-consistency.json": {"status": "pass", "issue_count": 0, "passed_scenarios": 1, "failed_scenarios": 0},
            }
            for name, payload in payloads.items():
                (trace / name).write_text(json.dumps(payload), encoding="utf-8")
            (trace / "c-cross" / "attempts.jsonl").write_text(json.dumps({"attempt_id": "final-1", "kind": "final"}) + "\n", encoding="utf-8")
            REPORT.write_report(root, root / "result" / "output.md", root / "result" / "issues" / "00-summary.md")
            self.assertIn("STATUS: SUCCESS", (root / "result" / "output.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
