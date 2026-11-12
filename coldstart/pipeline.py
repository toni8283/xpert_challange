"""Graph -> person dossiers -> chronological tasks -> conservative closure review."""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from check import validate
from llm import BudgetExceeded, Client, ModelError
from . import prompts
from .data import Corpus, compact, load_corrections
from .normalize import dedup_loops, normalize_goals, normalize_graph, normalize_loop, normalize_people
from .rules import infer_graph, infer_people, offline
from .schema_guard import schema_errors


def say(message):
    print("[xpert] " + message, file=sys.stderr, flush=True)


def packs(items, char_limit=28000, count_limit=50):
    batch, size = [], 0
    for item in items:
        length = len(json.dumps(item, ensure_ascii=False))
        if batch and (size + length > char_limit or len(batch) >= count_limit):
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += length
    if batch:
        yield batch


def ask(client, stage, prompt, payload, required, max_tokens=10000):
    for attempt in range(2):
        value = client.json(stage, prompt, payload, max_tokens=max_tokens)
        if all(isinstance(value.get(key), list) for key in required):
            return value
        prompt += "\nYour JSON object must contain these ARRAY fields: " + ", ".join(required)
    raise ModelError("Model returned an invalid object shape in stage " + stage)


def parallel(work, function, workers):
    if not work:
        return []
    results = [None] * len(work)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(function, job): index for index, job in enumerate(work)}
        try:
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    return results


def apply_chat_corrections(graph, corrections):
    ids = {o["id"] for o in graph["organisations"]}
    for cid, tie in corrections.get("chats", {}).items():
        if "organisation" in tie and tie["organisation"] not in ids:
            raise ValueError("Chat correction names an organisation absent from this run: " + tie["organisation"])
    graph["chats"] = [{"chat_id": t["chat_id"], **corrections["chats"][t["chat_id"]]} if t["chat_id"] in corrections.get("chats", {}) else t for t in graph["chats"]]
    return graph


def graph_payload(corpus, draft, corrections):
    chats = []
    for c in corpus.chats:
        chats.append({"chat_id": c["chat_id"], "name": compact(c.get("name", ""), 160),
                      "is_group": bool(c.get("is_group")),
                      "participants": [{"id": p, "names": corpus.names[p][:2], "seed": corpus.seed.get("circles", {}).get(p)} for p in c.get("participants", []) if p != "ME"],
                      "message_count": len(corpus.by_chat[c["chat_id"]]),
                      "sample": corpus.sample(corpus.by_chat[c["chat_id"]], 5 if c.get("is_group") else 4, 250)})
    return {"seed": corpus.seed, "corrections": corrections, "draft": draft,
            "me_names": corpus.names.get("ME", []), "chats": chats}


def conversation_packets(corpus, people, graph):
    people_by_id = {p["id"]: p for p in people}
    ties = {t["chat_id"]: {k: v for k, v in t.items() if k != "chat_id"} for t in graph["chats"]}
    max_chars = int(os.getenv("XPERT_CHUNK_CHARS", "18000"))
    max_messages = int(os.getenv("XPERT_CHUNK_MESSAGES", "120"))
    if max_chars < 2000 or max_messages < 8:
        raise ValueError("Chunk limits are too small; use at least 2000 characters / 8 messages")
    packets = []
    for c in corpus.chats:
        rows = corpus.active_messages(c["chat_id"])
        start = 0
        while start < len(rows):
            end, chars = start, 0
            while end < len(rows) and end - start < max_messages:
                chars += len(str(corpus.record(rows[end], 700)))
                if end > start and chars > max_chars:
                    break
                end += 1
            prefix = rows[max(0, start - 10):start]
            tail = rows[end:end + 6]
            packets.append({"chat_id": c["chat_id"], "name": compact(c.get("name", ""), 120),
                            "tie": ties[c["chat_id"]],
                            "people": [{"id": p, "names": corpus.names[p][:2], "circle": people_by_id.get(p, {}).get("circle")} for p in c.get("participants", []) if p != "ME"],
                            "source_ids": [m["id"] for m in rows[start:end]],
                            "messages": [corpus.record(m, 700) for m in prefix + rows[start:end] + tail]})
            start = end
    # Preserve chronology inside each window, but spend scarce inference budget on
    # recent obligations first. Older windows still receive model or fallback coverage.
    return sorted(packets, key=lambda p: max(float(corpus.message[mid]["ts"]) for mid in p["source_ids"]), reverse=True)


