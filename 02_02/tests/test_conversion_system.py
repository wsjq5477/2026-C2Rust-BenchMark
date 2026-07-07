import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def load_tool(name: str):
    path = PROJECT / "work" / "tools" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrameworkCheckpointTests(unittest.TestCase):
    def test_design_doc_layout_exists_and_legacy_layout_is_absent(self):
        required_files = [
            PROJECT / "INSTRUCTION.md",
            PROJECT / "work" / "agents" / "flashdb-orchestrator.md",
            PROJECT / "work" / "skills" / "test-migrator.md",
            PROJECT / "work" / "skills" / "test-triage.md",
            PROJECT / "work" / "skills" / "repairer.md",
            PROJECT / "work" / "skills" / "flashdb-migration" / "SKILL.md",
            PROJECT / "work" / "skills" / "flashdb-test-migration" / "SKILL.md",
            PROJECT / "work" / "skills" / "rust-compile-repair" / "SKILL.md",
            PROJECT / "work" / "skills" / "flashdb-report" / "SKILL.md",
            PROJECT / "work" / "knowledge" / "contest-rules.md",
            PROJECT / "work" / "knowledge" / "flashdb-test-map.md",
            PROJECT / "work" / "knowledge" / "flashdb-rust-architecture.md",
            PROJECT / "work" / "tools" / "gate.py",
            PROJECT / "work" / "tools" / "scan_c_project.py",
            PROJECT / "work" / "tools" / "build_c_model.py",
            PROJECT / "work" / "tools" / "design_rust_api.py",
            PROJECT / "work" / "tools" / "generate_rust_scaffold.py",
            PROJECT / "work" / "tools" / "c_cross_validate.py",
            PROJECT / "work" / "tools" / "migrate_tests.py",
            PROJECT / "work" / "tools" / "cargo_capture.py",
            PROJECT / "work" / "tools" / "test_failure_triage.py",
            PROJECT / "work" / "tools" / "test_consistency_check.py",
            PROJECT / "work" / "tools" / "unsafe_ratio.py",
            PROJECT / "work" / "tools" / "report_writer.py",
            PROJECT / "result" / "output.md",
            PROJECT / "result" / "issues" / "00-summary.md",
            PROJECT / "logs" / "interaction.md",
        ]
        missing = [str(path.relative_to(PROJECT)) for path in required_files if not path.is_file()]
        self.assertEqual([], missing)

        forbidden_paths = [
            PROJECT / "opencode.json",
            PROJECT / "flashDB_rust",
            PROJECT / "work" / "agents" / "test-migrator.md",
            PROJECT / "work" / "agents" / "test-triage.md",
            PROJECT / "work" / "agents" / "repairer.md",
            PROJECT / "work" / "skills" / "c-to-rust",
            PROJECT / "work" / "skills" / "dependency-analyzer.md",
            PROJECT / "work" / "skills" / "rust-translator.md",
            PROJECT / "work" / "skills" / "compile-healer.md",
            PROJECT / "work" / "skills" / "semantic-verifier.md",
        ]
        present = [str(path.relative_to(PROJECT)) for path in forbidden_paths if path.exists()]
        self.assertEqual([], present)

    def test_native_opencode_agent_entrypoint_is_documented(self):
        text = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        required_fragments = [
            "@flashdb-orchestrator",
            ".opencode/agents/flashdb-orchestrator.md",
            ".opencode/skills",
            "work/agents/flashdb-orchestrator.md",
            "work/skills/{subagent}.md",
            "work/skills/test-migrator.md",
            "work/skills/test-triage.md",
            "work/skills/repairer.md",
            "work 目录仍为权威源",
            "opencode 不能在会话中把当前 primary agent 自切换为另一个 primary agent",
            "如果启动前已经选择 flashdb-orchestrator",
            "默认 Build agent 按普通 Markdown fallback 执行也满足本检查点",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, text)
        self.assertNotIn("必须立即使用 `@flashdb-orchestrator`", text)
        self.assertNotIn("work/agents/test-migrator.md", text)
        self.assertNotIn("work/agents/test-triage.md", text)
        self.assertNotIn("work/agents/repairer.md", text)

    def test_agent_and_subagent_markdown_have_opencode_frontmatter(self):
        expected = {
            PROJECT / "work" / "agents" / "flashdb-orchestrator.md": ("mode: primary", "description:"),
            PROJECT / "work" / "skills" / "test-migrator.md": ("mode: subagent", "description:"),
            PROJECT / "work" / "skills" / "test-triage.md": ("mode: subagent", "description:"),
            PROJECT / "work" / "skills" / "repairer.md": ("mode: subagent", "description:"),
        }
        for path, fragments in expected.items():
            filename = str(path.relative_to(PROJECT))
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), filename)
            self.assertIn("\n---\n", text, filename)
            for fragment in fragments:
                self.assertIn(fragment, text, filename)

    def test_local_opencode_mirror_matches_work_sources_when_present(self):
        mirror = PROJECT / ".opencode"
        if not mirror.exists():
            self.skipTest(".opencode mirror is created outside the checked-in workbench")

        source_agent = PROJECT / "work" / "agents" / "flashdb-orchestrator.md"
        mirror_agent = mirror / "agents" / "flashdb-orchestrator.md"
        self.assertTrue(mirror_agent.is_file())
        self.assertEqual(source_agent.read_text(encoding="utf-8"), mirror_agent.read_text(encoding="utf-8"))

        for filename in ["test-migrator.md", "test-triage.md", "repairer.md"]:
            source_subagent = PROJECT / "work" / "skills" / filename
            mirror_subagent = mirror / "skills" / filename
            self.assertTrue(mirror_subagent.is_file())
            self.assertEqual(source_subagent.read_text(encoding="utf-8"), mirror_subagent.read_text(encoding="utf-8"))

        source_skill = PROJECT / "work" / "skills" / "flashdb-migration" / "SKILL.md"
        mirror_skill = mirror / "skills" / "flashdb-migration" / "SKILL.md"
        self.assertTrue(mirror_skill.is_file())
        self.assertEqual(source_skill.read_text(encoding="utf-8"), mirror_skill.read_text(encoding="utf-8"))

    def test_instruction_bootstraps_orchestrator_and_stops_at_checkpoint(self):
        text = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        required_fragments = [
            "/app/code/judge-assets/02_02_c_to_rust/code/FlashDB",
            "work/agents/flashdb-orchestrator.md",
            "BOOTSTRAP",
            "INIT_WORKSPACE",
            "READ_C_PROJECT",
            "BUILD_C_MODEL",
            "DESIGN_RUST_API",
            "GENERATE_RUST_SCAFFOLD",
            "REWRITE_CORE_MODULES",
            "VERIFY_RUST_WITH_C_TESTS",
            "MIGRATE_TESTS",
            "BUILD_TEST_REPAIR",
            "REPORT_AND_VERIFY",
            "workflow_state.json",
            "input_manifest.json",
            "c_project_model.json",
            "c_api_model.json",
            "c_test_model.json",
            "rust_api_design.json",
            "validation-matrix.json",
            "rust_test_mapping.json",
            "final-verification.md",
            "flashDB_rust",
            "不得修改平台",
            "不得预置",
            "python3 work/tools/scan_c_project.py",
            "python3 work/tools/build_c_model.py",
            "python3 work/tools/design_rust_api.py",
            "python3 work/tools/generate_rust_scaffold.py",
            "python3 work/tools/c_cross_validate.py",
            "python3 work/tools/migrate_tests.py",
            "python3 work/tools/cargo_capture.py",
            "python3 work/tools/test_failure_triage.py",
            "python3 work/tools/test_consistency_check.py",
            "python3 work/tools/unsafe_ratio.py",
            "python3 work/tools/report_writer.py",
            "python3 work/tools/gate.py --stage READ_C_PROJECT",
            "python3 work/tools/gate.py --stage BUILD_C_MODEL",
            "python3 work/tools/gate.py --stage DESIGN_RUST_API",
            "python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD",
            "python3 work/tools/gate.py --stage REWRITE_CORE_MODULES",
            "python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS",
            "python3 work/tools/gate.py --stage MIGRATE_TESTS",
            "python3 work/tools/gate.py --stage BUILD_TEST_REPAIR",
            "python3 work/tools/gate.py --stage REPORT_AND_VERIFY",
            "04-design-rust-api.md",
            "09-report-and-verify.md",
            "中文",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, text)
        self.assertNotIn("work/skills/c-to-rust/SKILL.md", text)
        self.assertNotIn("opencode 已使用 `@flashdb-orchestrator` 接管", text)

    def test_orchestrator_declares_exact_first_checkpoint_contract(self):
        text = (PROJECT / "work" / "agents" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        required_fragments = [
            "BOOTSTRAP",
            "INIT_WORKSPACE",
            "READ_C_PROJECT",
            "BUILD_C_MODEL",
            "DESIGN_RUST_API",
            "GENERATE_RUST_SCAFFOLD",
            "REWRITE_CORE_MODULES",
            "VERIFY_RUST_WITH_C_TESTS",
            "MIGRATE_TESTS",
            "BUILD_TEST_REPAIR",
            "REPORT_AND_VERIFY",
            "logs/trace/workflow_state.json",
            "logs/trace/01-init-workspace.md",
            "logs/trace/input_manifest.json",
            "logs/trace/02-read-c-project.md",
            "logs/trace/c_project_model.json",
            "logs/trace/c_api_model.json",
            "logs/trace/c_test_model.json",
            "logs/trace/03-build-c-model.md",
            "logs/trace/rust_api_design.json",
            "logs/trace/04-design-rust-api.md",
            "logs/trace/05-generate-rust-scaffold.md",
            "logs/trace/06-rewrite-core-modules.md",
            "logs/trace/06-5-verify-rust-with-c-tests.md",
            "logs/trace/validation-matrix.json",
            "logs/trace/rust_test_mapping.json",
            "logs/trace/07-migrate-tests.md",
            "logs/trace/cargo-build.log",
            "logs/trace/cargo-test.log",
            "logs/trace/unsafe-ratio.json",
            "logs/trace/final-verification.md",
            "logs/trace/09-report-and-verify.md",
            "python3 work/tools/scan_c_project.py",
            "python3 work/tools/build_c_model.py",
            "python3 work/tools/design_rust_api.py",
            "python3 work/tools/generate_rust_scaffold.py",
            "python3 work/tools/c_cross_validate.py",
            "python3 work/tools/migrate_tests.py",
            "python3 work/tools/cargo_capture.py",
            "python3 work/tools/test_failure_triage.py",
            "python3 work/tools/test_consistency_check.py",
            "python3 work/tools/unsafe_ratio.py",
            "python3 work/tools/report_writer.py",
            "python3 work/tools/gate.py --stage INIT_WORKSPACE",
            "python3 work/tools/gate.py --stage READ_C_PROJECT",
            "python3 work/tools/gate.py --stage BUILD_C_MODEL",
            "python3 work/tools/gate.py --stage DESIGN_RUST_API",
            "python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD",
            "python3 work/tools/gate.py --stage REWRITE_CORE_MODULES",
            "python3 work/tools/gate.py --stage VERIFY_RUST_WITH_C_TESTS",
            "python3 work/tools/gate.py --stage MIGRATE_TESTS",
            "python3 work/tools/gate.py --stage BUILD_TEST_REPAIR",
            "python3 work/tools/gate.py --stage REPORT_AND_VERIFY",
            "停止",
            "STATUS: SUCCESS",
            "中文",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, text)

    def test_project_local_skills_have_valid_frontmatter_and_clear_scope(self):
        expected = ["flashdb-migration", "flashdb-test-migration", "rust-compile-repair", "flashdb-report"]
        for skill_name in expected:
            path = PROJECT / "work" / "skills" / skill_name / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            self.assertIn(f"name: {skill_name}", text)
            self.assertIn("description:", text)
            self.assertNotIn("TODO", text)
            self.assertNotIn("TBD", text)
        migration_skill = (PROJECT / "work" / "skills" / "flashdb-migration" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("BUILD_C_MODEL", migration_skill)
        self.assertIn("DESIGN_RUST_API", migration_skill)
        self.assertIn("c_project_model.json", migration_skill)
        self.assertIn("rust_api_design.json", migration_skill)
        self.assertIn("不做 Clang AST", migration_skill)
        self.assertIn("不做宏展开", migration_skill)

    def test_gate_init_workspace_rejects_missing_state_and_accepts_valid_state(self):
        gate = PROJECT / "work" / "tools" / "gate.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "result" / "issues").mkdir(parents=True)
            (root / "logs" / "trace").mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")

            missing_state = subprocess.run(
                [sys.executable, str(gate), "--stage", "INIT_WORKSPACE", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertNotEqual(0, missing_state.returncode)
            self.assertIn("workflow_state.json", missing_state.stdout)

            state = {
                "current_stage": "INIT_WORKSPACE",
                "completed_stages": ["BOOTSTRAP", "INIT_WORKSPACE"],
                "checkpoint": "INIT_WORKSPACE",
                "rust_project_path": "flashDB_rust",
                "input_path_candidates": [
                    "/app/code/judge-assets/02_02_c_to_rust/code/FlashDB",
                    "judge-assets/code/FlashDB",
                    "../judge-assets/code/FlashDB",
                ],
                "build_status": "not_started",
                "test_status": "not_started",
                "unsafe_ratio": None,
                "repair_rounds": 0,
                "blocked_issues": [],
            }
            (root / "logs" / "trace" / "workflow_state.json").write_text(
                json.dumps(state, indent=2),
                encoding="utf-8",
            )
            (root / "logs" / "trace" / "01-init-workspace.md").write_text(
                "# INIT_WORKSPACE\n\n- workspace initialized\n",
                encoding="utf-8",
            )
            passed = subprocess.run(
                [sys.executable, str(gate), "--stage", "INIT_WORKSPACE", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, passed.returncode, passed.stdout)
            self.assertIn("INIT_WORKSPACE: PASS", passed.stdout)

    def test_init_workspace_documents_regenerated_outputs_and_empty_interaction_log(self):
        instruction = (PROJECT / "INSTRUCTION.md").read_text(encoding="utf-8")
        orchestrator = (PROJECT / "work" / "agents" / "flashdb-orchestrator.md").read_text(encoding="utf-8")
        for text in [instruction, orchestrator]:
            self.assertIn("删除旧", text)
            self.assertIn("重新创建", text)
            self.assertIn("只生成空文件", text)
            self.assertIn("logs/interaction.md", text)
            self.assertIn("不得写入标题、模板、阶段记录或自动执行内容", text)

    def test_scan_c_project_finds_flashdb_src_and_tests(self):
        scanner = load_tool("scan_c_project.py")
        source = PROJECT.parent / "judge-assets" / "code" / "FlashDB"
        manifest = scanner.scan_project(source)

        self.assertEqual(str(source.resolve()), manifest["source_root"])
        self.assertEqual("src", manifest["src_dir"])
        self.assertEqual("tests", manifest["tests_dir"])
        self.assertIn("src/fdb.c", manifest["core_sources"])
        self.assertIn("src/fdb_kvdb.c", manifest["core_sources"])
        self.assertIn("src/fdb_tsdb.c", manifest["core_sources"])
        self.assertTrue(any(path.startswith("tests/") and path.endswith(".c") for path in manifest["test_sources"]))
        self.assertGreaterEqual(manifest["counts"]["core_sources"], 5)
        self.assertGreaterEqual(manifest["counts"]["test_sources"], 1)
        self.assertIn("tests/Makefile", manifest["build_files"])

    def test_scan_c_project_cli_writes_manifest(self):
        source = PROJECT.parent / "judge-assets" / "code" / "FlashDB"
        scanner = PROJECT / "work" / "tools" / "scan_c_project.py"
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "input_manifest.json"
            completed = subprocess.run(
                [sys.executable, str(scanner), "--source", str(source), "--output", str(output)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(str(source.resolve()), manifest["source_root"])
            self.assertIn("READ_C_PROJECT: SCANNED", completed.stdout)

    def test_gate_read_c_project_rejects_missing_manifest_and_accepts_valid_manifest(self):
        gate = PROJECT / "work" / "tools" / "gate.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "result" / "issues").mkdir(parents=True)
            (root / "logs" / "trace").mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            state = {
                "current_stage": "READ_C_PROJECT",
                "completed_stages": ["BOOTSTRAP", "INIT_WORKSPACE", "READ_C_PROJECT"],
                "checkpoint": "READ_C_PROJECT",
                "rust_project_path": "flashDB_rust",
                "input_path_candidates": ["/app/code/judge-assets/02_02_c_to_rust/code/FlashDB"],
                "input_path": "/tmp/fake/FlashDB",
                "input_manifest": "logs/trace/input_manifest.json",
                "build_status": "not_started",
                "test_status": "not_started",
                "unsafe_ratio": None,
                "repair_rounds": 0,
                "blocked_issues": [],
            }
            (root / "logs" / "trace" / "workflow_state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "logs" / "trace" / "01-init-workspace.md").write_text("# init\n", encoding="utf-8")

            missing = subprocess.run(
                [sys.executable, str(gate), "--stage", "READ_C_PROJECT", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertNotEqual(0, missing.returncode)
            self.assertIn("input_manifest.json", missing.stdout)

            manifest = {
                "source_root": "/tmp/fake/FlashDB",
                "src_dir": "src",
                "tests_dir": "tests",
                "core_sources": ["src/fdb.c"],
                "test_sources": ["tests/fdb_kvdb_tc.c"],
                "headers": ["inc/fdb.h"],
                "build_files": ["Makefile"],
                "counts": {"core_sources": 1, "test_sources": 1, "headers": 1},
            }
            (root / "logs" / "trace" / "input_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "logs" / "trace" / "02-read-c-project.md").write_text("# read\n", encoding="utf-8")
            passed = subprocess.run(
                [sys.executable, str(gate), "--stage", "READ_C_PROJECT", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, passed.returncode, passed.stdout)
            self.assertIn("READ_C_PROJECT: PASS", passed.stdout)

    def test_build_c_model_extracts_project_api_and_tests(self):
        scanner = load_tool("scan_c_project.py")
        builder = load_tool("build_c_model.py")
        source = PROJECT.parent / "judge-assets" / "code" / "FlashDB"
        manifest = scanner.scan_project(source)
        models = builder.build_models(manifest)

        project_model = models["c_project_model"]
        api_model = models["c_api_model"]
        test_model = models["c_test_model"]

        self.assertIn("src/fdb_kvdb.c", project_model["modules"]["kvdb"])
        self.assertIn("src/fdb_tsdb.c", project_model["modules"]["tsdb"])
        self.assertIn("tests/fdb_kvdb_tc.c", project_model["modules"]["tests"])
        self.assertIn("inc/flashdb.h", project_model["include_graph"])
        self.assertIn("fdb_def.h", project_model["include_graph"]["inc/flashdb.h"])

        self.assertIn("fdb_kvdb_init", api_model["public_functions"])
        self.assertIn("fdb_tsdb_init", api_model["public_functions"])
        self.assertIn("fdb_kvdb_init", api_model["kvdb_symbols"])
        self.assertIn("fdb_tsdb_init", api_model["tsdb_symbols"])
        self.assertIn("FDB_NO_ERR", api_model["enum_values"])
        self.assertTrue(any(item["name"] == "fdb_kvdb" for item in api_model["structs"]))

        self.assertIn("tests/fdb_kvdb_tc.c", test_model["test_files"])
        self.assertIn("tests/fdb_tsdb_tc.c", test_model["test_files"])
        self.assertIn("test_fdb_gc", test_model["registered_tests"])
        self.assertIn("test_fdb_tsl_iter_by_time", test_model["registered_tests"])
        self.assertIn("test_fdb_gc", test_model["kvdb_tests"])
        self.assertIn("test_fdb_tsl_iter_by_time", test_model["tsdb_tests"])
        scenarios = test_model["standard_scenarios"]
        scenario_ids = [scenario["id"] for scenario in scenarios]
        self.assertEqual(len(scenarios), len(set(scenario_ids)))
        self.assertEqual(len(test_model["registered_test_invocations"]), len(scenarios))
        self.assertGreaterEqual(len(scenarios), len(test_model["registered_tests"]))
        self.assertIn("test_fdb_gc", scenario_ids)
        self.assertIn("test_fdb_tsl_iter_by_time", scenario_ids)
        gc = next(scenario for scenario in scenarios if scenario["id"] == "test_fdb_gc")
        self.assertEqual("kvdb", gc["suite"])
        self.assertIn("gc", gc["tags"])
        self.assertEqual("tests/fdb_kvdb_tc.c", gc["source_file"])
        self.assertIsInstance(gc["semantic_facts"]["called_functions"], list)
        self.assertIsInstance(gc["semantic_facts"]["observed_c_symbols"], list)

    def test_build_c_model_extracts_test_semantic_facts_without_fixed_case_list(self):
        builder = load_tool("build_c_model.py")
        bodies = builder.extract_function_bodies(
            """
            static void test_dynamic_case(void) {
                fdb_kv_set(&db, "k", "v");
                test_helper();
                TEST_ASSERT_EQUAL(FDB_NO_ERR, result);
            }
            """
        )
        self.assertEqual(["test_dynamic_case"], list(bodies))
        facts = builder.extract_test_semantics(bodies["test_dynamic_case"])
        self.assertIn("fdb_kv_set", facts["observed_c_symbols"])
        self.assertIn("test_helper", facts["helper_calls"])
        self.assertEqual(["TEST_ASSERT_EQUAL"], facts["assertion_macros"])
        self.assertEqual(1, facts["assertion_count"])
        invocations = builder.extract_registered_tests(
            "TEST_RUN(test_dynamic_case); TEST_RUN(test_dynamic_case); TEST_RUN(test_other);"
        )
        self.assertEqual(["test_dynamic_case", "test_dynamic_case", "test_other"], invocations)
        scenarios = builder.build_standard_scenarios(
            [
                {"name": name, "source_file": "tests/main.c", "source_index": index}
                for index, name in enumerate(invocations, start=1)
            ],
            {},
            {},
        )
        self.assertEqual(
            ["test_dynamic_case", "test_dynamic_case__2", "test_other"],
            [scenario["id"] for scenario in scenarios],
        )

    def test_build_c_model_derives_scorer_cases_from_registered_tests(self):
        scanner = load_tool("scan_c_project.py")
        builder = load_tool("build_c_model.py")
        source = PROJECT.parent / "judge-assets" / "code" / "FlashDB"
        test_model = builder.build_models(scanner.scan_project(source))["c_test_model"]

        cases = test_model["scorer_standard_cases"]
        registered = set(test_model["registered_tests"])
        self.assertEqual(len(cases), len(test_model["standard_scenarios"]))
        self.assertTrue(cases)
        for case in cases:
            self.assertEqual(1, len(case["required_c_tests"]))
            self.assertIn(case["required_c_tests"][0], registered)
            self.assertEqual(case["required_c_tests"], case["present_c_tests"])
            self.assertEqual([], case["missing_c_tests"])
            self.assertIn("semantic_obligations", case)
            self.assertTrue(case["semantic_obligations"])

    def test_build_c_model_does_not_emit_unregistered_fixed_scorer_cases(self):
        builder = load_tool("build_c_model.py")
        cases = builder.build_scorer_standard_cases(
            registered_invocations=[
                {"name": "test_dynamic_case", "source_file": "tests/custom.c", "source_index": 1}
            ],
            scenario_tags={"test_dynamic_case": ["extension"]},
            test_semantics={"test_dynamic_case": builder.extract_test_semantics("custom_api_call(); TEST_ASSERT_TRUE(ok);")},
        )
        self.assertEqual(1, len(cases))
        self.assertEqual("test_dynamic_case", cases[0]["scenario_id"])
        self.assertEqual("dynamic_case", cases[0]["case_name"])

    def test_build_c_model_cli_writes_three_models(self):
        scanner = load_tool("scan_c_project.py")
        source = PROJECT.parent / "judge-assets" / "code" / "FlashDB"
        builder = PROJECT / "work" / "tools" / "build_c_model.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = root / "input_manifest.json"
            manifest_path.write_text(json.dumps(scanner.scan_project(source)), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(builder),
                    "--manifest",
                    str(manifest_path),
                    "--output-dir",
                    str(root),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            self.assertIn("BUILD_C_MODEL: MODELS_WRITTEN", completed.stdout)
            for name in ["c_project_model.json", "c_api_model.json", "c_test_model.json"]:
                self.assertTrue((root / name).is_file(), name)

    def test_c_cross_validate_reports_malformed_scorer_cases(self):
        cross = load_tool("c_cross_validate.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "logs" / "trace"
            trace.mkdir(parents=True)
            (trace / "c_test_model.json").write_text(json.dumps({
                "scorer_standard_cases": [
                    {
                        "case_id": "1",
                        "case_name": "valid",
                        "scenario_id": "test_valid",
                        "suite": "kvdb",
                    },
                    "bad-entry",
                    {
                        "case_name": "missing_case_id",
                        "scenario_id": "test_missing_case_id",
                        "suite": "tsdb",
                    },
                ],
            }), encoding="utf-8")

            matrix = cross.build_matrix(root, trace)

            self.assertEqual(3, matrix["total_scenarios"])
            malformed = [
                item
                for item in matrix["scenarios"]
                if str(item["scenario_id"]).startswith("malformed_case_")
            ]
            self.assertEqual(2, len(malformed))
            for item in malformed:
                self.assertEqual("not_supported", item["rust_impl_c_test"])
                self.assertEqual("c_cross_harness_not_supported", item["diagnosis"])
                self.assertIn("malformed scorer_standard_cases entry", item["reason"])
                self.assertTrue(item["log"].startswith("logs/trace/c-cross/"))

    def test_gate_build_c_model_rejects_missing_models_and_accepts_valid_models(self):
        gate = PROJECT / "work" / "tools" / "gate.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "result" / "issues").mkdir(parents=True)
            (root / "logs" / "trace").mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            state = {
                "current_stage": "BUILD_C_MODEL",
                "completed_stages": ["BOOTSTRAP", "INIT_WORKSPACE", "READ_C_PROJECT", "BUILD_C_MODEL"],
                "checkpoint": "BUILD_C_MODEL",
                "rust_project_path": "flashDB_rust",
                "input_path_candidates": ["/app/code/judge-assets/02_02_c_to_rust/code/FlashDB"],
                "input_path": "/tmp/fake/FlashDB",
                "input_manifest": "logs/trace/input_manifest.json",
                "c_project_model": "logs/trace/c_project_model.json",
                "c_api_model": "logs/trace/c_api_model.json",
                "c_test_model": "logs/trace/c_test_model.json",
                "build_status": "not_started",
                "test_status": "not_started",
                "unsafe_ratio": None,
                "repair_rounds": 0,
                "blocked_issues": [],
            }
            (root / "logs" / "trace" / "workflow_state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "logs" / "trace" / "01-init-workspace.md").write_text("# init\n", encoding="utf-8")
            (root / "logs" / "trace" / "02-read-c-project.md").write_text("# read\n", encoding="utf-8")
            (root / "logs" / "trace" / "input_manifest.json").write_text(
                json.dumps({
                    "source_root": "/tmp/fake/FlashDB",
                    "src_dir": "src",
                    "tests_dir": "tests",
                    "core_sources": ["src/fdb.c"],
                    "test_sources": ["tests/fdb_kvdb_tc.c"],
                    "headers": ["inc/flashdb.h"],
                    "build_files": ["tests/Makefile"],
                    "counts": {"core_sources": 1, "test_sources": 1, "headers": 1},
                }),
                encoding="utf-8",
            )

            missing = subprocess.run(
                [sys.executable, str(gate), "--stage", "BUILD_C_MODEL", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertNotEqual(0, missing.returncode)
            self.assertIn("c_project_model.json", missing.stdout)

            (root / "logs" / "trace" / "c_project_model.json").write_text(json.dumps({
                "modules": {"kvdb": ["src/fdb_kvdb.c"], "tsdb": ["src/fdb_tsdb.c"], "tests": ["tests/fdb_kvdb_tc.c"]},
                "include_graph": {"inc/flashdb.h": ["fdb_def.h"]},
                "source_files": ["src/fdb_kvdb.c", "src/fdb_tsdb.c"],
                "headers": ["inc/flashdb.h"],
                "test_files": ["tests/fdb_kvdb_tc.c"],
                "build_files": ["tests/Makefile"],
            }), encoding="utf-8")
            (root / "logs" / "trace" / "c_api_model.json").write_text(json.dumps({
                "public_functions": ["fdb_kvdb_init", "fdb_tsdb_init"],
                "kvdb_symbols": ["fdb_kvdb_init"],
                "tsdb_symbols": ["fdb_tsdb_init"],
                "public_headers": ["inc/flashdb.h"],
                "structs": [{"name": "fdb_kvdb", "file": "inc/fdb_def.h"}],
                "typedefs": [],
                "macros": [],
                "enums": [],
                "enum_values": ["FDB_NO_ERR"],
            }), encoding="utf-8")
            (root / "logs" / "trace" / "c_test_model.json").write_text(json.dumps({
                "test_files": ["tests/fdb_kvdb_tc.c"],
                "test_functions": ["test_fdb_gc"],
                "registered_tests": ["test_fdb_gc"],
                "kvdb_tests": ["test_fdb_gc"],
                "tsdb_tests": ["test_fdb_tsl_iter_by_time"],
                "standard_scenarios": [
                    {
                        "id": "test_fdb_gc",
                        "name": "test_fdb_gc",
                        "suite": "kvdb",
                        "source": "registered",
                        "tags": ["kvdb", "gc"],
                    }
                ],
                "scorer_standard_cases": [
                    {
                        "case_id": "1",
                        "case_name": "fdb_gc",
                        "scenario_id": "test_fdb_gc",
                        "suite": "kvdb",
                        "required_c_tests": ["test_fdb_gc"],
                        "present_c_tests": ["test_fdb_gc"],
                        "missing_c_tests": [],
                        "semantic_obligations": ["gc"],
                    }
                ],
                "scenario_tags": {"test_fdb_gc": ["kvdb", "gc"]},
            }), encoding="utf-8")
            (root / "logs" / "trace" / "03-build-c-model.md").write_text("# model\n", encoding="utf-8")
            passed = subprocess.run(
                [sys.executable, str(gate), "--stage", "BUILD_C_MODEL", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, passed.returncode, passed.stdout)
            self.assertIn("BUILD_C_MODEL: PASS", passed.stdout)

    def test_design_rust_api_builds_canonical_safe_api(self):
        scanner = load_tool("scan_c_project.py")
        builder = load_tool("build_c_model.py")
        designer = load_tool("design_rust_api.py")
        source = PROJECT.parent / "judge-assets" / "code" / "FlashDB"
        models = builder.build_models(scanner.scan_project(source))
        design = designer.design_api(
            models["c_project_model"],
            models["c_api_model"],
            models["c_test_model"],
        )

        self.assertEqual("flashdb_rust", design["crate_name"])
        self.assertIn("error", design["modules"])
        self.assertIn("storage", design["modules"])
        self.assertEqual(len(design["modules"]), len(design["core_types"]))
        self.assertTrue(design["kvdb_api"])
        self.assertTrue(design["tsdb_api"])
        self.assertIn("Result<T, Error>", design["error_model"]["result_alias"])
        public_symbols = set(models["c_api_model"]["public_functions"])
        self.assertTrue(set(design["c_to_rust_symbol_map"]).issubset(public_symbols))
        self.assertIn("kvdb_tests", design["test_api"])
        self.assertIn("tsdb_tests", design["test_api"])

    def test_design_rust_api_cli_writes_design(self):
        scanner = load_tool("scan_c_project.py")
        builder = load_tool("build_c_model.py")
        source = PROJECT.parent / "judge-assets" / "code" / "FlashDB"
        designer = PROJECT / "work" / "tools" / "design_rust_api.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            models = builder.build_models(scanner.scan_project(source))
            for key, value in models.items():
                (root / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")
            output = root / "rust_api_design.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(designer),
                    "--project-model",
                    str(root / "c_project_model.json"),
                    "--api-model",
                    str(root / "c_api_model.json"),
                    "--test-model",
                    str(root / "c_test_model.json"),
                    "--output",
                    str(output),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout)
            self.assertIn("DESIGN_RUST_API: DESIGN_WRITTEN", completed.stdout)
            design = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(design["core_types"])

    def test_gate_design_rust_api_requires_chinese_log_and_valid_design(self):
        gate = PROJECT / "work" / "tools" / "gate.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "logs" / "trace"
            (root / "result" / "issues").mkdir(parents=True)
            trace.mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            state = {
                "current_stage": "DESIGN_RUST_API",
                "completed_stages": ["BOOTSTRAP", "INIT_WORKSPACE", "READ_C_PROJECT", "BUILD_C_MODEL", "DESIGN_RUST_API"],
                "checkpoint": "DESIGN_RUST_API",
                "rust_project_path": "flashDB_rust",
                "input_path_candidates": ["/app/code/judge-assets/02_02_c_to_rust/code/FlashDB"],
                "input_path": "/tmp/fake/FlashDB",
                "input_manifest": "logs/trace/input_manifest.json",
                "c_project_model": "logs/trace/c_project_model.json",
                "c_api_model": "logs/trace/c_api_model.json",
                "c_test_model": "logs/trace/c_test_model.json",
                "rust_api_design": "logs/trace/rust_api_design.json",
                "build_status": "not_started",
                "test_status": "not_started",
                "unsafe_ratio": None,
                "repair_rounds": 0,
                "blocked_issues": [],
            }
            (trace / "workflow_state.json").write_text(json.dumps(state), encoding="utf-8")
            for name in ["01-init-workspace.md", "02-read-c-project.md", "03-build-c-model.md"]:
                (trace / name).write_text("# 阶段\n", encoding="utf-8")
            for name in ["input_manifest.json", "c_project_model.json", "c_api_model.json", "c_test_model.json"]:
                (trace / name).write_text("{}", encoding="utf-8")

            missing = subprocess.run(
                [sys.executable, str(gate), "--stage", "DESIGN_RUST_API", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertNotEqual(0, missing.returncode)
            self.assertIn("rust_api_design.json", missing.stdout)

            valid_design = {
                "crate_name": "flashdb_rust",
                "modules": ["error", "flash", "kvdb", "tsdb"],
                "core_types": ["FlashStorage", "MemFlash", "FileFlash", "FdbError", "KvDb", "TsDb", "TslRecord"],
                "traits": ["FlashStorage"],
                "kvdb_api": [{"name": "set"}],
                "tsdb_api": [{"name": "append"}],
                "test_api": {"kvdb_tests": [], "tsdb_tests": []},
                "error_model": {"result_alias": "Result<T, FdbError>"},
                "storage_model": {"implementations": ["MemFlash", "FileFlash"]},
                "c_to_rust_symbol_map": {"fdb_kvdb_init": "KvDb::open", "fdb_tsdb_init": "TsDb::open"},
            }
            (trace / "rust_api_design.json").write_text(json.dumps(valid_design), encoding="utf-8")
            (trace / "04-design-rust-api.md").write_text("# API Design\n\nEnglish only log.\n", encoding="utf-8")
            english_log = subprocess.run(
                [sys.executable, str(gate), "--stage", "DESIGN_RUST_API", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertNotEqual(0, english_log.returncode)
            self.assertIn("中文", english_log.stdout)

            (trace / "04-design-rust-api.md").write_text("# Rust API 设计\n\n本阶段只设计 API，不生成 Rust 项目。\n", encoding="utf-8")
            passed = subprocess.run(
                [sys.executable, str(gate), "--stage", "DESIGN_RUST_API", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, passed.returncode, passed.stdout)
            self.assertIn("DESIGN_RUST_API: PASS", passed.stdout)

    def test_generate_scaffold_and_migrate_tests_create_runnable_rust_project(self):
        scaffold = PROJECT / "work" / "tools" / "generate_rust_scaffold.py"
        migrator = PROJECT / "work" / "tools" / "migrate_tests.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            design = {
                "crate_name": "flashdb_rust",
                "modules": ["error", "flash", "kvdb", "tsdb"],
                "core_modules": ["error", "flash", "kvdb", "tsdb"],
                "support_modules": [],
                "extension_modules": [],
                "core_types": ["FlashStorage", "MemFlash", "FileFlash", "FdbError", "KvDb", "TsDb", "TslRecord"],
                "kvdb_api": [{"name": "set"}, {"name": "get"}, {"name": "delete"}],
                "tsdb_api": [{"name": "append"}, {"name": "query_by_time"}],
                "test_api": {"kvdb_tests": ["test_fdb_kv_set_get"], "tsdb_tests": ["test_fdb_tsl_append"]},
                "unmapped_symbols": [],
                "excluded_sources": [],
            }
            tests = {
                "kvdb_tests": ["test_fdb_kv_set_get"],
                "tsdb_tests": ["test_fdb_tsl_append"],
                "extension_tests": [],
                "unclassified_tests": [],
                "standard_scenarios": [
                    {
                        "id": "test_fdb_kv_set_get",
                        "name": "test_fdb_kv_set_get",
                        "suite": "kvdb",
                        "source": "registered",
                        "tags": ["kvdb", "set", "get"],
                    },
                    {
                        "id": "test_fdb_tsl_append",
                        "name": "test_fdb_tsl_append",
                        "suite": "tsdb",
                        "source": "registered",
                        "tags": ["tsdb", "append"],
                    },
                ],
            }
            design_path = root / "rust_api_design.json"
            test_model_path = root / "c_test_model.json"
            design_path.write_text(json.dumps(design), encoding="utf-8")
            test_model_path.write_text(json.dumps(tests), encoding="utf-8")

            scaffold_run = subprocess.run(
                [sys.executable, str(scaffold), "--design", str(design_path), "--project", str(root / "flashDB_rust")],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, scaffold_run.returncode, scaffold_run.stdout)
            self.assertIn("GENERATE_RUST_SCAFFOLD: SCAFFOLD_WRITTEN", scaffold_run.stdout)
            for rel_path in ["Cargo.toml", "src/lib.rs", "src/error.rs", "src/flash.rs", "src/kvdb.rs", "src/tsdb.rs"]:
                self.assertTrue((root / "flashDB_rust" / rel_path).is_file(), rel_path)

            migrate_run = subprocess.run(
                [
                    sys.executable,
                    str(migrator),
                    "--test-model",
                    str(test_model_path),
                    "--design",
                    str(design_path),
                    "--project",
                    str(root / "flashDB_rust"),
                    "--mapping",
                    str(root / "rust_test_mapping.json"),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, migrate_run.returncode, migrate_run.stdout)
            self.assertIn("MIGRATE_TESTS: TESTS_WRITTEN", migrate_run.stdout)
            mapping = json.loads((root / "rust_test_mapping.json").read_text(encoding="utf-8"))
            self.assertIn("kvdb", mapping)
            self.assertIn("tsdb", mapping)
            self.assertEqual(2, mapping["total_scenarios"])
            self.assertEqual([], mapping["unmapped"])
            self.assertEqual(
                ["test_fdb_kv_set_get", "test_fdb_tsl_append"],
                [scenario["id"] for scenario in mapping["scenarios"]],
            )
            self.assertEqual(
                ["test_fdb_kv_set_get", "test_fdb_tsl_append"],
                [scenario["scorer_case_id"] for scenario in mapping["scenarios"]],
            )
            self.assertTrue(all("semantic_obligations" in scenario for scenario in mapping["scenarios"]))
            self.assertTrue(all(scenario["coverage"] == "pending" for scenario in mapping["scenarios"]))
            self.assertTrue((root / "flashDB_rust" / "tests" / "kvdb_tests.rs").is_file())
            self.assertTrue((root / "flashDB_rust" / "tests" / "tsdb_tests.rs").is_file())
            self.assertIn(
                "MIGRATION_PENDING",
                (root / "flashDB_rust" / "tests" / "kvdb_tests.rs").read_text(encoding="utf-8"),
            )

            cargo_test = subprocess.run(
                ["cargo", "test", "--quiet"],
                cwd=root / "flashDB_rust",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, cargo_test.returncode, cargo_test.stdout)

    def test_migrate_tests_uses_scorer_standard_cases_when_present(self):
        migrator = load_tool("migrate_tests.py")
        test_model = {
            "standard_scenarios": [
                {"id": "test_fdb_gc", "name": "test_fdb_gc", "suite": "kvdb", "tags": ["kvdb", "gc"]},
                {"id": "test_fdb_tsl_iter_by_time_1", "name": "test_fdb_tsl_iter_by_time_1", "suite": "tsdb", "tags": ["tsdb", "iter"]},
            ],
            "scorer_standard_cases": [
                {
                    "case_id": "10",
                    "case_name": "gc",
                    "scenario_id": "test_fdb_gc",
                    "suite": "kvdb",
                    "required_c_tests": ["test_fdb_gc"],
                    "semantic_obligations": ["four_phase_gc", "oldest_addr", "reboot"],
                },
                {
                    "case_id": "18",
                    "case_name": "tsl_iter_reverse",
                    "scenario_id": "test_fdb_tsl_iter_reverse",
                    "suite": "tsdb",
                    "required_c_tests": ["test_fdb_tsl_iter_reverse"],
                    "semantic_obligations": ["reverse_iteration"],
                },
                {
                    "case_id": "19",
                    "case_name": "tsl_iter_by_time",
                    "scenario_id": "test_fdb_tsl_iter_by_time_1",
                    "suite": "tsdb",
                    "required_c_tests": ["test_fdb_tsl_iter_by_time_1"],
                    "semantic_obligations": ["sector_boundary_matrix"],
                },
            ],
        }
        scenarios = migrator.standard_scenarios(test_model)
        self.assertEqual(
            ["test_fdb_gc", "test_fdb_tsl_iter_reverse", "test_fdb_tsl_iter_by_time_1"],
            [scenario["id"] for scenario in scenarios],
        )
        reverse = next(scenario for scenario in scenarios if scenario["id"] == "test_fdb_tsl_iter_reverse")
        self.assertEqual("18", reverse["scorer_case_id"])
        self.assertEqual("tsl_iter_reverse", reverse["scorer_case_name"])
        self.assertIn("reverse_iteration", reverse["semantic_obligations"])

    def test_gate_migrate_tests_rejects_missing_dynamic_scenario_mapping(self):
        gate = PROJECT / "work" / "tools" / "gate.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "logs" / "trace"
            project = root / "flashDB_rust"
            (root / "result" / "issues").mkdir(parents=True)
            trace.mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            (project / "tests").mkdir(parents=True)
            for rel_path in ["tests/kvdb_tests.rs", "tests/tsdb_tests.rs", "tests/equivalence_tests.rs"]:
                (project / rel_path).write_text("#[test]\nfn sample() { assert!(true); }\n", encoding="utf-8")
            state = {
                "current_stage": "MIGRATE_TESTS",
                "completed_stages": [
                    "BOOTSTRAP",
                    "INIT_WORKSPACE",
                    "READ_C_PROJECT",
                    "BUILD_C_MODEL",
                    "DESIGN_RUST_API",
                    "GENERATE_RUST_SCAFFOLD",
                    "REWRITE_CORE_MODULES",
                    "VERIFY_RUST_WITH_C_TESTS",
                    "MIGRATE_TESTS",
                ],
                "checkpoint": "MIGRATE_TESTS",
                "rust_project_path": "flashDB_rust",
                "input_path_candidates": ["/app/code/judge-assets/02_02_c_to_rust/code/FlashDB"],
                "input_path": "/tmp/fake/FlashDB",
                "input_manifest": "logs/trace/input_manifest.json",
                "c_project_model": "logs/trace/c_project_model.json",
                "c_api_model": "logs/trace/c_api_model.json",
                "c_test_model": "logs/trace/c_test_model.json",
                "rust_api_design": "logs/trace/rust_api_design.json",
                "rust_test_mapping": "logs/trace/rust_test_mapping.json",
                "build_status": "not_started",
                "test_status": "not_started",
                "unsafe_ratio": None,
                "repair_rounds": 0,
                "blocked_issues": [],
            }
            (trace / "workflow_state.json").write_text(json.dumps(state), encoding="utf-8")
            for name in [
                "01-init-workspace.md",
                "02-read-c-project.md",
                "03-build-c-model.md",
                "04-design-rust-api.md",
                "05-generate-rust-scaffold.md",
                "06-rewrite-core-modules.md",
                "07-migrate-tests.md",
                "input_manifest.json",
                "c_project_model.json",
                "c_api_model.json",
                "rust_api_design.json",
            ]:
                (trace / name).write_text("{}" if name.endswith(".json") else "# 阶段\n", encoding="utf-8")
            (trace / "c_test_model.json").write_text(json.dumps({
                "kvdb_tests": ["test_fdb_gc"],
                "tsdb_tests": ["test_fdb_tsl_append"],
                "standard_scenarios": [
                    {"id": "test_fdb_gc", "name": "test_fdb_gc", "suite": "kvdb", "tags": ["kvdb", "gc"]},
                    {"id": "test_fdb_tsl_append", "name": "test_fdb_tsl_append", "suite": "tsdb", "tags": ["tsdb", "append"]},
                ],
                "scorer_standard_cases": [
                    {
                        "case_id": "10",
                        "case_name": "gc",
                        "scenario_id": "test_fdb_gc",
                        "suite": "kvdb",
                        "required_c_tests": ["test_fdb_gc"],
                        "semantic_obligations": ["four_phase_gc"],
                    },
                    {
                        "case_id": "15",
                        "case_name": "tsl_append",
                        "scenario_id": "test_fdb_tsl_append",
                        "suite": "tsdb",
                        "required_c_tests": ["test_fdb_tsl_append"],
                        "semantic_obligations": ["append_log"],
                    },
                ],
            }), encoding="utf-8")
            (trace / "rust_test_mapping.json").write_text(json.dumps({
                "kvdb": ["test_fdb_gc"],
                "tsdb": [],
                "extension": [],
                "unmapped": [],
                "total_scenarios": 1,
                "scenarios": [
                    {
                        "id": "test_fdb_gc",
                        "name": "test_fdb_gc",
                        "suite": "kvdb",
                        "rust_test": "kvdb_test_fdb_gc",
                        "rust_file": "flashDB_rust/tests/kvdb_tests.rs",
                        "coverage": "semantic",
                    }
                ],
            }), encoding="utf-8")

            missing = subprocess.run(
                [sys.executable, str(gate), "--stage", "MIGRATE_TESTS", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertNotEqual(0, missing.returncode)
            self.assertIn("missing Rust mappings for C scenarios: test_fdb_tsl_append", missing.stdout)

    def test_cargo_capture_unsafe_ratio_report_and_final_gate(self):
        scaffold = PROJECT / "work" / "tools" / "generate_rust_scaffold.py"
        migrator = PROJECT / "work" / "tools" / "migrate_tests.py"
        cargo_capture = PROJECT / "work" / "tools" / "cargo_capture.py"
        unsafe_ratio = PROJECT / "work" / "tools" / "unsafe_ratio.py"
        report_writer = PROJECT / "work" / "tools" / "report_writer.py"
        gate = PROJECT / "work" / "tools" / "gate.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "logs" / "trace"
            issues = root / "result" / "issues"
            trace.mkdir(parents=True)
            issues.mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")

            design = {
                "crate_name": "flashdb_rust",
                "modules": ["error", "flash", "kvdb", "tsdb"],
                "core_modules": ["error", "flash", "kvdb", "tsdb"],
                "core_types": ["FlashStorage", "MemFlash", "FileFlash", "FdbError", "KvDb", "TsDb", "TslRecord"],
                "kvdb_api": [{"name": "set"}],
                "tsdb_api": [{"name": "append"}],
                "test_api": {"kvdb_tests": [], "tsdb_tests": []},
                "error_model": {"result_alias": "Result<T, FdbError>"},
                "storage_model": {"implementations": ["MemFlash", "FileFlash"]},
                "c_to_rust_symbol_map": {"fdb_kvdb_init": "KvDb::open", "fdb_tsdb_init": "TsDb::open"},
                "unmapped_symbols": [],
                "excluded_sources": [],
            }
            test_model = {
                "kvdb_tests": ["test_fdb_gc"],
                "tsdb_tests": ["test_fdb_tsl_append"],
                "extension_tests": [],
                "unclassified_tests": [],
                "standard_scenarios": [
                    {"id": "test_fdb_gc", "name": "test_fdb_gc", "suite": "kvdb", "tags": ["kvdb", "gc"]},
                    {"id": "test_fdb_tsl_append", "name": "test_fdb_tsl_append", "suite": "tsdb", "tags": ["tsdb", "append"]},
                ],
                "scorer_standard_cases": [
                    {
                        "case_id": "10",
                        "case_name": "gc",
                        "scenario_id": "test_fdb_gc",
                        "suite": "kvdb",
                        "required_c_tests": ["test_fdb_gc"],
                        "semantic_obligations": ["four_phase_gc"],
                    },
                    {
                        "case_id": "15",
                        "case_name": "tsl_append",
                        "scenario_id": "test_fdb_tsl_append",
                        "suite": "tsdb",
                        "required_c_tests": ["test_fdb_tsl_append"],
                        "semantic_obligations": ["append_log"],
                    },
                ],
            }
            (trace / "rust_api_design.json").write_text(json.dumps(design), encoding="utf-8")
            (trace / "c_test_model.json").write_text(json.dumps(test_model), encoding="utf-8")
            for name in ["c_project_model.json", "c_api_model.json", "input_manifest.json"]:
                (trace / name).write_text("{}", encoding="utf-8")

            subprocess.run(
                [sys.executable, str(scaffold), "--design", str(trace / "rust_api_design.json"), "--project", str(root / "flashDB_rust")],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(migrator),
                    "--test-model",
                    str(trace / "c_test_model.json"),
                    "--design",
                    str(trace / "rust_api_design.json"),
                    "--project",
                    str(root / "flashDB_rust"),
                    "--mapping",
                    str(trace / "rust_test_mapping.json"),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            mapping_path = trace / "rust_test_mapping.json"
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            for scenario in mapping["scenarios"]:
                scenario["coverage"] = "semantic"
                scenario["validated_obligations"] = scenario["semantic_obligations"]
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            for test_file in [
                root / "flashDB_rust" / "tests" / "kvdb_tests.rs",
                root / "flashDB_rust" / "tests" / "tsdb_tests.rs",
            ]:
                test_file.write_text(
                    test_file.read_text(encoding="utf-8").replace("    // MIGRATION_PENDING:", "    // Migrated:"),
                    encoding="utf-8",
                )
            cargo_run = subprocess.run(
                [sys.executable, str(cargo_capture), "--project", str(root / "flashDB_rust"), "--out", str(trace)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, cargo_run.returncode, cargo_run.stdout)
            self.assertTrue((trace / "cargo-build.log").is_file())
            self.assertTrue((trace / "cargo-test.log").is_file())
            self.assertTrue((trace / "cargo-results.json").is_file())

            ratio_run = subprocess.run(
                [sys.executable, str(unsafe_ratio), "--project", str(root / "flashDB_rust"), "--out", str(trace / "unsafe-ratio.json")],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, ratio_run.returncode, ratio_run.stdout)
            ratio = json.loads((trace / "unsafe-ratio.json").read_text(encoding="utf-8"))
            self.assertLessEqual(ratio["unsafe_ratio"], 0.10)

            state = {
                "current_stage": "DONE",
                "completed_stages": [
                    "BOOTSTRAP",
                    "INIT_WORKSPACE",
                    "READ_C_PROJECT",
                    "BUILD_C_MODEL",
                    "DESIGN_RUST_API",
                    "GENERATE_RUST_SCAFFOLD",
                    "REWRITE_CORE_MODULES",
                    "VERIFY_RUST_WITH_C_TESTS",
                    "MIGRATE_TESTS",
                    "BUILD_TEST_REPAIR",
                    "REPORT_AND_VERIFY",
                ],
                "checkpoint": "REPORT_AND_VERIFY",
                "rust_project_path": "flashDB_rust",
                "input_path_candidates": ["/app/code/judge-assets/02_02_c_to_rust/code/FlashDB"],
                "input_path": "/tmp/fake/FlashDB",
                "input_manifest": "logs/trace/input_manifest.json",
                "c_project_model": "logs/trace/c_project_model.json",
                "c_api_model": "logs/trace/c_api_model.json",
                "c_test_model": "logs/trace/c_test_model.json",
                "rust_api_design": "logs/trace/rust_api_design.json",
                "rust_test_mapping": "logs/trace/rust_test_mapping.json",
                "build_status": "pass",
                "test_status": "pass",
                "unsafe_ratio": ratio["unsafe_ratio"],
                "repair_rounds": 0,
                "blocked_issues": [],
            }
            (trace / "workflow_state.json").write_text(json.dumps(state), encoding="utf-8")
            for name in [
                "01-init-workspace.md",
                "02-read-c-project.md",
                "03-build-c-model.md",
                "04-design-rust-api.md",
                "05-generate-rust-scaffold.md",
                "06-rewrite-core-modules.md",
                "06-5-verify-rust-with-c-tests.md",
                "07-migrate-tests.md",
                "08-build-test-repair.md",
                "09-report-and-verify.md",
                "final-verification.md",
            ]:
                (trace / name).write_text("# 阶段\n\n中文验证记录。\n", encoding="utf-8")
            (trace / "validation-matrix.json").write_text(json.dumps({
                "stage": "VERIFY_RUST_WITH_C_TESTS",
                "policy": "advisory",
                "total_scenarios": 2,
                "summary": {"rust_impl_c_test": {"not_supported": 2}},
                "scenarios": [
                    {
                        "scenario_id": "test_fdb_gc",
                        "scorer_case_id": "10",
                        "suite": "kvdb",
                        "c_impl_c_test": "baseline",
                        "rust_impl_c_test": "not_supported",
                        "c_impl_rust_test": "not_run",
                        "rust_impl_rust_test": "pending",
                        "diagnosis": "c_cross_harness_not_supported",
                        "reason": "fixture advisory matrix",
                        "log": "logs/trace/c-cross/test_fdb_gc.log",
                    },
                    {
                        "scenario_id": "test_fdb_tsl_append",
                        "scorer_case_id": "15",
                        "suite": "tsdb",
                        "c_impl_c_test": "baseline",
                        "rust_impl_c_test": "not_supported",
                        "c_impl_rust_test": "not_run",
                        "rust_impl_rust_test": "pending",
                        "diagnosis": "c_cross_harness_not_supported",
                        "reason": "fixture advisory matrix",
                        "log": "logs/trace/c-cross/test_fdb_tsl_append.log",
                    },
                ],
            }), encoding="utf-8")

            report_run = subprocess.run(
                [
                    sys.executable,
                    str(report_writer),
                    "--root",
                    str(root),
                    "--output",
                    str(root / "result" / "output.md"),
                    "--issues",
                    str(issues / "00-summary.md"),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, report_run.returncode, report_run.stdout)
            output_text = (root / "result" / "output.md").read_text(encoding="utf-8")
            self.assertIn("STATUS: SUCCESS", output_text)
            self.assertIn("Cross Validation Matrix", output_text)
            self.assertIn("C tests on Rust", output_text)

            final_gate = subprocess.run(
                [sys.executable, str(gate), "--stage", "REPORT_AND_VERIFY", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, final_gate.returncode, final_gate.stdout)
            self.assertIn("REPORT_AND_VERIFY: PASS", final_gate.stdout)

    def test_cargo_capture_test_failure_writes_triage_before_repair(self):
        cargo_capture = PROJECT / "work" / "tools" / "cargo_capture.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "flashDB_rust"
            trace = root / "logs" / "trace"
            (project / "src").mkdir(parents=True)
            (project / "tests").mkdir()
            trace.mkdir(parents=True)
            (project / "Cargo.toml").write_text(
                '[package]\nname = "flashdb_rust"\nversion = "0.1.0"\nedition = "2021"\n',
                encoding="utf-8",
            )
            (project / "src" / "lib.rs").write_text("pub fn value_len() -> usize { 21 }\n", encoding="utf-8")
            (project / "tests" / "kvdb_tests.rs").write_text(
                "use flashdb_rust::value_len;\n"
                "#[test]\n"
                "fn kvdb_test_fdb_create_kv_blob() {\n"
                "    assert_eq!(value_len(), 16);\n"
                "}\n",
                encoding="utf-8",
            )
            (trace / "workflow_state.json").write_text(
                json.dumps({
                    "current_stage": "BUILD_TEST_REPAIR",
                    "checkpoint": "BUILD_TEST_REPAIR",
                    "test_failure_triage_required": False,
                }),
                encoding="utf-8",
            )
            (trace / "rust_test_mapping.json").write_text(
                json.dumps({
                    "scenarios": [
                        {
                            "rust_test": "kvdb_test_fdb_create_kv_blob",
                            "rust_file": "flashDB_rust/tests/kvdb_tests.rs",
                            "coverage": "semantic",
                            "validated_obligations": ["blob read returns bytes written"],
                        }
                    ]
                }),
                encoding="utf-8",
            )
            (trace / "c_test_model.json").write_text(json.dumps({"scorer_standard_cases": []}), encoding="utf-8")
            (trace / "validation-matrix.json").write_text(json.dumps({"scenarios": []}), encoding="utf-8")

            cargo_run = subprocess.run(
                [sys.executable, str(cargo_capture), "--project", str(project), "--out", str(trace)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            self.assertNotEqual(0, cargo_run.returncode)
            triage_path = trace / "test-failure-triage.jsonl"
            self.assertTrue(triage_path.is_file(), cargo_run.stdout)
            triage = [json.loads(line) for line in triage_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(1, len(triage))
            self.assertEqual("kvdb_test_fdb_create_kv_blob", triage[0]["failed_test"])
            self.assertEqual("assertion_mismatch", triage[0]["failure_kind"])
            self.assertEqual("test_oracle_suspect", triage[0]["classification"])
            self.assertFalse(triage[0]["allow_src_edit"])
            self.assertIn("flashDB_rust/tests", triage[0]["allowed_edit_scope"])
            state = json.loads((trace / "workflow_state.json").read_text(encoding="utf-8"))
            self.assertTrue(state["test_failure_triage_required"])

    def test_build_c_model_extracts_deep_semantic_obligations(self):
        builder = load_tool("build_c_model.py")
        body = """
            fdb_kvdb_control(&db, FDB_KVDB_CTRL_SET_SEC_SIZE, &sec_size);
            fdb_kv_set(&db, "kv0", value0);
            fdb_kv_set(&db, "kv1", value1);
            fdb_kv_set(&db, "kv2", value2);
            fdb_kv_set_blob(&db, "blob", big_blob, sec_size * 3);
            TEST_ASSERT_EQUAL(0, db.parent.oldest_addr % sec_size);
            fdb_kvdb_deinit(&db);
            fdb_kvdb_init(&db, "env", "path", NULL, NULL);
            TEST_ASSERT_NOT_NULL(fdb_kv_get(&db, "kv0"));
            fdb_tsl_append(&tsdb, 100, log, sizeof(log));
            fdb_tsl_append(&tsdb, 101, log, sizeof(log));
            fdb_tsl_iter_reverse(&tsdb, iter_cb, NULL);
            fdb_tsl_set_status(&tsdb, 100, FDB_TSL_USER_STATUS1);
            fdb_tsl_set_status(&tsdb, 101, FDB_TSL_DELETED);
            TEST_ASSERT_EQUAL(2, status_count);
        """

        facts = builder.extract_test_semantics(body)

        self.assertIn("oldest_addr", facts["assertion_targets"])
        self.assertIn("verify_addr_alignment", facts["semantic_markers"])
        self.assertIn("use_control_interface", facts["semantic_markers"])
        self.assertIn("verify_persistence_after_reboot", facts["semantic_markers"])
        self.assertGreaterEqual(facts["data_shape"]["kv_set_count"], 3)
        self.assertGreaterEqual(facts["data_shape"]["blob_multiplier"], 3)
        self.assertGreaterEqual(facts["data_shape"]["tsl_append_count"], 2)
        self.assertIn("iter_reverse", facts["scenario_features"])
        self.assertIn("multi_status_filter", facts["scenario_features"])

        obligations = builder.semantic_obligations_from_facts(["kvdb", "gc"], facts)
        for obligation in [
            "verify_addr_alignment",
            "use_control_interface",
            "verify_persistence_after_reboot",
            "data_shape:multi_kv_count:3",
            "data_shape:cross_sector_blob",
            "scenario:iter_reverse",
            "scenario:multi_status_filter",
        ]:
            self.assertIn(obligation, obligations)

    def test_design_rust_api_emits_test_observables_and_storage_constraints(self):
        designer = load_tool("design_rust_api.py")
        design = designer.design_api(
            {"source_files": ["src/fdb_file.c"], "headers": [], "test_files": []},
            {
                "public_functions": ["fdb_kvdb_init", "fdb_tsdb_init"],
                "kvdb_symbols": ["fdb_kvdb_init"],
                "tsdb_symbols": ["fdb_tsdb_init"],
                "macros": ["FDB_USING_FILE_POSIX_MODE"],
            },
            {
                "kvdb_tests": ["test_fdb_gc"],
                "tsdb_tests": ["test_fdb_tsl_iter_reverse"],
                "standard_scenarios": [],
                "scorer_standard_cases": [
                    {
                        "case_id": "10",
                        "case_name": "gc",
                        "scenario_id": "test_fdb_gc",
                        "suite": "kvdb",
                        "semantic_obligations": [
                            "verify_addr_alignment",
                            "use_control_interface",
                            "data_shape:cross_sector_blob",
                            "scenario:multi_status_filter",
                        ],
                    }
                ],
            },
        )

        self.assertEqual("file_sector_mode", design["storage_constraints"]["backend"])
        self.assertTrue(design["storage_constraints"]["fd_cache_required"])
        self.assertIn("{dir}/{name}.fdb.{index}", design["storage_constraints"]["sector_file_pattern"])
        observables = {item["name"] for item in design["test_api"]["observables"]}
        controls = {item["name"] for item in design["test_api"]["controls"]}
        self.assertIn("oldest_addr", observables)
        self.assertIn("sector_status", observables)
        self.assertIn("control", controls)

    def test_gate_design_rust_api_rejects_missing_required_test_observables(self):
        gate = PROJECT / "work" / "tools" / "gate.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "logs" / "trace"
            (root / "result" / "issues").mkdir(parents=True)
            trace.mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            state = {
                "current_stage": "DESIGN_RUST_API",
                "completed_stages": ["BOOTSTRAP", "INIT_WORKSPACE", "READ_C_PROJECT", "BUILD_C_MODEL", "DESIGN_RUST_API"],
                "checkpoint": "DESIGN_RUST_API",
                "rust_project_path": "flashDB_rust",
                "input_path_candidates": ["/app/code/judge-assets/02_02_c_to_rust/code/FlashDB"],
                "input_path": "/tmp/fake/FlashDB",
                "input_manifest": "logs/trace/input_manifest.json",
                "c_project_model": "logs/trace/c_project_model.json",
                "c_api_model": "logs/trace/c_api_model.json",
                "c_test_model": "logs/trace/c_test_model.json",
                "rust_api_design": "logs/trace/rust_api_design.json",
                "build_status": "not_started",
                "test_status": "not_started",
                "unsafe_ratio": None,
                "repair_rounds": 0,
                "blocked_issues": [],
            }
            (trace / "workflow_state.json").write_text(json.dumps(state), encoding="utf-8")
            for name in ["01-init-workspace.md", "02-read-c-project.md", "03-build-c-model.md"]:
                (trace / name).write_text("# 阶段\n", encoding="utf-8")
            for name in ["input_manifest.json", "c_project_model.json", "c_api_model.json"]:
                (trace / name).write_text("{}", encoding="utf-8")
            (trace / "c_test_model.json").write_text(json.dumps({
                "scorer_standard_cases": [
                    {
                        "case_id": "1",
                        "case_name": "kvdb_init",
                        "scenario_id": "test_fdb_kvdb_init",
                        "suite": "kvdb",
                        "semantic_obligations": ["verify_addr_alignment", "use_control_interface"],
                    }
                ]
            }), encoding="utf-8")
            (trace / "rust_api_design.json").write_text(json.dumps({
                "crate_name": "flashdb_rust",
                "modules": ["error", "storage", "kvdb", "tsdb"],
                "core_types": ["Error", "Storage", "Kvdb", "Tsdb"],
                "traits": [],
                "kvdb_api": [{"name": "init"}],
                "tsdb_api": [{"name": "init"}],
                "test_api": {"observables": [], "controls": []},
                "error_model": {"result_alias": "Result<T, Error>"},
                "storage_model": {"implementations": []},
                "storage_constraints": {"backend": "memory_only"},
                "c_to_rust_symbol_map": {"fdb_kvdb_init": "Kvdb::init", "fdb_tsdb_init": "Tsdb::init"},
            }), encoding="utf-8")
            (trace / "04-design-rust-api.md").write_text("# Rust API 设计\n\n中文。\n", encoding="utf-8")

            failed = subprocess.run(
                [sys.executable, str(gate), "--stage", "DESIGN_RUST_API", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            self.assertNotEqual(0, failed.returncode)
            self.assertIn("test_api missing observable oldest_addr", failed.stdout)
            self.assertIn("test_api missing control interface", failed.stdout)

    def test_test_consistency_check_rejects_shallow_semantic_mapping(self):
        checker = load_tool("test_consistency_check.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "logs" / "trace"
            tests_dir = root / "flashDB_rust" / "tests"
            trace.mkdir(parents=True)
            tests_dir.mkdir(parents=True)
            (trace / "c_test_model.json").write_text(json.dumps({
                "scorer_standard_cases": [
                    {
                        "case_id": "10",
                        "case_name": "gc",
                        "scenario_id": "test_fdb_gc",
                        "suite": "kvdb",
                        "semantic_facts": {"assertion_count": 4},
                        "semantic_obligations": [
                            "verify_addr_alignment",
                            "data_shape:multi_kv_count:4",
                        ],
                    }
                ]
            }), encoding="utf-8")
            (trace / "rust_test_mapping.json").write_text(json.dumps({
                "scenarios": [
                    {
                        "id": "test_fdb_gc",
                        "scorer_case_id": "10",
                        "coverage": "semantic",
                        "semantic_obligations": ["verify_addr_alignment", "data_shape:multi_kv_count:4"],
                        "validated_obligations": ["verify_addr_alignment", "data_shape:multi_kv_count:4"],
                        "assertion_evidence": [],
                        "rust_file": "flashDB_rust/tests/kvdb_tests.rs",
                        "rust_test": "kvdb_test_fdb_gc",
                    }
                ]
            }), encoding="utf-8")
            (tests_dir / "kvdb_tests.rs").write_text(
                "#[test]\n"
                "fn kvdb_test_fdb_gc() {\n"
                "    let result: Result<(), ()> = Ok(());\n"
                "    assert!(result.is_ok());\n"
                "}\n",
                encoding="utf-8",
            )

            report = checker.analyze_consistency(root)

            issue_codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("missing_assertion_evidence", issue_codes)
            self.assertIn("rust_assertion_count_below_threshold", issue_codes)
            self.assertIn("missing_direct_verify_obligation", issue_codes)
            self.assertIn("shallow_assertion_dominance", issue_codes)

    def test_gate_migrate_tests_runs_test_consistency_check(self):
        gate = PROJECT / "work" / "tools" / "gate.py"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "logs" / "trace"
            tests_dir = root / "flashDB_rust" / "tests"
            (root / "result" / "issues").mkdir(parents=True)
            trace.mkdir(parents=True)
            tests_dir.mkdir(parents=True)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            for rel_path in ["tests/kvdb_tests.rs", "tests/tsdb_tests.rs", "tests/equivalence_tests.rs"]:
                (root / "flashDB_rust" / rel_path).parent.mkdir(parents=True, exist_ok=True)
                (root / "flashDB_rust" / rel_path).write_text(
                    "#[test]\nfn kvdb_test_fdb_gc() { let result: Result<(), ()> = Ok(()); assert!(result.is_ok()); }\n",
                    encoding="utf-8",
                )
            state = {
                "current_stage": "MIGRATE_TESTS",
                "completed_stages": [
                    "BOOTSTRAP",
                    "INIT_WORKSPACE",
                    "READ_C_PROJECT",
                    "BUILD_C_MODEL",
                    "DESIGN_RUST_API",
                    "GENERATE_RUST_SCAFFOLD",
                    "REWRITE_CORE_MODULES",
                    "VERIFY_RUST_WITH_C_TESTS",
                    "MIGRATE_TESTS",
                ],
                "checkpoint": "MIGRATE_TESTS",
                "rust_project_path": "flashDB_rust",
                "input_path_candidates": ["/app/code/judge-assets/02_02_c_to_rust/code/FlashDB"],
                "input_path": "/tmp/fake/FlashDB",
                "input_manifest": "logs/trace/input_manifest.json",
                "c_project_model": "logs/trace/c_project_model.json",
                "c_api_model": "logs/trace/c_api_model.json",
                "c_test_model": "logs/trace/c_test_model.json",
                "rust_api_design": "logs/trace/rust_api_design.json",
                "rust_test_mapping": "logs/trace/rust_test_mapping.json",
                "build_status": "not_started",
                "test_status": "not_started",
                "unsafe_ratio": None,
                "repair_rounds": 0,
                "blocked_issues": [],
            }
            (trace / "workflow_state.json").write_text(json.dumps(state), encoding="utf-8")
            for name in [
                "01-init-workspace.md",
                "02-read-c-project.md",
                "03-build-c-model.md",
                "04-design-rust-api.md",
                "05-generate-rust-scaffold.md",
                "06-rewrite-core-modules.md",
                "06-5-verify-rust-with-c-tests.md",
                "07-migrate-tests.md",
                "input_manifest.json",
                "c_project_model.json",
                "c_api_model.json",
                "rust_api_design.json",
            ]:
                (trace / name).write_text("{}" if name.endswith(".json") else "# 阶段\n", encoding="utf-8")
            (trace / "c_test_model.json").write_text(json.dumps({
                "standard_scenarios": [
                    {"id": "test_fdb_gc", "name": "test_fdb_gc", "suite": "kvdb", "tags": ["kvdb", "gc"]}
                ],
                "scorer_standard_cases": [
                    {
                        "case_id": "10",
                        "case_name": "gc",
                        "scenario_id": "test_fdb_gc",
                        "suite": "kvdb",
                        "semantic_facts": {"assertion_count": 4},
                        "semantic_obligations": ["verify_addr_alignment"],
                    }
                ],
            }), encoding="utf-8")
            (trace / "rust_test_mapping.json").write_text(json.dumps({
                "kvdb": ["test_fdb_gc"],
                "tsdb": [],
                "extension": [],
                "unmapped": [],
                "total_scenarios": 1,
                "total_scorer_cases": 1,
                "source_to_rust": {"kvdb": "flashDB_rust/tests/kvdb_tests.rs"},
                "scenarios": [
                    {
                        "id": "test_fdb_gc",
                        "name": "test_fdb_gc",
                        "suite": "kvdb",
                        "scorer_case_id": "10",
                        "semantic_obligations": ["verify_addr_alignment"],
                        "validated_obligations": ["verify_addr_alignment"],
                        "coverage": "semantic",
                        "rust_file": "flashDB_rust/tests/kvdb_tests.rs",
                        "rust_test": "kvdb_test_fdb_gc",
                    }
                ],
            }), encoding="utf-8")

            failed = subprocess.run(
                [sys.executable, str(gate), "--stage", "MIGRATE_TESTS", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            self.assertNotEqual(0, failed.returncode)
            self.assertIn("test consistency failed", failed.stdout)
            self.assertIn("shallow_assertion_dominance", failed.stdout)


if __name__ == "__main__":
    unittest.main()
