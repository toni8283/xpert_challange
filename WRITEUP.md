# Cold Start — Toni Blair

**Release selection:** deterministic offline rules, zero model calls. Optional model ID: `baidu/ernie-5.5-flash-preview:free` on OpenRouter; publicly listed but **not live-tested**. `run.sh` defaults to offline; an explicitly authorised `XPERT_MODE=model` run reads the official `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` variables.

## Focus and approach

I prioritised the person/organisation graph and evidence-grounded tasks. Python 3.9+ and the standard library provide a reproducible entry point without dependency installation. Offline mode omits goals rather than inventing them; model mode implements all five outputs.

Runtime reads only chats, messages and seed, never answers. Timestamp-sorted indexes combine stable IDs, saved names, direct exchanges, group membership and seed labels. Domestic roles, internal teams and service groups supply relationship priors. Direct employee/staff chats attach to a supported organisation only with relevant context. Explicit user corrections outrank inference. These rules use no development identities or message IDs.

Task extraction requires an actionable request, commitment or concrete decision. Generic offers, autoresponders, greetings and contextless promises are filtered. Repeated asks merge conservatively; different payment amounts remain distinct. Obligations retain source, owner, source-anchored IST due date, status and help. Later evidence can establish completion or cancellation. Attachments must share the requested object; address/contact delivery requires actual carrier data from the responsible person. Acknowledgements, future promises, negated completion and elapsed deadlines do not establish completion. Postponement stays open unless later completion is evidenced.

Model mode builds a graph and person dossiers, extracts chronological overlapping windows, then retrieves later same-chat evidence for closure review and consolidates grounded user goals. Source ownership prevents duplicate window extraction. Invented IDs, cross-chat/backwards closures and unsupported goals are rejected. Quiet delegates/spouse plans stay quiet; private preparation may be assisted, external actions require approval. No action is executed.

The unchanged checker plus the full supplied schema validate output. Private caches, bounded retries, concurrency and a 25-minute budget control optional inference. Budget/provider failures retain completed work and report degraded fallback explicitly. Free OpenRouter requests require zero token prices, disable provider fallback and deny provider data collection; this may make the endpoint unavailable rather than weaken privacy.

## Measured results and cost

The official checker on **4,502 development messages** reports **26.0081/56**: circles **8.20/12**, organisations **2.61/8**, chats **6.73/8**, tasks found **3.74/14**, task status **4.73/14**. The recovered checkpoint scored 22.3940/56. These are in-sample measurements; hidden quality is unknown. Goals/help have no dev labels.

The final offline run takes approximately one second, makes **zero API calls** and costs **$0 per 1,000 messages**. **62 tests** cover synthetic 20,000-message execution, local HTTP model integration/cache replay, schema/ID/temporal guards, release-mode selection and regression cases. Local simulations verify mechanics, not model accuracy. No live-model quality, latency, billing or throughput comparison exists. ERNIE public metadata advertises JSON mode and a 1,024,000-token context; credentials and provider privacy suitability remain unresolved. No private dataset was sent to it.

## Errors and limitations

**13/41** eligible circles and **13/82** chat ties are wrong. **48/74** labelled task entries match among **285** predictions: **16.8% source precision**, **64.9% recall**. **25** matched statuses are correct; **zero** labelled-open tasks are falsely closed. Low precision and implicit multilingual/fragmented obligations remain the main weaknesses. Sparse relationships, ambiguous ownership, distant paraphrases and cross-chat completion are difficult. The incomplete key contains repeated/conflicting tasks and lacks closing evidence for done labels. I preserve it unchanged and do not duplicate predictions to exploit it.
