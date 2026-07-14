import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "work" / "tools"


def load_tool(filename: str):
    path = TOOLS / filename
    module_name = "workflow_optimization_test_" + path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WORKFLOWCTL = load_tool("workflowctl.py")
SCAFFOLD = load_tool("generate_rust_scaffold.py")
CORE_AUDIT = load_tool("core_impl_audit.py")
REPAIR_PLANNER = load_tool("repair_planner.py")
C_CROSS = load_tool("c_cross_validate.py")
CONVERGE = load_tool("c_cross_converge.py")
TASK_PACKET = load_tool("task_packet.py")
C_MODEL = load_tool("build_c_model.py")
REPORT_WRITER = load_tool("report_writer.py")
GATE = load_tool("gate.py")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class WorkflowControllerContractTests(unittest.TestCase):
    def _init(self, root: Path) -> None:
        result = WORKFLOWCTL.cmd_init(
            argparse.Namespace(root=str(root), force=False, max_c_cross_repairs=6)
        )
        self.assertEqual(0, result)

    def _begin_read(self, root: Path, *, require_output=None):
        result = WORKFLOWCTL.cmd_begin(
            argparse.Namespace(
                root=str(root),
                stage="READ_C_PROJECT",
                agent="c-analyzer",
                allow_path=[],
                require_output=list(require_output or []),
                resume=False,
            )
        )
        self.assertEqual(0, result)
        state = json.loads(
            (root / "logs" / "trace" / "workflow_state.json").read_text(encoding="utf-8")
        )
        active = state["active_stage_run"]
        run = json.loads((root / active["run_file"]).read_text(encoding="utf-8"))
        return state, active, run

    def test_init_and_begin_bind_run_to_root_nonce_and_required_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._init(root)
            state, active, run = self._begin_read(
                root, require_output=["logs/trace/custom-proof.json"]
            )

            self.assertEqual(str(root), state["run_root"]["canonical"])
            self.assertEqual(str(root), run["root"]["canonical"])
            self.assertEqual(active["run_id"], run["run_id"])
            self.assertEqual(active["nonce"], run["nonce"])
            self.assertRegex(run["nonce"], r"^[0-9a-f]{32}$")
            self.assertIn("logs/trace/input_manifest.json", run["required_outputs"])
            self.assertIn("logs/trace/02-read-c-project.md", run["required_outputs"])
            self.assertIn("logs/trace/custom-proof.json", run["required_outputs"])
            self.assertIn("INSTRUCTION.md", run["monitored_patterns"])
            self.assertIn("work/**", run["monitored_patterns"])
            self.assertEqual("COMPLETE_READ_C_PROJECT", state["next_action"])

    def test_begin_rejects_additional_paths_that_escape_workbench_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._init(root)
            args = argparse.Namespace(
                root=str(root),
                stage="READ_C_PROJECT",
                agent="c-analyzer",
                allow_path=["../outside"],
                require_output=[],
                resume=False,
            )
            with self.assertRaisesRegex(WORKFLOWCTL.WorkflowError, "escapes workbench root"):
                WORKFLOWCTL.cmd_begin(args)

    def test_begin_rejects_glob_based_scope_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._init(root)
            args = argparse.Namespace(
                root=str(root),
                stage="READ_C_PROJECT",
                agent="c-analyzer",
                allow_path=["**"],
                require_output=[],
                resume=False,
            )
            with self.assertRaisesRegex(WORKFLOWCTL.WorkflowError, "exact files, not glob"):
                WORKFLOWCTL.cmd_begin(args)

    def test_rewrite_repair_reuses_original_scaffold_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._init(root)
            baseline = {"flashDB_rust/src/common.rs": "scaffold-hash"}
            origin_path = root / "logs" / "trace" / "stage-runs" / "REWRITE_CORE_MODULES" / "origin.json"
            write_json(origin_path, {
                "stage": "REWRITE_CORE_MODULES",
                "root": WORKFLOWCTL._root_identity(root),
                "baseline": baseline,
            })
            state_path = root / "logs" / "trace" / "workflow_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.update({
                "current_stage": "REWRITE_CORE_MODULES",
                "checkpoint": "REWRITE_CORE_MODULES",
                "next_action": "REPAIR_REWRITE_CORE_MODULES",
                "retry_baseline_run": {
                    "run_file": origin_path.relative_to(root).as_posix(),
                    "run_sha256": WORKFLOWCTL._sha256(origin_path),
                },
            })
            write_json(state_path, state)
            args = argparse.Namespace(
                root=str(root), stage="REWRITE_CORE_MODULES", agent="rust-implementer",
                allow_path=[], require_output=[], resume=False,
            )
            with mock.patch.object(WORKFLOWCTL, "_invoke_task_packet", return_value=None), mock.patch.object(
                WORKFLOWCTL, "_prepare_static_rewrite", return_value=None
            ):
                self.assertEqual(0, WORKFLOWCTL.cmd_begin(args))
            active = json.loads(state_path.read_text(encoding="utf-8"))["active_stage_run"]
            run = json.loads((root / active["run_file"]).read_text(encoding="utf-8"))
            self.assertEqual(baseline, run["baseline"])

    def test_finish_rejects_protected_or_out_of_scope_changes_before_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "INSTRUCTION.md").write_text("original\n", encoding="utf-8")
            self._init(root)
            _, active, _ = self._begin_read(root)
            (root / "INSTRUCTION.md").write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(
                WORKFLOWCTL.WorkflowError, "protected/out-of-scope files: INSTRUCTION.md"
            ):
                WORKFLOWCTL.cmd_finish(
                    argparse.Namespace(
                        root=str(root), run_id=active["run_id"], nonce=active["nonce"]
                    )
                )

    def test_finish_detects_new_unscoped_root_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._init(root)
            _, active, _ = self._begin_read(root)
            (root / "UNSCOPED.txt").write_text("not allowed\n", encoding="utf-8")
            with self.assertRaisesRegex(WORKFLOWCTL.WorkflowError, "UNSCOPED.txt"):
                WORKFLOWCTL.cmd_finish(
                    argparse.Namespace(root=str(root), run_id=active["run_id"], nonce=active["nonce"])
                )

    def test_finish_rejects_controller_state_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._init(root)
            _, active, _ = self._begin_read(root)
            state_path = root / "logs" / "trace" / "workflow_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["max_c_cross_repairs"] = 99
            write_json(state_path, state)
            with self.assertRaisesRegex(WORKFLOWCTL.WorkflowError, "modified outside workflowctl"):
                WORKFLOWCTL.cmd_finish(
                    argparse.Namespace(root=str(root), run_id=active["run_id"], nonce=active["nonce"])
                )

    def test_finish_requires_machine_declared_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._init(root)
            _, active, _ = self._begin_read(
                root, require_output=["logs/trace/custom-proof.json"]
            )

            with self.assertRaisesRegex(
                WORKFLOWCTL.WorkflowError, "stage is missing required outputs"
            ) as raised:
                WORKFLOWCTL.cmd_finish(
                    argparse.Namespace(
                        root=str(root), run_id=active["run_id"], nonce=active["nonce"]
                    )
                )
            message = str(raised.exception)
            self.assertIn("logs/trace/input_manifest.json", message)
            self.assertIn("logs/trace/custom-proof.json", message)

    def test_report_candidate_is_bound_to_active_controller_transaction(self):
        state = {
            "controller_contract_version": 1,
            "current_stage": "REPORT_AND_VERIFY",
            "checkpoint": "REPORT_AND_VERIFY",
            "next_action": "COMPLETE_REPORT_AND_VERIFY",
            "active_stage_run": {
                "stage": "REPORT_AND_VERIFY",
                "run_id": "run-report-1",
            },
        }
        self.assertTrue(REPORT_WRITER.controller_report_candidate(state))
        state["active_stage_run"] = None
        self.assertFalse(REPORT_WRITER.controller_report_candidate(state))
        self.assertTrue(REPORT_WRITER.controller_report_candidate({"current_stage": "DONE"}))

    def test_repair_budget_counts_only_code_repair_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempts = root / "logs" / "trace" / "c-cross" / "attempts.jsonl"
            attempts.parent.mkdir(parents=True)
            attempts.write_text(
                "\n".join(
                    json.dumps({"kind": kind})
                    for kind in ["checkpoint", "repair", "confirmation", "checkpoint", "repair"]
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(2, WORKFLOWCTL._repair_attempt_count(root))

    def test_report_writer_emits_success_inside_active_report_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "logs" / "trace"
            write_json(trace / "workflow_state.json", {
                "controller_contract_version": 1,
                "current_stage": "REPORT_AND_VERIFY",
                "checkpoint": "REPORT_AND_VERIFY",
                "next_action": "COMPLETE_REPORT_AND_VERIFY",
                "active_stage_run": {"stage": "REPORT_AND_VERIFY", "run_id": "report-1"},
                "build_status": "pass",
                "test_status": "pass",
                "blocked_issues": [],
            })
            write_json(trace / "cargo-results.json", {"build": {"returncode": 0}, "test": {"returncode": 0}})
            write_json(trace / "unsafe-ratio.json", {"unsafe_ratio": 0.01, "unsafe_lines": 1})
            write_json(trace / "rust_api_design.json", {"crate_name": "flashdb_rust", "modules": []})
            write_json(trace / "rust_test_mapping.json", {"total_scenarios": 1})
            write_json(trace / "test-placeholder-check.json", {"status": "pass", "issue_count": 0})
            write_json(trace / "test-consistency.json", {"status": "pass", "issue_count": 0})
            write_json(trace / "validation-matrix.json", {
                "mode": "full",
                "scope": "all",
                "attempt_kind": "final",
                "execution_id": "final-1",
                "total_scenarios": 1,
                "summary": {"rust_impl_c_test": {"pass": 1}},
                "scenarios": [{"scenario_id": "one", "rust_impl_c_test": "pass"}],
            })
            attempts = trace / "c-cross" / "attempts.jsonl"
            attempts.parent.mkdir(parents=True)
            attempts.write_text(json.dumps({"attempt_id": "final-1", "kind": "final"}) + "\n", encoding="utf-8")
            output = root / "result" / "output.md"
            issues = root / "result" / "issues" / "00-summary.md"
            REPORT_WRITER.write_report(root, output, issues)
            self.assertIn("STATUS: SUCCESS", output.read_text(encoding="utf-8"))

    def test_budget_exhaustion_routes_to_terminal_failure_instead_of_report_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "logs" / "trace" / "validation-matrix.json", {
                "scenarios": [{"scenario_id": "one", "rust_impl_c_test": "fail"}],
            })
            state = {"c_cross_functional_status": "budget_exhausted"}
            self.assertEqual(
                "DONE_WITH_FAILURES",
                WORKFLOWCTL._next_after("REPORT_AND_VERIFY", state, root, False),
            )

    def test_machine_repair_actions_are_directly_accepted_stage_aliases(self):
        for action in ["REPAIR_ABI_LAYOUT", "REANALYZE_C_MODEL", "ISOLATE_SCENARIOS", "REPAIR_RUST"]:
            self.assertEqual("VERIFY_RUST_WITH_C_TESTS", WORKFLOWCTL._stage_for_action(action))

    def test_status_emits_copyable_repair_and_active_finish_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init(root)
            state_path = root / "logs" / "trace" / "workflow_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.update(
                {
                    "current_stage": "VERIFY_RUST_WITH_C_TESTS",
                    "checkpoint": "VERIFY_RUST_WITH_C_TESTS",
                    "next_action": "REPAIR_ABI_LAYOUT",
                }
            )
            write_json(state_path, state)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                WORKFLOWCTL.cmd_status(argparse.Namespace(root=str(root), json=False))
            self.assertIn("begin --stage REPAIR_ABI_LAYOUT", output.getvalue())
            self.assertIn("--agent rust-implementer", output.getvalue())

            state["next_action"] = "COMPLETE_VERIFY_RUST_WITH_C_TESTS"
            state["active_stage_run"] = {
                "run_id": "verify-run-1",
                "nonce": "0123456789abcdef",
                "stage": "VERIFY_RUST_WITH_C_TESTS",
            }
            write_json(state_path, state)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                WORKFLOWCTL.cmd_status(argparse.Namespace(root=str(root), json=False))
            self.assertIn(
                "finish --run-id verify-run-1 --nonce 0123456789abcdef",
                output.getvalue(),
            )

    def test_test_repair_budget_has_report_terminal_path(self):
        state = {"test_repair_rounds": 8, "max_test_repairs": 8}
        self.assertEqual(
            "REPORT_AND_VERIFY",
            WORKFLOWCTL._next_after("BUILD_TEST_REPAIR", state, Path("."), False),
        )


