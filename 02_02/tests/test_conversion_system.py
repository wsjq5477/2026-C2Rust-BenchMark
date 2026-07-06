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
            PROJECT / "work" / "agents" / "test-migrator.md",
            PROJECT / "work" / "agents" / "repairer.md",
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
            PROJECT / "work" / "tools" / "migrate_tests.py",
            PROJECT / "work" / "tools" / "cargo_capture.py",
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
            PROJECT / "work" / "skills" / "c-to-rust",
            PROJECT / "work" / "skills" / "dependency-analyzer.md",
            PROJECT / "work" / "skills" / "rust-translator.md",
            PROJECT / "work" / "skills" / "test-migrator.md",
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
            "work 目录仍为权威源",
            "opencode 不能在会话中把当前 primary agent 自切换为另一个 primary agent",
            "如果启动前已经选择 flashdb-orchestrator",
            "默认 Build agent 按普通 Markdown fallback 执行也满足本检查点",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, text)
        self.assertNotIn("必须立即使用 `@flashdb-orchestrator`", text)

    def test_agents_have_opencode_frontmatter(self):
        expected = {
            "flashdb-orchestrator.md": ("mode: primary", "description:"),
            "test-migrator.md": ("mode: subagent", "description:"),
            "repairer.md": ("mode: subagent", "description:"),
        }
        for filename, fragments in expected.items():
            text = (PROJECT / "work" / "agents" / filename).read_text(encoding="utf-8")
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
            "MIGRATE_TESTS",
            "BUILD_TEST_REPAIR",
            "REPORT_AND_VERIFY",
            "workflow_state.json",
            "input_manifest.json",
            "c_project_model.json",
            "c_api_model.json",
            "c_test_model.json",
            "rust_api_design.json",
            "rust_test_mapping.json",
            "final-verification.md",
            "flashDB_rust",
            "不得修改平台",
            "不得预置",
            "python3 work/tools/scan_c_project.py",
            "python3 work/tools/build_c_model.py",
            "python3 work/tools/design_rust_api.py",
            "python3 work/tools/generate_rust_scaffold.py",
            "python3 work/tools/migrate_tests.py",
            "python3 work/tools/cargo_capture.py",
            "python3 work/tools/unsafe_ratio.py",
            "python3 work/tools/report_writer.py",
            "python3 work/tools/gate.py --stage READ_C_PROJECT",
            "python3 work/tools/gate.py --stage BUILD_C_MODEL",
            "python3 work/tools/gate.py --stage DESIGN_RUST_API",
            "python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD",
            "python3 work/tools/gate.py --stage REWRITE_CORE_MODULES",
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
            "python3 work/tools/migrate_tests.py",
            "python3 work/tools/cargo_capture.py",
            "python3 work/tools/unsafe_ratio.py",
            "python3 work/tools/report_writer.py",
            "python3 work/tools/gate.py --stage INIT_WORKSPACE",
            "python3 work/tools/gate.py --stage READ_C_PROJECT",
            "python3 work/tools/gate.py --stage BUILD_C_MODEL",
            "python3 work/tools/gate.py --stage DESIGN_RUST_API",
            "python3 work/tools/gate.py --stage GENERATE_RUST_SCAFFOLD",
            "python3 work/tools/gate.py --stage REWRITE_CORE_MODULES",
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
        expected = {
            "flashdb-migration": "FlashDB C project modeling and Rust API migration",
            "flashdb-test-migration": "FlashDB C test migration",
            "rust-compile-repair": "Rust build or test failures",
            "flashdb-report": "FlashDB migration reports",
        }
        for skill_name, trigger_phrase in expected.items():
            path = PROJECT / "work" / "skills" / skill_name / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            self.assertIn(f"name: {skill_name}", text)
            self.assertIn("description: Use when", text)
            self.assertIn(trigger_phrase, text)
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
        self.assertEqual(["error", "flash", "kvdb", "tsdb"], design["modules"])
        for type_name in ["FlashStorage", "MemFlash", "FileFlash", "FdbError", "KvDb", "TsDb", "TslRecord"]:
            self.assertIn(type_name, design["core_types"])
        self.assertIn("FlashStorage", design["traits"])
        self.assertTrue(any(item["name"] == "set" for item in design["kvdb_api"]))
        self.assertTrue(any(item["name"] == "append" for item in design["tsdb_api"]))
        self.assertIn("Result<T, FdbError>", design["error_model"]["result_alias"])
        self.assertIn("MemFlash", design["storage_model"]["implementations"])
        self.assertIn("FileFlash", design["storage_model"]["implementations"])
        self.assertEqual("KvDb::open", design["c_to_rust_symbol_map"]["fdb_kvdb_init"])
        self.assertEqual("TsDb::open", design["c_to_rust_symbol_map"]["fdb_tsdb_init"])
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
            self.assertIn("KvDb", design["core_types"])

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
            self.assertTrue((root / "flashDB_rust" / "tests" / "kvdb_tests.rs").is_file())
            self.assertTrue((root / "flashDB_rust" / "tests" / "tsdb_tests.rs").is_file())

            cargo_test = subprocess.run(
                ["cargo", "test", "--quiet"],
                cwd=root / "flashDB_rust",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, cargo_test.returncode, cargo_test.stdout)

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
            test_model = {"kvdb_tests": [], "tsdb_tests": [], "extension_tests": [], "unclassified_tests": []}
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
                "07-migrate-tests.md",
                "08-build-test-repair.md",
                "09-report-and-verify.md",
                "final-verification.md",
            ]:
                (trace / name).write_text("# 阶段\n\n中文验证记录。\n", encoding="utf-8")

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
            self.assertIn("STATUS: SUCCESS", (root / "result" / "output.md").read_text(encoding="utf-8"))

            final_gate = subprocess.run(
                [sys.executable, str(gate), "--stage", "REPORT_AND_VERIFY", "--root", str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(0, final_gate.returncode, final_gate.stdout)
            self.assertIn("REPORT_AND_VERIFY: PASS", final_gate.stdout)


if __name__ == "__main__":
    unittest.main()
