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

Public repository: https://github.com/toni8283/xpert_challange . The source has been published on `main` and the GitHub integration verified its contents. Public repositories need no evaluator invitation. No collaborator has been invited.

Verify the current remote branch head (use the exact SHA for grading):

```bash
git ls-remote https://github.com/toni8283/xpert_challange.git refs/heads/main
```

Use the full 40-character remote SHA in the submission form. The GitHub commit SHA—not a local Git bundle or older checkpoint SHA—is the one to enter in the form. Any new documentation or source commit changes that SHA. If already submitted, submit the form again with the latest intended SHA before the deadline.

## Submit personally

Open [the official assessment](https://goals.xpert.chat/w/intern), go to Submit, and enter:

1. Your full name and the email used to register.
2. The public URL `https://github.com/toni8283/xpert_challange`, after verifying its files and main SHA.
3. The full 40-character SHA currently on remote main, as returned by the command above.
4. Model: `baidu/ernie-5.5-flash-preview:free` as the optional listed candidate.
5. Additional information: "This commit defaults to deterministic offline inference, makes zero model calls, and scored 26.0081/56 on development data. The optional model path is not live-benchmarked."

Submit before **12 November 2026, 23:59 IST**. The latest valid submission before the deadline wins; later code changes require a newly pushed SHA and a new form submission. Nothing has been submitted on your behalf. Do not submit a local-only SHA or a repository the evaluator cannot access.
