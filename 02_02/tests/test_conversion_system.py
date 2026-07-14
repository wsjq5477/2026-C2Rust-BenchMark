import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "work" / "tools"


def load_tool(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load_tool("gate.py")


class SimplifiedWorkbenchContractTests(unittest.TestCase):
    def test_required_tools_are_result_oriented(self):
        required = {
            "scan_c_project.py",
            "build_c_model.py",
            "abi_layout_extractor.py",
            "design_rust_api.py",
            "generate_rust_scaffold.py",
            "c_cross_validate.py",
            "migrate_tests.py",
            "cargo_capture.py",
            "test_consistency_check.py",
            "placeholder_check.py",
            "unsafe_ratio.py",
            "report_writer.py",
            "gate.py",
        }
        present = {path.name for path in TOOLS.glob("*.py")}
        self.assertTrue(required.issubset(present))
        self.assertFalse({
            "workflowctl.py", "task_packet.py", "rewrite_check.py",
            "repair_planner.py", "c_cross_converge.py",
        } & present)
        self.assertFalse((PROJECT / "work" / "knowledge" / "workflow-contract.json").exists())

    def test_primary_contract_is_single_agent_four_stage_flow(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "skills" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        for stage in ("ANALYZE", "IMPLEMENT", "VERIFY_AND_REPAIR", "TEST_AND_REPORT"):
            self.assertIn(stage, instruction)
            self.assertIn(stage, orchestrator)
        self.assertIn("c_cross_validate.py", instruction)
        self.assertNotIn("workflowctl", instruction)
        self.assertNotIn("必须提供 task packet", orchestrator)
        self.assertIn("可选 subagent", orchestrator)

    def test_q9_design_is_present_and_approved_for_this_branch(self):
        design = PROJECT.parent / "design_doc" / "Q9-转换工程架构简化设计.md"
        text = design.read_text(encoding="utf-8")
        self.assertIn("已批准", text)
        self.assertIn("workflowctl.py", text)
        self.assertIn("真实 C compile/link/run", text)

    def test_c_cross_failure_summary_is_not_a_controller_route(self):
        cross = load_tool("c_cross_validate.py")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "c-cross"
            matrix = {
                "execution_id": "fixture",
                "scenarios": [{
                    "scenario_id": "dynamic_case",
                    "scorer_case_id": "case-1",
                    "suite": "dynamic_suite",
                    "failure_layer": "assertion",
                    "diagnosis": "c_test_case_failed",
                    "reason": "observed mismatch",
                    "log": "logs/trace/c-cross/test.log",
                    "handoff": "rust-implementer",
                    "rust_impl_c_test": "fail",
                }],
            }
            summary = cross._write_failure_summary(matrix, output)
            saved = json.loads((output / "failure-summary.json").read_text(encoding="utf-8"))
            self.assertEqual("repair_required", summary["status"])
            self.assertEqual(summary, saved)
            self.assertNotIn("next_action", saved)
            self.assertEqual("dynamic_case", saved["failures"][0]["scenario_id"])

    def test_gate_exposes_only_result_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result" / "issues").mkdir(parents=True)
            (root / "logs" / "trace").mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            self.assertTrue(callable(GATE.check_analyze))
            self.assertTrue(callable(GATE.check_verify_and_repair))
            self.assertTrue(callable(GATE.check_final))


if __name__ == "__main__":
    unittest.main()