class ScaffoldAndImplementationAuditTests(unittest.TestCase):
    def _fixture(self, root: Path):
        project = root / "flashDB_rust"
        design_path = root / "logs" / "trace" / "rust_api_design.json"
        manifest_path = root / "logs" / "trace" / "scaffold-manifest.json"
        design = {
            "modules": ["error", "kvdb"],
            "c_abi_facade": {
                "functions": [
                    {
                        "rust_export": "fdb_get",
                        "params": [{"name": "key", "rust_ffi_type": "*const u8"}],
                        "return": {"rust_ffi_type": "i32"},
                    }
                ]
            },
        }
        write_json(design_path, design)
        (project / "src" / "ffi").mkdir(parents=True)
        (project / "Cargo.toml").write_text("[package]\nname='fixture'\n", encoding="utf-8")
        (project / "src" / "ffi" / "c_abi.rs").write_text(
            "// @c2rust-scaffold:neutral-ffi:v1 symbol=fdb_get\n"
            "#[no_mangle]\n"
            "pub extern \"C\" fn fdb_get(key: *const u8) -> i32 {\n"
            "    0\n"
            "}\n",
            encoding="utf-8",
        )
        (project / "src" / "kvdb.rs").write_text(
            "// @c2rust-scaffold:placeholder-module:v1 module=kvdb\n"
            "pub fn kvdb_module_available() -> bool { true }\n",
            encoding="utf-8",
        )
        SCAFFOLD.write_scaffold_manifest(
            design=design,
            project=project,
            manifest_path=manifest_path,
            placeholder_modules=["kvdb"],
            design_path=design_path,
        )
        return project, design_path, manifest_path

    def _audit(self, root: Path, project: Path, design: Path, manifest: Path):
        return CORE_AUDIT.audit(
            root=root,
            project=project,
            manifest_path=manifest,
            design_path=design,
        )

    def test_manifest_and_audit_distinguish_scaffold_neutral_and_real_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, design, manifest = self._fixture(root)
            manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(["fdb_get"], manifest_doc["stub_symbols"])
            self.assertIn("body_normalized_sha256", manifest_doc["ffi_functions"]["fdb_get"])
            ownership = manifest_doc["rewrite_ownership"]
            self.assertIn("src/kvdb.rs", ownership["core_owned_paths"])
            self.assertIn("src/ffi/c_abi.rs", ownership["facade_owned_paths"])
            self.assertEqual("fdb_get", ownership["frozen_contract_symbols"][0]["symbol"])
            categories = [
                set(ownership[name])
                for name in [
                    "core_owned_paths",
                    "facade_owned_paths",
                    "frozen_contract_paths",
                    "shared_readonly_paths",
                ]
            ]
            self.assertEqual(sum(map(len, categories)), len(set().union(*categories)))
            self.assertEqual(
                [], GATE.check_rewrite_ownership_manifest(project, manifest_doc)
            )

            initial = self._audit(root, project, design, manifest)
            initial_codes = {finding["code"] for finding in initial["findings"]}
            self.assertEqual("fail", initial["status"])
            self.assertIn("unchanged_scaffold_body", initial_codes)
            self.assertIn("constant_only_neutral_body", initial_codes)
            self.assertIn("placeholder_module", initial_codes)

            (project / "src" / "ffi" / "c_abi.rs").write_text(
                "#[no_mangle]\n"
                "pub extern \"C\" fn fdb_get(key: *const u8) -> i32 {\n"
                "    return 1;\n"
                "}\n",
                encoding="utf-8",
            )
            (project / "src" / "kvdb.rs").write_text(
                "pub fn configured_sector_count(sectors: &[u8]) -> usize { sectors.len() }\n",
                encoding="utf-8",
            )
            changed_neutral = self._audit(root, project, design, manifest)
            changed_codes = {finding["code"] for finding in changed_neutral["findings"]}
            self.assertNotIn("unchanged_scaffold_body", changed_codes)
            self.assertIn("constant_only_neutral_body", changed_codes)
            self.assertNotIn("placeholder_module", changed_codes)

            (project / "src" / "ffi" / "c_abi.rs").write_text(
                "#[no_mangle]\n"
                "pub extern \"C\" fn fdb_get(key: *const u8) -> i32 {\n"
                "    if key.is_null() { -1 } else { unsafe { *key as i32 } }\n"
                "}\n",
                encoding="utf-8",
            )
            implemented = self._audit(root, project, design, manifest)
            self.assertEqual("pass", implemented["status"], implemented["findings"])

            changed_signature = (project / "src" / "ffi" / "c_abi.rs").read_text(
                encoding="utf-8"
            ).replace(") -> i32", ") -> i64")
            (project / "src" / "ffi" / "c_abi.rs").write_text(
                changed_signature, encoding="utf-8"
            )
            signature_errors = GATE.check_rewrite_ownership_manifest(project, manifest_doc)
            self.assertTrue(
                any("frozen external signature changed" in item for item in signature_errors)
            )

    def test_frozen_signature_treats_rust_trailing_parameter_comma_as_equivalent(self):
        source = (
            "#[no_mangle]\n"
            "pub extern \"C\" fn fixture_export(\n"
            "    value: i32,\n"
            ") -> i32 {\n"
            "    value\n"
            "}\n"
        )
        self.assertEqual(
            "fixture_export(value:i32)->i32",
            GATE.extract_current_ffi_signature(source, "fixture_export"),
        )

    def test_abi_arrays_and_anonymous_aggregates_use_exact_byte_storage(self):
        array = {
            "ctype": "uint32_t",
            "kind": "array",
            "raw_declarator": "uint32_t values[4]",
            "sizeof": 16,
            "offset": 4,
            "alignof": 4,
        }
        anonymous = {
            "ctype": "union { uint32_t a; uint64_t b; }",
            "kind": "anonymous_union",
            "sizeof": 8,
            "offset": 20,
            "alignof": 4,
        }
        legacy_array = {
            "ctype": "uint32_t",
            "raw_declarator": "uint32_t values[4]",
            "sizeof": 16,
            "offset": 4,
        }
        self.assertEqual("[u8; 16]", SCAFFOLD.rust_field_type(array))
        self.assertEqual("[u8; 8]", SCAFFOLD.rust_field_type(anonymous))
        self.assertEqual("[u8; 16]", SCAFFOLD.rust_field_type(legacy_array))

        design = {
            "c_abi_facade": {
                "structs": [
                    {
                        "c_name": "fdb_weird_t",
                        "rust_name": "FdbWeird",
                        "sizeof": 40,
                        "alignof": 8,
                        "fields": [
                            {
                                "name": "count",
                                "ctype": "uint32_t",
                                "kind": "scalar",
                                "raw_declarator": "uint32_t count",
                                "sizeof": 4,
                                "offset": 0,
                                "alignof": 4,
                            },
                            {"name": "values", **array},
                            {"name": "choice", **anonymous},
                            {
                                "name": "next ptr",
                                "ctype": "void *",
                                "kind": "pointer",
                                "raw_declarator": "void *next_ptr",
                                "sizeof": 8,
                                "offset": 32,
                                "alignof": 8,
                            },
                        ],
                    }
                ]
            }
        }
        generated = SCAFFOLD.generate_c_types(design)
        self.assertIn("#[repr(align(8))]", generated)
        self.assertIn("pub values: [u8; 16]", generated)
        self.assertIn("pub choice: [u8; 8]", generated)
        self.assertIn("pub _pad_0: [u8; 4]", generated)
        self.assertIn("pub next_ptr: *mut std::ffi::c_void", generated)
        self.assertEqual("fdb_kv_type_0", SCAFFOLD.c_symbol_suffix("FDB.KV/type[0]"))
        self.assertEqual("FdbKvTypeT", SCAFFOLD.safe_rust_type("_fdb-kv/type_t"))

    def test_abi_only_regeneration_cannot_overwrite_core_implementation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "flashDB_rust"
            ffi = project / "src" / "ffi"
            ffi.mkdir(parents=True)
            core = project / "src" / "storage.rs"
            facade = ffi / "c_abi.rs"
            core.write_text("pub fn persisted() -> bool { true }\n", encoding="utf-8")
            facade.write_text(
                "pub extern \"C\" fn fdb_real() -> i32 { 7 }\n", encoding="utf-8"
            )
            (ffi / "c_types.rs").write_text("stale types\n", encoding="utf-8")
            (ffi / "layout_probe.rs").write_text("stale probe\n", encoding="utf-8")
            design_path = root / "rust_api_design.json"
            write_json(design_path, {"c_abi_facade": {"structs": [], "functions": []}})

            before = {core: core.read_bytes(), facade: facade.read_bytes()}
            result = SCAFFOLD.main(
                [
                    "--design",
                    str(design_path),
                    "--project",
                    str(project),
                    "--abi-only",
                ]
            )

            self.assertEqual(0, result)
            self.assertEqual(before[core], core.read_bytes())
            self.assertEqual(before[facade], facade.read_bytes())
            self.assertNotEqual("stale types\n", (ffi / "c_types.rs").read_text(encoding="utf-8"))
            self.assertNotEqual(
                "stale probe\n", (ffi / "layout_probe.rs").read_text(encoding="utf-8")
            )
            self.assertFalse((project / "Cargo.toml").exists())


