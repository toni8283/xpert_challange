#!/usr/bin/env python3
"""Synthetic-only OpenRouter compatibility probe. Never reads a dataset directory."""
import argparse
import getpass
import json
import os
import sys
import tempfile
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from llm import Client, ModelError

MODEL = "baidu/ernie-5.5-flash-preview:free"


def check_response(value):
    problems = []
    loops = value.get("open_loops")
    if not isinstance(loops, list):
        return ["Missing open_loops array"]
    expected = {"synthetic-1": ("done", "synthetic-3"), "synthetic-4": ("open", None)}
    found = set()
    for loop in loops:
        if not isinstance(loop, dict) or not isinstance(loop.get("source_msg"), str) or loop["source_msg"] not in expected:
            problems.append("Unknown or malformed source")
            continue
        source = loop["source_msg"]
        if source in found:
            problems.append("Duplicate task")
        found.add(source)
        status, close = expected[source]
        if loop.get("owner") != "ME" or loop.get("chat_id") != "synthetic-chat":
            problems.append("Incorrect entity reference")
        if loop.get("status") != status or loop.get("closed_by") != close:
            problems.append("Incorrect temporal status or closing evidence")
    if found != set(expected):
        problems.append("Missed synthetic task")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ask-key", action="store_true", help="Hidden input in an interactive terminal only")
    parser.add_argument("--output", default="reports/free-model-probe.json")
    args = parser.parse_args()
    report = {"model": MODEL, "input": "Built-in invented messages only", "private_dataset_sent": False,
              "paid_fallback_allowed": False, "real_model_called": False}
    client = None
    try:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=20) as response:
            catalog = json.load(response).get("data", [])
        item = next((m for m in catalog if m.get("id") == MODEL), None)
        if not item:
            raise ValueError("Requested free model is not currently listed")
        pricing = item.get("pricing", {})
        if any(Decimal(pricing.get(k, "Infinity")) != 0 for k in ("prompt", "completion")):
            raise ValueError("Model prices are not zero; no request made")
        report["catalog_verified_free"] = True
        report["context_length"] = item.get("context_length")
        key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        if not key and args.ask_key:
            if not sys.stdin.isatty() or not sys.stderr.isatty():
                raise ValueError("Secure hidden key entry requires an interactive terminal")
            key = getpass.getpass("OpenRouter API key (hidden; never saved): ")
        if not key:
            report["status"] = "blocked_missing_credentials"
            return save_report(args.output, report, 2)
        os.environ.update(LLM_BASE_URL="https://openrouter.ai/api/v1", LLM_MODEL=MODEL, LLM_API_KEY=key,
                          XPERT_MAX_CALLS="2", XPERT_MIN_REQUEST_INTERVAL="3.2")
        payload = {"chat_id": "synthetic-chat", "messages": [
            ["synthetic-1", "ME", "I'll email the training plan tomorrow"],
            ["synthetic-2", "contact-a", "Okay, thanks"],
            ["synthetic-3", "ME", "I emailed the training plan"],
            ["synthetic-4", "ME", "I'll book the train tickets tomorrow"],
            ["synthetic-5", "contact-a", "Sure, working on it"]]}
        prompt = ("Return one JSON object with open_loops. Extract the user's two commitments from these invented messages. "
                  "Use title,type,owner,chat_id,source_msg,status,closed_by. ME is the user. "
                  "Do not use acknowledgements or future plans as completion evidence. "
                  "Use exactly the original task source ID and actual completion ID, or null if open.")
        with tempfile.TemporaryDirectory(prefix="xpert-synthetic-probe-") as temp:
            client = Client(Path(temp) / "run", Path(temp) / "cache", time.monotonic() + 180)
            started = time.monotonic()
            value = client.json("synthetic_probe", prompt, payload, max_tokens=9000)
            report.update(real_model_called=client.calls > 0, seconds=round(time.monotonic() - started, 3), usage=client.stats)
            problems = check_response(value)
            report.update(status="passed" if not problems else "failed_semantic_validation", problems=problems)
            return save_report(args.output, report, 0 if not problems else 1)
    except (OSError, ValueError, ModelError) as exc:
        if client is not None:
            report.update(real_model_called=client.calls > 0, request_attempts=client.calls, usage=client.stats)
        report.update(status="blocked_or_failed", error_type=type(exc).__name__)
        # Provider text may echo data or secrets. Keep only a generic type.
        return save_report(args.output, report, 1)


def save_report(path, report, status):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return status


if __name__ == "__main__":
    sys.exit(main())
