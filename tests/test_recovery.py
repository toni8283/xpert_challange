"""Regression checks added while restoring the disconnected build."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from check import validate
from coldstart.data import Corpus
from coldstart.normalize import normalize_graph, normalize_loop
from coldstart.pipeline import main
from coldstart.policy import normalize_help
from coldstart.rules import infer_graph, infer_people, infer_loops
from coldstart.schema_guard import schema_errors
from llm import BudgetExceeded, Client, ModelError
from test_core import make_input, task

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = make_input(Path(self.temp.name) / "input")
        self.corpus = Corpus(self.folder)

    def tearDown(self):
        self.temp.cleanup()

    def test_casual_question_is_not_a_task(self):
        # A social check-in alone does not create a reminder obligation.
        m = {**self.corpus.message["t1"], "id": "social_q", "body": "How are you doing today?"}
        self.corpus.messages.append(m)
        self.corpus.message[m["id"]] = m
        self.corpus.by_chat[m["chat_id"]].append(m)
        graph = infer_graph(self.corpus)
        predicted = infer_loops(self.corpus, infer_people(self.corpus, graph))
        self.assertNotIn("social_q", {l["source_msg"] for l in predicted})

    def test_model_can_attach_a_direct_chat_to_organisation(self):
        draft = infer_graph(self.corpus)
        oid = draft["organisations"][0]["id"]
        graph = normalize_graph({"organisations": draft["organisations"], "chats": [{"chat_id": "direct_v", "organisation": oid}]}, draft, self.corpus)
        tie = next(t for t in graph["chats"] if t["chat_id"] == "direct_v")
        self.assertEqual(tie, {"chat_id": "direct_v", "organisation": oid})

    def test_graph_non_array_fields_retain_fallback(self):
        draft = infer_graph(self.corpus)
        self.assertEqual(normalize_graph({"organisations": None, "chats": 42}, draft, self.corpus), draft)

    def test_graph_missing_object_retains_fallback(self):
        draft = infer_graph(self.corpus)
        self.assertEqual(normalize_graph(None, draft, self.corpus), draft)

    def test_self_only_chat_has_valid_assignment(self):
        chats = [{"chat_id": "self", "name": "Notes", "is_group": False, "participants": ["ME"]}]
        (self.folder / "chats.jsonl").write_text(json.dumps(chats[0]) + "\n")
        (self.folder / "messages.jsonl").write_text("")
        (self.folder / "seed.json").write_text("{}")
        corpus = Corpus(self.folder)
        graph = infer_graph(corpus)
        result = {**graph, "people": [], "goals": [], "open_loops": []}
        self.assertEqual(validate(result, corpus.chats, corpus.messages), [])

    def test_contextless_done_does_not_close_execution(self):
        self.corpus.message["t3"]["body"] = "Done"
        loop = normalize_loop(task(status="done", closed_by="t3"), self.corpus, {})
        self.assertEqual(loop["status"], "open")

    def test_future_promise_does_not_close_execution(self):
        self.corpus.message["t3"]["body"] = "I will send the report tomorrow"
        loop = normalize_loop(task(status="done", closed_by="t3"), self.corpus, {})
        self.assertEqual(loop["status"], "open")

    def test_negated_completion_stays_open(self):
        self.corpus.message["t3"]["body"] = "The report has not been sent"
        loop = normalize_loop(task(status="done", closed_by="t3"), self.corpus, {})
        self.assertEqual(loop["status"], "open")

    def test_binary_decision_answer_can_close_question(self):
        self.corpus.message["t1"]["body"] = "Should we accept the revised proposal?"
        self.corpus.message["t3"]["body"] = "Yes"
        loop = normalize_loop(task(type="question", status="done", closed_by="t3"), self.corpus, {})
        self.assertEqual(loop["status"], "done")

    def test_thanks_does_not_close_question(self):
        self.corpus.message["t1"]["body"] = "Should we accept the revised proposal?"
        self.corpus.message["t3"]["body"] = "Thanks"
        loop = normalize_loop(task(type="question", status="done", closed_by="t3"), self.corpus, {})
        self.assertEqual(loop["status"], "open")

    def test_wrong_actors_yes_does_not_close_decision(self):
        self.corpus.message["t1"]["body"] = "Should we accept the revised proposal?"
        self.corpus.message["t2"]["body"] = "Yes"
        loop = normalize_loop(task(type="question", status="done", closed_by="t2"), self.corpus, {})
        self.assertEqual(loop["status"], "open")

    def test_spouses_independent_overdue_plan_stays_quiet(self):
        loop = task(owner="a", type="followup", due="2020-01-01")
        value = normalize_help({"action": "remind"}, loop, self.corpus, {"a": {"circle": "spouse"}})
        self.assertEqual(value["action"], "leave")

    def test_schema_rejects_unknown_nested_fields(self):
        graph = infer_graph(self.corpus)
        result = {**graph, "people": infer_people(self.corpus, graph), "goals": [], "open_loops": []}
        result["people"][0]["extra"] = True
        schema = json.loads((ROOT / "schema.json").read_text())
        self.assertTrue(schema_errors(result, schema))

    def test_schema_rejects_dual_chat_assignment(self):
        graph = infer_graph(self.corpus)
        graph["chats"][0]["organisation"] = graph["organisations"][0]["id"]
        result = {**graph, "people": [], "goals": [], "open_loops": []}
        schema = json.loads((ROOT / "schema.json").read_text())
        self.assertTrue(schema_errors(result, schema))

    def test_local_call_budget_does_not_discard_valid_output(self):
        env = {"XPERT_MODE": "model", "LLM_BASE_URL": "https://model.example/v1", "LLM_API_KEY": "synthetic-test-key", "LLM_MODEL": "test-model", "XPERT_MAX_CALLS": "0"}
        with patch.dict(os.environ, env), patch.object(Client, "_request", side_effect=AssertionError("Network must not be called")):
            result, metrics = main(self.folder, Path(self.temp.name) / "budget-output.json")
        self.assertTrue(metrics["budget_exhausted"])
        self.assertEqual(metrics["usage"]["request_attempts"], 0)
        self.assertEqual(validate(result, self.corpus.chats, self.corpus.messages), [])
        self.assertTrue(result["open_loops"])

    def test_model_provider_error_preserves_valid_fallback(self):
        # A failed provider must never destroy a valid previous-stage result
        # or leak user data/credentials into committed diagnostics.
        env = {"XPERT_MODE": "model", "LLM_BASE_URL": "https://model.example/v1",
               "LLM_API_KEY": "synthetic-test-key", "LLM_MODEL": "test-model"}
        with patch.dict(os.environ, env), patch.object(Client, "json", side_effect=ModelError("simulated provider failure")):
            result, metrics = main(self.folder, Path(self.temp.name) / "provider-error.json")
        self.assertTrue(metrics["model_degraded"])
        self.assertIn("graph", metrics["model_error_fallback_batches"])
        self.assertIn("loops", metrics["model_error_fallback_batches"])
        self.assertEqual(validate(result, self.corpus.chats, self.corpus.messages), [])
        self.assertTrue(result["open_loops"])
        report = (Path(self.temp.name) / "provider-error.run" / "report.json").read_text()
        self.assertNotIn("synthetic-test-key", report)
        self.assertNotIn("simulated provider failure", report)

    def test_client_budget_does_not_count_unsent_attempts(self):
        env = {"LLM_BASE_URL": "https://model.example/v1", "LLM_API_KEY": "synthetic-test-key", "LLM_MODEL": "test-model", "XPERT_MAX_CALLS": "0"}
        with patch.dict(os.environ, env):
            client = Client(Path(self.temp.name) / "run", Path(self.temp.name) / "cache", time.monotonic() + 30)
            with self.assertRaises(BudgetExceeded):
                client.json("test", "Return JSON", {})
        self.assertEqual(client.calls, 0)

    def test_output_cannot_overwrite_input(self):
        before = (self.folder / "messages.jsonl").read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            main(self.folder, self.folder / "messages.jsonl")
        self.assertEqual(before, (self.folder / "messages.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
