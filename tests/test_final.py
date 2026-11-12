"""Invented-data regressions for the final precision and completion changes."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from coldstart.data import Corpus
from coldstart.pipeline import main
from coldstart.rules import infer_graph, infer_people, infer_loops, attach_work_chats, _source_candidate
from llm import Client
from scripts.probe_free_model import check_response, MODEL
from test_core import make_input

ROOT = Path(__file__).resolve().parents[1]


class FinalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = make_input(Path(self.temp.name) / "input")
        self.corpus = Corpus(self.folder)

    def tearDown(self):
        self.temp.cleanup()

    def people(self):
        return {p["id"]: p for p in infer_people(self.corpus, infer_graph(self.corpus))}

    def candidate(self, body):
        return _source_candidate({**self.corpus.message["t1"], "body": body}, self.corpus, self.people())

    def source_loop(self, source, body, reply):
        self.corpus.message[source]["body"] = body
        close = "t3" if source == "t1" else "t6"
        self.corpus.message[close]["body"] = reply
        loops = infer_loops(self.corpus, list(self.people().values()))
        return next(l for l in loops if l["source_msg"] == source)

    def test_internal_group_supports_colleague(self):
        self.corpus.chat["team"]["name"] = "Cedar operations"
        self.assertEqual(self.people()["c"]["circle"], "colleague")

    def test_ad_service_group_supports_client(self):
        self.corpus.chat["team"]["name"] = "Acorn Ad-Targeting"
        self.assertEqual(self.people()["c"]["circle"], "client")

    def test_seed_circle_survives_internal_group(self):
        self.corpus.chat["house"]["name"] = "Cedar operations"
        self.assertEqual(self.people()["a"]["circle"], "spouse")

    def test_home_saved_name_needs_domestic_group(self):
        self.corpus.names["k"] = ["Morgan Home"]
        self.assertEqual(self.people()["k"]["circle"], "staff")
        self.corpus.chat["house"]["name"] = "Weekend friends"
        self.assertEqual(self.people()["k"]["circle"], "friend")

    def test_trading_company_supports_vendor(self):
        self.corpus.names["k"] = ["Acorn Trading Company"]
        self.assertEqual(self.people()["k"]["circle"], "vendor")

    def test_work_chat_requires_both_link_and_work_context(self):
        graph = infer_graph(self.corpus)
        oid = next(o["id"] for o in graph["organisations"] if o["name"] == "Cedar Studio")
        person = {"id": "v", "circle": "colleague", "links": [{"organisation": oid, "link": "runs"}]}
        attach_work_chats(self.corpus, graph, [person])
        self.assertEqual(next(t for t in graph["chats"] if t["chat_id"] == "direct_v")["organisation"], oid)
        graph = infer_graph(self.corpus)
        person["circle"] = "client"
        attach_work_chats(self.corpus, graph, [person])
        self.assertIn("person", next(t for t in graph["chats"] if t["chat_id"] == "direct_v"))

    def test_unrelated_attachment_does_not_complete_report(self):
        loop = self.source_loop("t1", "I'll send the report tomorrow", "Consent form attached")
        self.assertEqual(loop["status"], "open")

    def test_named_attachment_completes_report(self):
        loop = self.source_loop("t1", "I'll send the report tomorrow", "Report attached")
        self.assertEqual((loop["status"], loop["closed_by"]), ("done", "t3"))

    def test_generic_offers_are_not_obligations(self):
        for text in ("Thank you for contacting us, please visit our website", "Let me know if you need anything", "Feel free to call"):
            self.assertFalse(self.candidate(text), text)

    def test_contextless_promise_is_not_a_concrete_task(self):
        self.assertFalse(self.candidate("I'll figure"))
        self.assertTrue(self.candidate("I'll check the revised budget tomorrow"))

    def test_plural_future_commitment_is_retrieved(self):
        self.assertTrue(self.candidate("We'll send the revised budget tomorrow"))

    def test_small_group_couple_invitation_is_retrieved(self):
        m = {**self.corpus.message["t7"], "body": "Are you both coming to dinner?"}
        self.assertTrue(_source_candidate(m, self.corpus, self.people()))
        self.corpus.chat["house"]["participants"].append("extra")
        self.assertFalse(_source_candidate(m, self.corpus, self.people()))

    def test_actual_address_fulfils_request(self):
        loop = self.source_loop("t4", "Please share your address", "24 Acorn Road, third floor")
        self.assertEqual((loop["owner"], loop["status"], loop["closed_by"]), ("v", "done", "t6"))

    def test_address_question_does_not_fulfil_request(self):
        loop = self.source_loop("t4", "Please share your address", "Is the office at 24 Acorn Road?")
        self.assertEqual(loop["status"], "open")

    def test_actual_phone_fulfils_request(self):
        loop = self.source_loop("t4", "Please share the supplier phone number", "+1 202 555 0199")
        self.assertEqual((loop["status"], loop["closed_by"]), ("done", "t6"))

    def test_model_none_sentinel_uses_no_network(self):
        env = {"XPERT_MODE": "auto", "LLM_MODEL": "none", "LLM_BASE_URL": "https://model.example/v1", "LLM_API_KEY": "synthetic-test-key"}
        with patch.dict(os.environ, env), patch.object(Client, "_request", side_effect=AssertionError("No network")):
            _, report = main(self.folder, Path(self.temp.name) / "offline.json")
        self.assertEqual(report["mode"], "offline")
        self.assertEqual(report["usage"]["api_calls"], 0)

    def test_release_entrypoint_is_offline_even_with_official_environment(self):
        output = Path(self.temp.name) / "release.json"
        env = {**os.environ, "LLM_MODEL": MODEL, "LLM_BASE_URL": "https://invalid.example/v1", "LLM_API_KEY": "synthetic-test-key"}
        env.pop("XPERT_MODE", None)
        subprocess.run([str(ROOT / "run.sh"), str(self.folder), str(output)], env=env, check=True, capture_output=True, timeout=10)
        report = json.loads(output.with_suffix(".run").joinpath("report.json").read_text())
        self.assertEqual(report["mode"], "offline")
        self.assertEqual(report["usage"]["api_calls"], 0)

    def test_free_route_cannot_silently_use_paid_or_collecting_endpoint(self):
        bodies = []
        def transport(body, timeout):
            bodies.append(body)
            return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        env = {"LLM_BASE_URL": "https://openrouter.ai/api/v1", "LLM_API_KEY": "synthetic-test-key", "LLM_MODEL": MODEL, "XPERT_MIN_REQUEST_INTERVAL": "0"}
        with patch.dict(os.environ, env):
            client = Client(Path(self.temp.name) / "run", Path(self.temp.name) / "cache", time.monotonic() + 10, transport)
            client.json("test", "Return JSON", {})
        self.assertEqual(bodies[0]["provider"], {"max_price": {"prompt": 0, "completion": 0}, "allow_fallbacks": False, "data_collection": "deny"})
        self.assertNotIn("reasoning", bodies[0])

    def test_release_entrypoint_honours_explicit_model_mode_and_official_variables(self):
        output = Path(self.temp.name) / "explicit-model.json"
        env = {**os.environ, "XPERT_MODE": "model", "XPERT_MAX_CALLS": "0", "LLM_MODEL": MODEL,
               "LLM_BASE_URL": "https://invalid.example/v1", "LLM_API_KEY": "synthetic-test-key"}
        subprocess.run([str(ROOT / "run.sh"), str(self.folder), str(output)], env=env, check=True, capture_output=True, timeout=10)
        report = json.loads(output.with_suffix(".run").joinpath("report.json").read_text())
        self.assertEqual(report["mode"], "model")
        self.assertEqual(report["model"], MODEL)
        self.assertTrue(report["budget_exhausted"])
        self.assertEqual(report["usage"]["request_attempts"], 0)

    def test_synthetic_probe_rejects_hallucinations_and_malformed_references(self):
        valid = {"open_loops": [{"source_msg": s, "status": status, "closed_by": close, "owner": "ME", "chat_id": "synthetic-chat"} for s, status, close in [("synthetic-1", "done", "synthetic-3"), ("synthetic-4", "open", None)]]}
        self.assertEqual(check_response(valid), [])
        valid["open_loops"].append({"source_msg": []})
        self.assertTrue(check_response(valid))


if __name__ == "__main__":
    unittest.main()
