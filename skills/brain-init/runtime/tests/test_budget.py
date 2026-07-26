import unittest

from brain_runtime.budget import FanoutRequest, advise_fanout, record_budget_metric
from brain_runtime.contracts import BudgetSpec


class BudgetTests(unittest.TestCase):
    def test_one_slice_stays_single(self):
        req = FanoutRequest(
            slices=[{"id": "mda"}],
            parallelizable=True,
            exceeds_one_context=True,
            high_value=True,
        )
        decision = advise_fanout(req, BudgetSpec())
        self.assertEqual(decision.mode, "single")
        self.assertEqual(decision.max_workers, 1)

    def test_dependent_slices_stay_single(self):
        req = FanoutRequest(
            slices=[{"id": "business"}, {"id": "mda"}],
            parallelizable=False,
            exceeds_one_context=True,
            high_value=True,
        )
        self.assertEqual(advise_fanout(req, BudgetSpec()).mode, "single")

    def test_parallel_context_pressure_recommends_fanout(self):
        req = FanoutRequest(
            slices=[{"id": "business"}, {"id": "mda"}, {"id": "segments"}],
            parallelizable=True,
            exceeds_one_context=True,
            high_value=False,
        )
        decision = advise_fanout(req, BudgetSpec(max_workers=2))
        self.assertEqual(decision.mode, "fanout")
        self.assertEqual(decision.max_workers, 2)

    def test_parallel_low_value_work_that_fits_context_stays_single(self):
        req = FanoutRequest(
            slices=[{"id": "business"}, {"id": "mda"}],
            parallelizable=True,
            exceeds_one_context=False,
            high_value=False,
        )
        self.assertEqual(advise_fanout(req, BudgetSpec()).mode, "single")

    def test_record_budget_metric_copies_and_increments_selected_metric(self):
        manifest = {"metrics": {"workers": 1}, "run_id": "run-1"}

        updated = record_budget_metric(manifest, "workers", increment=2)

        self.assertEqual(updated["metrics"]["workers"], 3)
        self.assertEqual(manifest, {"metrics": {"workers": 1}, "run_id": "run-1"})

    def test_record_budget_metric_rejects_unknown_metric(self):
        with self.assertRaises(ValueError):
            record_budget_metric({}, "tokens")