def model_solution(corpus, client, workers, corrections, metrics):
    fallback_result = offline(corpus)
    def bounded_ask(stage, prompt, payload, required, max_tokens, fallback):
        try:
            return ask(client, stage, prompt, payload, required, max_tokens)
        except BudgetExceeded:
            # An exhausted time/call budget must never discard successfully
            # extracted batches. Record the degraded coverage explicitly.
            with client.lock:
                metrics["budget_exhausted"] = True
                counts = metrics.setdefault("budget_fallback_batches", {})
                counts[stage] = counts.get(stage, 0) + 1
            return fallback
        except ModelError as exc:
            # The optional provider may fail on a single malformed response,
            # rate limit, unsupported option, or authentication problem. Keep
            # an otherwise schema-valid baseline instead of aborting the whole
            # grading run. Never describe that batch as model-generated.
            with client.lock:
                counts = metrics.setdefault("model_error_fallback_batches", {})
                counts[stage] = counts.get(stage, 0) + 1
                metrics["model_degraded"] = True
            say("Model request failed in %s; using deterministic fallback (%s)" % (stage, type(exc).__name__))
            return fallback

    say("1/5 Building the organisation graph")
    draft = infer_graph(corpus)
    raw = bounded_ask("graph", prompts.GRAPH, graph_payload(corpus, draft, corrections), ["organisations", "chats"], 14000, draft)
    graph = apply_chat_corrections(normalize_graph(raw, draft, corpus), corrections)
    notes_raw = raw.get("relationship_notes")
    notes = [compact(s, 250) for s in notes_raw if isinstance(s, str)][:15] if isinstance(notes_raw, list) else []
    say("2/5 Classifying people from their cross-chat dossiers")
    fallback = infer_people(corpus, graph)
    ties = {t["chat_id"]: t.get("organisation") for t in graph["chats"]}
    dossiers = [corpus.dossier(pid, ties) for pid in sorted(corpus.ids)]
    jobs = list(packs(dossiers, 36000, 40))
    def classify(batch):
        return bounded_ask("people", prompts.PEOPLE, {"organisations": graph["organisations"], "relationship_notes": notes,
                    "corrections": corrections.get("people", {}), "people": batch}, ["people"], 10000, {"people": []})
    classified = parallel(jobs, classify, workers)
    people = normalize_people([p for response in classified for p in response["people"]], fallback, corpus, graph, corrections)
    people_by_id = {p["id"]: p for p in people}
    say("3/5 Extracting tasks in chronological conversation windows")
    packets = conversation_packets(corpus, people, graph)
    jobs = list(packs(packets, 26000, 10))
    metrics["conversation_windows"] = len(packets)
    metrics["extraction_batches"] = len(jobs)
    def extract(batch):
        allowed = {mid for packet in batch for mid in packet["source_ids"]}
        fallback = {"open_loops": [v for v in fallback_result["open_loops"] if v["source_msg"] in allowed], "goals": []}
        raw = bounded_ask("loops", prompts.LOOPS, {"snapshot_ist": corpus.local_time().isoformat(), "conversations": batch}, ["open_loops", "goals"],
                  int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "11000")), fallback)
        # A response cannot invent a source in another batch or an unrelated chat.
        loops = [normalize_loop(value, corpus, people_by_id, allowed) for value in raw["open_loops"]]
        return [loop for loop in loops if loop is not None], raw["goals"], len(loops) - sum(loop is not None for loop in loops)
    extracted = parallel(jobs, extract, workers)
    loops = dedup_loops([loop for found, _, _ in extracted for loop in found], corpus)
    metrics["invalid_loop_candidates_dropped"] = sum(n for _, _, n in extracted)
    goals = [g for _, proposed, _ in extracted for g in proposed]
    say("4/5 Reviewing unresolved tasks against later evidence")
    reviews = []
    for index, loop in enumerate(loops):
        if loop["status"] != "open":
            continue
        later = corpus.future_evidence(loop)
        if later:
            reviews.append({"index": index, "loop": loop, "source": corpus.record(corpus.message[loop["source_msg"]], 850),
                            "owner_circle": people_by_id.get(loop["owner"], {}).get("circle", "self"), "later": later})
    review_jobs = list(packs(reviews, 26000, 12))
    def review(batch):
        value = bounded_ask("closure", prompts.CLOSURE, {"snapshot_ist": corpus.local_time().isoformat(), "candidates": batch}, ["updates"], 6500, {"updates": []})
        allowed = {item["index"]: {r[0] for r in item["later"]} for item in batch}
        return value["updates"], allowed
    reviewed = parallel(review_jobs, review, workers)
    for updates, allowed in reviewed:
        for update in updates:
            if not isinstance(update, dict):
                continue
            index = update.get("index")
            if not isinstance(index, int) or isinstance(index, bool) or index not in allowed:
                continue
            original = loops[index]
            if update.get("source_msg") != original["source_msg"]:
                continue
            if update.get("closed_by") is not None and (not isinstance(update["closed_by"], str) or update["closed_by"] not in allowed[index]):
                continue
            combined = {**original, **{k: update[k] for k in ("status", "closed_by", "help") if k in update}}
            normalized = normalize_loop(combined, corpus, people_by_id)
            if normalized:
                loops[index] = normalized
    say("5/5 Selecting grounded goals and validating output")
    candidates = normalize_goals(goals, corpus, limit=40)
    # Keep candidate selection small; final selection still uses the cited message text.
    if candidates:
        evidence_ids = {mid for g in candidates for mid in g["evidence"]}
        selected = bounded_ask("goals", prompts.GOALS,
                       {"seed_goals": corpus.seed.get("goals", []), "candidates": candidates,
                        "evidence": [corpus.record(corpus.message[mid], 1000) for mid in sorted(evidence_ids)]}, ["goals"], 4500, {"goals": candidates})
        candidates = normalize_goals(selected["goals"], corpus)
    return {**graph, "people": people, "goals": candidates, "open_loops": dedup_loops(loops, corpus)}


