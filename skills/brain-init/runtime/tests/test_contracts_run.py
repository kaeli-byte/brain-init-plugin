from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import threading
import unittest
from unittest.mock import patch

import brain_runtime.run as run_module
import brain_runtime.verify as verify_module
from brain_runtime.budget import FanoutRequest
from brain_runtime.contracts import BudgetSpec, RetryFeedback, RunSpec
from brain_runtime.run import (
    create_run,
    declare_artifacts,
    finish_run,
    plan_run,
    record_event,
    run_dir_for,
)
from brain_runtime.trace import TraceEvent, append_event, read_events
from brain_runtime.verify import merge_semantic_report, verify_run


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

    def test_create_run_rejects_missing_input_file(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            spec = RunSpec(
                "capture",
                "shadow",
                ["raw/missing.pdf"],
                None,
                BudgetSpec(),
            )

            with self.assertRaisesRegex(
                FileNotFoundError,
                "input reference does not exist",
            ):
                create_run(vault, spec)

    def test_create_run_rejects_absolute_input_reference(self):
        with TemporaryDirectory() as td:
            owned_root = Path(td)
            vault = owned_root / "vault"
            vault.mkdir()
            external = owned_root / "external-input.pdf"
            external.write_bytes(b"external sentinel")
            spec = RunSpec(
                "capture",
                "shadow",
                [str(external)],
                None,
                BudgetSpec(),
            )

            with self.assertRaisesRegex(ValueError, "vault-relative"):
                create_run(vault, spec)

    def test_create_run_rejects_parent_traversing_input_reference(self):
        with TemporaryDirectory() as td:
            owned_root = Path(td)
            vault = owned_root / "vault"
            vault.mkdir()
            external = owned_root / "external-input.pdf"
            external.write_bytes(b"external sentinel")
            spec = RunSpec(
                "capture",
                "shadow",
                ["../external-input.pdf"],
                None,
                BudgetSpec(),
            )

            with self.assertRaisesRegex(ValueError, "parent traversal"):
                create_run(vault, spec)

    def test_create_run_rejects_outward_symlinked_input_reference(self):
        with TemporaryDirectory() as td:
            owned_root = Path(td)
            vault = owned_root / "vault"
            raw = vault / "raw"
            raw.mkdir(parents=True)
            external = owned_root / "external-input.pdf"
            external.write_bytes(b"external sentinel")
            (raw / "linked-input.pdf").symlink_to(external)
            spec = RunSpec(
                "capture",
                "shadow",
                ["raw/linked-input.pdf"],
                None,
                BudgetSpec(),
            )

            with self.assertRaisesRegex(ValueError, "escapes the vault"):
                create_run(vault, spec)

    def test_create_run_rejects_symlinked_runs_ownership_root(self):
        with TemporaryDirectory() as td:
            owned_root = Path(td)
            vault = owned_root / "vault"
            brain = vault / ".brain"
            brain.mkdir(parents=True)
            external_runs = owned_root / "external-runs"
            external_runs.mkdir()
            (brain / "runs").symlink_to(external_runs, target_is_directory=True)
            spec = RunSpec("capture", "shadow", [], None, BudgetSpec())

            with self.assertRaisesRegex(ValueError, "symlinked runtime ownership path"):
                create_run(vault, spec)
            self.assertEqual(list(external_runs.iterdir()), [])

    def test_run_dir_rejects_symlinked_run_component_inside_vault(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            runs = vault / ".brain" / "runs"
            real_run = runs / "real-run"
            real_run.mkdir(parents=True)
            (runs / "linked-run").symlink_to(real_run, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symlinked runtime ownership path"):
                run_dir_for(vault, "linked-run")

    def test_record_event_rejects_symlinked_events_file(self):
        with TemporaryDirectory() as td:
            owned_root = Path(td)
            vault = owned_root / "vault"
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            events_path = vault / ".brain" / "runs" / run_id / "events.jsonl"
            external_events = owned_root / "external-events.jsonl"
            external_events.write_bytes(b"external sentinel\n")
            events_path.unlink()
            events_path.symlink_to(external_events)

            with self.assertRaisesRegex(ValueError, "symlinked runtime ownership file"):
                record_event(vault, run_id, "worker.finish", "researcher.mda")
            self.assertEqual(external_events.read_bytes(), b"external sentinel\n")

    def test_record_event_rejects_fifo_events_file_without_blocking(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            events_path = vault / ".brain" / "runs" / run_id / "events.jsonl"
            events_path.unlink()
            os.mkfifo(events_path)
            finished = threading.Event()
            errors = []

            def write_event():
                try:
                    record_event(
                        vault,
                        run_id,
                        "worker.finish",
                        "researcher.mda",
                    )
                except BaseException as error:
                    errors.append(error)
                finally:
                    finished.set()

            writer = threading.Thread(target=write_event)
            writer.start()
            completed_without_reader = finished.wait(timeout=1.0)
            reader_descriptor = None
            if not completed_without_reader:
                reader_descriptor = os.open(events_path, os.O_RDONLY | os.O_NONBLOCK)
            writer.join(timeout=5)
            if reader_descriptor is not None:
                os.close(reader_descriptor)

            self.assertTrue(
                completed_without_reader,
                "opening a non-regular events file blocked waiting for a FIFO reader",
            )
            self.assertFalse(writer.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ValueError)
            self.assertIn("not regular", str(errors[0]))

    def test_record_event_rejects_symlinked_lock_file(self):
        with TemporaryDirectory() as td:
            owned_root = Path(td)
            vault = owned_root / "vault"
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            run_dir = vault / ".brain" / "runs" / run_id
            external_lock = owned_root / "external.lock"
            (run_dir / ".lock").symlink_to(external_lock)

            with self.assertRaisesRegex(ValueError, "symlinked runtime ownership file"):
                record_event(vault, run_id, "worker.finish", "researcher.mda")
            self.assertFalse(external_lock.exists())

    def test_record_event_rejects_symlinked_manifest_file(self):
        with TemporaryDirectory() as td:
            owned_root = Path(td)
            vault = owned_root / "vault"
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            run_dir = vault / ".brain" / "runs" / run_id
            manifest_path = run_dir / "manifest.json"
            external_manifest = owned_root / "external-manifest.json"
            external_manifest.write_bytes(manifest_path.read_bytes())
            external_before = external_manifest.read_bytes()
            manifest_path.unlink()
            manifest_path.symlink_to(external_manifest)
            events_before = (run_dir / "events.jsonl").read_bytes()

            with self.assertRaisesRegex(ValueError, "symlinked runtime ownership file"):
                record_event(vault, run_id, "worker.finish", "researcher.mda")

            self.assertEqual(external_manifest.read_bytes(), external_before)
            self.assertEqual((run_dir / "events.jsonl").read_bytes(), events_before)

    def test_finish_run_marks_manifest_completed(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            spec = RunSpec("capture", "shadow", [], "annual-report-v1", BudgetSpec())
            run_id = create_run(vault, spec)
            finish_run(vault, run_id, shadow_verdict=False)
            manifest = json.loads((vault / ".brain/runs" / run_id / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertIs(manifest["shadow_verdict"], False)
            self.assertEqual(read_events(vault / ".brain/runs" / run_id)[-1].kind, "run.finish")

    def test_finish_run_serializes_with_event_writer(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            writer_loaded = threading.Event()
            release_writer = threading.Event()
            finish_attempted = threading.Event()
            finish_loaded = threading.Event()
            errors = []
            original_load = run_module.load_manifest
            original_run_lock = run_module.run_lock

            def controlled_load(vault_path, loaded_run_id):
                manifest = original_load(vault_path, loaded_run_id)
                thread_name = threading.current_thread().name
                if thread_name == "event-writer":
                    writer_loaded.set()
                    if not release_writer.wait(timeout=5):
                        raise TimeoutError("event writer was not released")
                elif thread_name == "finisher":
                    finish_loaded.set()
                return manifest

            @contextmanager
            def observed_run_lock(vault_path, loaded_run_id):
                if threading.current_thread().name == "finisher":
                    finish_attempted.set()
                with original_run_lock(vault_path, loaded_run_id):
                    yield

            def capture_error(callback):
                try:
                    callback()
                except BaseException as error:
                    errors.append(error)

            with (
                patch.object(
                    run_module,
                    "load_manifest",
                    side_effect=controlled_load,
                ),
                patch.object(run_module, "run_lock", observed_run_lock),
            ):
                writer = threading.Thread(
                    name="event-writer",
                    target=capture_error,
                    args=(lambda: record_event(
                        vault,
                        run_id,
                        "worker.finish",
                        "researcher.mda",
                    ),),
                )
                writer.start()
                self.assertTrue(writer_loaded.wait(timeout=5))
                finisher = threading.Thread(
                    name="finisher",
                    target=capture_error,
                    args=(lambda: finish_run(vault, run_id, shadow_verdict=True),),
                )
                finisher.start()
                self.assertTrue(finish_attempted.wait(timeout=5))
                bypassed_lock = finish_loaded.wait(timeout=0.1)
                release_writer.set()
                writer.join(timeout=5)
                finisher.join(timeout=5)

            self.assertFalse(
                bypassed_lock,
                "finish_run loaded the manifest while an event writer held the run lock",
            )
            self.assertFalse(writer.is_alive())
            self.assertFalse(finisher.is_alive())
            self.assertEqual(errors, [])
            manifest = json.loads(
                (
                    vault / ".brain" / "runs" / run_id / "manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["metrics"]["workers"], 1)

    def test_finish_run_serializes_with_semantic_writer(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            run_dir = vault / ".brain" / "runs" / run_id
            (run_dir / "verification.json").write_text(
                json.dumps({
                    "accepted": True,
                    "checks": [],
                    "failures": [],
                    "warnings": [],
                    "semantic": {"status": "skipped"},
                }),
                encoding="utf-8",
            )
            semantic_loaded = threading.Event()
            release_semantic = threading.Event()
            finish_attempted = threading.Event()
            finish_loaded = threading.Event()
            errors = []
            original_semantic_load = verify_module.load_manifest
            original_finish_load = run_module.load_manifest
            original_run_lock = run_module.run_lock

            def controlled_semantic_load(vault_path, loaded_run_id):
                manifest = original_semantic_load(vault_path, loaded_run_id)
                semantic_loaded.set()
                if not release_semantic.wait(timeout=5):
                    raise TimeoutError("semantic writer was not released")
                return manifest

            def controlled_finish_load(vault_path, loaded_run_id):
                manifest = original_finish_load(vault_path, loaded_run_id)
                if threading.current_thread().name == "finisher":
                    finish_loaded.set()
                return manifest

            @contextmanager
            def observed_run_lock(vault_path, loaded_run_id):
                if threading.current_thread().name == "finisher":
                    finish_attempted.set()
                with original_run_lock(vault_path, loaded_run_id):
                    yield

            def capture_error(callback):
                try:
                    callback()
                except BaseException as error:
                    errors.append(error)

            semantic_payload = {
                "checks": [{
                    "id": "semantic.race",
                    "passed": False,
                    "severity": "critical",
                }],
            }
            with (
                patch.object(
                    verify_module,
                    "load_manifest",
                    side_effect=controlled_semantic_load,
                ),
                patch.object(
                    run_module,
                    "load_manifest",
                    side_effect=controlled_finish_load,
                ),
                patch.object(run_module, "run_lock", observed_run_lock),
            ):
                semantic = threading.Thread(
                    name="semantic-writer",
                    target=capture_error,
                    args=(lambda: merge_semantic_report(
                        vault,
                        run_id,
                        semantic_payload,
                    ),),
                )
                semantic.start()
                self.assertTrue(semantic_loaded.wait(timeout=5))
                finisher = threading.Thread(
                    name="finisher",
                    target=capture_error,
                    args=(lambda: finish_run(vault, run_id),),
                )
                finisher.start()
                self.assertTrue(finish_attempted.wait(timeout=5))
                bypassed_lock = finish_loaded.wait(timeout=0.1)
                release_semantic.set()
                semantic.join(timeout=5)
                finisher.join(timeout=5)

            self.assertFalse(
                bypassed_lock,
                "finish_run loaded the manifest while a semantic writer held the run lock",
            )
            self.assertFalse(semantic.is_alive())
            self.assertFalse(finisher.is_alive())
            self.assertEqual(errors, [])
            manifest = json.loads(
                (run_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(
                manifest["metrics"]["semantic_verifier_calls"],
                1,
            )
            self.assertIs(manifest["shadow_verdict"], False)
            verification = json.loads(
                (run_dir / "verification.json").read_text(encoding="utf-8")
            )
            self.assertFalse(verification["accepted"])
            self.assertTrue(any(
                check["id"] == "semantic.race"
                for check in verification["checks"]
            ))

    def test_semantic_writer_rejects_completed_run_without_changing_verdict(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            run_dir = vault / ".brain" / "runs" / run_id
            verification_path = run_dir / "verification.json"
            verification_path.write_text(
                json.dumps({
                    "accepted": True,
                    "checks": [],
                    "failures": [],
                    "warnings": [],
                    "semantic": {"status": "skipped"},
                }),
                encoding="utf-8",
            )
            finish_run(vault, run_id)
            events_before = (run_dir / "events.jsonl").read_bytes()
            report_before = verification_path.read_bytes()

            with self.assertRaisesRegex(ValueError, "completed"):
                merge_semantic_report(
                    vault,
                    run_id,
                    {
                        "checks": [{
                            "id": "semantic.late",
                            "passed": False,
                            "severity": "critical",
                        }],
                    },
                )

            self.assertEqual(verification_path.read_bytes(), report_before)
            self.assertEqual((run_dir / "events.jsonl").read_bytes(), events_before)
            manifest = json.loads(
                (run_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "completed")
            self.assertTrue(manifest["shadow_verdict"])
            self.assertEqual(
                manifest["metrics"]["semantic_verifier_calls"],
                0,
            )

    def test_event_writer_rejects_completed_run_without_appending(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            finish_run(vault, run_id, shadow_verdict=True)
            run_dir = vault / ".brain" / "runs" / run_id
            events_before = (run_dir / "events.jsonl").read_bytes()

            with self.assertRaisesRegex(ValueError, "completed"):
                record_event(vault, run_id, "worker.finish", "researcher.late")

            self.assertEqual((run_dir / "events.jsonl").read_bytes(), events_before)
            manifest = json.loads(
                (run_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["metrics"]["workers"], 0)

    def test_plan_writer_rejects_completed_run_without_mutating_state(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            finish_run(vault, run_id)
            run_dir = vault / ".brain" / "runs" / run_id
            events_before = (run_dir / "events.jsonl").read_bytes()
            manifest_before = (run_dir / "manifest.json").read_bytes()
            request = FanoutRequest(
                slices=[{"id": "mda"}],
                parallelizable=True,
                exceeds_one_context=False,
                high_value=False,
            )

            with self.assertRaisesRegex(ValueError, "completed"):
                plan_run(vault, run_id, request)

            self.assertFalse((run_dir / "plan.json").exists())
            self.assertEqual((run_dir / "events.jsonl").read_bytes(), events_before)
            self.assertEqual((run_dir / "manifest.json").read_bytes(), manifest_before)

    def test_artifact_writer_rejects_completed_run_without_mutating_state(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            artifact = vault / "wiki" / "claim.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("# Claim\n", encoding="utf-8")
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            finish_run(vault, run_id)
            run_dir = vault / ".brain" / "runs" / run_id
            events_before = (run_dir / "events.jsonl").read_bytes()
            manifest_before = (run_dir / "manifest.json").read_bytes()

            with self.assertRaisesRegex(ValueError, "completed"):
                declare_artifacts(vault, run_id, ["wiki/claim.md"])

            self.assertFalse((run_dir / "artifacts.json").exists())
            self.assertEqual((run_dir / "events.jsonl").read_bytes(), events_before)
            self.assertEqual((run_dir / "manifest.json").read_bytes(), manifest_before)

    def test_verify_writer_rejects_completed_run_without_mutating_state(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            artifact = vault / "wiki" / "claim.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("# Claim\n", encoding="utf-8")
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            declare_artifacts(vault, run_id, ["wiki/claim.md"])
            finish_run(vault, run_id)
            run_dir = vault / ".brain" / "runs" / run_id
            events_before = (run_dir / "events.jsonl").read_bytes()
            manifest_before = (run_dir / "manifest.json").read_bytes()
            adapter_called = False

            def adapter(vault_path, run_path, artifacts):
                nonlocal adapter_called
                adapter_called = True
                return []

            with self.assertRaisesRegex(ValueError, "completed"):
                verify_run(vault, run_id, adapter)

            self.assertFalse(adapter_called)
            self.assertFalse((run_dir / "verification.json").exists())
            self.assertEqual((run_dir / "events.jsonl").read_bytes(), events_before)
            self.assertEqual((run_dir / "manifest.json").read_bytes(), manifest_before)

    def test_semantic_writer_rejects_symlinked_verification_file(self):
        with TemporaryDirectory() as td:
            owned_root = Path(td)
            vault = owned_root / "vault"
            run_id = create_run(
                vault,
                RunSpec("capture", "shadow", [], None, BudgetSpec()),
            )
            run_dir = vault / ".brain" / "runs" / run_id
            verification_path = run_dir / "verification.json"
            external_report = owned_root / "external-verification.json"
            external_report.write_text(
                json.dumps({
                    "accepted": True,
                    "checks": [],
                    "failures": [],
                    "warnings": [],
                    "semantic": {"status": "skipped"},
                }),
                encoding="utf-8",
            )
            verification_path.symlink_to(external_report)
            events_before = (run_dir / "events.jsonl").read_bytes()

            with self.assertRaisesRegex(ValueError, "symlinked runtime ownership file"):
                merge_semantic_report(
                    vault,
                    run_id,
                    {
                        "checks": [{
                            "id": "semantic.safe",
                            "passed": True,
                            "severity": "critical",
                        }],
                    },
                )

            self.assertTrue(verification_path.is_symlink())
            self.assertEqual(
                json.loads(external_report.read_text(encoding="utf-8"))["checks"],
                [],
            )
            self.assertEqual((run_dir / "events.jsonl").read_bytes(), events_before)
            manifest = json.loads(
                (run_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["metrics"]["semantic_verifier_calls"],
                0,
            )

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
