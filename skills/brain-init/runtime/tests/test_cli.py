import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from brain_runtime.trace import read_events
from helpers import FIXTURES, build_capture_vault


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-capture-[0-9a-f]{8}\n$")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.vault = Path(self.temporary.name) / "vault"
        self.paths = build_capture_vault(self.vault)

    def tearDown(self):
        self.temporary.cleanup()

    def _run(self, *args, check=True):
        cmd = [sys.executable, "-m", "brain_runtime.cli", *map(str, args)]
        env = {**os.environ, "PYTHONPATH": str(RUNTIME_ROOT)}
        return subprocess.run(
            cmd,
            env=env,
            text=True,
            capture_output=True,
            check=check,
        )

    def _write_json(self, name, payload):
        path = self.vault / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _start(self, *extra):
        result = self._run(
            "start",
            "--vault",
            self.vault,
            "--operation",
            "capture",
            "--mode",
            "shadow",
            "--profile",
            "annual-report-v1",
            "--input",
            "raw/annual-reports/acme-2025-annual-report.pdf",
            *extra,
        )
        self.assertRegex(result.stdout, RUN_ID)
        self.assertEqual(result.stderr, "")
        return result.stdout.strip()

    def test_shadow_runtime_end_to_end(self):
        run_id = self._start()
        run_dir = self.vault / ".brain" / "runs" / run_id

        request_file = self.vault / "section-map.json"
        shutil.copyfile(FIXTURES / "section-map-fanout.json", request_file)
        self._run(
            "plan",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--request-file",
            request_file,
        )
        plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["decision"]["mode"], "fanout")
        self.assertEqual(plan["decision"]["max_workers"], 3)
        plan_events = read_events(run_dir)[-2:]
        self.assertEqual(
            [event.kind for event in plan_events],
            ["plan.section_map", "plan.fanout"],
        )
        self.assertEqual(plan_events[0].data, {"slice_count": 3})

        self._run(
            "event",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--kind",
            "worker.start",
            "--label",
            "researcher.mda",
        )
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["workers"], 0)
        self._run(
            "event",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--kind",
            "worker.finish",
            "--label",
            "researcher.mda",
        )
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["workers"], 1)

        invalid_claim = self.vault / self.paths[0]
        shutil.copyfile(FIXTURES / "invalid-claim-no-source.md", invalid_claim)
        paths_file = self._write_json("declared-paths.json", self.paths)
        self._run(
            "declare",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--paths-file",
            paths_file,
        )
        artifacts = json.loads(
            (run_dir / "artifacts.json").read_text(encoding="utf-8")
        )["artifacts"]
        self.assertEqual([item["path"] for item in artifacts], self.paths)
        self.assertTrue(
            all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in artifacts)
        )

        verify_result = self._run(
            "verify",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
        )
        self.assertIn("Runtime shadow: REJECT", verify_result.stdout)
        self.assertIn("1 warning)", verify_result.stdout)
        self.assertEqual(verify_result.returncode, 0)

        semantic_file = self._write_json(
            "semantic-report.json",
            {
                "checks": [
                    {
                        "id": "semantic.evidence_supports_claim",
                        "passed": True,
                        "severity": "warning",
                        "artifact": self.paths[0],
                        "message": "",
                        "source": "untrusted-input",
                    }
                ]
            },
        )
        self._run(
            "semantic",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--report-file",
            semantic_file,
        )
        verification_path = run_dir / "verification.json"
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        imported = [
            check
            for check in verification["checks"]
            if check["id"] == "semantic.evidence_supports_claim"
        ]
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["source"], "semantic")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["semantic_verifier_calls"], 1)

        report_before_skip = verification_path.read_bytes()
        skipped = self._run(
            "semantic",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--report-file",
            semantic_file,
        )
        self.assertIn("semantic verification skipped", skipped.stdout.lower())
        self.assertEqual(verification_path.read_bytes(), report_before_skip)
        self.assertEqual(read_events(run_dir)[-1].kind, "budget.warning")

        self._run(
            "finish",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
        )
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "completed")
        self.assertFalse(manifest["shadow_verdict"])

    def test_single_slice_plan_persists_context_flag_for_annual_report_verify(self):
        first_claim = self.vault / self.paths[0]
        second_claim = first_claim.with_name("claim-acme-revenue-second.md")
        second_claim.write_text(
            first_claim.read_text(encoding="utf-8").replace(
                "claim-acme-revenue-12345678",
                "claim-acme-revenue-87654321",
            ),
            encoding="utf-8",
        )
        self.paths.insert(1, second_claim.relative_to(self.vault).as_posix())
        start = self._run(
            "start",
            "--vault",
            self.vault,
            "--operation",
            "capture",
            "--mode",
            "shadow",
            "--profile",
            "small-document-v1",
            "--input",
            "raw/annual-reports/acme-2025-annual-report.pdf",
        )
        run_id = start.stdout.strip()
        run_dir = self.vault / ".brain" / "runs" / run_id
        request_file = self.vault / "section-map-single.json"
        shutil.copyfile(FIXTURES / "section-map-single.json", request_file)

        self._run(
            "plan",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--request-file",
            request_file,
        )
        self._run(
            "event",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--kind",
            "workflow.log",
            "--label",
            "capture.log",
            "--data-json",
            '{"passed":true}',
        )
        self._run(
            "declare",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--paths-file",
            self._write_json("single-slice-paths.json", self.paths),
        )

        plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        self.assertIn("exceeds_one_context", plan)
        self.assertIs(plan["exceeds_one_context"], False)
        verified = self._run(
            "verify",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
        )
        self.assertIn("Runtime shadow: ACCEPT", verified.stdout)

    def test_event_rejects_forbidden_trace_data_without_recording_it(self):
        run_id = self._start()
        run_dir = self.vault / ".brain" / "runs" / run_id
        original_events = (run_dir / "events.jsonl").read_bytes()

        result = self._run(
            "event",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--kind",
            "worker.finish",
            "--label",
            "researcher.mda",
            "--data-json",
            '{"nested":{"transcript":"must not persist"}}',
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden trace data keys", result.stderr)
        self.assertEqual((run_dir / "events.jsonl").read_bytes(), original_events)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["workers"], 0)

    def test_attempt_label_increments_attempt_metric(self):
        run_id = self._start()
        run_dir = self.vault / ".brain" / "runs" / run_id

        self._run(
            "event",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--kind",
            "repair.finish",
            "--label",
            "attempt.1",
        )

        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["attempts"], 1)

    def test_semantic_rejects_unknown_severity_without_consuming_budget(self):
        run_id = self._start()
        run_dir = self.vault / ".brain" / "runs" / run_id
        report_file = self._write_json(
            "bad-semantic-report.json",
            {
                "checks": [
                    {
                        "id": "semantic.unknown",
                        "passed": False,
                        "severity": "fatal",
                    }
                ]
            },
        )

        result = self._run(
            "semantic",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--report-file",
            report_file,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("severity", result.stderr)
        self.assertFalse((run_dir / "verification.json").exists())
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["semantic_verifier_calls"], 0)

    def test_start_budget_flags_are_stored_in_manifest(self):
        run_id = self._start(
            "--max-workers",
            "2",
            "--max-attempts",
            "4",
            "--max-semantic-verifier-calls",
            "0",
        )
        run_dir = self.vault / ".brain" / "runs" / run_id
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(
            manifest["budget"],
            {
                "max_workers": 2,
                "max_attempts": 4,
                "max_semantic_verifier_calls": 0,
            },
        )

    def test_adapter_boundary_resolves_capture_and_rejects_unknown_operation(self):
        from brain_runtime import adapters
        from brain_runtime.adapters.capture import capture_checks

        resolver = getattr(adapters, "verification_adapter_for", None)
        self.assertIsNotNone(resolver)
        self.assertIs(resolver("capture"), capture_checks)
        with self.assertRaisesRegex(ValueError, "unsupported verification operation"):
            resolver("unknown-operation")

    def test_generic_cli_has_no_capture_specific_adapter_dependency(self):
        cli_source = (
            RUNTIME_ROOT / "brain_runtime" / "cli.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("adapters.capture", cli_source)
        self.assertNotIn("capture_checks", cli_source)
        self.assertNotIn('manifest["operation"] != "capture"', cli_source)

    def test_verify_reports_unknown_operation_as_runtime_input_error(self):
        start = self._run(
            "start",
            "--vault",
            self.vault,
            "--operation",
            "unknown-operation",
            "--mode",
            "shadow",
        )

        result = self._run(
            "verify",
            "--vault",
            self.vault,
            "--run-id",
            start.stdout.strip(),
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported verification operation", result.stderr)

    def test_start_accepts_multiple_inputs_after_one_input_flag(self):
        second_input = self.vault / "raw/annual-reports/acme-2024.pdf"
        second_input.write_bytes(b"fixture-pdf-2024")

        result = self._run(
            "start",
            "--vault",
            self.vault,
            "--operation",
            "capture",
            "--mode",
            "shadow",
            "--input",
            "raw/annual-reports/acme-2025-annual-report.pdf",
            "raw/annual-reports/acme-2024.pdf",
        )
        run_id = result.stdout.strip()
        manifest = json.loads(
            (
                self.vault / ".brain" / "runs" / run_id / "manifest.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(len(manifest["inputs"]), 2)

    def test_run_id_cannot_escape_the_vault_run_directory(self):
        (self.vault / ".brain" / "runs").mkdir(parents=True)
        escaped = self.vault / "outside"
        escaped.mkdir()
        (escaped / "manifest.json").write_text(
            json.dumps(
                {
                    "operation": "capture",
                    "metrics": {
                        "workers": 0,
                        "attempts": 0,
                        "semantic_verifier_calls": 0,
                    },
                }
            ),
            encoding="utf-8",
        )
        (escaped / "events.jsonl").write_text("", encoding="utf-8")

        result = self._run(
            "event",
            "--vault",
            self.vault,
            "--run-id",
            "../../outside",
            "--kind",
            "worker.finish",
            "--label",
            "researcher.escape",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((escaped / "events.jsonl").read_text(encoding="utf-8"), "")

    def test_operation_cannot_add_path_components_to_run_id(self):
        result = self._run(
            "start",
            "--vault",
            self.vault,
            "--operation",
            "capture/../../../../outside",
            "--mode",
            "shadow",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("safe path component", result.stderr)

    def test_concurrent_worker_finish_events_do_not_lose_metrics(self):
        run_id = self._start()
        run_dir = self.vault / ".brain" / "runs" / run_id
        commands = [
            [
                sys.executable,
                "-m",
                "brain_runtime.cli",
                "event",
                "--vault",
                str(self.vault),
                "--run-id",
                run_id,
                "--kind",
                "worker.finish",
                "--label",
                f"researcher.{index}",
            ]
            for index in range(20)
        ]
        env = {**os.environ, "PYTHONPATH": str(RUNTIME_ROOT)}

        processes = [
            subprocess.Popen(
                command,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for command in commands
        ]
        results = [process.communicate() for process in processes]

        self.assertTrue(
            all(process.returncode == 0 for process in processes),
            results,
        )
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["workers"], len(processes))

    def test_oversized_semantic_id_does_not_mutate_report_or_budget(self):
        run_id = self._start()
        run_dir = self.vault / ".brain" / "runs" / run_id
        paths_file = self._write_json("declared-paths.json", self.paths)
        self._run(
            "declare",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--paths-file",
            paths_file,
        )
        self._run(
            "verify",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
        )
        verification_path = run_dir / "verification.json"
        report_before = verification_path.read_bytes()
        report_file = self._write_json(
            "oversized-semantic-report.json",
            {
                "checks": [
                    {
                        "id": "semantic." + ("x" * 9000),
                        "passed": True,
                        "severity": "info",
                    }
                ]
            },
        )

        result = self._run(
            "semantic",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--report-file",
            report_file,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(verification_path.read_bytes(), report_before)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["semantic_verifier_calls"], 0)

    def test_concurrent_semantic_submissions_observe_one_call_budget(self):
        run_id = self._start()
        run_dir = self.vault / ".brain" / "runs" / run_id
        paths_file = self._write_json("declared-paths.json", self.paths)
        self._run(
            "declare",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--paths-file",
            paths_file,
        )
        self._run(
            "verify",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
        )
        report_file = self._write_json(
            "semantic-report.json",
            {
                "checks": [
                    {
                        "id": "semantic.concurrent",
                        "passed": True,
                        "severity": "info",
                    }
                ]
            },
        )
        command = [
            sys.executable,
            "-m",
            "brain_runtime.cli",
            "semantic",
            "--vault",
            str(self.vault),
            "--run-id",
            run_id,
            "--report-file",
            str(report_file),
        ]
        env = {**os.environ, "PYTHONPATH": str(RUNTIME_ROOT)}

        processes = [
            subprocess.Popen(
                command,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        results = [process.communicate() for process in processes]

        self.assertTrue(
            all(process.returncode == 0 for process in processes),
            results,
        )
        self.assertEqual(
            sum("budget exhausted" in stdout for stdout, _ in results),
            1,
        )
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["metrics"]["semantic_verifier_calls"], 1)
        verification = json.loads(
            (run_dir / "verification.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            sum(
                check["id"] == "semantic.concurrent"
                for check in verification["checks"]
            ),
            1,
        )

    def test_semantic_critical_failure_rejects_accepted_deterministic_report(self):
        first_claim = self.vault / self.paths[0]
        second_claim = first_claim.with_name("claim-acme-revenue-second.md")
        second_claim.write_text(
            first_claim.read_text(encoding="utf-8").replace(
                "claim-acme-revenue-12345678",
                "claim-acme-revenue-87654321",
            ),
            encoding="utf-8",
        )
        self.paths.insert(1, second_claim.relative_to(self.vault).as_posix())
        run_id = self._start()
        run_dir = self.vault / ".brain" / "runs" / run_id
        self._run(
            "event",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--kind",
            "workflow.log",
            "--label",
            "log.completed",
            "--data-json",
            '{"passed":true}',
        )
        paths_file = self._write_json("declared-paths.json", self.paths)
        self._run(
            "declare",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--paths-file",
            paths_file,
        )
        deterministic = self._run(
            "verify",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
        )
        self.assertIn("Runtime shadow: ACCEPT", deterministic.stdout)
        report_file = self._write_json(
            "semantic-reject.json",
            {
                "checks": [
                    {
                        "id": "semantic.evidence_supports_claim",
                        "passed": False,
                        "severity": "critical",
                        "artifact": self.paths[0],
                        "message": "claim is not supported",
                    }
                ]
            },
        )

        semantic = self._run(
            "semantic",
            "--vault",
            self.vault,
            "--run-id",
            run_id,
            "--report-file",
            report_file,
        )

        self.assertEqual(semantic.returncode, 0)
        self.assertIn("Runtime shadow: REJECT", semantic.stdout)
        verification = json.loads(
            (run_dir / "verification.json").read_text(encoding="utf-8")
        )
        self.assertFalse(verification["accepted"])
        self.assertTrue(
            any(
                failure["check"] == "semantic.evidence_supports_claim"
                for failure in verification["failures"]
            )
        )


if __name__ == "__main__":
    unittest.main()
