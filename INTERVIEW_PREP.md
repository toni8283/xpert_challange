# Understand and defend the solution

## A ten-minute walkthrough

1. **Problem (one minute).** A useful assistant must know relationships before interpreting tasks. False completion and needless interruption are costly. All evidence is tied to stable IDs, so renamed hidden data cannot reuse memorised people.
2. **Input and graph (two minutes).** Open `data.py`, then `rules.py` and the graph/people prompts. Explain direct vs group evidence, seed authority, organisation merging and why a client's company is not automatically a user organisation.
3. **Tasks (three minutes).** Open `conversation_packets`, the extraction prompt and `normalize_loop`. Trace a source through its chronological window, disjoint source boundary, owner, due date, later closure and help action.
4. **Reliability and cost (two minutes).** Open `llm.py`. Explain cache keys, 4 workers, bounded retries, JSON-mode compatibility, token logs, time limits and how authentication failures produce explicitly labelled fallback batches rather than silent model claims.
5. **Evidence and failure (two minutes).** Show `reports/dev-offline.json` and any real model report you have since generated. Say plainly what was measured. Explain low offline source precision and the incomplete/noisy dev labels. End with one improvement you would test next, using a held-out chronological slice and a real model run.

## Questions you should be able to answer

| Question | Your explanation should include |
|---|---|
| Why not send the entire export in one prompt? | Cost, context pressure, mixing speakers/chats, poor source attribution, and harder retry/debugging |
| Why do identity before tasks? | A cook's request, a client's request and a spouse's own plan imply different ownership/intervention |
| Why not make every group an organisation? | Project/client groups can belong to one company; family and class groups can belong to a person |
| Does “OK” mean done? | It can answer a decision, but usually only acknowledges an execution request |
| Why are some real done tasks left open? | A later proof is required; cross-chat or missing-media evidence may be unavailable |
| Why is the dev score 26.01? | This is the zero-cost rules run; source precision and sparse identity evidence are weak; model quality has not yet been measured |
| Does a cheap solution automatically win? | No; the brief scales cost points by quality |
| What can the model hallucinate? | A relationship, source, date, owner or closure; validators catch invalid references but not every semantic mistake |
| What do you know about goals/help performance? | Nothing quantitative from the dev key: those labels are absent; synthetic tests only verify mechanics and policy boundaries |
| What would you improve with another day? | Run the exact chosen model, inspect source/status error categories, tune recall/precision on one slice and recheck on another; add better cross-chat closure retrieval |
| What does the AI log prove? | It records actual collaboration and observed checks; it is not a claim that the candidate wrote everything unaided |

## Practise a live correction

Generate a fresh fictional example with `python3 scripts/make_example.py example`. Read its IDs before applying a correction; the illustrative IDs below are not universal:

```bash
./run.sh example artifacts/before.json
```

Create `corrections.json` containing:

```json
{"people":{"P07":{"circle":"client"}}}
```

Run:

```bash
XPERT_CORRECTIONS="$PWD/corrections.json" ./run.sh example artifacts/after.json
python3 check.py example artifacts/after.json
python3 -m unittest discover -s tests -v
```

The intentional correction changes a fictional printer from vendor to client. The old answer key will disagree with that new correction; this is expected. Show that the correction wins globally while all references remain valid, and explain that unrelated labels are retained. In model mode the corrected circle is also supplied to the task prompts.

The correction format currently handles people/circle and chat ownership. Other correction types require a small, tested code change. Do not pretend this is a complete conversational memory system.

## Be candid about AI and validation

You used AI tools, as the brief allows. Explain the choices you reviewed: independent identity/task passes, stable source IDs, explicit closure evidence, privacy boundaries and the difference between a real provider benchmark and a local simulated response. Never quote the synthetic API fixture's outcome as a model score.


## Recovery additions

The rebuilt package passes 42 tests, including 18 recovery/continuation regression checks. `schema_guard.py` enforces every keyword used by the original schema during real execution. Model chat assignment now supports direct work chats attached to organisations. Explicit binary answers can resolve a real decision, while generic acknowledgements, future promises and negated completion remain open. A spouse's independent plan remains quiet even if overdue. Local call/time limits preserve completed model work and use fallback for unprocessed batches, recorded in metrics; provider failures trigger logged, schema-valid fallback batches.

The previous scratch build was lost during disconnection. This is a restored earlier implementation plus new verified fixes; use the new commit in the release rather than the earlier unpersisted hash. The offline result remains 22.39/56. Live model quality/cost is still unmeasured.
