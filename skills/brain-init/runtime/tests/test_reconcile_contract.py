from pathlib import Path
import json
import unittest

import yaml

from brain_runtime.reconcile_contract import (
    ACTION_STATES,
    DISPOSITIONS,
    RECORD_STATUSES,
    candidate_id,
    normalize_claim_text,
)


BRAIN_INIT_ROOT = Path(__file__).resolve().parents[2]


class ReconcileContractTests(unittest.TestCase):
    def test_candidate_id_is_stable_after_whitespace_normalization(self):
        first = candidate_id("src-acme", "  Margin   increased to 14%. ")
        second = candidate_id("src-acme", "Margin increased to 14%.")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^candidate-[0-9a-f]{12}$")

    def test_candidate_id_is_scoped_to_source(self):
        self.assertNotEqual(
            candidate_id("src-acme", "Margin increased."),
            candidate_id("src-beta", "Margin increased."),
        )

    def test_normalize_claim_text_rejects_empty_and_non_string(self):
        with self.assertRaises(ValueError):
            normalize_claim_text("   ")
        with self.assertRaises(ValueError):
            normalize_claim_text(None)

    def test_candidate_id_rejects_blank_source(self):
        with self.assertRaises(ValueError):
            candidate_id("  ", "Margin increased.")

    def test_contract_enums_are_exact(self):
        self.assertEqual(
            DISPOSITIONS,
            {
                "new", "corroborating", "updating",
                "contradicting", "superseding", "irrelevant",
            },
        )
        self.assertEqual(
            RECORD_STATUSES,
            {"staged", "pending_review", "complete", "incomplete"},
        )
        self.assertEqual(
            ACTION_STATES,
            {"pending", "applied", "not_applicable", "rejected"},
        )

    def test_reconciliation_schema_and_obsidian_types_cover_new_fields(self):
        schema = yaml.safe_load(
            (BRAIN_INIT_ROOT / "assets/schemas/reconciliation.yaml").read_text()
        )
        types = json.loads(
            (BRAIN_INIT_ROOT / "assets/obsidian/types.json").read_text()
        )["types"]
        for field in (
            "reconciliation_id", "origin", "search_method",
            "coverage_complete", "candidates",
        ):
            self.assertIn(field, schema)
            self.assertIn(field, types)
        self.assertIn("valid_from", types)
        self.assertIn("valid_to", types)


if __name__ == "__main__":
    unittest.main()
