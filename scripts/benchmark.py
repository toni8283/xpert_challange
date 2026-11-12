#!/usr/bin/env python3
"""Run the solution and the UNMODIFIED checker; save aggregate metrics only.

python3 scripts/benchmark.py data/dev --mode offline
python3 scripts/benchmark.py data/dev --mode model --ask-key
"""
import argparse
import getpass
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import check
from coldstart.pipeline import main


def benchmark(folder, output, report):
    result, run = main(folder, output)
    chats, messages, seed, answers = check.load_input(folder)
    if answers is None:
        raise ValueError("This folder has no answer key; use run.sh for inference-only runs")
    fractions = check.score(result, answers, seed, messages)
    points = {key: None if value is None else value * check.POINTS[key] for key, value in fractions.items()}
    total = sum(value for value in points.values() if value is not None)
    possible = sum(check.POINTS[key] for key, value in fractions.items() if value is not None)
    # Same greedy one-to-one loop matching as the supplied checker, without exporting IDs/text.
    pairs, used = [], set()
    for loop in result["open_loops"]:
        for index, truth in enumerate(answers["open_loops"]):
            if index not in used and loop["source_msg"] in truth["source_msgs"]:
                used.add(index)
                pairs.append((loop, truth))
                break
    seeded = set(seed.get("circles", {}))
    circle_map = {p["id"]: p["circle"] for p in result["people"]}
    confusion = Counter((p["circle"], circle_map.get(p["id"], "missing")) for p in answers["people"] if p["id"] not in seeded)
    summary = {
        "mode": run["mode"], "model": run["model"], "messages": len(messages), "chats": len(chats),
        "score_fractions": fractions, "score_points": points, "total": total, "possible": possible,
        "seconds": run["seconds"], "usage": run["usage"], "cost_estimate": run["cost_estimate"],
        "loop_diagnostics": {"predicted": len(result["open_loops"]), "labelled": len(answers["open_loops"]),
            "matched": len(pairs), "matching_source_precision": len(pairs) / max(1, len(result["open_loops"])),
            "matching_source_recall": len(pairs) / max(1, len(answers["open_loops"])),
            "matched_status_correct": sum(p["status"] == a["status"] for p, a in pairs),
            "false_closures_of_labelled_open": sum(a["status"] == "open" and p["status"] != "open" for p, a in pairs),
            "unique_label_source_sets": len({tuple(a["source_msgs"]) for a in answers["open_loops"]}),
            "labels_without_closing_evidence": sum(a["status"] != "open" and not a.get("closing_msgs") for a in answers["open_loops"])},
        "circle_confusion": [{"actual": actual, "predicted": predicted, "count": n} for (actual, predicted), n in sorted(confusion.items())],
        "notes": ["Official checker and answer key are unchanged.",
                  "Goals/help absent from dev labels are unmeasured, not zero.",
                  "A local fixture test verifies API mechanics, not model quality.",
                  "Only aggregate counts are exported; never commit output JSON, caches, or challenge chats."]}
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    check.main(["check.py", str(folder), str(output)])
    print("Aggregate benchmark: " + str(report))
    print("Mode: %s; model: %s; API calls: %d" % (run["mode"], run["model"] or "none", run["usage"]["api_calls"]))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir")
    parser.add_argument("--mode", choices=["offline", "model"], default="offline")
    parser.add_argument("--ask-key", action="store_true", help="Read a model key privately; never save it")
    parser.add_argument("--output")
    parser.add_argument("--report")
    args = parser.parse_args()
    os.environ["XPERT_MODE"] = args.mode
    if args.mode == "model":
        os.environ.setdefault("LLM_BASE_URL", "https://openrouter.ai/api/v1")
        os.environ.setdefault("LLM_MODEL", "openai/gpt-oss-120b")
        if args.ask_key and not os.getenv("LLM_API_KEY"):
            if not sys.stdin.isatty() or not sys.stderr.isatty():
                parser.error("Secure hidden key entry requires an interactive terminal")
            os.environ["LLM_API_KEY"] = getpass.getpass("OpenRouter API key (hidden, not saved): ")
    elif args.ask_key:
        parser.error("--ask-key is only for --mode model")
    try:
        benchmark(args.input_dir, args.output or "artifacts/dev-%s.json" % args.mode,
                  args.report or "reports/dev-%s.json" % args.mode)
    except (ValueError, RuntimeError, OSError) as exc:
        print("Benchmark failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
