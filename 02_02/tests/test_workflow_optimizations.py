import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "work" / "tools"
TEST_TEMP_ROOT = PROJECT / "logs" / "trace" / "tmp" / "tests"


def project_temp_directory():
    TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="workflow-optimizations-", dir=TEST_TEMP_ROOT)


def load_tool(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location("simplified_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


REPORT = load_tool("report_writer.py")
GATE = load_tool("gate.py")
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


def write_test_repair_evidence(root: Path, *, repairs_used: int) -> None:
    trace = root / "logs" / "trace"
    cargo_path = trace / "cargo-results.json"
    cargo = json.loads(cargo_path.read_text(encoding="utf-8"))
    test_result = cargo.get("test") if isinstance(cargo.get("test"), dict) else {}
    test_result["returncode"] = int(test_result.get("returncode", 0 if cargo.get("test_status") == "pass" else 1))
    cargo["test"] = test_result
    executed_status = "ok" if cargo.get("test_status") == "pass" else "FAILED"
    cargo_test_log = trace / "cargo-test.log"
    cargo_test_log.write_text(
        f"running 1 test\ntest rust_dynamic ... {executed_status}\n",
        encoding="utf-8",
    )
    execution, _ = REPORT.analyze_current_test_execution(root, cargo)
    execution["log_sha256"] = REPORT._sha256(cargo_test_log)
    cargo["test_execution"] = execution
    manifest = REPORT.current_test_input_manifest(root)
    rows = [
        {"attempt_id": f"test-repair-{index}", "kind": "repair"}
        for index in range(max(0, repairs_used - 1))
    ]
    latest_id = "test-checkpoint" if repairs_used == 0 else f"test-repair-{repairs_used - 1}"
    latest_kind = "checkpoint" if repairs_used == 0 else "repair"
    rows.append({
        "attempt_id": latest_id,
        "kind": latest_kind,
        "source_manifest": manifest,
        "repair_attempts_recorded": repairs_used,
        "build_status": cargo.get("build_status"),
        "test_status": cargo.get("test_status"),
        "test_execution_status": execution.get("status"),
        "cargo_test_log_sha256": execution.get("log_sha256"),
    })
    (trace / "test-repair-attempts.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    cargo["repair_convergence"] = {
        "attempt_id": latest_id,
        "kind": latest_kind,
        "repair_attempts_recorded": repairs_used,
        "source_manifest": manifest,
        "test_execution_status": execution.get("status"),
        "cargo_test_log_sha256": execution.get("log_sha256"),
    }
    task_state = "confirmed_pass" if cargo.get("test_status") == "pass" else "exhausted" if repairs_used >= 4 else "queued"
    queue_path = trace / "repair-work-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.is_file() else {"schema_version": 1, "phases": {}}
    counts = {state: (1 if state == task_state else 0) for state in sorted({
        "queued", "active", "provisional_pass", "confirmed_pass", "deferred_no_progress", "regressed", "exhausted"
    })}
    queue_summary = {
        "total": 1,
        "counts": counts,
        "all_pass": task_state == "confirmed_pass",
        "queue_exhausted": task_state in {"confirmed_pass", "exhausted"},
        "pending_task_ids": [] if task_state in {"confirmed_pass", "exhausted"} else ["dynamic-case"],
        "sweep": 2 if repairs_used >= 2 else 1,
        "last_full_confirmation_id": latest_id,
    }
    queue.setdefault("phases", {})["tests"] = {
        "tasks": {"dynamic-case": {"task_id": "dynamic-case", "state": task_state}},
        "summary": queue_summary,
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    cargo["repair_convergence"]["work_queue"] = queue_summary
    cargo_path.write_text(json.dumps(cargo), encoding="utf-8")


def write_successful_c_cross_evidence(root: Path) -> None:
    trace = root / "logs" / "trace"
    cross = trace / "c-cross"
    cross.mkdir(parents=True, exist_ok=True)
    convergence = {
        "status": "success",
        "terminal": True,
        "next_action": "report_success",
        "repair_attempts_recorded": 0,
        "work_queue": {
            "total": 1,
            "counts": {"confirmed_pass": 1},
            "all_pass": True,
            "queue_exhausted": True,
            "pending_task_ids": [],
            "sweep": 1,
            "last_full_confirmation_id": "final-1",
        },
    }
    matrix = {
        "mode": "full",
        "scope": "all",
        "attempt_kind": "final",
        "execution_id": "final-1",
        "total_scenarios": 1,
        "summary": {"rust_impl_c_test": {"pass": 1}},
        "scenarios": [{"scenario_id": "dynamic-case", "rust_impl_c_test": "pass"}],
        "convergence": convergence,
    }
    matrix.update(GATE.expected_matrix_scope(matrix))
    (trace / "validation-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
    (cross / "attempts.jsonl").write_text(
        json.dumps({"attempt_id": "final-1", "kind": "final"}) + "\n",
        encoding="utf-8",
    )
    (cross / "failure-summary.json").write_text(json.dumps({
        **convergence,
        "execution_id": "final-1",
    }), encoding="utf-8")
    queue_path = trace / "repair-work-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.is_file() else {"schema_version": 1, "phases": {}}
    queue.setdefault("phases", {})["c_cross"] = {
        "tasks": {"dynamic-case": {"task_id": "dynamic-case", "state": "confirmed_pass"}},
        "summary": convergence["work_queue"],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    for filename, phase in (
        ("build-check.json", "build"),
        ("layout-check.json", "layout"),
        ("link-check.json", "link"),
    ):
        (cross / filename).write_text(json.dumps({"phase": phase, "status": "pass"}), encoding="utf-8")
    (cross / "layout-check.log").write_text("layout pass\n", encoding="utf-8")


class ResultEvidenceTests(unittest.TestCase):
    def test_final_c_cross_requires_fresh_full_final_attempt(self):
        passing = {
            "mode": "full",
            "scope": "all",
            "attempt_kind": "final",
            "execution_id": "final-1",
            "scenarios": [{"rust_impl_c_test": "pass"}],
        }
        passing.update(GATE.expected_matrix_scope(passing))
        self.assertTrue(REPORT.final_c_cross_verified(passing, [{"attempt_id": "final-1", "kind": "final"}]))
        self.assertFalse(REPORT.final_c_cross_verified(passing, [{"attempt_id": "older", "kind": "final"}]))

    def test_report_status_uses_results_not_workflow_state(self):
        with project_temp_directory() as directory:
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
            write_successful_c_cross_evidence(root)
            write_test_repair_evidence(root, repairs_used=0)
            status = REPORT.write_report(root, root / "result" / "output.md", root / "result" / "issues" / "00-summary.md")
            self.assertEqual("SUCCESS", status)
            self.assertIn("STATUS: SUCCESS", (root / "result" / "output.md").read_text(encoding="utf-8"))

    def test_report_refuses_nonterminal_failure_and_accepts_failed_final(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            trace = root / "logs" / "trace"
            (root / "result" / "issues").mkdir(parents=True)
            (trace / "c-cross").mkdir(parents=True)
            semantic_fixture(root)
            (trace / "cargo-results.json").write_text(json.dumps({"build_status": "fail", "test_status": "fail"}), encoding="utf-8")
            (trace / "unsafe-ratio.json").write_text(json.dumps({"unsafe_ratio": 0.2}), encoding="utf-8")
            matrix = {
                "mode": "full",
                "scope": "all",
                "attempt_kind": "confirmation",
                "execution_id": "confirm-1",
                "scenarios": [{"scenario_id": "dynamic-case", "rust_impl_c_test": "fail", "reason": "mismatch"}],
            }
            matrix.update(GATE.expected_matrix_scope(matrix))
            (trace / "validation-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
            repair_attempts = [{"attempt_id": "confirm-1", "kind": "confirmation"}]
            (trace / "c-cross" / "attempts.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in repair_attempts),
                encoding="utf-8",
            )
            write_test_repair_evidence(root, repairs_used=0)
            convergence_path = trace / "c-cross" / "failure-summary.json"
            convergence_path.write_text(json.dumps({
                "status": "repair_required",
                "terminal": False,
                "repair_attempts_recorded": 0,
                "work_queue": {"queue_exhausted": False, "pending_task_ids": ["dynamic-case"]},
            }), encoding="utf-8")
            output = root / "result" / "output.md"
            issues = root / "result" / "issues" / "00-summary.md"
            self.assertEqual("INCOMPLETE", REPORT.write_report(root, output, issues))
            self.assertIn("STATUS: INCOMPLETE", output.read_text(encoding="utf-8"))
            convergence_path.write_text(json.dumps({
                "status": "failed_final",
                "terminal": True,
                "execution_id": "confirm-1",
                "repair_attempts_recorded": 0,
                "work_queue": {"queue_exhausted": True, "pending_task_ids": []},
            }), encoding="utf-8")
            self.assertEqual("INCOMPLETE", REPORT.write_report(root, output, issues))
            write_test_repair_evidence(root, repairs_used=4)
            self.assertEqual("FAILED", REPORT.write_report(root, output, issues))
            self.assertIn("STATUS: FAILED", output.read_text(encoding="utf-8"))

    def test_test_failures_require_two_real_repairs_before_failed_final(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            trace = root / "logs" / "trace"
            (root / "result" / "issues").mkdir(parents=True)
            (trace / "c-cross").mkdir(parents=True)
            semantic_fixture(root)
            (trace / "cargo-results.json").write_text(json.dumps({
                "build_status": "pass",
                "test_status": "fail",
                "build": {"returncode": 0},
                "test": {"returncode": 1},
            }), encoding="utf-8")
            (trace / "unsafe-ratio.json").write_text(json.dumps({"unsafe_ratio": 0.0}), encoding="utf-8")
            (trace / "validation-matrix.json").write_text(json.dumps({
                "mode": "full",
                "scope": "all",
                "attempt_kind": "final",
                "execution_id": "final-1",
                "scenarios": [{"scenario_id": "dynamic-case", "rust_impl_c_test": "pass"}],
            }), encoding="utf-8")
            write_successful_c_cross_evidence(root)
            output = root / "result" / "output.md"
            issues = root / "result" / "issues" / "00-summary.md"
            write_test_repair_evidence(root, repairs_used=1)
            self.assertEqual("INCOMPLETE", REPORT.write_report(root, output, issues))
            test_status, errors, _ = GATE.evaluate_test_stage(root)
            self.assertEqual("repair_required", test_status)
            self.assertTrue(any("repair next queued test" in error for error in errors))
            write_test_repair_evidence(root, repairs_used=4)
            self.assertEqual("FAILED", REPORT.write_report(root, output, issues))
            test_status, errors, _ = GATE.evaluate_test_stage(root)
            self.assertEqual("failed_final", test_status)
            self.assertEqual([], errors)

    def test_pre_report_gate_blocks_until_test_stage_is_terminal(self):
        with project_temp_directory() as directory:
            root = Path(directory)
            trace = root / "logs" / "trace"
            (root / "result" / "issues").mkdir(parents=True)
            semantic_fixture(root)
            (root / "logs" / "interaction.md").write_text("", encoding="utf-8")
            write_successful_c_cross_evidence(root)
            (trace / "cargo-results.json").write_text(json.dumps({
                "build_status": "pass",
                "test_status": "fail",
                "build": {"returncode": 0},
                "test": {"returncode": 1},
            }), encoding="utf-8")
            (trace / "cargo-build.log").write_text("build pass\n", encoding="utf-8")
            write_test_repair_evidence(root, repairs_used=0)
            errors = GATE.check_test_and_report(root)
            self.assertTrue(any("repair next queued test" in error for error in errors))

            write_test_repair_evidence(root, repairs_used=4)
            self.assertEqual([], GATE.check_test_and_report(root))


if __name__ == "__main__":
    unittest.main()
