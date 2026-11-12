# Xpert Cold Start — Evidence-First WhatsApp Understanding

A Python 3.9+ solution for the [Xpert Winter Internship 2026 Cold Start challenge](https://goals.xpert.chat/w/intern). It turns WhatsApp conversation history into structured information about **people, organisations, chats, goals, and tasks**, including evidence-backed decisions about when an assistant should intervene.

The submitted release is **deterministic and offline by default**. An optional OpenAI-compatible model pipeline is implemented separately, but has **not** been live-benchmarked.

## Results at a glance

| Metric | Verified development result |
| --- | ---: |
| Official development checker | **26.0081 / 56** |
| Published Xpert model baseline | 17.5 / 56 |
| Automated tests | **62 passed** |
| LLM requests in the evaluated offline run | **0** |
| Model cost per 1,000 messages | **$0** |
| Development input | 4,502 messages, 138 chats |

The results above are from the *provided development set*, not the hidden evaluation. The Xpert baseline uses a different implementation; the comparison is only on the shared development score. See [EVALUATION.md](EVALUATION.md) and the aggregate [development report](reports/dev-offline.json) for the breakdown and limitations.

## Quick start

**Requirements:** Python 3.9+, Bash, and the Python standard library. No package installation is needed.

The grading interface is:

```bash
./run.sh <input_dir> <output.json>
```

To generate a **fictional** test input, run the solution, and validate its output:

```bash
python3 scripts/make_example.py example
mkdir -p artifacts
./run.sh example artifacts/example.json
python3 check.py example artifacts/example.json
```

Run the automated tests:

```bash
python3 -m unittest discover -s tests -v
```

For an authorised **local** development benchmark, place the supplied challenge input privately under `data/dev/` and run:

```bash
python3 scripts/benchmark.py data/dev --mode offline
```

The program reads `chats.jsonl`, `messages.jsonl`, and optional `seed.json` from the input directory. The official development checker reads answer keys separately; inference itself does not.

## Output contract

The program writes a single JSON object with these five arrays:

```json
{
  "people": [],
  "organisations": [],
  "chats": [],
  "goals": [],
  "open_loops": []
}
```

- **People:** relationship circles, organisation links, and care relationships.
- **Organisations:** user-associated businesses, homes, schools, and other groups.
- **Chats:** exactly one person or organisation association per conversation.
- **Goals:** supported longer-term goals with original message IDs as evidence.
- **Open loops:** commitments, follow-ups, deadlines, and decisions, including ownership, status, closure evidence, and whether to `assist`, `remind`, or `leave`.

The supplied [schema](schema.json) and [checker](check.py) validate output structure and references.

## Approach and code layout

| Component | Responsibility |
| --- | --- |
| [`solution.py`](solution.py) and [`run.sh`](run.sh) | Stable command-line entry point and execution-mode selection |
| [`coldstart/data.py`](coldstart/data.py) | Load messages, preserve source IDs, handle voice transcripts, and build chronological indexes |
| [`coldstart/rules.py`](coldstart/rules.py) | Offline relationship, organisation, chat, and task inference |
| [`coldstart/pipeline.py`](coldstart/pipeline.py) | Optional multi-stage model-assisted extraction and evidence retrieval |
| [`coldstart/normalize.py`](coldstart/normalize.py) and [`coldstart/schema_guard.py`](coldstart/schema_guard.py) | Normalize output and reject unsupported references or invalid structures |
| [`coldstart/policy.py`](coldstart/policy.py) | Decide when assistance, reminders, or non-intervention are appropriate |
| [`llm.py`](llm.py) | OpenAI-compatible API transport, retries, and usage accounting |
| [`tests/`](tests) | Synthetic regression tests and integration checks |

The implementation favors **source-grounded predictions**. Task status is based on later evidence, rather than treating an acknowledgement, expired deadline, or promise as proof of completion. It preserves stable IDs, applies known seed relationships, and avoids hard-coding development identities or answer labels. Assistance recommendations describe a next step; they do not execute external actions.

## Model support (optional)

The grading entry point `run.sh` **defaults to offline inference**, even if the evaluator provides model credentials. To opt into the model pipeline, explicitly set `XPERT_MODE=model` and supply these environment variables securely:

- `LLM_BASE_URL` — OpenAI-compatible API endpoint
- `LLM_API_KEY` — provider credential
- `LLM_MODEL` — exact model ID

Then run:

```bash
XPERT_MODE=model ./run.sh <input_dir> <output.json>
```

The documented optional OpenRouter candidate is `baidu/ernie-5.5-flash-preview:free`. **It has not been live-tested**, and the measured 26.0081/56 score does **not** come from that model. The optional code includes bounded requests, private caching, schema guards, and deterministic degradation handling. See [MODEL_SELECTION.md](MODEL_SELECTION.md) for the provider compatibility and privacy caveats.

No model key is needed to reproduce the submitted offline behavior.

## Known limitations

Development task matching has **16.8% matching-source precision** and **64.9% recall** against the provided labels. Indirect requests, multilingual phrasing, ambiguous task owners, and cross-chat completion evidence remain challenging. Offline mode deliberately does **not** infer additional goals; goal and assistance quality are not labelled in the development checker. Hidden-set performance is unknown.

For measured failure categories and cost assumptions, see the required [WRITEUP.md](WRITEUP.md).

## Privacy, reproducibility, and AI development records

The repository excludes challenge conversation datasets, answer keys, generated private predictions, model caches, and API credentials. Do not commit those files or transmit private conversations to an unapproved model provider. The code uses the configured model endpoint only when explicitly enabled with `XPERT_MODE=model` or the task-only `XPERT_TASK_REVIEW=1` option below.

The required [`ai-logs/`](ai-logs) directory contains authentic development-session records and clearly marked partial transcripts. These logs are part of the assessment's AI-tool transparency requirements.

Additional documentation: [submission guide](SUBMISSION.md) · [evaluation report](EVALUATION.md) · [model-selection notes](MODEL_SELECTION.md) · [interview preparation](INTERVIEW_PREP.md).

## Experimental task-only completion review

This feature branch adds an opt-in review of unresolved task statuses. It does not change people, organisations, chat assignments, task extraction, owners or source IDs. The stable published offline release remains the submission fallback. No main-branch merge is authorised.

A model can confirm completion/cancellation that lexical rules rejected (for example, a contextual "Done" or a paraphrase). Structural checks still require a listed later message from the same chat. Semantic acknowledgement/future-word filters are deliberately not reapplied after the model verdict. The model can still be wrong: there is **no measured real-model score improvement**. Task-source retrieval and the loops-found metric are unchanged by this feature.

Use any **OpenAI-compatible** local server or cloud API through the existing `llm.Client`, or inject an adapter implementing `JSONModel.json` into `review_completions`. A local example, after starting your own server:

```bash
# Dummy key is for a local server that ignores authentication only.
LLM_BASE_URL=http://localhost:8000/v1 \
LLM_API_KEY=local-unused \
LLM_MODEL=your-local-model-id \
XPERT_MODE=offline XPERT_TASK_REVIEW=1 \
./run.sh <input_dir> <output.json>
```

For a cloud provider, configure its actual base URL/model and inject credentials securely through the environment. Do not send private conversations until that provider has been authorised. Enabling task-only review with full `XPERT_MODE=model` is rejected to prevent accidentally changing the graph/person stages.

Token controls: 71-word system prompt; full source plus at most ten short later candidates and one preceding context message; numeric speaker/message references; shared text deduplicated within each batch; up to eight tasks / 6,000 compact JSON characters; sparse numeric verdicts with no explanation; private response caching. Long candidate bodies are skipped instead of presenting clipped text as proof. Retrieval can miss distant semantic paraphrases and cross-chat evidence. Character limits are not exact tokenizer counts, and reasoning models may consume additional reasoning tokens.

Output cap: `XPERT_TASK_REVIEW_OUTPUT_TOKENS=256` by default, configurable up to 16,000 for models needing more reasoning/output space. Time budget: `XPERT_TASK_REVIEW_SECONDS=300`. Existing `XPERT_MAX_CALLS`, free-route restrictions and rate pacing apply. Invalid responses, provider failures and budget exhaustion retain the baseline task for the affected batch. Metrics report actual returned token counts and accepted/invalid verdicts; estimated prices must be set for the actual provider.

Verification on this branch: **75 tests passed**, including 13 new synthetic review/integration/cache regressions. Offline development score remains **26.008092745190027/56** with zero API calls. A dry construction of dev requests produced 36 batches for 257 eligible unresolved tasks, maximum 5,312 input JSON characters; no model received those requests. Mock verdicts establish integration behavior, not semantic accuracy or a live-model benchmark.
