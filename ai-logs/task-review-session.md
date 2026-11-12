# Task-only semantic completion review — 12 November 2026

This is a factual partial session/action record; synthetic tests are not real-model evaluations. Private data/tool payloads are omitted.

Actual user instruction excerpts:

> Instead of these rules, use a placeholder model (which can be replaced with a local model or a cloud based api for a frontier model) for the classification

> Only change the part used to track tasks

> do not commit anything to main branch until iunless I say

Implementation: isolated feature worktree/branch based on the current published main commit 5f54fac2852649e7cc5c7f015ecb29906a0144c0. Added a provider-neutral JSONModel interface and completion-only reviewer, with a small opt-in hook in the offline pipeline. No main-branch write or merge. No changes to extraction, relationships, graph, chat ties, source IDs, owners, official checker or schema.

The review uses a 71-word system prompt, compact shared messages and numeric verdicts. It lets the model judge meaning rather than reapplying the semantic heuristics it was asked to reconsider. Validation still rejects invented/out-of-batch/cross-chat/backwards evidence and conflicting duplicate verdicts. Completed tasks are not sent. Unresolved/uncertain/postponed tasks are omitted from the model's sparse output and retain baseline status. Configurable output, time, request budgets, existing private caching and explicit fallback are preserved.

Observed tests: all 75 tests passed (62 existing plus 13 new), including invented paraphrase/contextual-done/cancellation decisions, abstention, invalid/duplicate/cross-chat verdicts, provider/budget failures, compact message reuse, long-proof exclusion, task-only activation and cache replay. These responses are supplied test stubs, not a claim that a real model understood the examples.

Official checker, offline mode: 26.008092745190027/56, 285 predicted tasks, zero model calls. A private local dry request-builder check counted 276 unresolved tasks, 257 eligible tasks and 36 potential batches; maximum 5,312 and mean 2,716 compact input JSON characters. No built request was sent to a model. Python 3.9 grammar passed for changed sources; original checker/schema bytes remain identical.

No real model was called, no API key was requested in chat, no paid calls or purchases were made, and no private dataset was sent to a new provider. A semantic score gain remains unmeasured and is not promised. This completion-only change cannot improve source-task recall or loops-found score. Promote only after an authorised actual-model benchmark and explicit user permission to change main.
