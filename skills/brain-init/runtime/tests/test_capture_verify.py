from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import unittest

from brain_runtime.adapters.capture import capture_checks
from brain_runtime.contracts import BudgetSpec, RunSpec
from brain_runtime.run import create_run, declare_artifacts, run_dir_for
from brain_runtime.trace import TraceEvent, append_event, read_events
from brain_runtime.verify import verify_run
from helpers import FIXTURES, build_capture_vault


EXPECTED_CHECK_IDS = {
    "artifact.exists",
    "artifact.sha256",
    "frontmatter.valid_yaml",
    "claim.required_fields",
    "claim.confidence_enum",
    "claim.status_enum",
    "claim.source_evidence",
    "claim.source_page_exists",
    "evidence.locator_resolves",
    "source.required_fields",
    "source.enum_values",
    "source.company_link",
    "company.source_backlink",
    "capture.claim_count_min",
    "capture.source_count",
    "capture.company_count",
    "capture.section_plan",
    "capture.profile_recognized",
    "workflow.qmd_refresh",
    "workflow.log_completed",
}


class CaptureVerifyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.vault = Path(self.temporary.name) / "vault"
        self.paths = build_capture_vault(self.vault)

    def tearDown(self):
        self.temporary.cleanup()

    def _add_second_claim(self):
        first = self.vault / self.paths[0]
        second = first.with_name("claim-acme-revenue-second.md")
        second.write_text(
            first.read_text().replace(
                "claim-acme-revenue-12345678",
                "claim-acme-revenue-87654321",
            )
        )
        self.paths.insert(1, second.relative_to(self.vault).as_posix())

    def _create_run(
        self,
        *,
        profile="annual-report-v1",
        plan=True,
        log_passed=True,
        qmd_passed=True,
        qmd_event=True,
        metadata=None,
        input_refs=None,
    ):
        input_refs = input_refs or [
            "raw/annual-reports/acme-2025-annual-report.pdf",
        ]
        run_id = create_run(
            self.vault,
            RunSpec(
                "capture",
                "shadow",
                input_refs,
                profile,
                BudgetSpec(),
                metadata=metadata or {
                    "source_type": "annual-report",
                    "exceeds_one_context": True,
                },
            ),
        )
        run_dir = run_dir_for(self.vault, run_id)
        if plan:
            shutil.copyfile(FIXTURES / "section-map-fanout.json", run_dir / "plan.json")
        if log_passed is not None:
            self._event(run_id, "workflow.log", log_passed)
        if qmd_event:
            self._event(run_id, "workflow.qmd", qmd_passed)
        return run_id

    def _event(self, run_id, kind, passed):
        append_event(
            run_dir_for(self.vault, run_id),
            TraceEvent(
                ts="2026-07-26T00:00:00Z",
                kind=kind,
                operation="capture",
                run_id=run_id,
                label=f"{kind} result",
                data={"passed": passed},
            ),
        )

    def _verify(self, *, claim_fixture=None, **run_options):
        if claim_fixture:
            shutil.copyfile(FIXTURES / claim_fixture, self.vault / self.paths[0])
        self._add_second_claim()
        run_id = self._create_run(**run_options)
        declare_artifacts(self.vault, run_id, self.paths)
        return verify_run(self.vault, run_id, capture_checks)

    def _add_mixed_locator_source(self, unavailable_first):
        source = self.vault / "wiki/sources/src-acme-unavailable.md"
        source.write_text(
            (FIXTURES / "valid-source.md").read_text()
            .replace(
                "source_id: src-acme-2025-annual-report",
                "source_id: src-acme-unavailable",
            )
            .replace(
                "raw/annual-reports/acme-2025-annual-report.pdf",
                "raw/annual-reports/acme-unavailable.pdf",
            )
        )
        self.paths.append(source.relative_to(self.vault).as_posix())
        unavailable = (
            "  - source: \"[[src-acme-unavailable]]\"\n"
            "    passage: \"A locator that cannot be mechanically checked.\"\n"
            "    context: \"Unavailable conversion\"\n"
        )
        disproven = (
            "  - source: \"[[src-acme-2025-annual-report]]\"\n"
            "    passage: \"A passage that is not present.\"\n"
            "    context: \"Converted markdown exists\"\n"
        )
        entries = unavailable + disproven if unavailable_first else disproven + unavailable
        claim = self.vault / self.paths[0]
        claim.write_text(
            claim.read_text().replace(
                "  - source: \"[[src-acme-2025-annual-report]]\"\n"
                "    passage: \"Revenue for 2025 was RMB 10 billion.\"\n"
                "    context: \"Page 12, Results of Operations\"\n",
                entries,
            )
        )

    @staticmethod
    def _checks(report, check_id):
        return [check for check in report.checks if check.id == check_id]

    def test_declare_artifacts_hashes_only_vault_relative_files(self):
        run_id = self._create_run()
        refs = declare_artifacts(self.vault, run_id, self.paths)

        self.assertEqual([ref.path for ref in refs], self.paths)
        self.assertTrue(all(not Path(ref.path).is_absolute() for ref in refs))
        payload = json.loads((run_dir_for(self.vault, run_id) / "artifacts.json").read_text())
        self.assertEqual(payload, {"artifacts": [ref.to_dict() for ref in refs]})
        event = read_events(run_dir_for(self.vault, run_id))[-1]
        self.assertEqual(event.kind, "artifact.declare")
        self.assertEqual(event.data, {"count": 3, "paths": self.paths})
        self.assertNotIn("Acme generated", json.dumps(event.data))

    def test_declare_artifacts_rejects_parent_traversal(self):
        outside = self.vault.parent / "outside.md"
        outside.write_text("outside")
        run_id = self._create_run()

        with self.assertRaises(ValueError):
            declare_artifacts(self.vault, run_id, ["../outside.md"])

    def test_declare_artifacts_singularizes_unambiguous_wiki_category(self):
        technology = self.vault / "wiki/technologies/technology-fluid-handling.md"
        technology.parent.mkdir(parents=True)
        technology.write_text("---\nlast_reviewed: 2026-07-26\n---\n# Fluid Handling\n")
        run_id = self._create_run()

        refs = declare_artifacts(
            self.vault,
            run_id,
            ["wiki/technologies/technology-fluid-handling.md"],
        )

        self.assertEqual(refs[0].kind, "technology")

    def test_declare_artifacts_rejects_duplicate_normalized_paths(self):
        run_id = self._create_run()

        with self.assertRaisesRegex(ValueError, "duplicate artifact path"):
            declare_artifacts(
                self.vault,
                run_id,
                [
                    "wiki/claims/claim-acme-revenue.md",
                    "wiki/claims/../claims/claim-acme-revenue.md",
                ],
            )

    def test_oversized_declaration_does_not_partially_replace_artifact_state(self):
        run_id = self._create_run()
        run_dir = run_dir_for(self.vault, run_id)
        declare_artifacts(self.vault, run_id, self.paths)
        artifacts_before = (run_dir / "artifacts.json").read_bytes()
        events_before = (run_dir / "events.jsonl").read_bytes()
        oversized_paths = []
        directory = self.vault / "wiki" / "analyses"
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(60):
            artifact = directory / (
                f"analysis-{index:03d}-" + ("x" * 150) + ".md"
            )
            artifact.write_text("---\nlast_reviewed: 2026-07-26\n---\n")
            oversized_paths.append(artifact.relative_to(self.vault).as_posix())

        with self.assertRaisesRegex(ValueError, "trace event exceeds"):
            declare_artifacts(self.vault, run_id, oversized_paths)

        self.assertEqual(
            (run_dir / "artifacts.json").read_bytes(),
            artifacts_before,
        )
        self.assertEqual((run_dir / "events.jsonl").read_bytes(), events_before)

    def test_valid_capture_is_accepted(self):
        report = self._verify()

        self.assertTrue(report.accepted)
        self.assertTrue(EXPECTED_CHECK_IDS.issubset({check.id for check in report.checks}))
        self.assertFalse([check for check in report.checks if not check.passed])

    def test_complete_capture_artifact_set_accepts_root_index_and_log(self):
        index_path = self.vault / "wiki/index.md"
        index_path.write_text(
            "---\n"
            "last_reviewed: 2026-07-26\n"
            "---\n"
            "# Index\n",
            encoding="utf-8",
        )
        log_path = self.vault / "wiki/log.md"
        log_path.write_text(
            "---\n"
            "tags: [log]\n"
            "created: 2026-07-26\n"
            "---\n"
            "# Operations Log\n",
            encoding="utf-8",
        )
        self.paths.extend(["wiki/index.md", "wiki/log.md"])

        report = self._verify()

        self.assertTrue(report.accepted)
        self.assertFalse([
            check
            for check in self._checks(report, "page.last_reviewed")
            if check.artifact == "wiki/log.md"
        ])

    def test_missing_source_evidence_is_rejected(self):
        report = self._verify(claim_fixture="invalid-claim-no-source.md")

        self.assertFalse(report.accepted)
        self.assertTrue(any(not check.passed for check in self._checks(report, "claim.source_evidence")))

    def test_invalid_claim_status_is_rejected(self):
        report = self._verify(claim_fixture="invalid-claim-status.md")

        self.assertFalse(report.accepted)
        self.assertTrue(any(not check.passed for check in self._checks(report, "claim.status_enum")))

    def test_missing_source_company_backlink_is_rejected(self):
        company = self.vault / "wiki/companies/company-acme.md"
        company.write_text(company.read_text().replace("[[src-acme-2025-annual-report]]", ""))

        report = self._verify()

        self.assertFalse(report.accepted)
        self.assertTrue(any(not check.passed for check in self._checks(report, "company.source_backlink")))

    def test_missing_evidence_passage_is_rejected_when_markdown_exists(self):
        claim = self.vault / self.paths[0]
        claim.write_text(
            claim.read_text().replace(
                "Revenue for 2025 was RMB 10 billion.",
                "A passage that is not present.",
            )
        )

        report = self._verify()

        self.assertFalse(report.accepted)
        self.assertTrue(any(not check.passed for check in self._checks(report, "evidence.locator_resolves")))

    def test_critical_locator_failure_survives_later_unavailable_warning(self):
        self._add_mixed_locator_source(unavailable_first=False)

        report = self._verify()

        failed = [
            check for check in self._checks(report, "evidence.locator_resolves")
            if not check.passed
        ]
        self.assertTrue(failed)
        self.assertTrue(all(check.severity == "critical" for check in failed))
        self.assertFalse(report.accepted)

    def test_critical_locator_failure_survives_earlier_unavailable_warning(self):
        self._add_mixed_locator_source(unavailable_first=True)

        report = self._verify()

        failed = [
            check for check in self._checks(report, "evidence.locator_resolves")
            if not check.passed
        ]
        self.assertTrue(failed)
        self.assertTrue(all(check.severity == "critical" for check in failed))
        self.assertFalse(report.accepted)

    def test_two_claim_minimum_is_a_critical_output_contract_check(self):
        run_id = self._create_run()
        declare_artifacts(self.vault, run_id, self.paths)

        report = verify_run(self.vault, run_id, capture_checks)

        check = self._checks(report, "capture.claim_count_min")[0]
        self.assertFalse(check.passed)
        self.assertEqual(check.severity, "critical")
        self.assertFalse(report.accepted)

    def test_long_annual_report_requires_recorded_section_plan(self):
        report = self._verify(plan=False)

        check = self._checks(report, "capture.section_plan")[0]
        self.assertFalse(check.passed)
        self.assertEqual(check.severity, "warning")
        self.assertTrue(report.accepted)

    def test_annual_report_requires_recognized_profile(self):
        report = self._verify(profile="custom-profile")

        check = self._checks(report, "capture.profile_recognized")[0]
        self.assertFalse(check.passed)
        self.assertEqual(check.severity, "critical")
        self.assertFalse(report.accepted)

    def test_fanout_plan_marks_annual_report_as_long(self):
        report = self._verify(
            profile="custom-profile",
            metadata={"source_type": "annual-report"},
        )

        check = self._checks(report, "capture.profile_recognized")[0]
        self.assertFalse(check.passed)
        self.assertFalse(report.accepted)

    def test_sec_10k_path_accepts_sec_filing_profile_without_source_metadata(self):
        sec_input = self.vault / "raw/sec-filings/acme-10-k.pdf"
        sec_input.parent.mkdir(parents=True)
        sec_input.write_bytes(b"fixture-10-k")

        report = self._verify(
            profile="sec-filing-v1",
            metadata={"exceeds_one_context": True},
            input_refs=["raw/sec-filings/acme-10-k.pdf"],
        )

        check = self._checks(report, "capture.profile_recognized")[0]
        self.assertTrue(check.passed)
        self.assertTrue(report.accepted)

    def test_sec_10k_path_rejects_unrecognized_profile_without_source_metadata(self):
        sec_input = self.vault / "raw/sec-filings/acme-10-k.pdf"
        sec_input.parent.mkdir(parents=True)
        sec_input.write_bytes(b"fixture-10-k")

        report = self._verify(
            profile="custom-profile",
            metadata={"exceeds_one_context": True},
            input_refs=["raw/sec-filings/acme-10-k.pdf"],
        )

        check = self._checks(report, "capture.profile_recognized")[0]
        self.assertFalse(check.passed)
        self.assertEqual(check.severity, "critical")
        self.assertFalse(report.accepted)

    def test_missing_qmd_completion_is_warning_not_rejection(self):
        report = self._verify(qmd_event=False)

        check = self._checks(report, "workflow.qmd_refresh")[0]
        self.assertFalse(check.passed)
        self.assertEqual(check.severity, "warning")
        self.assertTrue(report.accepted)

    def test_failed_qmd_refresh_is_warning_not_rejection(self):
        report = self._verify(qmd_passed=False)

        check = self._checks(report, "workflow.qmd_refresh")[0]
        self.assertFalse(check.passed)
        self.assertEqual(check.severity, "warning")
        self.assertTrue(report.accepted)

    def test_missing_completed_log_signal_is_critical(self):
        report = self._verify(log_passed=None)

        check = self._checks(report, "workflow.log_completed")[0]
        self.assertFalse(check.passed)
        self.assertEqual(check.severity, "critical")
        self.assertFalse(report.accepted)

    def test_artifact_declaration_always_contains_sha256(self):
        run_id = self._create_run()
        refs = declare_artifacts(self.vault, run_id, self.paths)

        self.assertTrue(refs)
        for ref in refs:
            self.assertRegex(ref.sha256, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