def main(input_dir, output_path):
    started = time.monotonic()
    corpus = Corpus(input_dir)
    corrections = load_corrections(os.getenv("XPERT_CORRECTIONS"), corpus)
    output = Path(output_path).resolve()
    if output in {Path(input_dir).resolve() / name for name in ("chats.jsonl", "messages.jsonl", "seed.json")}:
        raise ValueError("The output must not overwrite an input file")
    output.parent.mkdir(parents=True, exist_ok=True)
    run_dir = output.parent / (output.stem + ".run")
    run_dir.mkdir(parents=True, exist_ok=True)
    usage = run_dir / "usage.jsonl"
    if usage.exists():
        usage.unlink()
    mode = os.getenv("XPERT_MODE", "auto").lower()
    if mode not in {"auto", "offline", "model"}:
        raise ValueError("XPERT_MODE must be auto, offline or model")
    configured = [bool(os.getenv(k)) for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")]
    task_review = os.getenv("XPERT_TASK_REVIEW", "0") == "1"
    no_model = os.getenv("LLM_MODEL", "").strip().lower() in {"none", "offline"}
    if task_review and (mode == "model" or not all(configured) or no_model):
        raise ValueError("Task-only review needs all LLM_* variables and XPERT_MODE=offline (or auto), not full model mode")
    if mode == "model" and no_model:
        raise ValueError("Model mode needs an actual model ID, not none/offline")
    wants_model = mode != "offline" and not task_review and not (mode == "auto" and no_model)
    if wants_model and any(configured) and not all(configured):
        raise ValueError("Set all three of LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, or use XPERT_MODE=offline")
    if mode == "model" and not all(configured):
        raise ValueError("Model mode needs LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
    enabled = wants_model and all(configured)
    metrics = {"mode": "model" if enabled else "offline", "input_messages": len(corpus.messages),
               "input_chats": len(corpus.chats), "input_people": len(corpus.ids),
               "model": os.getenv("LLM_MODEL") if enabled else None, "snapshot_ist": corpus.local_time().isoformat()}
    if enabled:
        budget = min(1620, max(30, int(os.getenv("XPERT_TIME_BUDGET_SECONDS", "1500"))))
        workers = min(8, max(1, int(os.getenv("XPERT_WORKERS", "4"))))
        cache_dir = Path(os.getenv("XPERT_CACHE_DIR", str(output.parent / ".xpert-cache")))
        client = Client(run_dir, cache_dir, started + budget)
        result = model_solution(corpus, client, workers, corrections, metrics)
        client.stats["request_attempts"] = client.calls
        metrics["usage"] = client.stats
        in_price = float(os.getenv("LLM_INPUT_PRICE_PER_MILLION", ".15"))
        out_price = float(os.getenv("LLM_OUTPUT_PRICE_PER_MILLION", ".60"))
        cost = (client.stats["prompt_tokens"] * in_price + client.stats["completion_tokens"] * out_price) / 1e6
        metrics["cost_estimate"] = {"usd": round(cost, 6), "usd_per_1000_messages": round(cost * 1000 / max(1, len(corpus.messages)), 6),
                                    "input_usd_per_million": in_price, "output_usd_per_million": out_price,
                                    "note": "Assumed prices, not billing. Set price environment variables for a different model/provider. Cached calls cost zero on this run."}
    else:
        say("Running deterministic extraction; task-only model review enabled" if task_review else "No configured model: running the deterministic zero-cost baseline (goals omitted)")
        result = offline(corpus)
        result["people"] = normalize_people([], result["people"], corpus, result, corrections)
        apply_chat_corrections(result, corrections)
        # Recompute intervention policy after a user correction.
        people = {p["id"]: p for p in result["people"]}
        result["open_loops"] = [normalize_loop(loop, corpus, people) for loop in result["open_loops"]]
        result["open_loops"] = [loop for loop in result["open_loops"] if loop is not None]
        metrics["usage"] = {"api_calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0}
        metrics["cost_estimate"] = {"usd": 0, "usd_per_1000_messages": 0}
        if task_review:
            from .task_review import review_completions
            budget = min(1500, max(10, int(os.getenv("XPERT_TASK_REVIEW_SECONDS", "300"))))
            cache = Path(os.getenv("XPERT_CACHE_DIR", str(output.parent / ".xpert-cache")))
            client = Client(run_dir, cache, started + budget)
            output_tokens = min(16000, max(64, int(os.getenv("XPERT_TASK_REVIEW_OUTPUT_TOKENS", "256"))))
            metrics["task_review"] = review_completions(corpus, result["open_loops"], client, output_tokens)
            metrics["mode"] = "offline+task_review"
            metrics["model"] = client.model
            client.stats["request_attempts"] = client.calls
            metrics["usage"] = client.stats
            in_price = float(os.getenv("LLM_INPUT_PRICE_PER_MILLION", ".15"))
            out_price = float(os.getenv("LLM_OUTPUT_PRICE_PER_MILLION", ".60"))
            cost = (client.stats["prompt_tokens"] * in_price + client.stats["completion_tokens"] * out_price) / 1e6
            metrics["cost_estimate"] = {"usd": round(cost, 6), "usd_per_1000_messages": round(cost * 1000 / max(1, len(corpus.messages)), 6),
                                        "note": "Assumed token prices, not billing; set prices for the actual provider/model. Failed requests may have unreported usage."}
    schema = json.loads((Path(__file__).resolve().parents[1] / "schema.json").read_text(encoding="utf-8"))
    errors = validate(result, corpus.chats, corpus.messages) + schema_errors(result, schema)
    if errors:
        raise ValueError("Output validation failed: " + "; ".join(errors[:5]))
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    metrics["seconds"] = round(time.monotonic() - started, 3)
    metrics["output_counts"] = {k: len(v) for k, v in result.items()}
    (run_dir / "report.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    say("Wrote %s: %d people, %d organisations, %d loops in %.2fs" % (output.name, len(result["people"]), len(result["organisations"]), len(result["open_loops"]), metrics["seconds"]))
    return result, metrics
