from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from brain_runtime.contracts import BudgetSpec, RetryFeedback, RunSpec
from brain_runtime.run import create_run, finish_run
from brain_runtime.trace import TraceEvent, append_event, read_events


class ContractRunTests(unittest.TestCase):
    def test_run_spec_round_trip(self):
        spec = RunSpec(
            operation="capture",
            mode="shadow",
            input_refs=["raw/annual-reports/acme-2025.pdf"],
            profile="annual-report-v1",
            budget=BudgetSpec(),
            metadata={"source_type": "annual-report"},
        )
        restored = RunSpec.from_dict(spec.to_dict())
        self.assertEqual(restored, spec)

    def test_retry_feedback_is_compact_and_serializable(self):
        feedback = RetryFeedback(
            attempt=1,
            retryable=True,
            failures=[{
                "artifact": "wiki/claims/claim-acme.md",
                "check": "evidence.locator_resolves",
                "message": "passage not found in converted markdown",
            }],
        )
        payload = feedback.to_dict()
        self.assertEqual(payload["attempt"], 1)
        self.assertNotIn("messages", payload)
        self.assertNotIn("transcript", payload)

    def test_create_run_writes_manifest_and_start_event(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            src = vault / "raw/annual-reports/acme-2025.pdf"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"fixture-pdf")
            spec = RunSpec(
                operation="capture",
                mode="shadow",
                input_refs=["raw/annual-reports/acme-2025.pdf"],
                profile="annual-report-v1",
                budget=BudgetSpec(),
            )

            run_id = create_run(vault, spec)
            run_dir = vault / ".brain/runs" / run_id
            manifest = json.loads((run_dir / "manifest.json").read_text())

            self.assertEqual(manifest["operation"], "capture")
            self.assertEqual(manifest["mode"], "shadow")
            self.assertEqual(len(manifest["inputs"]), 1)
            self.assertRegex(manifest["inputs"][0]["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(read_events(run_dir)[0].kind, "run.start")

    def test_finish_run_marks_manifest_completed(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            spec = RunSpec("capture", "shadow", [], "annual-report-v1", BudgetSpec())
            run_id = create_run(vault, spec)
            finish_run(vault, run_id, shadow_verdict=False)
            manifest = json.loads((vault / ".brain/runs" / run_id / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertFalse(manifest["shadow_verdict"])
            self.assertEqual(read_events(vault / ".brain/runs" / run_id)[-1].kind, "run.finish")

    def test_append_event_rejects_forbidden_keys_nested_in_payload(self):
        with TemporaryDirectory() as td:
            event = TraceEvent(
                ts="2026-07-26T00:00:00Z",
                kind="worker.finish",
                operation="capture",
                run_id="20260726T000000Z-capture-deadbeef",
                label="worker result",
                data={"result": [{"details": {"transcript": "must not persist"}}]},
            )

            with self.assertRaisesRegex(ValueError, "transcript"):
                append_event(Path(td), event)

    def test_append_event_rejects_forbidden_keys_nested_in_tuple(self):
        with TemporaryDirectory() as td:
            event = TraceEvent(
                ts="2026-07-26T00:00:00Z",
                kind="worker.finish",
                operation="capture",
                run_id="20260726T000000Z-capture-deadbeef",
                label="worker result",
                data={"result": ({"transcript": "must not persist"},)},
            )

            with self.assertRaisesRegex(ValueError, "transcript"):
                append_event(Path(td), event)


if __name__ == "__main__":
    unittest.main()
