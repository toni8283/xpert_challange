"""Contract and failure tests using invented conversations, never the dev answer key."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check import validate
from coldstart.data import Corpus, IST, tokens
from coldstart.normalize import dedup_loops, normalize_goals, normalize_graph, normalize_loop, normalize_people
from coldstart.pipeline import conversation_packets, main
from coldstart.policy import normalize_help, parse_due, reminder_time
from coldstart.rules import infer_graph, infer_people
from llm import Client, ModelError, parse_object


def make_input(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    chats = [
        {"chat_id": "direct_a", "name": "Robin", "is_group": False, "participants": ["ME", "a"]},
        {"chat_id": "direct_v", "name": "Lane Printers", "is_group": False, "participants": ["ME", "v"]},
        {"chat_id": "team", "name": "Cedar team", "is_group": True, "participants": ["ME", "c"]},
        {"chat_id": "house", "name": "Household", "is_group": True, "participants": ["ME", "a", "s", "k"]},
    ]
    start = int(datetime(2026, 10, 20, 10, tzinfo=IST).timestamp())
    items = [
        ("t1", "direct_a", "ME", "User", "I'll send the report tomorrow"),
        ("t2", "direct_a", "a", "Robin", "OK"),
        ("t3", "direct_a", "ME", "User", "Report sent"),
        ("t4", "direct_v", "ME", "User", "Please send the invoice tomorrow"),
        ("t5", "direct_v", "v", "Lane Printers", "I'll send it"),
        ("t6", "direct_v", "v", "Lane Printers", "Still preparing the invoice"),
        ("t7", "house", "s", "Sam driver", "I'll pick the child up at 6"),
        ("t8", "direct_a", "ME", "User", "My goal is to run three times a week this year"),
    ]
    messages = [{"id": mid, "chat_id": cid, "sender_id": pid, "sender_name": name,
                 "ts": start + i * 60, "kind": "voice_transcript" if mid == "t8" else "text",
                 "body": body, "quoted_id": None} for i, (mid, cid, pid, name, body) in enumerate(items)]
    for name, rows in [("chats.jsonl", chats), ("messages.jsonl", messages)]:
        (folder / name).write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    (folder / "seed.json").write_text(json.dumps({"circles": {"a": "spouse"}, "organisations": ["Cedar Studio"], "goals": []}))
    return folder


def task(source="t1", **changes):
    value = {"title": "Send the report", "type": "commitment", "owner": "ME", "chat_id": "direct_a",
             "source_msg": source, "due": None, "status": "open", "closed_by": None}
    value.update(changes)
    return value


def assert_schema(case, value, schema, path="$"):
    """Enforce the exact subset of JSON Schema used by the official contract."""
    if "enum" in schema:
        case.assertIn(value, schema["enum"], path)
    if "oneOf" in schema:
        case.assertEqual(sum(all(k in value for k in option.get("required", [])) for option in schema["oneOf"]), 1, path)
    kind = schema.get("type")
    if isinstance(kind, list):
        if value is None and "null" in kind:
            return
        kind = next(k for k in kind if k != "null")
    if kind == "object":
        case.assertIsInstance(value, dict, path)
        case.assertTrue(set(schema.get("required", [])) <= set(value), path)
        if schema.get("additionalProperties") is False:
            case.assertTrue(set(value) <= set(schema.get("properties", {})), path)
        for key, child in schema.get("properties", {}).items():
            if key in value:
                assert_schema(case, value[key], child, path + "." + key)
    elif kind == "array":
        case.assertIsInstance(value, list, path)
        case.assertGreaterEqual(len(value), schema.get("minItems", 0), path)
        case.assertLessEqual(len(value), schema.get("maxItems", 10 ** 9), path)
        for i, child in enumerate(value):
            assert_schema(case, child, schema["items"], path + "[%d]" % i)
    elif kind == "string":
        case.assertIsInstance(value, str, path)
    elif kind == "boolean":
        case.assertIsInstance(value, bool, path)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = make_input(Path(self.tmp.name) / "input")
        self.corpus = Corpus(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def normalize(self, value):
        return normalize_loop(value, self.corpus, {})

    def test_acknowledgement_is_not_execution(self):
        loop = self.normalize(task(status="done", closed_by="t2"))
        self.assertEqual(loop["status"], "open")
        self.assertIsNone(loop["closed_by"])

    def test_explicit_later_completion(self):
        loop = self.normalize(task(status="done", closed_by="t3"))
        self.assertEqual(loop["status"], "done")
        self.assertIsNone(loop["help"])

    def test_cross_chat_or_earlier_closure_rejected(self):
        self.assertEqual(self.normalize(task(status="done", closed_by="t6"))["status"], "open")
        self.assertEqual(self.normalize(task(source="t3", status="done", closed_by="t1"))["status"], "open")

    def test_hallucinated_source_or_owner_rejected(self):
        self.assertIsNone(self.normalize(task(source="unknown")))
        self.assertIsNone(self.normalize(task(owner="not-a-person")))
        self.assertIsNone(self.normalize(task(chat_id="team")))

    def test_batch_source_boundary(self):
        self.assertIsNone(normalize_loop(task(), self.corpus, {}, {"t4"}))

    def test_other_persons_work_stays_quiet(self):
        loop = task(source="t4", chat_id="direct_v", owner="v", type="followup")
        help_ = normalize_help({"action": "assist", "next_step": "Send a message", "needs_yes": False}, loop, self.corpus, {})
        self.assertEqual(help_["action"], "leave")

    def test_external_action_needs_yes(self):
        help_ = normalize_help({"action": "assist", "next_step": "Book the appointment", "needs_yes": False}, task(), self.corpus, {})
        self.assertTrue(help_["needs_yes"])

    def test_private_draft_can_proceed(self):
        help_ = normalize_help({"action": "assist", "next_step": "Draft a reply for review", "needs_yes": False}, task(), self.corpus, {})
        self.assertFalse(help_["needs_yes"])

    def test_relative_due_uses_message_ist(self):
        ts = datetime(2026, 10, 20, 23, 50, tzinfo=IST).timestamp()
        self.assertEqual(parse_due("kal bhej dunga", ts), "2026-10-21")
        self.assertEqual(parse_due("send by Friday", ts), "2026-10-23")
        self.assertIsNone(parse_due("kal kiya tha", ts))
        self.assertIsNone(parse_due("no date given", ts))

    def test_reminder_is_after_snapshot(self):
        when = datetime.fromisoformat(reminder_time("2020-01-01", self.corpus))
        self.assertGreater(when.timestamp(), self.corpus.now)
        self.assertIsNotNone(when.utcoffset())

    def test_reasonable_model_reminder_time_is_preserved(self):
        value = {"action": "remind", "remind_at": "2026-10-20T17:30:00+05:30"}
        self.assertEqual(normalize_help(value, task(), self.corpus, {})["remind_at"], value["remind_at"])

    def test_wrong_types_from_model_do_not_crash_normalization(self):
        draft = infer_graph(self.corpus)
        graph = normalize_graph({"organisations": [{"id": "bad", "name": "Bad", "type": [], "side": "home", "role": "owner"}],
                                 "chats": [{"chat_id": []}, {"chat_id": "team", "organisation": {}}]}, draft, self.corpus)
        fallback = infer_people(self.corpus, graph)
        people = normalize_people([{"id": [], "circle": "staff"}, {"id": "a", "circle": "spouse", "links": 42, "looks_after": 42}], fallback, self.corpus, graph, {})
        self.assertEqual(len(people), len(self.corpus.ids))
        self.assertIsNone(self.normalize(task(owner=[])))
        self.assertEqual(normalize_goals([{"title": "Goal", "area": [], "type": "habit", "horizon": "1yr", "evidence": 42}], self.corpus), [])

    def test_seed_then_user_correction(self):
        graph = infer_graph(self.corpus)
        fallback = infer_people(self.corpus, graph)
        proposed = [{"id": "a", "circle": "client", "links": [{"organisation": graph["organisations"][0]["id"], "link": "runs"}]}]
        normal = normalize_people(proposed, fallback, self.corpus, graph, {})
        self.assertEqual(next(p for p in normal if p["id"] == "a")["circle"], "spouse")
        corrected = normalize_people(proposed, fallback, self.corpus, graph, {"people": {"a": {"circle": "relative"}}})
        person = next(p for p in corrected if p["id"] == "a")
        self.assertEqual(person["circle"], "relative")
        self.assertNotIn("links", person)

    def test_different_payment_amounts_not_merged(self):
        loops = [task(title="Pay 3500 for supplies"), task(title="Pay 4500 for supplies")]
        self.assertEqual(len(dedup_loops(loops, self.corpus)), 2)
        self.assertIn("3500", tokens("Pay 3500"))

    def test_goals_need_real_user_evidence(self):
        base = {"title": "Run regularly", "area": "health", "type": "habit", "horizon": "1yr"}
        self.assertEqual(normalize_goals([{**base, "evidence": ["t2"]}], self.corpus), [])
        self.assertEqual(normalize_goals([{**base, "evidence": ["invented"]}], self.corpus), [])
        self.assertEqual(len(normalize_goals([{**base, "evidence": ["t8"]}], self.corpus)), 1)

    def test_voice_text_and_all_chunk_sources_preserved(self):
        graph = infer_graph(self.corpus)
        people = infer_people(self.corpus, graph)
        with patch.dict(os.environ, {"XPERT_CHUNK_MESSAGES": "8", "XPERT_CHUNK_CHARS": "2000"}):
            packets = conversation_packets(self.corpus, people, graph)
        mids = [mid for p in packets for mid in p["source_ids"]]
        self.assertIn("t8", mids)
        self.assertEqual(len(mids), len(set(mids)))

    def test_offline_never_reads_answers_and_meets_schema(self):
        answers = self.folder / "answers"
        answers.mkdir()
        (answers / "answers.json").write_text("This is deliberately invalid and must not be opened")
        output = Path(self.tmp.name) / "result.json"
        with patch.dict(os.environ, {"XPERT_MODE": "offline"}):
            result, metrics = main(self.folder, output)
        self.assertEqual(metrics["usage"]["api_calls"], 0)
        self.assertEqual(validate(result, self.corpus.chats, self.corpus.messages), [])
        assert_schema(self, result, json.loads((ROOT / "schema.json").read_text()))

    def test_input_line_order_does_not_change_output(self):
        with patch.dict(os.environ, {"XPERT_MODE": "offline"}):
            first, _ = main(self.folder, Path(self.tmp.name) / "first.json")
            messages = self.folder / "messages.jsonl"
            messages.write_text("\n".join(reversed(messages.read_text().splitlines())) + "\n")
            second, _ = main(self.folder, Path(self.tmp.name) / "second.json")
        self.assertEqual(first, second)

    def test_arbitrary_ids_and_names_supported(self):
        for filename in ("chats.jsonl", "messages.jsonl", "seed.json"):
            path = self.folder / filename
            content = path.read_text().replace('"a"', '"new-person-91"').replace("Robin", "New Contact").replace("Cedar", "Maple")
            path.write_text(content)
        with patch.dict(os.environ, {"XPERT_MODE": "offline"}):
            result, _ = main(self.folder, Path(self.tmp.name) / "renamed.json")
        self.assertEqual(next(p for p in result["people"] if p["id"] == "new-person-91")["circle"], "spouse")
        self.assertNotIn('"a"', json.dumps(result))


class ClientTests(unittest.TestCase):
    def test_json_fences_and_no_partial_object_recovery(self):
        self.assertEqual(parse_object('```json\n{"ok": true}\n```'), {"ok": True})
        with self.assertRaises(ValueError):
            parse_object('{"outer": {"inner": 1}, "unfinished":')

    def test_usage_cache_and_retry_json_mode_compatibility(self):
        seen = []
        def transport(body, timeout):
            seen.append(copy.deepcopy(body))
            if len(seen) == 1:
                raise urllib.error.HTTPError("https://model.example", 400, "format unsupported", {}, None)
            return {"choices": [{"finish_reason": "stop", "message": {"content": '{"people": []}'}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LLM_BASE_URL": "https://model.example/v1", "LLM_API_KEY": "synthetic-test-key", "LLM_MODEL": "test-model"}), patch("llm.time.sleep"):
            client = Client(Path(tmp) / "run", Path(tmp) / "cache", time.monotonic() + 30, transport=transport)
            self.assertEqual(client.json("test", "Return JSON", {}), {"people": []})
            # The successful request's cache is keyed by the ORIGINAL request contract.
            client.json_format = True
            self.assertEqual(client.json("test", "Return JSON", {}), {"people": []})
            self.assertEqual(len(seen), 2)
            self.assertNotIn("response_format", seen[1])
            self.assertEqual(client.stats["cache_hits"], 1)
            self.assertEqual(client.stats["prompt_tokens"], 12)

    def test_auth_failure_is_not_silently_offline(self):
        def transport(body, timeout):
            raise urllib.error.HTTPError("https://model.example", 401, "unauthorized", {}, None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LLM_BASE_URL": "https://model.example/v1", "LLM_API_KEY": "synthetic-test-key", "LLM_MODEL": "test-model"}):
            client = Client(Path(tmp) / "run", Path(tmp) / "cache", time.monotonic() + 30, transport=transport)
            with self.assertRaisesRegex(ModelError, "401"):
                client.json("test", "Return JSON", {})


class PipelineTests(unittest.TestCase):
    def test_twenty_thousand_messages_in_clean_offline_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "large"
            folder.mkdir()
            chats = [{"chat_id": "chat-%d" % i, "name": "Maple team %d" % i if i % 2 else "Contact %d" % i,
                      "is_group": bool(i % 2), "participants": ["ME", "person-%d" % i]} for i in range(320)]
            rows = []
            for i in range(20000):
                cid = i % 320
                sender = "ME" if i // 320 % 8 == 0 else "person-%d" % cid
                body = "Please send the draft tomorrow" if sender == "ME" else "Thanks"
                rows.append({"id": "large-%d" % i, "chat_id": "chat-%d" % cid, "sender_id": sender,
                             "sender_name": "User" if sender == "ME" else "Contact %d" % cid,
                             "ts": 1792459800 + i * 30, "kind": "voice_transcript" if i % 997 == 0 else "text",
                             "body": body, "quoted_id": None})
            (folder / "chats.jsonl").write_text("\n".join(json.dumps(c) for c in chats))
            (folder / "messages.jsonl").write_text("\n".join(json.dumps(m) for m in rows))
            (folder / "seed.json").write_text(json.dumps({"circles": {}, "organisations": ["Maple Analytics"], "goals": []}))
            with patch.dict(os.environ, {"XPERT_MODE": "offline"}):
                result, metrics = main(folder, Path(tmp) / "large-output.json")
            self.assertEqual(metrics["input_messages"], 20000)
            self.assertEqual(len(result["chats"]), 320)
            self.assertEqual(metrics["usage"]["api_calls"], 0)
            self.assertLess(metrics["seconds"], 60)

    def test_complete_model_protocol_and_cold_cache_replay(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, payload))
                prompt = payload["messages"][0]["content"]
                if "Discover organisations" in prompt:
                    result = {"organisations": [{"id": "cedar", "name": "Cedar Studio", "type": "company", "side": "work", "role": "owner"},
                                                  {"id": "home", "name": "Home", "type": "residence", "side": "home", "role": "owner"}],
                              "chats": [{"chat_id": "team", "organisation": "cedar"}, {"chat_id": "house", "organisation": "home"}], "relationship_notes": []}
                elif "Classify EVERY" in prompt:
                    result = {"people": [{"id": "a", "circle": "spouse"}, {"id": "v", "circle": "vendor"},
                                          {"id": "c", "circle": "colleague", "links": [{"organisation": "cedar", "link": "runs"}]},
                                          {"id": "s", "circle": "staff", "links": [{"organisation": "home", "link": "supports"}], "looks_after": ["k"]}, {"id": "k", "circle": "child"}]}
                elif "Find concrete tasks" in prompt:
                    result = {"open_loops": [task(), task(source="t4", title="Wait for the invoice", owner="v", type="followup", chat_id="direct_v")],
                              "goals": [{"title": "Run three times a week", "area": "health", "type": "habit", "horizon": "1yr", "evidence": ["t8"]}]}
                elif "Review candidate loops" in prompt:
                    result = {"updates": [{"index": 0, "source_msg": "t1", "status": "done", "closed_by": "t3", "help": None},
                                          {"index": 1, "source_msg": "t4", "status": "open", "closed_by": None, "help": {"action": "leave", "reason": "Vendor is preparing it"}}]}
                else:
                    result = {"goals": [{"title": "Run three times a week", "area": "health", "type": "habit", "horizon": "1yr", "evidence": ["t8"]}]}
                body = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                                   "usage": {"prompt_tokens": 100, "completion_tokens": 30}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                folder = make_input(Path(tmp) / "input")
                output = Path(tmp) / "output.json"
                env = {**os.environ, "XPERT_MODE": "model", "LLM_BASE_URL": "http://127.0.0.1:%d/v1" % server.server_port,
                       "LLM_API_KEY": "synthetic-local-key", "LLM_MODEL": "local-fixture", "XPERT_WORKERS": "2"}
                subprocess.run([str(ROOT / "run.sh"), str(folder), str(output)], check=True, env=env, capture_output=True)
                result = json.loads(output.read_text())
                self.assertEqual(result["open_loops"][0]["status"], "done")
                self.assertEqual(result["open_loops"][1]["help"]["action"], "leave")
                self.assertEqual(len(result["goals"]), 1)
                assert_schema(self, result, json.loads((ROOT / "schema.json").read_text()))
                self.assertEqual(len(requests), 5)
                self.assertTrue(all(path == "/v1/chat/completions" for path, _ in requests))
                first_usage = json.loads((output.parent / "output.run" / "report.json").read_text())["usage"]
                self.assertEqual(first_usage["prompt_tokens"], 500)
                subprocess.run([str(ROOT / "run.sh"), str(folder), str(output)], check=True, env=env, capture_output=True)
                second_usage = json.loads((output.parent / "output.run" / "report.json").read_text())["usage"]
                self.assertEqual(second_usage["api_calls"], 0)
                self.assertEqual(second_usage["cache_hits"], 5)
                self.assertEqual(len(requests), 5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
