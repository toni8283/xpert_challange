# Evidence-first WhatsApp Cold Start

A Python 3.9+ solution to the [Xpert Cold Start challenge](https://goals.xpert.chat/w/intern): infer people and organisations, find grounded goals, and track tasks without hiding unfinished work.

**No pip dependencies.** The required entry point is unchanged:

```bash
./run.sh <input_dir> <output.json>
```

Start with [START_HERE.md](START_HERE.md) for testing and submission. [WRITEUP.md](WRITEUP.md) explains the approach and measured failures.

Restored and revalidated after the workspace disconnect: **62 tests pass**. The release excludes all supplied datasets and answer keys.

## Measured results

On the supplied 4,502-message dev set, **offline rules score 26.01 / 56 with zero API calls**. The starter checker and schema are byte-for-byte unchanged. The challenge page reports 17.5 / 56 for its model baseline. These are dev results; hidden-set performance is unknown.

| Part | Offline points |
|---|---:|
| Circles | 8.20 / 12 |
| Organisations | 2.61 / 8 |
| Chat attachments | 6.73 / 8 |
| Loops found | 3.74 / 14 |
| Loop status | 4.73 / 14 |
| Goals / help | Unlabelled in dev |
| Total measured | **26.01 / 56** |

The **model-assisted path is implemented but not live-benchmarked**: no model API credentials were available during development. Its API protocol, caching and end-to-end assembly are tested with a local simulated server, which establishes mechanics rather than model quality. Do the live benchmark before claiming model performance. Aggregate evidence is in [reports/dev-offline.json](reports/dev-offline.json). Current verification is in [EVALUATION.md](EVALUATION.md).

## Run locally

The input folder contains `chats.jsonl`, `messages.jsonl`, and optional `seed.json`. Inference never reads an answer key. The evaluation script reads it separately.

```bash
# Generate fresh fictional input; no key required.
python3 scripts/make_example.py example
./run.sh example artifacts/example.json
python3 check.py example artifacts/example.json

# After extracting the challenge data into data/dev/:
python3 scripts/benchmark.py data/dev --mode offline

# Synthetic-only free-model check; hidden input in an interactive terminal.
python3 scripts/probe_free_model.py --ask-key
# Real-data model benchmark requires separate privacy/transmission authorisation.
# Set the official LLM_* variables, then use --mode model.

# Tests: synthetic conversations only, no paid requests.
python3 -m unittest discover -s tests -v
```

The shipped `run.sh` defaults to the measured offline path, including when the grader supplies credentials. For an explicitly authorised model run set `XPERT_MODE=model` plus `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`. Calling `solution.py` directly uses auto mode unless overridden: all three variables select the configured model; no configuration selects offline. `LLM_MODEL=none` or `offline` also selects offline in auto mode. Partial configuration produces a clear error. Provider/model failures fall back to deterministic batches with explicit degradation metrics. Local call/time-budget exhaustion retains completed model work and uses deterministic predictions for unprocessed batches, with that reduction recorded in the run report. `XPERT_MODE=model` explicitly requires a model. `XPERT_MODE=offline` explicitly disables calls.

The user-requested optional model to **test** is `baidu/ernie-5.5-flash-preview:free` through `https://openrouter.ai/api/v1`. `.env.example` documents the variables; `.env` files are not auto-loaded. Any model change needs its own benchmark.

## How it works

| Stage | Evidence and purpose | Implementation |
|---|---|---|
| Input | Sort by source time; preserve stable IDs, voice text, seeds, saved-name aliases and cross-chat membership | `coldstart/data.py` |
| Organisation graph | Sample both ends and action-bearing turns; merge project/client groups under the user's organisations | `coldstart/rules.py`, graph prompt |
| Person dossiers | Combine direct and group evidence per ID; keep supplied circles authoritative and apply user corrections | People prompt, `normalize.py` |
| Task extraction | Read chronological windows with overlapping context; batch short chats; preserve a source for each task | Loop prompt, `pipeline.py` |
| Closure review | Retrieve subsequent same-chat evidence for unresolved tasks; preserve source/owner and require a later closing message | Closure prompt, `normalize.py` |
| Goals and help | Deduplicate durable user goals with real ME evidence; choose private assistance, a reminder, or silence | Goal prompt, `policy.py` |

A message can contain several tasks; repeated paraphrases are merged conservatively. Amounts are included in deduplication, so different payments do not collapse just because both say "pay". Bare acknowledgement does not close an execution task. A genuine answer can close a decision question. No closure is inferred just because a due date passed.

Direct staff/colleague chats can attach to a relevant organisation. Recent windows run first when inference budget is scarce. The entire history is considered; earlier loops are not discarded using an estimated scoring window. The grader alone knows that window. Time calculations use the final input timestamp and IST, making reruns independent of the machine date.

The offline baseline uses the same input/policy guards, simple role language and group overlap. It deliberately emits no inferred goals. It is a measurable fallback, not a substitute for semantic evaluation.

## Cost and runtime controls

Responses are cached by endpoint, model, prompt and generation settings. Optional transport JSON mode is excluded from the cache key to survive providers that reject it; every cached value is still a complete parsed JSON object. Only cache misses call the model. Caches contain inferred private information and must not be committed or shared.

| Variable | Default | Purpose |
|---|---|---|
| `XPERT_WORKERS` | `4` | Concurrent independent batches, capped at 8 |
| `XPERT_TIME_BUDGET_SECONDS` | `1500` | Stop issuing calls before the 30-minute grading limit |
| `XPERT_MAX_CALLS` | `200` (`40` for OpenRouter `:free`) | Bound API request attempts |
| `XPERT_CHUNK_MESSAGES` | `120` | Maximum source messages per window |
| `XPERT_CHUNK_CHARS` | `18000` | Additional character limit per window |
| `LLM_MAX_OUTPUT_TOKENS` | `11000` | Extraction completion cap |
| `LLM_JSON_MODE` | `1` | Try JSON mode; retry without it if rejected |
| `XPERT_CACHE_DIR` | `.xpert-cache` beside output | Private response cache |
| `XPERT_CORRECTIONS` | unset | JSON file of explicit user corrections |

Each output has a sibling `<stem>.run/` directory with fresh `usage.jsonl` and `report.json`: actual returned token counts, cache hits, request attempts, phase totals, time and counts. No API key or raw prompt is written there. Unsuccessful HTTP attempts may have no provider token usage; cost estimates cannot recover tokens that a provider did not report. Invalid JSON gets bounded retries; rate limits/temporary provider failures use backoff; request timeouts are bounded; off-endpoint redirects are refused. A provider failure is recorded as `model_degraded` / `model_error_fallback_batches` and the affected stage uses a deterministic fallback; cached successful batches remain reusable. Local budget exhaustion is handled separately: remaining batches fall back and `budget_exhausted` is recorded instead of losing the output.

Optional model-mode cost-estimate defaults retain the older GPT-OSS assumption of $0.15/M input and $0.60/M output, observed at the [OpenRouter models API](https://openrouter.ai/api/v1/models) on 12 November 2026. Override `LLM_INPUT_PRICE_PER_MILLION` and `LLM_OUTPUT_PRICE_PER_MILLION` when appropriate. Set both prices to zero for a verified free-only test; assessment costing uses the paid equivalent. These are estimates, not a measured model bill or a guarantee about future prices. Offline cost is exactly zero.

## Apply a correction

Create a private JSON file, using IDs from your input/output:

```json
{
  "people": {"synthetic-person-a": {"circle": "client"}},
  "chats": {"synthetic-chat-a": {"person": "synthetic-person-b"}}
}
```

```bash
XPERT_CORRECTIONS=/absolute/path/corrections.json ./run.sh example artifacts/corrected.json
```

These illustrative synthetic IDs must be replaced with IDs from your own input. Explicit corrections outrank seed circles; seed circles outrank model guesses. Changed inputs/correction context change cache keys. A correction cannot introduce an unknown ID, circle or organisation. Rerun tests and compare aggregate reports after changing policy or prompts.

## Known limits

Offline matching-source precision is 16.8%, recall 64.9%; sparse contacts and everyday conversational asks remain difficult. Model-specific error rates, cost and full-size runtime have not been measured. Goal/help quality cannot be evaluated on the dev labels. Retrieval can miss a closure in another chat, a distant paraphrase or an omitted media attachment. Large forwards are trimmed; this saves cost but can lose a real task buried inside a forward. The dev key has duplicates, conflicting statuses and no closing evidence for its 49 done labels; these limitations are documented, not repaired or exploited.

## Data and AI use

Do not commit the real challenge data, output predictions, caches or credentials. The ZIP contains only code, documentation, aggregate metrics and synthetic test/generation code. All supplied datasets, including the starter example and every answer key, are excluded. All inference network traffic goes only to the configured model endpoint; there is no scraping, web search, telemetry or WhatsApp automation in the submitted code. Generated help is a recommendation, not execution of an action. Delete the challenge data and private caches after the challenge as requested by its organisers.

`ai-logs/final-work-session.md` records this final continuation. `ai-logs/session.md` is a recovered record of the earlier AI collaboration; `ai-logs/recovery-session.md` records this restoration; `ai-logs/engineering-notes.md` separately records decisions and observed checks. Raw tool payloads containing challenge chats are excluded. Add the actual exports of any later AI sessions you use.
