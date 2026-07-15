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
PLACEHOLDER = load_tool("placeholder_check.py")
CONSISTENCY = load_tool("test_consistency_check.py")


def semantic_fixture(root: Path) -> None:
    trace = root / "logs" / "trace"
    c_source = root / "c_input" / "tests" / "fixture.c"
    rust_test = root / "flashDB_rust" / "tests" / "dynamic.rs"
    trace.mkdir(parents=True, exist_ok=True)
    c_source.parent.mkdir(parents=True, exist_ok=True)
    rust_test.parent.mkdir(parents=True, exist_ok=True)
    c_source.write_text("void test_dynamic(void) {\n  assert(1);\n}\n", encoding="utf-8")
    rust_test.write_text("#[test]\nfn rust_dynamic() {\n  let actual = 1;\n  assert_eq!(actual, 1);\n}\n", encoding="utf-8")
    (trace / "input_manifest.json").write_text(json.dumps({"source_root": str(root / "c_input")}), encoding="utf-8")
    (trace / "c_test_model.json").write_text(json.dumps({"scorer_standard_cases": [{"scenario_id": "dynamic-case", "case_id": "case-1", "source_file": "tests/fixture.c", "required_c_tests": ["test_dynamic"]}]}), encoding="utf-8")
    (trace / "rust_api_design.json").write_text(json.dumps({"crate_name": "fixture", "modules": []}), encoding="utf-8")
    mapping = {"total_scenarios": 1, "extension": [], "unmapped": [], "source_to_rust": {"fixture": "flashDB_rust/tests/dynamic.rs"}, "scenarios": [{"id": "dynamic-case", "source_file": "tests/fixture.c", "required_c_tests": ["test_dynamic"], "rust_file": "flashDB_rust/tests/dynamic.rs", "rust_test": "rust_dynamic", "implementation_status": "implemented"}]}
    (trace / "rust_test_mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
    fingerprint = CONSISTENCY.build_input_fingerprint(root)
    review = {"schema_version": 1, "status": "pass", "reviewer_mode": "primary_readonly_fallback", "input_fingerprint": fingerprint, "total_c_scenarios": 1, "reviewed_scenarios": 1, "c_only": [], "rust_only": [], "logic_mismatch": [], "cases": [{"scenario_id": "dynamic-case", "c_function": "test_dynamic", "rust_test": "rust_dynamic", "status": "pass", "dimensions": {name: "pass" for name in CONSISTENCY.DIMENSIONS}, "c_evidence": [{"path": "c_input/tests/fixture.c", "function": "test_dynamic", "line_start": 1, "line_end": 3, "summary": "C case"}], "rust_evidence": [{"path": "flashDB_rust/tests/dynamic.rs", "function": "rust_dynamic", "line_start": 1, "line_end": 5, "summary": "Rust case"}], "differences": []}]}
    (trace / "test-semantic-review.json").write_text(json.dumps(review), encoding="utf-8")
    placeholder = PLACEHOLDER.analyze_placeholders(root, rust_test.parent, trace / "rust_test_mapping.json")
    consistency = CONSISTENCY.analyze_consistency(root)
    (trace / "test-placeholder-check.json").write_text(json.dumps(placeholder), encoding="utf-8")
    (trace / "test-consistency.json").write_text(json.dumps(consistency), encoding="utf-8")


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
            semantic_fixture(root)
            payloads = {
                "cargo-results.json": {"build_status": "pass", "test_status": "pass", "build": {"returncode": 0}, "test": {"returncode": 0}},
                "unsafe-ratio.json": {"unsafe_ratio": 0.0, "unsafe_lines": 0},
                "validation-matrix.json": {"mode": "full", "scope": "all", "attempt_kind": "final", "execution_id": "final-1", "total_scenarios": 1, "summary": {"rust_impl_c_test": {"pass": 1}}, "scenarios": [{"rust_impl_c_test": "pass"}]},
            }
            for name, payload in payloads.items():
                (trace / name).write_text(json.dumps(payload), encoding="utf-8")
            (trace / "c-cross" / "attempts.jsonl").write_text(json.dumps({"attempt_id": "final-1", "kind": "final"}) + "\n", encoding="utf-8")
            REPORT.write_report(root, root / "result" / "output.md", root / "result" / "issues" / "00-summary.md")
            self.assertIn("STATUS: SUCCESS", (root / "result" / "output.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
