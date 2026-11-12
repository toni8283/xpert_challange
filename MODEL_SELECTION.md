# Model and release selection

The shipped `run.sh` defaults to **offline**. This is the strongest measured implementation: **26.008092745190027/56**, zero provider calls, zero provider spend. It does not infer goals. No live model has been compared with it, so no model superiority claim is made.

For the required model field, the optional candidate is **`baidu/ernie-5.5-flash-preview:free`** through `https://openrouter.ai/api/v1`. State in the additional information that the submitted entry point deliberately makes no model calls. The assessment permits rules and zero-call solutions. Its free-model paid-equivalent pricing therefore does not affect this release's zero usage.

## Public compatibility check, 12 November 2026

| Property | Observed public metadata / policy |
|---|---|
| Availability | Exact model ID listed in OpenRouter's live catalogue |
| Token price | Prompt and completion both zero for the free variant |
| Context | 1,024,000 tokens |
| Maximum completion | 921,600 tokens in API metadata |
| JSON | `response_format` and `structured_outputs` advertised; not live-verified |
| Reasoning | Mandatory high effort; code does not send unsupported low effort |
| Provider | Baidu endpoint; no adequate retention/training guarantee established |
| Free quotas | 20 requests/minute, ordinarily 50/day without qualifying purchased credits; account limits may be lower |
| Privacy decision | No real dataset sent; explicit authorisation is still required |

The client paces free requests at 3.2 seconds, defaults to 40 attempts, caps token prices at zero, disables provider fallback and requests `data_collection: deny`. These restrictions may leave no eligible route. They are not proof of contractual privacy or zero retention. Do not loosen them to force a test. No credits were purchased.

Sources: [model](https://openrouter.ai/baidu/ernie-5.5-flash-preview:free), [catalogue](https://openrouter.ai/api/v1/models), [free models](https://openrouter.ai/collections/free-models), [provider routing](https://openrouter.ai/docs/features/provider-routing), [privacy](https://openrouter.ai/privacy).

## Synthetic-only test

```bash
python3 scripts/probe_free_model.py --ask-key
```

Run in your own interactive terminal. Hidden key input is never saved. This sends only invented built-in messages; it accepts no dataset path. It first checks live zero pricing and then validates actual source IDs, task coverage, entity references and completion evidence. The recorded attempt in this release stopped **before inference: missing credentials**. No real model was called.

Only after a separate privacy decision and explicit authorisation to send the private data, configure the official variables and use `XPERT_MODE=model` or `scripts/benchmark.py --mode model`. Compare the unchanged checker and measured usage with the offline report. A catalogue listing, mock server or blocked probe is not a model benchmark. Evaluation uses its own key; a free ID may be mapped to the paid equivalent as the assessment explains.
