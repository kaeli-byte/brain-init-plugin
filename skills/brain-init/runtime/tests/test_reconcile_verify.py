from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import unittest

from brain_runtime.contracts import BudgetSpec, RunSpec
from brain_runtime.reconcile_contract import candidate_id
from brain_runtime.run import create_run, declare_artifacts, run_dir_for, snapshot_tree
from brain_runtime.trace import TraceEvent, append_event
from brain_runtime.verify import verify_run

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SOURCE_ID = "src-acme-2026-annual-report"
RECORD_PATH = "wiki/reconciliations/reconcile-src-acme-2026-annual-report.md"
SOURCE_PATH = "wiki/sources/src-acme-2026-annual-report.md"
NEW_CLAIM_PATH = "wiki/claims/claim-acme-revenue-2026.md"
TARGET_CLAIM_PATH = "wiki/claims/claim-acme-operating-margin.md"

NEW_CLAIM_TEXT = "Acme's 2026 revenue reached RMB 12 billion."
CORROBORATING_CLAIM_TEXT = "Acme's 2026 operating margin increased to 14 percent."


def _source_page(key_claims="[claim-acme-operating-margin]"):
    return (
        "---\n"
        f"source_id: {SOURCE_ID}\n"
        "raw_path: raw/annual-reports/acme-2026-annual-report.pdf\n"
        "source_type: annual-report\n"
        "publisher: Acme Corporation\n"
        "date_published: 2026-04-01\n"
        "date_ingested: 2026-07-27\n"
        "last_reviewed: 2026-07-27\n"
        "reliability: audited\n"
        "materiality: high\n"
        f"key_claims: {key_claims}\n"
        "entities_covered: [entity-acme]\n"
        "---\n"
        "# Acme 2026 Annual Report\n"
    )


def _claim_page(
    claim_id_value,
    claim_text,
    *,
    status="confirmed",
    confidence="high",
    source_evidence_sources=f'[[{SOURCE_ID}]]',
    extra_frontmatter="",
    related_links="",
):
    return (
        "---\n"
        f"claim_id: {claim_id_value}\n"
        f'claim_text: "{claim_text}"\n'
        f"confidence: {confidence}\n"
        f"status: {status}\n"
        "source_evidence:\n"
        f'  - source: "{source_evidence_sources}"\n'
        '    passage: "Supporting passage."\n'
        '    context: "Page 1"\n'
        "first_seen: 2026-07-27\n"
        "last_verified: 2026-07-27\n"
        "last_reviewed: 2026-07-27\n"
        f"{extra_frontmatter}"
        "---\n"
        "# Evidence\n"
        "## Supporting\n"
        f"[[{SOURCE_ID}]]\n"
        f"{related_links}"
    )


def _frontmatter_block(**overrides):
    fields = {
        "reconciliation_id": "reconcile-src-acme-2026-annual-report",
        "source": f'"[[{SOURCE_ID}]]"',
        "origin": "capture",
        "status": "complete",
        "search_method": "qmd",
        "coverage_complete": "true",
        "created": "2026-07-27",
        "last_reviewed": "2026-07-27",
    }
    fields.update({key: str(value) for key, value in overrides.items()})
    lines = [f"{key}: {value}" for key, value in fields.items()]
    return "\n".join(lines)


def _candidate_block(
    claim_text,
    *,
    source_id=SOURCE_ID,
    candidate_id_value=None,
    disposition="new",
    target_claim="",
    reason='"A reason."',
    confidence_effect="unchanged",
    review_state="not_required",
    action_state="applied",
    result_claim='"[[claim-acme-revenue-2026]]"',
    reviewed_by="",
    reviewed_at="",
    review_note="",
):
    if candidate_id_value is None:
        candidate_id_value = candidate_id(source_id, claim_text)
    return (
        f"  - candidate_id: {candidate_id_value}\n"
        f'    claim_text: "{claim_text}"\n'
        "    source_evidence:\n"
        f'      - source: "[[{source_id}]]"\n'
        '        passage: "Exact supporting passage."\n'
        '        context: "Page 1"\n'
        '    entities: ["[[company-acme]]"]\n'
        f"    disposition: {disposition}\n"
        f"    target_claim: {target_claim}\n"
        f"    reason: {reason}\n"
        f"    confidence_effect: {confidence_effect}\n"
        f"    review_state: {review_state}\n"
        f"    action_state: {action_state}\n"
        f"    result_claim: {result_claim}\n"
        f"    reviewed_by: {reviewed_by}\n"
        f"    reviewed_at: {reviewed_at}\n"
        f"    review_note: {review_note}\n"
    )


