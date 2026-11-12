# Xpert project — final handoff

**26.0081/56 offline; 62 tests pass.** This continuation preserves the recovered Git history and improves the 22.3940 checkpoint. The final default is the verified, zero-call offline path. Read `WRITEUP.md` and `EVALUATION.md` for measured limitations.

## Verify and run

Python 3.9+, standard library only.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/make_example.py example
./run.sh example artifacts/example.json
python3 check.py example artifacts/example.json
# Restore the supplied data privately to data/dev before benchmarking:
python3 scripts/benchmark.py data/dev --mode offline
```

Every supplied dataset, answer key, private prediction, response cache and credential is excluded. The entry point defaults to offline even if the evaluator supplies all three `LLM_*` variables. An explicit `XPERT_MODE=model` enables the optional OpenAI-compatible pipeline and honours those variables. Do not enable an untested model in the final release without a new benchmark and commit.

The free candidate `baidu/ernie-5.5-flash-preview:free` is publicly listed but has not run. For a synthetic-only compatibility test on your own machine: `python3 scripts/probe_free_model.py --ask-key`. Enter the key in its hidden terminal prompt, never chat or project files. A real-data run requires a separate provider/privacy authorisation.

## Repository and exact commit

Public repository: https://github.com/toni8283/xpert_challange . The connected integration has verified that it exists and permits uploads. Public repositories need no evaluator invitation. No collaborator has been invited.

Verify the branch head after publishing:

```bash
git ls-remote https://github.com/toni8283/xpert_challange.git refs/heads/main
```

Use the full 40-character remote SHA in the submission form. The enclosing release manifest records the remote publication SHA when verified. The bundle preserves the recovered local development history; connector-created remote commits can have a different SHA. Do not confuse the two histories.

## Submit personally

Open [the official assessment](https://goals.xpert.chat/w/intern), go to Submit, and enter:

1. Your full name and the email used to register.
2. The public URL `https://github.com/toni8283/xpert_challange`, after verifying its files and main SHA.
3. The full 40-character SHA verified on remote main (recorded in the outer manifest).
4. Model: `baidu/ernie-5.5-flash-preview:free` as the optional listed candidate.
5. Additional information: "This commit defaults to deterministic offline inference, makes zero model calls, and scored 26.0081/56 on development data. The optional model path is not live-benchmarked."

Submit before **12 November 2026, 23:59 IST**. The latest valid submission before the deadline wins; later code changes require a newly pushed SHA and a new form submission. Nothing has been submitted on your behalf. Do not submit a local-only SHA or a repository the evaluator cannot access.
