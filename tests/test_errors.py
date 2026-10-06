import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace

from persona_lab.backends import FixtureBackend, LocalLLMBackend
from persona_lab.contracts import ContractError, Decision
from persona_lab.runner import run, jobs
from persona_lab.reports import summarize, export

ROOT = Path(__file__).resolve().parents[1]


class ErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = ROOT / "data/packs/synthetic-fixture.jsonl"
        self.source = json.loads((ROOT / "data/packs/synthetic-fixture.json").read_text())
        self.spec = json.loads((ROOT / "examples/experiment.json").read_text())
        self.store = Path(self.temp.name) / "run.sqlite"

    def execute(self, backend, **kwargs):
        return run(self.path, self.source, self.spec, self.store, backend, **kwargs)

    def test_invalid_json_and_timeout_continue_are_separate_from_unknown_and_retry_only_errors(self):
        called = []
        class Faults(FixtureBackend):
            def decide(inner, job):
                if job.ordinal in {3, 17}: raise ContractError("invalid model JSON")
                if job.ordinal == 24: raise TimeoutError("local request timed out")
                return super().decide(job)
        status = self.execute(Faults())
        self.assertEqual((status["cursor"], status["status"], status["backend_errors"]), (56, "completed_with_errors", 3))
        report = summarize(self.store)
        self.assertEqual((report["valid_decisions"], report["backend_errors"]), (53, 3))
        self.assertNotIn("__backend_error__", str([g["choice_counts"] for g in report["groups"]]))
        with sqlite3.connect(self.store) as db:
            original = dict(db.execute("SELECT job_id,payload FROM results WHERE status!='backend_error'"))
        class Retry(FixtureBackend):
            def decide(inner, job):
                called.append(job.ordinal)
                return super().decide(job)
        status = self.execute(Retry(), retry_errors=True)
        self.assertEqual(called, [3, 17, 24])
        self.assertEqual((status["status"], status["backend_errors"], status["cursor"]), ("completed", 0, 56))
        with sqlite3.connect(self.store) as db:
            current = dict(db.execute("SELECT job_id,payload FROM results"))
        self.assertTrue(all(current[key] == value for key, value in original.items()))

    def test_persistently_invalid_response_can_be_exported_without_mock_replacement(self):
        class Invalid(FixtureBackend):
            kind = "local_inference"
            backend_id = "invalid-response-test"
            def decide(inner, job): return Decision("unlisted", "ok", ("r",), ("product.price",))
        self.execute(Invalid())
        report = summarize(self.store)
        self.assertEqual((report["valid_decisions"], report["backend_errors"]), (0, 56))
        self.assertEqual(report["backend_kind"], "local_inference")
        self.assertEqual(report["paired_transition_count"], 0)
        for format in ("json", "csv", "md"):
            self.assertTrue(export(self.store, format)[0])

    def test_purchase_and_no_event_churn_gates_make_no_model_request(self):
        self.spec["assumptions"] = {}
        stream = list(jobs(self.path, self.source, self.spec))
        backend = LocalLLMBackend()
        for domain in ("purchase", "churn"):
            job = next(j for j in stream if j.question["domain"] == domain)
            self.assertEqual(backend.decide(job).choice, "unknown")
        self.assertEqual(backend.metrics["requests"], 0)

    def test_large_repeat_count_is_lazy(self):
        self.spec["repeats"] = 1000000000
        self.assertEqual(next(jobs(self.path, self.source, self.spec)).ordinal, 0)

    def test_csv_formula_identifiers_are_escaped(self):
        self.spec["products"][0]["id"] = "=1+1"
        self.execute(FixtureBackend())
        csv, _ = export(self.store, "csv")
        self.assertIn("'=1+1", csv)

    def test_budget_conflicts_are_flagged_without_rewriting_results(self):
        self.spec["assumptions"] = {"purchase_budget_jpy_minor": 1500}
        class OverBudget(FixtureBackend):
            def decide(inner, job):
                if job.question["domain"] == "purchase":
                    return Decision("buy", "ok", ("model_choice",), ("product.price",))
                return super().decide(job)
        self.execute(OverBudget())
        report = summarize(self.store)
        self.assertEqual(report["consistency_warnings"]["purchase_above_explicit_budget"], 4)
        self.assertEqual(report["valid_decisions"], 56)
        self.assertEqual(report["backend_errors"], 0)
        self.assertEqual(report["paired_purchase_transitions"], [{"from": "buy", "to": "buy", "count": 4}])
        self.assertEqual(next(g for g in report["groups"] if g["product_id"] == "A" and g["domain"] == "purchase")["choice_counts"], {"buy": 4})
        self.assertIn("run_budget_conflicts", export(self.store, "csv")[0])
        self.assertIn("budget: 4 decisions", export(self.store, "md")[0])


if __name__ == "__main__": unittest.main()
