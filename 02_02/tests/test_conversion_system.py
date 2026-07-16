import ast
import importlib.util
import json
import shutil
import sys
import tempfile
import time
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
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


GATE = load_tool("gate.py")
PLACEHOLDER = load_tool("placeholder_check.py")
CONSISTENCY = load_tool("test_consistency_check.py")
TRIAGE = load_tool("test_failure_triage.py")
AUDIT = load_tool("core_impl_audit.py")
SCAFFOLD = load_tool("generate_rust_scaffold.py")
CROSS = load_tool("c_cross_validate.py")
REPORT = load_tool("report_writer.py")
QUEUE = load_tool("repair_work_queue.py")
SNAPSHOT = load_tool("submission_snapshot.py")
WATCHDOG = load_tool("contest_watchdog.py")


def implementation_fixture(root: Path, *, implemented: bool = False) -> dict:
    trace = root / "logs" / "trace"
    project = root / "flashDB_rust"
    trace.mkdir(parents=True, exist_ok=True)
    (trace / "c-cross").mkdir(parents=True, exist_ok=True)
    (root / "result" / "issues").mkdir(parents=True, exist_ok=True)
    (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
    design = {
        "crate_name": "fixture",
        "modules": ["core"],
        "c_abi_facade": {
            "functions": [{
                "rust_export": "fixture_value",
                "params": [],
                "return": {"rust_ffi_type": "i32"},
            }],
        },
    }
    design_path = trace / "rust_api_design.json"
    manifest_path = trace / "scaffold-manifest.json"
    design_path.write_text(json.dumps(design), encoding="utf-8")
    SCAFFOLD.generate_project(
        design,
        project,
        manifest_path=manifest_path,
        design_path=design_path,
    )
    if implemented:
        (project / "src" / "core.rs").write_text(
            "pub fn value() -> i32 { 42 }\n",
            encoding="utf-8",
        )
        (project / "src" / "ffi" / "c_abi.rs").write_text(
            "#[no_mangle]\npub extern \"C\" fn fixture_value() -> i32 { crate::core::value() }\n",
            encoding="utf-8",
        )
    return design


def persist_implementation_audit(
    root: Path,
    *,
    kind: str,
    layout_pass: bool = True,
) -> tuple[dict, dict]:
    trace = root / "logs" / "trace"
    result = AUDIT.audit_workspace(root)
    layout = {
        "phase": "layout",
        "status": "pass" if layout_pass else "fail",
        "build_status": "pass" if layout_pass else "fail",
        "layout_status": "pass" if layout_pass else "not_run",
        "source_manifest": result["source_manifest"],
    }
    (trace / "c-cross" / "scaffold-layout-check.json").write_text(
        json.dumps(layout),
        encoding="utf-8",
    )
    _, evidence = AUDIT.record_attempt(
        trace / "implementation-attempts.jsonl",
        result,
        kind=kind,
        layout=layout,
    )
    result["convergence"] = evidence
    (trace / "implementation-audit.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result, evidence


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
    def test_platform_agent_and_skill_source_layout(self):
        primary = PROJECT / "work" / "agents" / "flashdb-orchestrator.md"
        self.assertTrue(primary.is_file())
        self.assertIn("mode: primary", primary.read_text(encoding="utf-8"))
        self.assertEqual({"flashdb-orchestrator.md"}, {path.name for path in (PROJECT / "work" / "agents").glob("*.md")})

        expected_subagents = {
            "rust-implementer.md",
            "test-migrator.md",
            "test-semantic-reviewer.md",
        }
        present_subagents = {path.name for path in (PROJECT / "work" / "subagent").glob("*.md")}
        self.assertEqual(expected_subagents, present_subagents)
        self.assertFalse(list((PROJECT / "work" / "skills").glob("*.md")))
        for skill in (PROJECT / "work" / "skills").iterdir():
            self.assertTrue((skill / "SKILL.md").is_file(), skill)

    def test_platform_sync_script_mirrors_agents_and_skills(self):
        script = PROJECT.parent / "sync_opencode.sh"
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn('PROJECT="$ROOT/02_02"', text)
        self.assertIn('TARGET="$ROOT/.opencode"', text)
        self.assertIn('SKILLS_SOURCE="$WORK/skills"', text)
        self.assertIn('AGENTS_SOURCE="$WORK/agents"', text)
        self.assertIn('SUBAGENTS_SOURCE="$WORK/subagent"', text)
        self.assertIn('SKILLS_TARGET="$TARGET/skills"', text)
        self.assertIn('AGENTS_TARGET="$TARGET/agents"', text)

    def test_required_tools_are_result_oriented(self):
        required = {
            "scan_c_project.py",
            "build_c_model.py",
            "abi_layout_extractor.py",
            "design_rust_api.py",
            "generate_rust_scaffold.py",
            "core_impl_audit.py",
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

    def test_core_impl_audit_rejects_untouched_and_cosmetic_scaffold(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            implementation_fixture(root)
            untouched = AUDIT.audit_workspace(root)
            codes = {item["code"] for item in untouched["findings"]}
            self.assertEqual("fail", untouched["status"])
            self.assertIn("unchanged_scaffold_body", codes)
            self.assertIn("constant_only_neutral_body", codes)
            self.assertIn("placeholder_module", codes)

            for relative in ("src/core.rs", "src/ffi/c_abi.rs"):
                path = root / "flashDB_rust" / relative
                text = path.read_text(encoding="utf-8")
                text = "\n".join(
                    line for line in text.splitlines()
                    if "@c2rust-scaffold:" not in line
                ) + "\n"
                path.write_text(text, encoding="utf-8")
            cosmetic = AUDIT.audit_workspace(root)
            cosmetic_codes = {item["code"] for item in cosmetic["findings"]}
            self.assertEqual("fail", cosmetic["status"])
            self.assertIn("unchanged_scaffold_body", cosmetic_codes)
            self.assertIn("placeholder_module", cosmetic_codes)
            self.assertIn("cosmetic_only_file_change", cosmetic_codes)

    def test_core_impl_audit_freezes_ffi_signature_and_accepts_real_path(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            implementation_fixture(root, implemented=True)
            implemented = AUDIT.audit_workspace(root)
            self.assertEqual("pass", implemented["status"])
            self.assertEqual(1, implemented["summary"]["checked_frozen_signatures"])

            ffi = root / "flashDB_rust" / "src" / "ffi" / "c_abi.rs"
            ffi.write_text(
                "#[no_mangle]\npub extern \"C\" fn fixture_value() -> i64 { 42 }\n",
                encoding="utf-8",
            )
            changed = AUDIT.audit_workspace(root)
            self.assertIn(
                "changed_frozen_ffi_signature",
                {item["code"] for item in changed["findings"]},
            )

    def test_implement_gate_requires_current_audit_attempt_and_layout(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            implementation_fixture(root, implemented=True)
            _, evidence = persist_implementation_audit(root, kind="checkpoint")
            self.assertEqual("ready_for_verify", evidence["status"])
            self.assertEqual([], GATE.check_implement(root))
            self.assertEqual(0, GATE.main(["--stage", "IMPLEMENT", "--root", str(root)]))
            _, preflight = CROSS.implementation_preflight(
                root,
                root / "logs" / "trace",
            )
            self.assertTrue(preflight["valid"])
            self.assertTrue(preflight["layout_current"])

            core = root / "flashDB_rust" / "src" / "core.rs"
            core.write_text("pub fn value() -> i32 { 43 }\n", encoding="utf-8")
            errors = GATE.check_implement(root)
            self.assertTrue(any("stale" in error for error in errors))
            _, stale_preflight = CROSS.implementation_preflight(
                root,
                root / "logs" / "trace",
            )
            self.assertFalse(stale_preflight["valid"])
            self.assertFalse(stale_preflight["layout_current"])

    def test_implement_failed_final_requires_real_repair_and_confirmation(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            implementation_fixture(root)
            _, checkpoint = persist_implementation_audit(root, kind="checkpoint")
            self.assertEqual("implementation_required", checkpoint["status"])
            self.assertEqual(1, GATE.main(["--stage", "IMPLEMENT", "--root", str(root)]))

            core = root / "flashDB_rust" / "src" / "core.rs"
            core.write_text("pub fn value() -> i32 { 7 }\n", encoding="utf-8")
            _, repair = persist_implementation_audit(root, kind="repair")
            self.assertEqual("implementation_required", repair["status"])
            self.assertEqual("repair_scaffold_residue", repair["next_action"])

            # The remaining FFI scaffold task gets its full per-task 2+2
            # scheduling quantum; unrelated implementation findings are not a
            # project-wide one-repair terminal budget.
            for value in (8, 9, 10):
                core.write_text(f"pub fn value() -> i32 {{ {value} }}\n", encoding="utf-8")
                _, repair = persist_implementation_audit(root, kind="repair")
            self.assertEqual("run_fresh_implementation_confirmation", repair["next_action"])

            _, confirmation = persist_implementation_audit(root, kind="confirmation")
            self.assertEqual("failed_final", confirmation["status"])
            self.assertEqual([], GATE.check_implement(root))
            self.assertEqual(0, GATE.main(["--stage", "IMPLEMENT", "--root", str(root)]))

            output = root / "result" / "output.md"
            issues = root / "result" / "issues" / "00-summary.md"
            self.assertEqual("FAILED", REPORT.write_report(root, output, issues))
            report = output.read_text(encoding="utf-8")
            self.assertIn("failed_stage: `IMPLEMENT`", report)
            self.assertIn("C-Cross: `not_run`", report)
            self.assertIn("Rust tests: `not_run`", report)
            self.assertIn("unsafe ratio: `not_run`", report)
            self.assertEqual([], GATE.check_final(root))

    def test_implement_failed_final_can_report_current_build_failure(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            implementation_fixture(root)
            persist_implementation_audit(root, kind="checkpoint")

            project = root / "flashDB_rust"
            (project / "src" / "core.rs").write_text(
                "pub fn value() -> i32 { 42 }\n",
                encoding="utf-8",
            )
            (project / "src" / "ffi" / "c_abi.rs").write_text(
                "#[no_mangle]\npub extern \"C\" fn fixture_value() -> i32 { crate::core::value() }\n",
                encoding="utf-8",
            )
            audit, repair = persist_implementation_audit(
                root,
                kind="repair",
                layout_pass=False,
            )
            self.assertEqual("pass", audit["status"])
            self.assertEqual("implementation_required", repair["status"])
            _, confirmation = persist_implementation_audit(
                root,
                kind="confirmation",
                layout_pass=False,
            )
            self.assertEqual("failed_final", confirmation["status"])
            self.assertEqual([], GATE.check_implement(root))

            output = root / "result" / "output.md"
            issues = root / "result" / "issues" / "00-summary.md"
            self.assertEqual("FAILED", REPORT.write_report(root, output, issues))
            self.assertEqual([], GATE.check_final(root))

    def test_c_cross_preflight_rejects_scaffold_without_attempt_side_effects(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            implementation_fixture(root)
            persist_implementation_audit(root, kind="checkpoint")
            trace = root / "logs" / "trace"
            c_cross = trace / "c-cross"
            matrix_path = trace / "validation-matrix.json"
            attempts_path = c_cross / "attempts.jsonl"
            matrix_path.write_text('{"sentinel": true}\n', encoding="utf-8")
            attempts_path.write_text('{"attempt_id": "sentinel"}\n', encoding="utf-8")
            matrix_before = matrix_path.read_bytes()
            attempts_before = attempts_path.read_bytes()

            code = CROSS.main([
                "--root", str(root),
                "--project", "flashDB_rust",
                "--out", "logs/trace",
                "--mode", "full",
                "--attempt-kind", "checkpoint",
            ])
            self.assertEqual(2, code)
            self.assertEqual(matrix_before, matrix_path.read_bytes())
            self.assertEqual(attempts_before, attempts_path.read_bytes())

    def test_c_cross_repair_chain_reaudits_without_reusing_initial_source_fingerprint(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            implementation_fixture(root, implemented=True)
            persist_implementation_audit(root, kind="checkpoint")
            project = root / "flashDB_rust"
            c_cross_attempts = root / "logs" / "trace" / "c-cross" / "attempts.jsonl"
            c_cross_attempts.write_text(
                json.dumps({
                    "attempt_id": "checkpoint-1",
                    "kind": "checkpoint",
                    "source_manifest": CROSS._source_manifest(project),
                }) + "\n",
                encoding="utf-8",
            )
            (root / "logs" / "trace" / "validation-matrix.json").write_text(
                json.dumps({"execution_id": "checkpoint-1"}),
                encoding="utf-8",
            )

            (project / "src" / "core.rs").write_text(
                "pub fn value() -> i32 { 43 }\n",
                encoding="utf-8",
            )
            audit, evidence = CROSS.implementation_preflight(
                root,
                root / "logs" / "trace",
            )
            self.assertEqual("pass", audit["status"])
            self.assertTrue(evidence["valid"])
            self.assertEqual("existing_c_cross_chain", evidence["basis"])

            (project / "src" / "ffi" / "c_abi.rs").write_text(
                "#[no_mangle]\npub extern \"C\" fn fixture_value() -> i32 { 0 }\n",
                encoding="utf-8",
            )
            audit, evidence = CROSS.implementation_preflight(
                root,
                root / "logs" / "trace",
            )
            self.assertEqual("fail", audit["status"])
            self.assertFalse(evidence["valid"])
            self.assertEqual("implementation_required", evidence["status"])

    def test_primary_contract_is_thin_agent_four_stage_flow(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "agents" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        for stage in ("ANALYZE", "IMPLEMENT", "VERIFY_AND_REPAIR", "TEST_AND_REPORT"):
            self.assertIn(stage, instruction)
            self.assertIn(stage, orchestrator)
        self.assertIn("c_cross_validate.py", instruction)
        self.assertIn("contest_watchdog.py start", instruction)
        self.assertNotIn("workflowctl", instruction)
        self.assertNotIn("必须提供 task packet", orchestrator)
        self.assertIn("## 调度原则", orchestrator)
        self.assertIn("queued scenario", instruction)
        self.assertIn("完成一次真实修改后立即返回", instruction)
        self.assertIn("验证失败时使用新 session", orchestrator)

    def test_global_repair_budget_constants_are_removed(self):
        sources = "\n".join(
            (TOOLS / name).read_text(encoding="utf-8")
            for name in (
                "core_impl_audit.py",
                "c_cross_validate.py",
                "cargo_capture.py",
                "gate.py",
                "report_writer.py",
            )
        )
        for forbidden in (
            "MAX_IMPLEMENTATION_REPAIR_ATTEMPTS",
            "MAX_REPAIR_ATTEMPTS",
            "MAX_TEST_REPAIR_ATTEMPTS",
            "EXPECTED_C_CROSS_REPAIR_ATTEMPTS",
            "EXPECTED_TEST_REPAIR_ATTEMPTS",
            "max_repair_attempts",
            "remaining_repair_attempts",
        ):
            self.assertNotIn(forbidden, sources)
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        self.assertIn("不存在全局 8 次 repair 预算", instruction)
        self.assertIn("不存在全局两轮 repair 预算", instruction)

    def test_implement_contract_orders_scaffold_audit_gate_before_full_c_cross(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "agents" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        section = instruction.split("## 2. IMPLEMENT", 1)[1].split("## 3. VERIFY_AND_REPAIR", 1)[0]
        generate = section.index("generate_rust_scaffold.py")
        layout = section.index("--scaffold-layout-only")
        implement = section.index("初始实现后")
        audit = section.index("core_impl_audit.py")
        gate = section.index("gate.py --stage IMPLEMENT")
        full_cross = instruction.index("--mode full --attempt-kind checkpoint")
        self.assertLess(generate, layout)
        self.assertLess(layout, implement)
        self.assertLess(implement, audit)
        self.assertLess(audit, gate)
        self.assertLess(instruction.index("gate.py --stage IMPLEMENT"), full_cross)
        self.assertIn("implementation_required", section)
        self.assertIn("IMPLEMENT `failed_final`", section)
        self.assertIn("不存在全局一次 repair 预算", orchestrator)
        self.assertNotIn("全局最多 1 次", section)

    def test_agents_cannot_bypass_project_owned_temp_or_subagent_contracts(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "agents" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        self.assertIn("logs/trace/tmp/<task>/", instruction)
        self.assertIn("禁止使用 `/tmp/**`、`/var/tmp/**`", instruction)
        self.assertIn('"*": deny', orchestrator)
        self.assertNotIn('"general": allow', orchestrator)
        self.assertIn("禁止 General、Explore、Scout", orchestrator)
        self.assertIn("大 JSON", orchestrator)
        for name in (
            "rust-implementer.md",
            "test-migrator.md",
            "test-semantic-reviewer.md",
        ):
            agent = (PROJECT / "work" / "subagent" / name).read_text(encoding="utf-8")
            self.assertIn("mode: subagent", agent, name)
            self.assertNotIn("hidden: true", agent, name)
            self.assertIn("task: deny", agent, name)
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
        orchestrator = (PROJECT / "work" / "agents" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        implementer = (PROJECT / "work" / "subagent" / "rust-implementer.md").read_text(encoding="utf-8")
        design = (PROJECT.parent / "design_doc" / "Q11-OpenCode上下文爆炸分析与优化方案.md").read_text(encoding="utf-8")
        self.assertIn("不自行循环验证或返回源码全文", instruction)
        self.assertIn("最小 cluster", instruction)
        self.assertIn("新的 `rust-implementer`", instruction)
        self.assertIn("不恢复旧上下文", orchestrator)
        self.assertIn("不得读取或要求返回完整 C/Rust tree", orchestrator)
        self.assertIn("完成一次最小修改后返回", implementer)
        self.assertIn("不得自行进入下一轮、扩大 task", implementer)
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
        reviewer = (PROJECT / "work" / "subagent" / "test-semantic-reviewer.md").read_text(encoding="utf-8")
        self.assertIn("只对主执行者分配的一个动态 scenario", reviewer)
        self.assertIn("关键 API、输入数据、初始化/控制配置、生命周期边界、操作顺序", reviewer)
        self.assertIn("semantic_review_merge.py", reviewer)
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

    def test_c_cross_failure_summary_is_a_bounded_convergence_decision(self):
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
            self.assertFalse(saved["terminal"])
            self.assertEqual("repair_next_queued_task", saved["next_action"])
            self.assertEqual(0, saved["repair_attempts_recorded"])
            self.assertEqual("dynamic_case", saved["failures"][0]["scenario_id"])

    def test_c_cross_convergence_distinguishes_required_ready_and_terminal(self):
        cross = load_tool("c_cross_validate.py")
        failed = {
            "mode": "full",
            "scope": "all",
            "attempt_kind": "confirmation",
            "scenarios": [{"rust_impl_c_test": "fail"}],
        }
        passing = {**failed, "scenarios": [{"rust_impl_c_test": "pass"}]}
        self.assertEqual("repair_required", cross.convergence_status(failed, [])["status"])
        self.assertEqual("ready_for_final", cross.convergence_status(passing, [])["status"])
        self.assertEqual(
            "success",
            cross.convergence_status({**passing, "attempt_kind": "final"}, [])["status"],
        )
        exhausted_phase = {
            "tasks": {"dynamic": {"task_id": "dynamic", "state": "exhausted"}},
            "dynamic_task_ids": ["dynamic"],
            "sweep": 2,
        }
        exhausted = cross.convergence_status(failed, [], exhausted_phase)
        self.assertEqual("failed_final", exhausted["status"])
        self.assertTrue(exhausted["terminal"])
        selected = cross.convergence_status({**failed, "scope": "selected"}, [], exhausted_phase)
        self.assertEqual("repair_required", selected["status"])
        self.assertEqual("run_full_confirmation", selected["next_action"])

    def test_c_cross_repair_scope_and_architecture_escalation_are_enforced(self):
        cross = load_tool("c_cross_validate.py")
        cluster = ["case-a"]
        before = {"flashDB_rust/src/lib.rs": "old"}
        after = {"flashDB_rust/src/lib.rs": "new"}
        checkpoint = {"kind": "confirmation", "source_manifest": before, "regression": False}
        self.assertEqual([], cross.validate_repair_request(
            [checkpoint],
            repair_kind="local",
            cluster_scenarios=cluster,
            declared_changed_files=["flashDB_rust/src/lib.rs"],
            current_source_manifest=after,
        ))
        undeclared = cross.validate_repair_request(
            [checkpoint],
            repair_kind="local",
            cluster_scenarios=cluster,
            declared_changed_files=["flashDB_rust/src/other.rs"],
            current_source_manifest=after,
        )
        self.assertTrue(any("exactly match" in error for error in undeclared))
        stalled = [
            checkpoint,
            {"kind": "repair", "repair_kind": "local", "cluster_scenarios": cluster, "progress": False, "source_manifest": before},
            {"kind": "repair", "repair_kind": "local", "cluster_scenarios": cluster, "progress": False, "source_manifest": before},
        ]
        local_errors = cross.validate_repair_request(
            stalled,
            repair_kind="local",
            cluster_scenarios=cluster,
            declared_changed_files=["flashDB_rust/src/lib.rs"],
            current_source_manifest=after,
        )
        self.assertTrue(any("architecture review" in error for error in local_errors))
        architecture_errors = cross.validate_repair_request(
            stalled,
            repair_kind="architecture",
            cluster_scenarios=cluster,
            declared_changed_files=["flashDB_rust/src/lib.rs"],
            current_source_manifest=after,
        )
        self.assertEqual([], architecture_errors)

    def test_full_confirmation_detects_regression_against_best_known_matrix(self):
        cross = load_tool("c_cross_validate.py")
        with project_temp_directory() as directory:
            root = Path(directory)
            c_cross = root / "logs" / "trace" / "c-cross"
            project = root / "flashDB_rust"
            (project / "src").mkdir(parents=True)
            (project / "src" / "lib.rs").write_text("pub fn fixture() {}\n", encoding="utf-8")
            (c_cross / "snapshots").mkdir(parents=True)
            (c_cross / "checkpoints").mkdir(parents=True)
            best = {
                "attempt_id": "best-1",
                "score": [2, 0, 0, 0],
                "source_scope": "src/**",
            }
            (c_cross / "snapshots" / "best.json").write_text(json.dumps(best), encoding="utf-8")
            best_matrix = {
                "mode": "full",
                "scope": "all",
                "scenarios": [
                    {"scenario_id": "case-a", "rust_impl_c_test": "pass"},
                    {"scenario_id": "case-b", "rust_impl_c_test": "pass"},
                ],
            }
            (c_cross / "checkpoints" / "best-1.json").write_text(json.dumps(best_matrix), encoding="utf-8")
            previous_selected = {
                "mode": "full",
                "scope": "selected",
                "scenarios": [{"scenario_id": "case-b", "rust_impl_c_test": "fail"}],
            }
            current = {
                "execution_id": "confirm-2",
                "mode": "full",
                "scope": "all",
                "scenarios": [
                    {"scenario_id": "case-a", "rust_impl_c_test": "fail"},
                    {"scenario_id": "case-b", "rust_impl_c_test": "fail"},
                ],
            }
            attempt = cross.record_attempt(
                c_cross,
                previous_selected,
                current,
                attempt_kind="confirmation",
                trigger="fixture",
                changed_files=[],
                project_root=project,
                source_manifest=cross._source_manifest(project),
            )
            self.assertTrue(attempt["regression"])
            self.assertTrue(attempt["restore_best_available"])

    def test_cargo_capture_counts_real_test_repairs_without_global_budget(self):
        sys.path.insert(0, str(TOOLS))
        try:
            cargo = load_tool("cargo_capture.py")
        finally:
            sys.path.pop(0)
        report = load_tool("report_writer.py")
        with project_temp_directory() as directory:
            root = Path(directory)
            project = root / "flashDB_rust"
            out = root / "logs" / "trace"
            (project / "src").mkdir(parents=True)
            (project / "tests").mkdir(parents=True)
            out.mkdir(parents=True)
            source = project / "src" / "lib.rs"
            source.write_text("pub fn value() -> u8 { 0 }\n", encoding="utf-8")
            (project / "tests" / "fixture.rs").write_text("#[test]\nfn fixture() {}\n", encoding="utf-8")
            (project / "Cargo.toml").write_text("[package]\nname='fixture'\nversion='0.1.0'\n", encoding="utf-8")
            (out / "rust_test_mapping.json").write_text("{}\n", encoding="utf-8")
            attempts_path = out / "test-repair-attempts.jsonl"

            attempts, checkpoint = cargo.prepare_test_attempt(project, out)
            self.assertEqual([], attempts)
            self.assertEqual("checkpoint", checkpoint["kind"])
            self.assertEqual(report.current_test_input_manifest(root), checkpoint["source_manifest"])
            attempts_path.write_text(json.dumps(checkpoint) + "\n", encoding="utf-8")

            source.write_text("pub fn value() -> u8 { 1 }\n", encoding="utf-8")
            _, repair_one = cargo.prepare_test_attempt(project, out)
            self.assertEqual("repair", repair_one["kind"])
            self.assertEqual(1, repair_one["repair_attempts_recorded"])
            with attempts_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(repair_one) + "\n")

            source.write_text("pub fn value() -> u8 { 2 }\n", encoding="utf-8")
            _, repair_two = cargo.prepare_test_attempt(project, out)
            self.assertEqual(2, repair_two["repair_attempts_recorded"])
            with attempts_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(repair_two) + "\n")

            source.write_text("pub fn value() -> u8 { 3 }\n", encoding="utf-8")
            _, repair_three = cargo.prepare_test_attempt(project, out)
            self.assertEqual(3, repair_three["repair_attempts_recorded"])

    def test_cargo_capture_rejects_zero_or_unexecuted_mapped_tests(self):
        sys.path.insert(0, str(TOOLS))
        try:
            cargo = load_tool("cargo_capture.py")
        finally:
            sys.path.pop(0)
        with project_temp_directory() as directory:
            root = Path(directory)
            project = root / "flashDB_rust"
            out = root / "logs" / "trace"
            (project / "tests").mkdir(parents=True)
            out.mkdir(parents=True)
            mapping = {
                "scenarios": [{
                    "id": "dynamic-case",
                    "rust_file": "flashDB_rust/tests/dynamic.rs",
                    "rust_test": "rust_dynamic",
                }],
            }
            (out / "rust_test_mapping.json").write_text(json.dumps(mapping), encoding="utf-8")

            zero = cargo.analyze_test_execution(
                project,
                out,
                "running 0 tests\ntest result: ok. 0 passed; 0 failed\n",
                0,
            )
            self.assertEqual("fail", zero["status"])
            self.assertIn("rust_dynamic", zero["missing_expected_tests"])
            self.assertIn("flashDB_rust/tests contains no Rust test files", zero["reason"])

            (project / "tests" / "dynamic.rs").write_text(
                "#[test]\nfn rust_dynamic() { assert!(true); }\n",
                encoding="utf-8",
            )
            not_executed = cargo.analyze_test_execution(
                project,
                out,
                "running 1 test\ntest unrelated ... ok\n",
                0,
            )
            self.assertEqual("fail", not_executed["status"])
            self.assertEqual(["rust_dynamic"], not_executed["missing_expected_tests"])

            ignored = cargo.analyze_test_execution(
                project,
                out,
                "running 1 test\ntest rust_dynamic ... ignored\n",
                0,
            )
            self.assertEqual("fail", ignored["status"])
            self.assertEqual(["rust_dynamic"], ignored["ignored_expected_tests"])

            executed = cargo.analyze_test_execution(
                project,
                out,
                "running 1 test\ntest suite::rust_dynamic ... ok\n",
                0,
            )
            self.assertEqual("pass", executed["status"])
            self.assertEqual(1, executed["matched_expected_count"])

    def test_placeholder_rejects_empty_test_directory_and_mapping(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            tests = root / "flashDB_rust" / "tests"
            mapping = root / "logs" / "trace" / "rust_test_mapping.json"
            tests.mkdir(parents=True)
            mapping.parent.mkdir(parents=True)
            mapping.write_text(json.dumps({"scenarios": []}), encoding="utf-8")
            report = PLACEHOLDER.analyze_placeholders(root, tests, mapping)
            self.assertEqual("fail", report["status"])
            self.assertEqual(
                {"empty_mapping", "empty_test_directory"},
                {issue["code"] for issue in report["issues"]},
            )

    def test_cargo_requires_fresh_placeholder_terminal_state(self):
        sys.path.insert(0, str(TOOLS))
        try:
            cargo = load_tool("cargo_capture.py")
            with project_temp_directory() as directory:
                root = Path(directory)
                project = root / "flashDB_rust"
                tests = project / "tests"
                out = root / "logs" / "trace"
                tests.mkdir(parents=True)
                out.mkdir(parents=True)
                mapping = out / "rust_test_mapping.json"
                mapping.write_text(json.dumps({
                    "scenarios": [{
                        "id": "dynamic-case",
                        "rust_file": "flashDB_rust/tests/dynamic.rs",
                        "rust_test": "rust_dynamic",
                    }],
                }), encoding="utf-8")

                missing = PLACEHOLDER.analyze_placeholders(root, tests, mapping)
                (out / "test-placeholder-check.json").write_text(json.dumps(missing), encoding="utf-8")
                convergence = cargo.record_placeholder_attempt(project, out, missing)
                self.assertEqual("repair_required", convergence["status"])
                precondition = cargo.validate_placeholder_precondition(project, out)
                self.assertEqual(["dynamic-case"], precondition["failed_scenario_ids"])

                (tests / "dynamic.rs").write_text(
                    "#[test]\nfn rust_dynamic() { let actual = 1; assert_eq!(actual, 1); }\n",
                    encoding="utf-8",
                )
                implemented = PLACEHOLDER.analyze_placeholders(root, tests, mapping)
                (out / "test-placeholder-check.json").write_text(json.dumps(implemented), encoding="utf-8")
                convergence = cargo.record_placeholder_attempt(project, out, implemented)
                self.assertEqual("ready_for_cargo", convergence["status"])
                precondition = cargo.validate_placeholder_precondition(project, out)
                self.assertEqual("pass", precondition["status"])
                self.assertEqual(["dynamic-case"], precondition["ready_scenario_ids"])
        finally:
            sys.path.pop(0)

    @unittest.skipUnless(shutil.which("cargo"), "cargo is required for execution-evidence integration")
    def test_cargo_capture_matches_real_mapped_test_execution(self):
        sys.path.insert(0, str(TOOLS))
        try:
            cargo = load_tool("cargo_capture.py")
            report_writer = load_tool("report_writer.py")
            with project_temp_directory() as directory:
                root = Path(directory)
                project = root / "flashDB_rust"
                out = root / "logs" / "trace"
                (project / "src").mkdir(parents=True)
                (project / "tests").mkdir(parents=True)
                out.mkdir(parents=True)
                (project / "Cargo.toml").write_text(
                    "[package]\nname = \"fixture\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
                    encoding="utf-8",
                )
                (project / "src" / "lib.rs").write_text("pub fn value() -> u8 { 1 }\n", encoding="utf-8")
                (project / "tests" / "dynamic.rs").write_text(
                    "#[test]\nfn rust_dynamic() {\n    let actual = 1;\n    assert_eq!(actual, 1);\n}\n",
                    encoding="utf-8",
                )
                mapping = out / "rust_test_mapping.json"
                mapping.write_text(json.dumps({
                    "scenarios": [{
                        "id": "dynamic-case",
                        "rust_file": "flashDB_rust/tests/dynamic.rs",
                        "rust_test": "rust_dynamic",
                    }],
                }), encoding="utf-8")
                placeholder = PLACEHOLDER.analyze_placeholders(root, project / "tests", mapping)
                self.assertEqual("pass", placeholder["status"])
                (out / "test-placeholder-check.json").write_text(json.dumps(placeholder), encoding="utf-8")
                cargo.record_placeholder_attempt(project, out, placeholder)

                result = cargo.capture(project, out)
                self.assertEqual("pass", result["test_status"])
                self.assertEqual(1, result["test_execution"]["expected_count"])
                self.assertEqual(1, result["test_execution"]["matched_expected_count"])
                attempts = report_writer.load_jsonl(out / "test-repair-attempts.jsonl")
                self.assertTrue(report_writer.test_repair_evidence(root, result, attempts)["valid"])
        finally:
            sys.path.pop(0)

    def test_restore_best_known_replaces_regressed_source_tree(self):
        cross = load_tool("c_cross_validate.py")
        with project_temp_directory() as directory:
            root = Path(directory)
            project = root / "flashDB_rust"
            c_cross = root / "logs" / "trace" / "c-cross"
            snapshot = c_cross / "snapshots" / "best-1"
            (project / "src").mkdir(parents=True)
            (snapshot / "files" / "src").mkdir(parents=True)
            (c_cross / "snapshots").mkdir(parents=True, exist_ok=True)
            current = project / "src" / "lib.rs"
            current.write_text("regressed\n", encoding="utf-8")
            (project / "src" / "extra.rs").write_text("remove me\n", encoding="utf-8")
            saved = snapshot / "files" / "src" / "lib.rs"
            saved.write_text("best known\n", encoding="utf-8")
            (snapshot / "manifest.json").write_text(json.dumps({
                "files": [{"path": "src/lib.rs", "sha256": cross._sha256(saved)}],
            }), encoding="utf-8")
            (c_cross / "snapshots" / "best.json").write_text(json.dumps({
                "attempt_id": "best-1",
                "source_scope": "src/**",
            }), encoding="utf-8")
            evidence = cross.restore_best_known(c_cross, project)
            self.assertEqual("best known\n", current.read_text(encoding="utf-8"))
            self.assertFalse((project / "src" / "extra.rs").exists())
            self.assertEqual("run_full_confirmation", evidence["next_action"])

    def test_gate_rejects_repair_required_convergence(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            cross_dir = root / "logs" / "trace" / "c-cross"
            cross_dir.mkdir(parents=True)
            (root / "logs" / "trace" / "validation-matrix.json").write_text(
                json.dumps({
                    "execution_id": "attempt-1",
                    "convergence": {
                        "status": "repair_required",
                        "terminal": False,
                        "next_action": "repair_next_queued_task",
                        "repair_attempts_recorded": 0,
                        "work_queue": {
                            "total": 1,
                            "counts": {state: (1 if state == "queued" else 0) for state in sorted(QUEUE.VALID_STATES)},
                            "all_pass": False,
                            "queue_exhausted": False,
                            "pending_task_ids": ["dynamic-case"],
                            "sweep": 1,
                            "last_full_confirmation_id": None,
                        },
                    },
                }), encoding="utf-8"
            )
            (cross_dir / "attempts.jsonl").write_text(
                json.dumps({"attempt_id": "attempt-1", "kind": "checkpoint"}) + "\n",
                encoding="utf-8",
            )
            queue_summary = {
                "total": 1,
                "counts": {state: (1 if state == "queued" else 0) for state in sorted(QUEUE.VALID_STATES)},
                "all_pass": False,
                "queue_exhausted": False,
                "pending_task_ids": ["dynamic-case"],
                "sweep": 1,
                "last_full_confirmation_id": None,
            }
            (root / "logs" / "trace" / "repair-work-queue.json").write_text(json.dumps({
                "schema_version": 1,
                "phases": {"c_cross": {"tasks": {}, "summary": queue_summary}},
            }), encoding="utf-8")
            (cross_dir / "failure-summary.json").write_text(json.dumps({
                "status": "repair_required",
                "terminal": False,
                "next_action": "repair_next_queued_task",
                "execution_id": "attempt-1",
                "repair_attempts_recorded": 0,
                "work_queue": queue_summary,
            }), encoding="utf-8")
            summary, errors = GATE.check_convergence(root)
            self.assertEqual("repair_required", summary["status"])
            self.assertEqual([], errors)

    def test_gate_exposes_only_result_stages(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            (root / "result" / "issues").mkdir(parents=True)
            (root / "logs" / "trace").mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            self.assertTrue(callable(GATE.check_analyze))
            self.assertTrue(callable(GATE.check_implement))
            self.assertTrue(callable(GATE.check_verify_and_repair))
            self.assertTrue(callable(GATE.check_test_and_report))
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
            self.assertEqual("fail", consistency["scenarios"][0]["status"])

    def test_test_and_report_contract_orders_real_repair_evidence(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "agents" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        section = instruction.split("## 4. TEST_AND_REPORT", 1)[1]
        migrate = section.index("migrate_tests.py")
        test_migrator = section.index("queued scenario")
        placeholder = section.index("placeholder_check.py")
        cargo = section.index("cargo_capture.py")
        reviewer = section.index("semantic_review_merge.py")
        consistency = section.index("test_consistency_check.py")
        stage_gate = section.index("gate.py --stage TEST_AND_REPORT")
        unsafe = section.index("unsafe_ratio.py")
        report = section.index("report_writer.py")
        self.assertLess(migrate, test_migrator)
        self.assertLess(test_migrator, placeholder)
        self.assertLess(placeholder, cargo)
        self.assertLess(cargo, reviewer)
        self.assertLess(reviewer, consistency)
        self.assertLess(consistency, stage_gate)
        self.assertLess(stage_gate, unsafe)
        self.assertLess(unsafe, report)
        self.assertIn("一个 reviewer case 失败不能抹掉其他 current pass", section)
        self.assertIn("不存在全局两轮 repair 预算", section)
        self.assertIn("测试或经证据授权的生产源码发生修改", section)
        self.assertIn("queued scenario/最小 helper cluster", orchestrator)
        self.assertNotIn("cargo_capture.py --project flashDB_rust --out logs/trace || true", section)

    def test_placeholder_uses_source_evidence_not_mapping_status(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            semantic_fixture(root)
            mapping_path = root / "logs" / "trace" / "rust_test_mapping.json"
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            mapping["scenarios"][0]["implementation_status"] = "pending"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            report = PLACEHOLDER.analyze_placeholders(
                root,
                root / "flashDB_rust" / "tests",
                mapping_path,
            )
            self.assertEqual("pass", report["status"])
            self.assertNotIn("implementation_pending", {item["code"] for item in report["issues"]})

    def test_stale_semantic_review_short_circuits_derived_mismatches(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            semantic_fixture(root, review_status="fail")
            test_file = root / "flashDB_rust" / "tests" / "dynamic.rs"
            test_file.write_text(test_file.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
            consistency = CONSISTENCY.analyze_consistency(root)
            self.assertEqual("fail", consistency["status"])
            self.assertEqual(1, consistency["issue_count"])
            self.assertEqual("stale_semantic_review", consistency["issues"][0]["code"])
            self.assertEqual("stale", consistency["semantic_review"]["status"])
            self.assertEqual(0, consistency["passed_scenarios"])
            self.assertEqual([], consistency["logic_mismatch"])

    def test_triage_extracts_all_assertion_failures_without_guessing_oracle(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            trace = root / "logs" / "trace"
            trace.mkdir(parents=True)
            (trace / "rust_test_mapping.json").write_text(json.dumps({
                "scenarios": [
                    {"id": "case-a", "rust_test": "rust_case_a", "rust_file": "flashDB_rust/tests/a.rs", "source_file": "tests/a.c", "required_c_tests": ["test_a"]},
                    {"id": "case-b", "rust_test": "rust_case_b", "rust_file": "flashDB_rust/tests/b.rs", "source_file": "tests/b.c", "required_c_tests": ["test_b"]},
                ],
            }), encoding="utf-8")
            (trace / "cargo-test.log").write_text(
                "---- suite::rust_case_a stdout ----\n"
                "thread 'suite::rust_case_a' panicked at tests/a.rs:10:5:\n"
                "assertion failed: expected_a\n\n"
                "---- suite::rust_case_b stdout ----\n"
                "thread 'suite::rust_case_b' panicked at tests/b.rs:20:5:\n"
                "assertion `left == right` failed\n  left: 4\n right: 5\n\n"
                "failures:\n    suite::rust_case_a\n    suite::rust_case_b\n",
                encoding="utf-8",
            )
            records = TRIAGE.build_records(root, trace)
            self.assertEqual(["rust_case_a", "rust_case_b"], [item["failed_test"] for item in records])
            self.assertEqual(["case-a", "case-b"], [item["scenario_id"] for item in records])
            self.assertTrue(all(item["classification"] == "insufficient_evidence" for item in records))
            self.assertTrue(all(not item["allow_src_edit"] for item in records))
            self.assertNotIn("test_oracle_suspect", {item["classification"] for item in records})

    def test_triage_authorizes_only_evidenced_production_source_location(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            trace = root / "logs" / "trace"
            trace.mkdir(parents=True)
            (trace / "cargo-test.log").write_text(
                "---- suite::rust_case stdout ----\n"
                "thread 'suite::rust_case' panicked at flashDB_rust/src/storage.rs:42:9:\n"
                "storage invariant failed\n\n"
                "failures:\n    suite::rust_case\n",
                encoding="utf-8",
            )
            record = TRIAGE.build_records(root, trace)[0]
            self.assertEqual("rust_impl_suspect", record["classification"])
            self.assertTrue(record["allow_src_edit"])
            self.assertEqual(["flashDB_rust/src/storage.rs"], record["allowed_edit_scope"])

    def test_per_scenario_review_failure_does_not_erase_other_passes(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            trace = root / "logs" / "trace"
            c_source = root / "c_input" / "tests" / "fixture.c"
            rust_test = root / "flashDB_rust" / "tests" / "fixture.rs"
            c_source.parent.mkdir(parents=True)
            rust_test.parent.mkdir(parents=True)
            trace.mkdir(parents=True)
            c_source.write_text(
                "void test_a(void) {\n  assert(1);\n}\nvoid test_b(void) {\n  assert(1);\n}\n",
                encoding="utf-8",
            )
            rust_test.write_text(
                "#[test]\nfn rust_a() { assert_eq!(1, 1); }\n#[test]\nfn rust_b() { assert_eq!(1, 1); }\n",
                encoding="utf-8",
            )
            (trace / "input_manifest.json").write_text(json.dumps({"source_root": str(root / "c_input")}), encoding="utf-8")
            cases = [
                {"scenario_id": "case-a", "case_id": "1", "source_file": "tests/fixture.c", "required_c_tests": ["test_a"]},
                {"scenario_id": "case-b", "case_id": "2", "source_file": "tests/fixture.c", "required_c_tests": ["test_b"]},
            ]
            (trace / "c_test_model.json").write_text(json.dumps({"scorer_standard_cases": cases}), encoding="utf-8")
            (trace / "rust_api_design.json").write_text(json.dumps({"crate_name": "fixture", "modules": []}), encoding="utf-8")
            mapping = {
                "total_scenarios": 2,
                "scenarios": [
                    {"id": "case-a", "source_file": "tests/fixture.c", "required_c_tests": ["test_a"], "rust_file": "flashDB_rust/tests/fixture.rs", "rust_test": "rust_a"},
                    {"id": "case-b", "source_file": "tests/fixture.c", "required_c_tests": ["test_b"], "rust_file": "flashDB_rust/tests/fixture.rs", "rust_test": "rust_b"},
                ],
            }
            (trace / "rust_test_mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
            fingerprint = CONSISTENCY.build_input_fingerprint(root)
            all_pass = {name: "pass" for name in CONSISTENCY.DIMENSIONS}
            assertion_fail = {**all_pass, "assertion": "fail"}
            review = {
                "schema_version": 1,
                "status": "fail",
                "reviewer_mode": "primary_readonly_fallback",
                "input_fingerprint": fingerprint,
                "total_c_scenarios": 2,
                "reviewed_scenarios": 2,
                "c_only": [],
                "rust_only": [],
                "logic_mismatch": [{"scenario_id": "case-b"}],
                "cases": [
                    {
                        "scenario_id": "case-a", "c_function": "test_a", "rust_test": "rust_a", "status": "pass", "dimensions": all_pass,
                        "c_evidence": [{"path": "c_input/tests/fixture.c", "function": "test_a", "line_start": 1, "line_end": 3}],
                        "rust_evidence": [{"path": "flashDB_rust/tests/fixture.rs", "function": "rust_a", "line_start": 1, "line_end": 2}],
                        "differences": [],
                    },
                    {
                        "scenario_id": "case-b", "c_function": "test_b", "rust_test": "rust_b", "status": "fail", "dimensions": assertion_fail,
                        "c_evidence": [{"path": "c_input/tests/fixture.c", "function": "test_b", "line_start": 4, "line_end": 6}],
                        "rust_evidence": [{"path": "flashDB_rust/tests/fixture.rs", "function": "rust_b", "line_start": 3, "line_end": 4}],
                        "differences": ["assertion semantics differ"],
                    },
                ],
            }
            (trace / "test-semantic-review.json").write_text(json.dumps(review), encoding="utf-8")
            report = CONSISTENCY.analyze_consistency(root)
            statuses = {row["scenario_id"]: row["status"] for row in report["scenarios"]}
            self.assertEqual("pass", statuses["case-a"])
            self.assertEqual("fail", statuses["case-b"])
            self.assertEqual(1, report["passed_scenarios"])

    def test_repair_queue_round_robin_exhausts_only_the_hard_task(self):
        with project_temp_directory() as directory:
            path = Path(directory) / "repair-work-queue.json"
            QUEUE.sync_tasks(path, "tests", ["hard", "easy"])
            QUEUE.record_attempt(path, "tests", ["hard"], attempt_id="hard-1")
            phase = QUEUE.record_attempt(path, "tests", ["hard"], attempt_id="hard-2")
            self.assertEqual("deferred_no_progress", phase["tasks"]["hard"]["state"])
            phase = QUEUE.record_attempt(path, "tests", ["easy"], attempt_id="easy-1", passed_ids=["easy"])
            self.assertEqual(2, phase["sweep"])
            self.assertEqual("queued", phase["tasks"]["hard"]["state"])
            QUEUE.record_attempt(path, "tests", ["hard"], attempt_id="hard-3")
            QUEUE.record_attempt(path, "tests", ["hard"], attempt_id="hard-4")
            phase = QUEUE.sync_tasks(path, "tests", ["hard", "easy"], passed_ids=["easy"], full_confirmation_id="confirm-1")
            decision = QUEUE.convergence(phase, current_full_confirmation_id="confirm-1")
            self.assertEqual("failed_final", decision["status"])
            self.assertEqual("confirmed_pass", phase["tasks"]["easy"]["state"])
            self.assertEqual("exhausted", phase["tasks"]["hard"]["state"])

    def test_submission_snapshot_restores_best_without_git(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            project = root / "flashDB_rust"
            trace = root / "logs" / "trace"
            (project / "src").mkdir(parents=True)
            (project / "tests").mkdir(parents=True)
            trace.mkdir(parents=True)
            (project / "Cargo.toml").write_text("[package]\nname='fixture'\nversion='0.1.0'\n", encoding="utf-8")
            source = project / "src" / "lib.rs"
            source.write_text("pub fn value() -> u8 { 1 }\n", encoding="utf-8")
            (project / "tests" / "fixture.rs").write_text("#[test]\nfn fixture() { assert_eq!(1, 1); }\n", encoding="utf-8")
            (trace / "cargo-results.json").write_text(json.dumps({"build_status": "pass"}), encoding="utf-8")
            captured = SNAPSHOT.capture(root, kind="baseline")
            source.write_text("broken\n", encoding="utf-8")
            (project / "tests" / "extra.rs").write_text("remove me\n", encoding="utf-8")
            restored = SNAPSHOT.restore_best(root, reason="contest_deadline")
            self.assertEqual(captured["snapshot_id"], restored["snapshot_id"])
            self.assertEqual("pub fn value() -> u8 { 1 }\n", source.read_text(encoding="utf-8"))
            self.assertFalse((project / "tests" / "extra.rs").exists())
            self.assertTrue(SNAPSHOT.verify_current(root)["matches"])

    def test_short_watchdog_freezes_and_restores_best_submission(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            project = root / "flashDB_rust"
            trace = root / "logs" / "trace"
            (root / "result" / "issues").mkdir(parents=True)
            (project / "src").mkdir(parents=True)
            trace.mkdir(parents=True)
            (project / "Cargo.toml").write_text("[package]\nname='fixture'\nversion='0.1.0'\n", encoding="utf-8")
            source = project / "src" / "lib.rs"
            source.write_text("pub fn value() -> u8 { 1 }\n", encoding="utf-8")
            (trace / "cargo-results.json").write_text(json.dumps({"build_status": "pass"}), encoding="utf-8")
            best = SNAPSHOT.capture(root, kind="baseline")
            source.write_text("pub fn value() -> u8 { 0 }\n", encoding="utf-8")
            WATCHDOG.start(root, freeze_after_seconds=0.2)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                state = WATCHDOG.contest_guard.contest_state(root)
                if state["status"] == "submission_frozen":
                    break
                time.sleep(0.05)
            else:
                self.fail("short watchdog did not freeze the submission")
            self.assertEqual("pub fn value() -> u8 { 1 }\n", source.read_text(encoding="utf-8"))
            frozen = json.loads((trace / "deadline-final.json").read_text(encoding="utf-8"))
            self.assertEqual(best["snapshot_id"], frozen["snapshot_id"])
            self.assertEqual([], GATE.check_final(root))

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
