import ast
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "work" / "tools"
TEST_TEMP_ROOT = PROJECT / "logs" / "trace" / "tmp" / "tests"


def project_temp_directory():
    TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="conversion-system-", dir=TEST_TEMP_ROOT)


def load_tool(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load_tool("gate.py")
PLACEHOLDER = load_tool("placeholder_check.py")
CONSISTENCY = load_tool("test_consistency_check.py")


def semantic_fixture(root: Path, *, review_status: str = "pass") -> dict:
    trace = root / "logs" / "trace"
    c_source = root / "c_input" / "tests" / "fixture.c"
    rust_test = root / "flashDB_rust" / "tests" / "dynamic.rs"
    trace.mkdir(parents=True)
    c_source.parent.mkdir(parents=True)
    rust_test.parent.mkdir(parents=True)
    c_source.write_text("void test_dynamic(void) {\n  assert(1);\n}\n", encoding="utf-8")
    rust_test.write_text("#[test]\nfn rust_dynamic() {\n  let actual = 1;\n  assert_eq!(actual, 1);\n}\n", encoding="utf-8")
    (trace / "input_manifest.json").write_text(json.dumps({"source_root": str(root / "c_input")}), encoding="utf-8")
    (trace / "c_test_model.json").write_text(json.dumps({"scorer_standard_cases": [{"scenario_id": "dynamic-case", "case_id": "case-1", "source_file": "tests/fixture.c", "required_c_tests": ["test_dynamic"]}]}), encoding="utf-8")
    (trace / "rust_api_design.json").write_text(json.dumps({"crate_name": "fixture", "modules": []}), encoding="utf-8")
    mapping = {"total_scenarios": 1, "extension": [], "unmapped": [], "source_to_rust": {"fixture": "flashDB_rust/tests/dynamic.rs"}, "scenarios": [{"id": "dynamic-case", "source_file": "tests/fixture.c", "required_c_tests": ["test_dynamic"], "rust_file": "flashDB_rust/tests/dynamic.rs", "rust_test": "rust_dynamic", "implementation_status": "implemented"}]}
    (trace / "rust_test_mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
    dimensions = {name: "pass" for name in CONSISTENCY.DIMENSIONS}
    differences: list[dict[str, str]] = []
    logic_mismatch: list[dict[str, str]] = []
    if review_status != "pass":
        dimensions["lifecycle"] = review_status
        differences = [{"dimension": "lifecycle", "detail": "Rust test omits the C reopen boundary."}]
        logic_mismatch = [{"scenario_id": "dynamic-case", "detail": differences[0]["detail"]}]
    review = {"schema_version": 1, "status": review_status, "reviewer_mode": "primary_readonly_fallback", "input_fingerprint": CONSISTENCY.build_input_fingerprint(root), "total_c_scenarios": 1, "reviewed_scenarios": 1, "c_only": [], "rust_only": [], "logic_mismatch": logic_mismatch, "cases": [{"scenario_id": "dynamic-case", "c_function": "test_dynamic", "rust_test": "rust_dynamic", "status": review_status, "dimensions": dimensions, "c_evidence": [{"path": "c_input/tests/fixture.c", "function": "test_dynamic", "line_start": 1, "line_end": 3, "summary": "C case"}], "rust_evidence": [{"path": "flashDB_rust/tests/dynamic.rs", "function": "rust_dynamic", "line_start": 1, "line_end": 5, "summary": "Rust case"}], "differences": differences}]}
    (trace / "test-semantic-review.json").write_text(json.dumps(review), encoding="utf-8")
    placeholder = PLACEHOLDER.analyze_placeholders(root, rust_test.parent, trace / "rust_test_mapping.json")
    consistency = CONSISTENCY.analyze_consistency(root)
    (trace / "test-placeholder-check.json").write_text(json.dumps(placeholder), encoding="utf-8")
    (trace / "test-consistency.json").write_text(json.dumps(consistency), encoding="utf-8")
    return consistency


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

    def test_primary_contract_is_thin_agent_four_stage_flow(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "skills" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        for stage in ("ANALYZE", "IMPLEMENT", "VERIFY_AND_REPAIR", "TEST_AND_REPORT"):
            self.assertIn(stage, instruction)
            self.assertIn(stage, orchestrator)
        self.assertIn("c_cross_validate.py", instruction)
        self.assertNotIn("workflowctl", instruction)
        self.assertNotIn("必须提供 task packet", orchestrator)
        self.assertIn("可选 subagent", orchestrator)
        self.assertIn("同一次无人值守运行内的自动上下文隔离手段", instruction)
        self.assertIn("不限制总数", instruction)
        self.assertIn("启动新的短 session", orchestrator)

    def test_agents_cannot_bypass_project_owned_temp_or_subagent_contracts(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "skills" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        self.assertIn("logs/trace/tmp/<task>/", instruction)
        self.assertIn("不得访问或使用 `/tmp/**`、`/var/tmp/**`", instruction)
        self.assertIn('"*": deny', orchestrator)
        self.assertIn('"general": allow', orchestrator)
        self.assertIn("若运行时只提供 `general`", orchestrator)
        self.assertIn("完整读取并执行对应 `work/skills/{subagent}.md`", orchestrator)
        for name in (
            "flashdb-orchestrator.md",
            "c-analyzer.md",
            "rust-implementer.md",
            "repairer.md",
            "test-migrator.md",
            "test-semantic-reviewer.md",
        ):
            agent = (PROJECT / "work" / "skills" / name).read_text(encoding="utf-8")
            self.assertIn('"* /tmp*": deny', agent, name)
            self.assertIn('"*=/tmp*": deny', agent, name)
            self.assertIn('"* /var/tmp*": deny', agent, name)
            self.assertIn('"*=/var/tmp*": deny', agent, name)
            self.assertIn('"/tmp": deny', agent, name)
            self.assertIn('"/tmp/**": deny', agent, name)
            self.assertIn('"/var/tmp": deny', agent, name)
            self.assertIn('"/var/tmp/**": deny', agent, name)

    def test_context_contract_uses_bounded_automatic_worker_handoffs(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "skills" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        implementer = (PROJECT / "work" / "skills" / "rust-implementer.md").read_text(encoding="utf-8")
        repairer = (PROJECT / "work" / "skills" / "repairer.md").read_text(encoding="utf-8")
        design = (PROJECT.parent / "design_doc" / "Q11-OpenCode上下文爆炸分析与优化方案.md").read_text(encoding="utf-8")
        self.assertIn("不得要求或接收 C/Rust 源码全文", instruction)
        self.assertIn("一个 failure cluster", instruction)
        self.assertIn("新的 repair session", instruction)
        self.assertIn("不得依赖用户第二次输入", orchestrator)
        self.assertIn("不得创建要求返回全文源码的 reader task", orchestrator)
        self.assertIn("完成一次最小实现或修复后立即返回", implementer)
        self.assertIn("不得自行进入下一轮验证、调试或扩大到其他 failure cluster", implementer)
        self.assertIn("完成一次修改后立即返回", repairer)
        self.assertIn("新的 repair session 接力", repairer)
        self.assertIn("不依赖 compact、插件、人工 continuation 或新的 primary session", design)
        self.assertNotIn("FULL content", instruction + orchestrator)
        self.assertNotIn("do not summarize", instruction + orchestrator)

    def test_abi_probe_uses_project_owned_temporary_directory(self):
        extractor = (TOOLS / "abi_layout_extractor.py").read_text(encoding="utf-8")
        model_builder = (TOOLS / "build_c_model.py").read_text(encoding="utf-8")
        self.assertIn('dir=owned_temp_root', extractor)
        self.assertIn('output_dir / "tmp" / "abi-layout"', model_builder)

    def test_python_temporary_directories_always_use_project_owned_parent(self):
        paths = sorted((PROJECT / "work").rglob("*.py")) + sorted((PROJECT / "tests").glob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != "TemporaryDirectory":
                    continue
                keywords = {item.arg for item in node.keywords}
                self.assertIn("dir", keywords, f"{path} must place temporary directories under logs/trace/tmp")

    def test_q9_design_is_present_and_approved_for_this_branch(self):
        design = PROJECT.parent / "design_doc" / "Q9-转换工程架构简化设计.md"
        text = design.read_text(encoding="utf-8")
        self.assertIn("已实施", text)
        self.assertIn("workflowctl.py", text)
        self.assertIn("真实 C compile/link/run", text)

    def test_semantic_reviewer_is_self_contained(self):
        reviewer = (PROJECT / "work" / "skills" / "test-semantic-reviewer.md").read_text(encoding="utf-8")
        self.assertIn("对每个动态 C scenario，依次完成以下操作", reviewer)
        self.assertIn("关键 API、输入数据、初始化/控制配置、生命周期边界、操作顺序", reviewer)
        self.assertNotIn("评分平台的方案 B", reviewer)

    def test_extension_scorer_case_is_mapped_not_reported_as_unmapped(self):
        migrator = load_tool("migrate_tests.py")
        model = {
            "scorer_standard_cases": [{
                "scenario_id": "extension-case",
                "case_id": "case-1",
                "suite": "extension",
                "source_file": "tests/fixture.c",
                "required_c_tests": ["test_extension"],
            }],
        }
        with project_temp_directory() as directory:
            mapping = migrator.generate_tests(
                model,
                {"unmapped_symbols": ["unimplemented_api"]},
                Path(directory) / "fixture",
                Path(directory) / "mapping.json",
            )
            self.assertEqual([], mapping["unmapped"])
            self.assertEqual(["unimplemented_api"], mapping["unmapped_symbols"])
            self.assertEqual("extension-case", mapping["scenarios"][0]["id"])

    def test_c_cross_failure_summary_is_not_a_controller_route(self):
        cross = load_tool("c_cross_validate.py")
        with project_temp_directory() as directory:
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
        with project_temp_directory() as directory:
            root = Path(directory)
            (root / "result" / "issues").mkdir(parents=True)
            (root / "logs" / "trace").mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            self.assertTrue(callable(GATE.check_analyze))
            self.assertTrue(callable(GATE.check_verify_and_repair))
            self.assertTrue(callable(GATE.check_final))

    def test_semantic_review_is_required_for_dynamic_consistency(self):
        with project_temp_directory() as directory:
            consistency = semantic_fixture(Path(directory))
            self.assertEqual("pass", consistency["status"])
            self.assertEqual(1, consistency["passed_scenarios"])

    def test_semantic_mismatch_fails_even_when_rust_test_has_assertion(self):
        with project_temp_directory() as directory:
            consistency = semantic_fixture(Path(directory), review_status="fail")
            self.assertEqual("fail", consistency["status"])
            codes = {item["code"] for item in consistency["issues"]}
            self.assertIn("semantic_review_lifecycle", codes)
            self.assertIn("logic_mismatch", codes)

    def test_final_gate_rejects_stale_test_evidence(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            semantic_fixture(root)
            test_file = root / "flashDB_rust" / "tests" / "dynamic.rs"
            test_file.write_text(test_file.read_text(encoding="utf-8") + "\n// changed after review\n", encoding="utf-8")
            errors = GATE.check_test_quality(root)
            self.assertIn("test-placeholder-check.json is stale or does not match current inputs", errors)
            self.assertIn("test-consistency.json is stale or does not match current inputs", errors)


if __name__ == "__main__":
    unittest.main()