def _record(*candidates, body_headings=True, **record_overrides):
    frontmatter = _frontmatter_block(**record_overrides)
    body = (
        "# Reconciliation: Acme 2026 Annual Report\n"
        "\n## Summary\n\nSummary.\n"
        "\n## Pending Review\n\nNone.\n"
        "\n## Changelog\n\n- Applied.\n"
    )
    if not body_headings:
        body = "# Reconciliation: Acme 2026 Annual Report\n"
    return f"---\n{frontmatter}\ncandidates:\n{''.join(candidates)}---\n{body}"


class ReconcileVerifyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.vault = Path(self.temporary.name) / "vault"
        self.vault.mkdir(parents=True)
        (self.vault / "wiki/claims").mkdir(parents=True)
        (self.vault / "wiki/sources").mkdir(parents=True)
        (self.vault / "wiki/reconciliations").mkdir(parents=True)
        (self.vault / "wiki/index.md").write_text(
            "---\nlast_reviewed: 2026-07-27\n---\n# Index\n", encoding="utf-8"
        )

    def tearDown(self):
        self.temporary.cleanup()

    # -- vault builders ------------------------------------------------------

    def _write(self, relative, content):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_source(self, **kwargs):
        self._write(SOURCE_PATH, _source_page(**kwargs))

    def _write_target_claim(self, **kwargs):
        self._write(
            TARGET_CLAIM_PATH,
            _claim_page("claim-acme-operating-margin", "Acme's operating margin was 14 percent.", **kwargs),
        )

    def _write_new_claim(self, **kwargs):
        self._write(
            NEW_CLAIM_PATH,
            _claim_page("claim-acme-revenue-2026", NEW_CLAIM_TEXT, **kwargs),
        )

    def _write_record(self, content):
        self._write(RECORD_PATH, content)

    # -- run helpers ---------------------------------------------------------

    def _create_run(self, extra_inputs=None):
        inputs = [
            path
            for path in [RECORD_PATH, SOURCE_PATH, TARGET_CLAIM_PATH]
            if (self.vault / path).is_file()
        ]
        inputs.extend(extra_inputs or [])
        return create_run(
            self.vault,
            RunSpec("reconcile", "shadow", inputs, None, BudgetSpec()),
        )

    def _event(self, run_id, kind, data=None):
        append_event(
            run_dir_for(self.vault, run_id),
            TraceEvent(
                ts="2026-07-27T00:00:00Z",
                kind=kind,
                operation="reconcile",
                run_id=run_id,
                label=f"{kind} result",
                data=data or {"passed": True},
            ),
        )

    def _workflow_events(self, run_id, *, search=True, classified=True, review_decisions=0, qmd=True, log=True):
        if search:
            self._event(run_id, "reconcile.search", {"method": "qmd", "coverage_complete": True})
        if classified:
            self._event(run_id, "reconcile.classified", {"new": 1, "corroborating": 1})
        for _ in range(review_decisions):
            self._event(run_id, "review.decision", {"candidate_id": "candidate-x", "decision": "approved"})
        if qmd:
            self._event(run_id, "workflow.qmd")
        if log:
            self._event(run_id, "workflow.log")

    def _verify(self, *, declared, extra_inputs=None, with_baseline=True, **event_kwargs):
        run_id = self._create_run(extra_inputs=extra_inputs)
        if with_baseline:
            snapshot_tree(self.vault, run_id, "wiki")
        self._workflow_events(run_id, **event_kwargs)
        declare_artifacts(self.vault, run_id, declared)
        from brain_runtime.adapters.reconcile import reconcile_checks
        return verify_run(self.vault, run_id, reconcile_checks)

    @staticmethod
    def _checks(report, check_id):
        return [check for check in report.checks if check.id == check_id]

    def _failed(self, report, check_id):
        return [check for check in self._checks(report, check_id) if not check.passed]

    # -- valid record --------------------------------------------------------

    def _build_valid_vault(self):
        self._write_source(key_claims="[claim-acme-operating-margin, claim-acme-revenue-2026]")
        self._write_target_claim()
        self._write_new_claim()
        shutil.copyfile(FIXTURES / "reconciliation-valid.md", self.vault / RECORD_PATH)

    def test_valid_complete_record_is_accepted(self):
        self._build_valid_vault()
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertTrue(report.accepted, [f"{c.id}: {c.message}" for c in report.checks if not c.passed and c.severity == "critical"])

    # -- structural record checks ----------------------------------------------

    def test_missing_required_field_is_rejected(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        # Build a record whose frontmatter omits the `source` field entirely.
        frontmatter = "\n".join(
            line for line in _frontmatter_block().splitlines()
            if not line.startswith("source:")
        )
        candidates = (
            _candidate_block(NEW_CLAIM_TEXT)
            + _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="corroborating",
                               target_claim='"[[claim-acme-operating-margin]]"',
                               result_claim='"[[claim-acme-operating-margin]]"')
        )
        self._write_record(
            f"---\n{frontmatter}\ncandidates:\n{candidates}---\n"
            "# Reconciliation: Acme 2026 Annual Report\n"
            "\n## Summary\n\nSummary.\n"
            "\n## Pending Review\n\nNone.\n"
            "\n## Changelog\n\n- Applied.\n"
        )
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.record.required_fields"))

    def test_invalid_origin_is_rejected(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="corroborating",
                             target_claim='"[[claim-acme-operating-margin]]"',
                             result_claim='"[[claim-acme-operating-margin]]"'),
            origin="bogus",
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.origin_enum"))

    def test_invalid_record_status_is_rejected(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="corroborating",
                             target_claim='"[[claim-acme-operating-margin]]"',
                             result_claim='"[[claim-acme-operating-margin]]"'),
            status="bogus",
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.record.status"))

    def test_duplicate_candidate_ids_are_rejected(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        duplicate_id = candidate_id(SOURCE_ID, NEW_CLAIM_TEXT)
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(CORROBORATING_CLAIM_TEXT,
                             candidate_id_value=duplicate_id,
                             disposition="corroborating",
                             target_claim='"[[claim-acme-operating-margin]]"',
                             result_claim='"[[claim-acme-operating-margin]]"'),
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.candidate_ids_unique"))

    def test_candidate_id_mismatch_is_rejected(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT, candidate_id_value="candidate-deadbeef0000"),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="corroborating",
                             target_claim='"[[claim-acme-operating-margin]]"',
                             result_claim='"[[claim-acme-operating-margin]]"'),
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.candidate_id_hash"))

    def test_capture_fewer_than_two_candidates_is_rejected(self):
        self._write_source()
        self._write_new_claim()
        record = _record(_candidate_block(NEW_CLAIM_TEXT))
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        failed = self._failed(report, "reconcile.candidate_count_min")
        self.assertTrue(failed)
        self.assertEqual(failed[0].severity, "critical")

    def test_legacy_single_candidate_is_accepted(self):
        self._write_source()
        self._write_target_claim()
        record = _record(
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="corroborating",
                             target_claim='"[[claim-acme-operating-margin]]"',
                             result_claim='"[[claim-acme-operating-margin]]"'),
            origin="legacy",
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(self._failed(report, "reconcile.candidate_count_min"))

    def test_more_than_six_capture_candidates_is_warning_only(self):
        self._write_source()
        blocks = []
        for index in range(7):
            text = f"Acme claim number {index} is true."
            blocks.append(_candidate_block(text, disposition="irrelevant", result_claim="",
                                           action_state="not_applicable", confidence_effect="not_applicable"))
        record = _record(*blocks)
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, "wiki/index.md"])
        count_checks = self._checks(report, "reconcile.candidate_count_max")
        self.assertTrue(count_checks)
        self.assertTrue(all(c.severity == "warning" for c in count_checks))

    def test_null_disposition_allowed_for_staged_record(self):
        self._write_source()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT, disposition="", target_claim="", reason="",
                             confidence_effect="", review_state="", action_state="", result_claim=""),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="", target_claim="", reason="",
                             confidence_effect="", review_state="", action_state="", result_claim=""),
            status="staged",
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, "wiki/index.md"])
        self.assertFalse(self._failed(report, "reconcile.disposition_enum"))

    def test_null_disposition_forbidden_for_complete_record(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT, disposition="", reason="", confidence_effect="",
                             review_state="", action_state="", result_claim=""),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="corroborating",
                             target_claim='"[[claim-acme-operating-margin]]"',
                             result_claim='"[[claim-acme-operating-margin]]"'),
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.disposition_enum"))

    def test_new_forbidden_when_coverage_incomplete(self):
        self._write_source()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="irrelevant", result_claim="",
                             action_state="not_applicable", confidence_effect="not_applicable"),
            coverage_complete="false",
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.candidate_new_requires_coverage"))

    def test_target_required_for_corroborating(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="corroborating",
                             result_claim='"[[claim-acme-operating-margin]]"'),
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.target_contract"))

    def test_target_forbidden_for_new(self):
        self._write_source()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT, target_claim='"[[claim-acme-operating-margin]]"'),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="irrelevant", result_claim="",
                             action_state="not_applicable", confidence_effect="not_applicable"),
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.target_contract"))

    def test_target_must_appear_in_manifest_inputs(self):
        self._write_source()
        self._write(
            "wiki/claims/claim-undeclared-target.md",
            _claim_page("claim-undeclared-target", "Some other proposition."),
        )
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(CORROBORATING_CLAIM_TEXT, disposition="corroborating",
                             target_claim='"[[claim-undeclared-target]]"',
                             result_claim='"[[claim-undeclared-target]]"'),
        )
        self._write_record(record)
        report = self._verify(
            declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, "wiki/claims/claim-undeclared-target.md", "wiki/index.md"],
        )
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.target_snapshotted"))

    # -- disposition-effect checks ----------------------------------------------

    def test_new_result_claim_must_exist_and_be_declared(self):
        self._write_source()
        self._write_target_claim()
        shutil.copyfile(FIXTURES / "reconciliation-valid.md", self.vault / RECORD_PATH)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.result_contract"))

    def test_rejected_sensitive_candidate_requires_review_note_and_no_result(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(
                CORROBORATING_CLAIM_TEXT,
                disposition="updating",
                target_claim='"[[claim-acme-operating-margin]]"',
                review_state="rejected",
                action_state="rejected",
                result_claim="",
                reviewed_by="human",
                reviewed_at="2026-07-27",
                review_note="",
            ),
        )
        self._write_record(record)
        report = self._verify(declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"],
                              review_decisions=1)
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.review_contract"))

    def test_approved_updating_requires_temporal_fields_and_superseded_by(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        self._write(
            "wiki/claims/claim-acme-operating-margin-2026.md",
            _claim_page(
                "claim-acme-operating-margin-2026",
                "Acme's 2026 operating margin was 15 percent.",
            ),
        )
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(
                CORROBORATING_CLAIM_TEXT,
                disposition="updating",
                target_claim='"[[claim-acme-operating-margin]]"',
                review_state="approved",
                action_state="applied",
                result_claim='"[[claim-acme-operating-margin-2026]]"',
                reviewed_by="human",
                reviewed_at="2026-07-27",
                review_note='"Approved."',
            ),
        )
        self._write_record(record)
        report = self._verify(
            declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH,
                      "wiki/claims/claim-acme-operating-margin-2026.md", "wiki/index.md"],
            extra_inputs=["wiki/claims/claim-acme-operating-margin-2026.md"],
            review_decisions=1,
        )
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.temporal_supersession"))

    def test_approved_contradiction_requires_disputed_status_and_opposing_evidence(self):
        self._write_source()
        self._write_target_claim()
        self._write(
            "wiki/claims/claim-acme-margin-contradiction.md",
            _claim_page("claim-acme-margin-contradiction", "Acme's margin did not increase."),
        )
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(
                CORROBORATING_CLAIM_TEXT,
                disposition="contradicting",
                target_claim='"[[claim-acme-operating-margin]]"',
                review_state="approved",
                action_state="applied",
                result_claim='"[[claim-acme-margin-contradiction]]"',
                reviewed_by="human",
                reviewed_at="2026-07-27",
                review_note='"Approved dispute."',
            ),
        )
        self._write_record(record)
        report = self._verify(
            declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH,
                      "wiki/claims/claim-acme-margin-contradiction.md", "wiki/index.md"],
            extra_inputs=["wiki/claims/claim-acme-margin-contradiction.md"],
            review_decisions=1,
        )
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.contradiction_evidence"))

    def test_pending_sensitive_target_retains_input_hash(self):
        self._write_source()
        self._write_target_claim()
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(
                CORROBORATING_CLAIM_TEXT,
                disposition="updating",
                target_claim='"[[claim-acme-operating-margin]]"',
                review_state="pending",
                action_state="pending",
                result_claim="",
            ),
            status="pending_review",
        )
        self._write_record(record)
        report_run = self._create_run()
        snapshot_tree(self.vault, report_run, "wiki")
        target = self.vault / TARGET_CLAIM_PATH
        target.write_text(target.read_text(encoding="utf-8") + "\nmutated while pending\n", encoding="utf-8")
        self._workflow_events(report_run)
        declare_artifacts(self.vault, report_run, [RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"])
        from brain_runtime.adapters.reconcile import reconcile_checks
        report = verify_run(self.vault, report_run, reconcile_checks)
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.pending_target_unchanged"))

    # -- scope checks -------------------------------------------------------------

    def test_undeclared_changed_wiki_page_is_critical(self):
        self._build_valid_vault()
        run_id = self._create_run()
        snapshot_tree(self.vault, run_id, "wiki")
        index = self.vault / "wiki/index.md"
        index.write_text(index.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        self._workflow_events(run_id)
        declare_artifacts(self.vault, run_id, [RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH])
        from brain_runtime.adapters.reconcile import reconcile_checks
        report = verify_run(self.vault, run_id, reconcile_checks)
        self.assertFalse(report.accepted)
        failed = self._failed(report, "reconcile.declared_scope")
        self.assertTrue(failed)
        self.assertEqual(failed[0].severity, "critical")

    def test_removed_wiki_page_is_critical(self):
        self._build_valid_vault()
        run_id = self._create_run()
        snapshot_tree(self.vault, run_id, "wiki")
        (self.vault / "wiki/index.md").unlink()
        self._workflow_events(run_id)
        declare_artifacts(self.vault, run_id, [RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH])
        from brain_runtime.adapters.reconcile import reconcile_checks
        report = verify_run(self.vault, run_id, reconcile_checks)
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.declared_scope"))

    def test_missing_baseline_is_critical(self):
        self._build_valid_vault()
        report = self._verify(
            declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"],
            with_baseline=False,
        )
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "reconcile.baseline_present"))

    # -- workflow-event checks -----------------------------------------------------

    def test_missing_search_event_is_critical(self):
        self._build_valid_vault()
        report = self._verify(
            declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"],
            search=False,
        )
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "workflow.reconcile_search"))

    def test_missing_review_decision_event_is_critical(self):
        self._write_source()
        self._write(
            "wiki/claims/claim-acme-operating-margin-2026.md",
            _claim_page(
                "claim-acme-operating-margin-2026",
                "Acme's 2026 operating margin was 15 percent.",
                extra_frontmatter="valid_from: 2026-01-01\n",
            ),
        )
        self._write_target_claim(
            status="superseded",
            extra_frontmatter="valid_to: 2025-12-31\nsuperseded_by: \"[[claim-acme-operating-margin-2026]]\"\n",
        )
        self._write_new_claim()
        record = _record(
            _candidate_block(NEW_CLAIM_TEXT),
            _candidate_block(
                CORROBORATING_CLAIM_TEXT,
                disposition="updating",
                target_claim='"[[claim-acme-operating-margin]]"',
                review_state="approved",
                action_state="applied",
                result_claim='"[[claim-acme-operating-margin-2026]]"',
                reviewed_by="human",
                reviewed_at="2026-07-27",
                review_note='"Approved."',
            ),
        )
        self._write_record(record)
        report = self._verify(
            declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH,
                      "wiki/claims/claim-acme-operating-margin-2026.md", "wiki/index.md"],
            extra_inputs=["wiki/claims/claim-acme-operating-margin-2026.md"],
            review_decisions=0,
        )
        self.assertFalse(report.accepted)
        self.assertTrue(self._failed(report, "workflow.review_decision"))

    def test_missing_log_event_is_critical(self):
        self._build_valid_vault()
        report = self._verify(
            declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"],
            log=False,
        )
        self.assertFalse(report.accepted)
        failed = self._failed(report, "workflow.log_completed")
        self.assertTrue(failed)
        self.assertEqual(failed[0].severity, "critical")

    def test_missing_qmd_event_is_warning_not_rejection(self):
        self._build_valid_vault()
        report = self._verify(
            declared=[RECORD_PATH, SOURCE_PATH, NEW_CLAIM_PATH, TARGET_CLAIM_PATH, "wiki/index.md"],
            qmd=False,
        )
        failed = self._failed(report, "workflow.qmd_refresh")
        self.assertTrue(failed)
        self.assertEqual(failed[0].severity, "warning")
        self.assertTrue(report.accepted)


if __name__ == "__main__":
    unittest.main()