class StaticRewriteControllerTests(unittest.TestCase):
    def _prepare(self, root: Path) -> tuple[Path, dict]:
        self.assertEqual(
            0,
            WORKFLOWCTL.cmd_init(
                argparse.Namespace(root=str(root), force=False, max_c_cross_repairs=6)
            ),
        )
        project = root / "flashDB_rust"
        design_path = root / "logs" / "trace" / "rust_api_design.json"
        manifest_path = root / "logs" / "trace" / "scaffold-manifest.json"
        design = {
            "crate_name": "static_rewrite_fixture",
            "modules": ["error", "core_model"],
            "implementation_requirements": [
                {
                    "id": "REQ-1",
                    "invariant": "Values written to the model can be read back.",
                    "symbols": ["model_set", "model_get"],
                    "acceptance_scenarios": ["set_then_get"],
                    "suggested_files": ["src/core_model.rs"],
                    "dependency_ids": [],
                }
            ],
            "c_abi_facade": {
                "functions": [
                    {
                        "rust_export": "fixture_export",
                        "params": [],
                        "return": {"rust_ffi_type": "i32"},
                    }
                ]
            },
        }
        write_json(design_path, design)
        write_json(root / "logs" / "trace" / "c_test_model.json", {})
        SCAFFOLD.generate_project(
            design,
            project,
            manifest_path=manifest_path,
            design_path=design_path,
        )
        state_path = root / "logs" / "trace" / "workflow_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update(
            {
                "current_stage": "GENERATE_RUST_SCAFFOLD",
                "checkpoint": "GENERATE_RUST_SCAFFOLD",
                "next_action": "REWRITE_CORE_MODULES",
            }
        )
        write_json(state_path, state)
        return project, design

    def _packet(self, root: Path, role: str) -> str:
        design = json.loads(
            (root / "logs" / "trace" / "rust_api_design.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (root / "logs" / "trace" / "scaffold-manifest.json").read_text(encoding="utf-8")
        )
        packet = TASK_PACKET.build_task_packet(
            "REWRITE_CORE_MODULES", design, {}, None, rust_project="flashDB_rust"
        )
        TASK_PACKET.apply_static_rewrite_role(packet, manifest, role, "flashDB_rust")
        packet.pop("source_artifacts", None)
        path = (
            root
            / "logs"
            / "trace"
            / "task-packets"
            / f"rewrite_core_modules-{role.lower()}.json"
        )
        write_json(path, packet)
        return path.relative_to(root).as_posix()

    def _begin_parent(self, root: Path) -> dict:
        with mock.patch.object(WORKFLOWCTL, "_invoke_task_packet", return_value=None):
            self.assertEqual(
                0,
                WORKFLOWCTL.cmd_begin(
                    argparse.Namespace(
                        root=str(root),
                        stage="REWRITE_CORE_MODULES",
                        agent="rust-implementer",
                        allow_path=[],
                        require_output=[],
                        resume=False,
                    )
                ),
            )
        return json.loads(
            (root / "logs" / "trace" / "workflow_state.json").read_text(encoding="utf-8")
        )["active_stage_run"]

    def _begin_worker(self, root: Path, *, packet_padding_bytes: int = 0) -> dict:
        def fake_packet(_root, _stage, action=None, rewrite_role=None):
            self.assertIsNotNone(rewrite_role)
            relative = self._packet(root, rewrite_role)
            if packet_padding_bytes:
                packet_path = root / relative
                packet = json.loads(packet_path.read_text(encoding="utf-8"))
                packet["test_only_padding"] = "x" * packet_padding_bytes
                write_json(packet_path, packet)
            return relative

        with mock.patch.object(WORKFLOWCTL, "_invoke_task_packet", side_effect=fake_packet):
            self.assertEqual(
                0,
                WORKFLOWCTL.cmd_next_rewrite_worker(argparse.Namespace(root=str(root))),
            )
        return json.loads(
            (root / "logs" / "trace" / "rewrite-state.json").read_text(encoding="utf-8")
        )["active_worker"]

    def _finish_worker(self, root: Path, active: dict) -> int:
        run = json.loads((root / active["run_file"]).read_text(encoding="utf-8"))
        write_json(
            root
            / "logs"
            / "trace"
            / "rewrite-check"
            / run["role"].lower()
            / str(run["attempt"])
            / "result.json",
            {
                "schema_version": 1,
                "role": run["role"],
                "revision": run["attempt"],
                "status": "pass",
                "phases": [],
            },
        )
        completed = argparse.Namespace(returncode=0, stdout="{}")
        with mock.patch.object(WORKFLOWCTL.subprocess, "run", return_value=completed):
            return WORKFLOWCTL.cmd_finish_rewrite_worker(
                argparse.Namespace(
                    root=str(root),
                    worker_run_id=active["worker_run_id"],
                    nonce=active["nonce"],
                    status="complete",
                )
            )

    def test_static_rewrite_enforces_owner_order_and_forward_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            project, _ = self._prepare(root)
            self._begin_parent(root)

            core_worker = self._begin_worker(root)
            self.assertEqual("IMPLEMENT_CORE", core_worker["role"])
            (project / "src" / "core_model.rs").write_text(
                "pub fn model_ready() -> bool { true }\n", encoding="utf-8"
            )
            self.assertEqual(0, self._finish_worker(root, core_worker))
            rewrite = json.loads(
                (root / "logs" / "trace" / "rewrite-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("FACADE", rewrite["phase"])
            self.assertEqual(1, rewrite["core_revision"])

            facade_worker = self._begin_worker(root)
            self.assertEqual("WIRE_FACADE", facade_worker["role"])
            (project / "src" / "ffi" / "c_abi.rs").write_text(
                '#[no_mangle]\npub extern "C" fn fixture_export() -> i32 { 7 }\n',
                encoding="utf-8",
            )
            self.assertEqual(0, self._finish_worker(root, facade_worker))
            rewrite = json.loads(
                (root / "logs" / "trace" / "rewrite-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("READY", rewrite["phase"])
            self.assertEqual(1, rewrite["facade_revision"])
            self.assertEqual(1, rewrite["facade_based_on_core_revision"])

    def test_static_rewrite_rejects_cross_owner_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            project, _ = self._prepare(root)
            self._begin_parent(root)
            active = self._begin_worker(root)
            (project / "src" / "ffi" / "c_abi.rs").write_text(
                '#[no_mangle]\npub extern "C" fn fixture_export() -> i32 { 9 }\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(WORKFLOWCTL.WorkflowError, "another owner/frozen"):
                self._finish_worker(root, active)

    def test_static_worker_dispatch_does_not_gate_on_packet_file_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._prepare(root)
            self._begin_parent(root)

            active = self._begin_worker(root, packet_padding_bytes=32 * 1024)

            self.assertEqual("IMPLEMENT_CORE", active["role"])

    def test_static_retry_packet_carries_bounded_failure_and_cumulative_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            project, _ = self._prepare(root)
            self._begin_parent(root)
            first = self._begin_worker(root)
            (project / "src" / "core_model.rs").write_text(
                "pub fn model_ready() -> bool { true }\n", encoding="utf-8"
            )
            first_run = json.loads((root / first["run_file"]).read_text(encoding="utf-8"))
            first_result = (
                root
                / "logs"
                / "trace"
                / "rewrite-check"
                / first_run["role"].lower()
                / str(first_run["attempt"])
                / "result.json"
            )
            write_json(
                first_result,
                {
                    "schema_version": 1,
                    "role": "IMPLEMENT_CORE",
                    "revision": 1,
                    "status": "fail",
                    "phases": [
                        {
                            "phase": "check",
                            "status": "fail",
                            "exit_code": 101,
                            "log_path": "logs/trace/rewrite-check/implement_core/1/check.log",
                            "tail": "missing internal method",
                        }
                    ],
                },
            )
            failed = argparse.Namespace(returncode=1, stdout="failed")
            with mock.patch.object(WORKFLOWCTL.subprocess, "run", return_value=failed):
                self.assertEqual(
                    0,
                    WORKFLOWCTL.cmd_finish_rewrite_worker(
                        argparse.Namespace(
                            root=str(root),
                            worker_run_id=first["worker_run_id"],
                            nonce=first["nonce"],
                            status="complete",
                            reason=None,
                        )
                    ),
                )

            second = self._begin_worker(root)
            second_run = json.loads((root / second["run_file"]).read_text(encoding="utf-8"))
            packet = json.loads((root / second_run["packet"]).read_text(encoding="utf-8"))
            self.assertIn("missing internal method", json.dumps(packet["retry_context"]))
            command = packet["completion_contract"]["command"]
            self.assertIn(second["worker_run_id"], command)
            self.assertNotIn("<WORKER_", command)

            self.assertEqual(0, self._finish_worker(root, second))
            rewrite = json.loads(
                (root / "logs" / "trace" / "rewrite-state.json").read_text(encoding="utf-8")
            )
            receipt = json.loads(
                (root / rewrite["latest_receipts"]["IMPLEMENT_CORE"]).read_text(encoding="utf-8")
            )
            self.assertEqual([], receipt["attempt_changed_files"])
            self.assertEqual(
                ["flashDB_rust/src/core_model.rs"], receipt["changed_files"]
            )

    def test_static_role_packets_have_disjoint_write_scopes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._prepare(root)
            design = json.loads(
                (root / "logs" / "trace" / "rust_api_design.json").read_text(encoding="utf-8")
            )
            design["implementation_requirements"][0]["suggested_files"] = [
                "src/core_model.rs",
                "src/c_abi.rs",
            ]
            manifest = json.loads(
                (root / "logs" / "trace" / "scaffold-manifest.json").read_text(encoding="utf-8")
            )
            core = TASK_PACKET.build_task_packet(
                "REWRITE_CORE_MODULES", design, {}, None, rust_project="flashDB_rust"
            )
            facade = TASK_PACKET.build_task_packet(
                "REWRITE_CORE_MODULES", design, {}, None, rust_project="flashDB_rust"
            )
            TASK_PACKET.apply_static_rewrite_role(core, manifest, "IMPLEMENT_CORE", "flashDB_rust")
            TASK_PACKET.apply_static_rewrite_role(facade, manifest, "WIRE_FACADE", "flashDB_rust")
            self.assertTrue(
                set(core["allowed_modification_paths"]).isdisjoint(
                    facade["allowed_modification_paths"]
                )
            )
            self.assertTrue(core["requirements"])
            self.assertEqual([], facade["requirements"])
            self.assertTrue(facade["facade_contracts"])
            self.assertEqual([], core["evidence_paths"])
            self.assertNotIn("src/c_abi.rs", core["requirements"][0]["suggested_files"])
            self.assertIn(
                "src/c_abi.rs", core["requirements"][0]["non_writable_dependencies"]
            )

    def test_core_role_packet_keeps_all_model_derived_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._prepare(root)
            design_path = root / "logs" / "trace" / "rust_api_design.json"
            design = json.loads(design_path.read_text(encoding="utf-8"))
            design["implementation_requirements"] = [
                {
                    "id": f"REQ-{index}",
                    "invariant": f"model-derived invariant {index}",
                    "symbols": [f"symbol_{index}"],
                    "acceptance_scenarios": [f"scenario_{index}"],
                    "suggested_files": ["src/core_model.rs"],
                    "dependency_ids": [],
                }
                for index in range(15)
            ]
            write_json(design_path, design)
            output = root / "logs" / "trace" / "task-packets" / "all-core.json"
            self.assertEqual(
                0,
                TASK_PACKET.main(
                    [
                        "--root",
                        str(root),
                        "--stage",
                        "REWRITE_CORE_MODULES",
                        "--rewrite-role",
                        "IMPLEMENT_CORE",
                        "--output",
                        str(output),
                    ]
                ),
            )
            packet = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(15, len(packet["requirements"]))
            self.assertEqual([], packet["selection"]["omitted_requirement_ids"])


class RepairAndAttemptRoutingTests(unittest.TestCase):
    def test_repair_plan_prioritizes_layout_then_behavior_and_scopes_evidence(self):
        matrix = {
            "execution_id": "attempt-3",
            "attempt_kind": "repair",
            "selected_suites": [],
            "scenarios": [
                {
                    "scenario_id": "layout_fdb_kvdb_t",
                    "suite": "layout",
                    "rust_impl_c_test": "fail",
                    "diagnosis": "c_abi_layout_mismatch",
                    "failure_layer": "layout",
                    "log": "logs/trace/c-cross/layout.log",
                },
                {
                    "scenario_id": "test_gc",
                    "suite": "kvdb",
                    "rust_impl_c_test": "fail",
                    "diagnosis": "c_test_case_failed",
                    "failure_layer": "full",
                    "log": "logs/trace/c-cross/test_gc.log",
                    "repair_context": {
                        "public_api_calls": ["fdb_kv_set", "fdb_kv_get"],
                        "semantic_obligations": ["latest-write-wins"],
                    },
                },
                {
                    "scenario_id": "test_already_ok",
                    "suite": "kvdb",
                    "rust_impl_c_test": "pass",
                },
            ],
        }
        plan = REPAIR_PLANNER.build_repair_plan(matrix)
        self.assertEqual("repair_required", plan["status"])
        self.assertEqual("REPAIR_ABI_LAYOUT", plan["next_action"])
        self.assertEqual(2, plan["failure_count"])
        self.assertEqual("layout", plan["tasks"][0]["failure_layer"])
        self.assertEqual("abi-layout-tool", plan["tasks"][0]["target_agent"])
        self.assertEqual("rust-implementer", plan["tasks"][1]["target_agent"])
        self.assertEqual(["fdb_kv_get", "fdb_kv_set"], plan["tasks"][1]["affected_symbols"])
        self.assertEqual(["latest-write-wins"], plan["tasks"][1]["requirements"])
        self.assertIn("--suite kvdb", plan["tasks"][1]["verification_command"])

    def test_runtime_not_run_is_routed_to_scenario_isolation(self):
        matrix = {
            "execution_id": "attempt-crash",
            "scenarios": [
                {
                    "scenario_id": "test_after_crash",
                    "suite": "tsdb",
                    "rust_impl_c_test": "not_run",
                    "diagnosis": "c_runner_runtime_failed",
                    "failure_layer": "runtime",
                    "reason": "runner terminated before scenario",
                    "log": "logs/trace/c-cross/tsdb.log",
                }
            ],
        }
        plan = REPAIR_PLANNER.build_repair_plan(matrix)
        self.assertEqual("ISOLATE_SCENARIOS", plan["next_action"])
        self.assertEqual(1, len(plan["isolation_queue"]))
        entry = plan["isolation_queue"][0]
        self.assertEqual("test_after_crash", entry["scenario_id"])
        self.assertIn("--scenario test_after_crash", entry["command"])

    def test_attempt_comparison_detects_progress_and_protects_prior_passes(self):
        previous = {
            "scenarios": [
                {"scenario_id": "stable", "rust_impl_c_test": "pass"},
                {
                    "scenario_id": "repair_me",
                    "suite": "kvdb",
                    "rust_impl_c_test": "fail",
                    "failure_layer": "build",
                    "reason": "undefined symbol at 0x1234",
                },
            ]
        }
        progressed = {
            "scenarios": [
                {"scenario_id": "stable", "rust_impl_c_test": "pass"},
                {"scenario_id": "repair_me", "rust_impl_c_test": "pass"},
            ]
        }
        comparison = C_CROSS.compare_attempt(previous, progressed)
        self.assertTrue(comparison["progress"])
        self.assertFalse(comparison["regression"])

        regressed = {
            "scenarios": [
                {
                    "scenario_id": "stable",
                    "suite": "kvdb",
                    "rust_impl_c_test": "fail",
                    "failure_layer": "full",
                    "reason": "wrong value at 0x9999",
                },
                {"scenario_id": "repair_me", "rust_impl_c_test": "pass"},
            ]
        }
        comparison = C_CROSS.compare_attempt(previous, regressed)
        self.assertTrue(comparison["regression"])
        self.assertFalse(comparison["progress"])
        self.assertEqual(
            C_CROSS.failure_fingerprint(
                {
                    "scenario_id": "x",
                    "suite": "kvdb",
                    "failure_layer": "full",
                    "reason": "bad pointer 0x1111",
                }
            ),
            C_CROSS.failure_fingerprint(
                {
                    "scenario_id": "x",
                    "suite": "kvdb",
                    "failure_layer": "full",
                    "reason": "bad pointer 0xFFFF",
                }
            ),
        )

    def test_convergence_packet_routes_regression_to_explicit_best_restore(self):
        packet = CONVERGE.build_task_packet(
            {"execution_id": "attempt-7", "verification_result": "fail"},
            {"tasks": [{"task_id": "repair-01", "target_agent": "rust-implementer"}]},
            [
                {
                    "kind": "repair",
                    "regression": True,
                    "restore_best_available": True,
                    "best_known": {"attempt_id": "attempt-5", "score": [10, 0, 0, 0]},
                    "stalled_rounds": 1,
                }
            ],
            {"queue": []},
            max_rounds=8,
        )
        self.assertEqual("RESTORE_BEST", packet["next_action"])
        self.assertEqual("controller", packet["task"]["target_agent"])
        self.assertIn("--restore-best", packet["task"]["verification_command"])
        self.assertEqual(7, packet["round_budget"]["remaining"])


class ScenarioIrAndTaskPacketTests(unittest.TestCase):
    def test_scenario_ir_preserves_helper_callback_public_api_and_assertion_order(self):
        source = """
static void iter_cb(void *ctx) {
    fdb_kv_get(ctx, "k");
    TEST_ASSERT_TRUE(ctx != 0);
}
static void helper(void *db) {
    fdb_kv_set(db, "k", "v");
}
void test_demo(void) {
    helper(0);
    fdb_kv_iterate(0, iter_cb, 0);
    TEST_ASSERT_EQUAL(1, fdb_kv_get(0, "k"));
}
"""
        records = C_MODEL.extract_function_body_records(source, "tests/demo.c")
        steps = C_MODEL.build_scenario_ir(
            "test_demo",
            "test_demo",
            {
                "source_file": "tests/demo.c",
                "registration_source_file": "tests/runner.c",
                "source_line": 44,
                "runner": "tests/runner.c",
            },
            records,
            {"fdb_kv_get", "fdb_kv_set", "fdb_kv_iterate"},
        )
        self.assertEqual(list(range(1, len(steps) + 1)), [step["order"] for step in steps])
        self.assertEqual(
            [f"test_demo:s{index:03d}" for index in range(1, len(steps) + 1)],
            [step["id"] for step in steps],
        )
        calls = [step["call"] for step in steps]
        self.assertLess(calls.index("helper"), calls.index("fdb_kv_set"))
        self.assertLess(calls.index("fdb_kv_iterate"), calls.index("iter_cb"))
        self.assertIn("TEST_ASSERT_TRUE", calls)
        self.assertIn("TEST_ASSERT_EQUAL", calls)
        callback = next(step for step in steps if step["kind"] == "callback_dispatch")
        self.assertEqual("iter_cb", callback["call"])
        self.assertEqual("iterator_callback", callback["call_type"])

    def test_task_packet_is_bounded_and_follows_repair_focus_with_dependencies(self):
        design = {
            "input_digest": "digest-1",
            "implementation_requirements": [
                {
                    "id": "REQ-BASE",
                    "invariant": "database must be initialized before writes",
                    "symbols": ["fdb_init"],
                    "acceptance_scenarios": ["scenario_boot"],
                },
                {
                    "id": "REQ-WRITE",
                    "invariant": "new value replaces prior value",
                    "symbols": ["fdb_kv_set"],
                    "acceptance_scenarios": ["scenario_write"],
                    "dependency_ids": ["REQ-BASE"],
                },
                {
                    "id": "REQ-EXTRA",
                    "invariant": "unrelated requirement",
                    "symbols": ["fdb_tsl_append"],
                    "acceptance_scenarios": ["scenario_tsl"],
                },
            ],
        }
        test_model = {
            "input_digest": "digest-1",
            "standard_scenarios": [
                {
                    "id": "scenario_boot",
                    "name": "test_boot",
                    "suite": "kvdb",
                    "order": 1,
                    "scenario_ir": [
                        {"id": "boot:s001", "order": 1, "kind": "call", "call": "fdb_init", "call_type": "public_api"}
                    ],
                },
                {
                    "id": "scenario_write",
                    "name": "test_write",
                    "suite": "kvdb",
                    "order": 2,
                    "scenario_ir": [
                        {"id": "write:s001", "order": 1, "kind": "invoke_test", "call": "test_write"},
                        {"id": "write:s002", "order": 2, "kind": "call", "call": "fdb_kv_set", "call_type": "public_api"},
                        {"id": "write:s003", "order": 3, "kind": "assertion", "call": "TEST_ASSERT_EQUAL", "expression": "expected, actual"},
                    ],
                },
                {
                    "id": "scenario_tsl",
                    "name": "test_tsl",
                    "suite": "tsdb",
                    "order": 3,
                    "scenario_ir": [],
                },
            ],
        }
        repair_plan = {
            "tasks": [
                {
                    "status": "pending",
                    "requirements": ["REQ-WRITE"],
                    "scenario_ids": ["scenario_write"],
                    "affected_symbols": ["fdb_kv_set"],
                    "allowed_edit_scope": ["flashDB_rust/src/kvdb.rs"],
                }
            ]
        }
        packet = TASK_PACKET.build_task_packet(
            "VERIFY_RUST_WITH_C_TESTS",
            design,
            test_model,
            repair_plan,
            max_requirements=2,
            max_scenarios=1,
            max_steps=3,
        )
        self.assertEqual(["REQ-BASE", "REQ-WRITE"], [item["id"] for item in packet["requirements"]])
        self.assertEqual(["scenario_write"], [item["id"] for item in packet["scenarios"]])
        self.assertEqual([1, 2, 3], [step["order"] for step in packet["scenarios"][0]["scenario_ir"]])
        self.assertIn("fdb_init", packet["symbols"])
        self.assertIn("fdb_kv_set", packet["symbols"])
        self.assertTrue(packet["selection"]["bounded"])
        self.assertIn("REQ-EXTRA", packet["selection"]["omitted_requirement_ids"])
        self.assertIn("scenario_tsl", packet["selection"]["omitted_scenario_ids"])
        self.assertEqual(
            ["flashDB_rust/src/kvdb.rs", "logs/trace/**"],
            packet["allowed_modification_paths"],
        )
        repair_command = packet["verification_commands"][-1]
        self.assertIn("--attempt-kind repair", repair_command)
        self.assertIn("--changed-file <flashDB_rust/src/changed-file.rs>", repair_command)

    def test_task_packet_contract_matches_controller_and_supplies_evidence(self):
        contract = TASK_PACKET.load_workflow_contract()
        self.assertEqual(WORKFLOWCTL.PROTECTED_PATHS, contract["protected_paths"])
        self.assertEqual(WORKFLOWCTL.STAGE_ALLOWED_PATHS, {
            stage: value["allowed_paths"] for stage, value in contract["stages"].items()
        })
        self.assertEqual(WORKFLOWCTL.STAGE_REQUIRED_OUTPUTS, {
            stage: value["required_outputs"] for stage, value in contract["stages"].items()
        })
        for stage, stage_contract in contract["stages"].items():
            packet = TASK_PACKET.build_task_packet(stage, {}, {})
            self.assertEqual(stage_contract["allowed_paths"], packet["allowed_modification_paths"])
            self.assertEqual(stage_contract["required_outputs"], packet["evidence_paths"])

    def test_task_packet_contract_defaults_bound_scenarios_and_steps(self):
        test_model = {
            "standard_scenarios": [
                {
                    "id": f"scenario-{scenario_index}",
                    "order": scenario_index,
                    "scenario_ir": [
                        {
                            "id": f"scenario-{scenario_index}:s{step_index:03d}",
                            "order": step_index,
                            "kind": "assertion",
                            "call": "TEST_ASSERT_TRUE",
                        }
                        for step_index in range(1, 21)
                    ],
                }
                for scenario_index in range(1, 6)
            ]
        }
        packet = TASK_PACKET.build_task_packet("BUILD_C_MODEL", {}, test_model)
        self.assertEqual(3, len(packet["scenarios"]))
        self.assertTrue(all(len(item["scenario_ir"]) == 16 for item in packet["scenarios"]))

    def test_verify_without_repair_plan_uses_checkpoint_contract(self):
        packet = TASK_PACKET.build_task_packet("VERIFY_RUST_WITH_C_TESTS", {}, {})
        self.assertEqual(
            ["flashDB_rust/src/**", "logs/trace/**"],
            packet["allowed_modification_paths"],
        )
        command = packet["verification_commands"][-1]
        self.assertIn("--attempt-kind checkpoint", command)
        self.assertNotIn("--changed-file", command)

    def test_task_packet_rejects_mixed_input_versions(self):
        with self.assertRaisesRegex(ValueError, "input_digest values do not match"):
            TASK_PACKET.build_task_packet(
                "REWRITE_CORE_MODULES",
                {"input_digest": "design-a", "implementation_requirements": []},
                {"input_digest": "tests-b", "standard_scenarios": []},
            )

    def test_report_task_packet_allows_only_final_report_outputs(self):
        packet = TASK_PACKET.build_task_packet("REPORT_AND_VERIFY", {}, {})
        self.assertEqual(
            ["logs/trace/**", "result/**"],
            packet["allowed_modification_paths"],
        )
        self.assertEqual("workflowctl", packet["completion_contract"]["owner"])
        commands = "\n".join(packet["verification_commands"])
        self.assertIn("--attempt-kind final", commands)
        self.assertIn("report_writer.py", commands)
        self.assertNotIn("gate.py", commands)
        self.assertTrue(any("non-zero" in note for note in packet["command_notes"]))

    def test_stage_packets_are_self_contained_business_command_lists(self):
        expected_tools = {
            "READ_C_PROJECT": "scan_c_project.py",
            "BUILD_C_MODEL": "build_c_model.py",
            "DESIGN_RUST_API": "design_rust_api.py",
            "GENERATE_RUST_SCAFFOLD": "generate_rust_scaffold.py",
            "MIGRATE_TESTS": "migrate_tests.py",
            "BUILD_TEST_REPAIR": "cargo_capture.py",
        }
        for stage, tool in expected_tools.items():
            with self.subTest(stage=stage):
                packet = TASK_PACKET.build_task_packet(stage, {}, {})
                commands = "\n".join(packet["verification_commands"])
                self.assertIn(tool, commands)
                self.assertNotIn("gate.py", commands)

    def test_read_packet_resolves_controller_captured_source_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "platform input" / "FlashDB"
            write_json(
                root / "logs" / "trace" / "workflow_state.json",
                {"input_source_root": str(source)},
            )
            output = root / "logs" / "trace" / "task-packets" / "read.json"
            self.assertEqual(
                0,
                TASK_PACKET.main(
                    [
                        "--root",
                        str(root),
                        "--stage",
                        "READ_C_PROJECT",
                        "--output",
                        str(output),
                    ]
                ),
            )
            packet = json.loads(output.read_text(encoding="utf-8"))
            command = packet["verification_commands"][0]
            self.assertNotIn("$FLASHDB_SOURCE", command)
            self.assertIn(str(source), command)
            self.assertEqual(str(source), packet["runtime_context"]["flashdb_source"])


if __name__ == "__main__":
    unittest.main()
