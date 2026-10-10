# Day 2: model evaluation and inference routing

Thirty hand-labeled documents, three GPT-4.1 tiers, ninety paid calls, then a deterministic router scored against the strong tier already on disk. The exam never writes to Postgres. The hypothesis agent is untouched. Source: `experiments/day02`, 10 Oct 2026.

## What the exam was built to answer

gpt-4.1 won, 29 of 30 against 28 for mini and 18 for nano. It costs about 5.2 times mini and 24 times nano per call. Nano’s dominant miss is a missed event, and every subtle document failed. The router scored 27 of 30 at $0.017 versus $0.048 for strong-only, about 65% less spend. Two of its three misses are the cheap model changing its answer on a second call, not a bad route.

| System | Strict correct | Notes |
|---|---:|---|
| gpt-4.1 | 29/30 | Won the shootout |
| gpt-4.1-mini | 28/30 | One case behind strong |
| gpt-4.1-nano | 18/30 | Every subtle document failed |
| Router | 27/30 | About 65% cheaper than strong-only |

## Shootout

Each of the 30 cases was sent to `gpt-4.1-nano`, `gpt-4.1-mini`, and `gpt-4.1` at temperature 0. A provider exception would have been recorded on that row and the loop would have continued. None occurred. Schema validity was 100% on every tier, and precision was 100%: no model invented an event on a document that had none. The gap is recall.

| Metric | Nano | Mini | Strong | How it is counted |
|---|---:|---:|---:|---|
| Strict accuracy | 60.0% | 93.3% | 96.7% | Correct cases / 30 |
| Correct cases | 18 | 28 | 29 | Exact set match |
| Schema validity | 100% | 100% | 100% | Parsed draft, empty error |
| Recall | 45.5% | 95.5% | 100% | Every labeled pair found / 22 event docs |
| Precision | 100% | 100% | 100% | Emitted event and the doc had one |
| Mean latency | 1,256 ms | 1,524 ms | 1,369 ms | Wall clock per call |
| Cost per call | $0.000066 | $0.000307 | $0.001606 | Configured per-million rates |
| Cost per correct | $0.000109 | $0.000329 | $0.001661 | Total spend / correct cases |

Recall’s denominator is 22, not 30. Six irrelevant notes and two messy notes (a denied rumor, a hypothetical cut) are labeled `expected_event: false`. Recall ignores extra events. Strict accuracy does not. That is why mini recall is 95.5% while strict accuracy is 93.3%: d02-27 found the OpenAI price cut and also invented an Anthropic one.

Mean cost per 1,000 documents, from the exam’s measured dollars:

| System | USD per 1,000 documents |
|---|---:|
| Nano | $0.066 |
| Mini | $0.307 |
| Strong | $1.606 |
| Router | $0.569 |

Router cost includes the four escalations.

## Accuracy by document bucket

The set was written before any paid call. Eight obvious, six subtle, six irrelevant, five multiple-event, five messy. Bodies are a few hundred words. Event types stay inside the existing enum. These are not the 53 live events from the 10 Oct desk run.

Strict-correct rate within each bucket:

| Bucket | Nano | Mini | Strong | Router |
|---|---:|---:|---:|---:|
| Obvious | 87.5% (7/8) | 87.5% (7/8) | 100% (8/8) | 75% (6/8) |
| Subtle | 0% (0/6) | 100% (6/6) | 100% (6/6) | 100% (6/6) |
| Irrelevant | 100% (6/6) | 100% (6/6) | 100% (6/6) | 100% (6/6) |
| Multiple | 40% (2/5) | 100% (5/5) | 100% (5/5) | 100% (5/5) |
| Messy | 60% (3/5) | 80% (4/5) | 80% (4/5) | 80% (4/5) |

Subtle is 0 of 6 for nano and 6 of 6 for mini, strong, and the router. Messy stays at 4 of 5 for every system above nano because d02-27 fails all three tiers.

## Where the one extra correct case came from

Mini and strong disagree on a single document. d02-08 says DeepSeek’s MATH score moved from 71 to 89. Nano returned nothing. Mini called it a model release. gpt-4.1 called it a benchmark change, which is the label. That is the only case where the strong tier earned the price difference. Every other mini miss is d02-27, and strong misses that one too: both added a price change for Anthropic after the text said Anthropic’s prices were unchanged.

## Cheap-model failures

Twelve nano rows were strict-incorrect. Schema failures, wrong entities, and hallucinations on empty documents are all zero. Nano’s errors are misses and type mistakes. Categories use the Day 2 names, mapped onto the existing failure taxonomy.

| Category | Nano misses |
|---|---:|
| F1 missed event | 5 |
| F6 multiple-event | 3 |
| F2 wrong type | 2 |
| F7 ambiguity | 2 |

F3 wrong entity, F4 hallucination, and F5 malformed schema are empty. One primary category per incorrect nano row.

What actually predicted a miss:

- Subtle wording did. All 6 subtle documents failed. 7 of 8 obvious documents succeeded. The obvious miss is the benchmark score, which never uses a release or price verb.
- Multiple stated events did, partly. 3 of 5 failed. The two that succeeded name both events with ordinary verbs: released and lowered, raised and acquired.
- Length did not. Incorrect cases averaged 67 words and correct cases averaged 53. The long irrelevant essay, 358 words, was correct. A length cutoff would have sent a document nano already got right to the expensive model.
- Mean name-count did not. The tail did. d02-25 has 9 organization-like names and was a total miss, and no correct nano case has more than 4.

| Case | Bucket | Category | What nano did |
|---|---|---|---|
| d02-08 | Obvious | F1 missed event | Empty list. MATH 71 to 89, no release verb. |
| d02-09 | Subtle | F1 missed event | Empty list. Magistral “generally available”. |
| d02-10 | Subtle | F1 missed event | Empty list. $1.50 to $0.75, word “price” absent. |
| d02-13 | Subtle | F1 missed event | Empty list. MI400 described as sampling. |
| d02-14 | Subtle | F1 missed event | Empty list. Financing buried in a partnership note. |
| d02-11 | Subtle | F2 wrong type | Amazon “will spend $25B” labeled funding, not capex. |
| d02-12 | Subtle | F2 wrong type | 150 MW computing hall labeled OTHER. “Data center” absent. |
| d02-22 | Multiple | F6 multiple-event | Kept Microsoft capex, dropped the Wisconsin site. |
| d02-24 | Multiple | F6 multiple-event | Empty list. H200 launch and the MMLU gain both dropped. |
| d02-25 | Multiple | F6 multiple-event | Empty list. Three CoreWeave events after six non-announcements. |
| d02-28 | Messy | F7 ambiguity | Empty list. A 20% cut corrected to 5% in the same article. |
| d02-27 | Messy | F7 ambiguity | Empty list. OpenAI cut 10%; Anthropic unchanged. All tiers fail strict. |

## What was built

Day 1 already ran a source document through one structured model call into an economic event or an extraction failure. Day 2 put a sync inference interface in front of that call, scored it, and added a router. `OpenAIStructuredClient` remains the only SDK owner. Tiers are model-name strings on the existing model argument. Callers, SQLAlchemy, and the test fake stay synchronous.

### `app/inference`

`InferenceResult` carries the draft list, model, tokens, latency, cost, success, error, attempts, and the router fields `route`, `escalated`, and `escalation_reason`. An empty events list is a successful “no event” parse.

`extract_event` builds the same messages as the live extractor: system prompt, title, url, published time, body capped at 12,000 characters. It accepts any object with those four fields, so a JSONL case does not need a database row. Cost uses `compute_cost`.

### Live desk

`extract_document` now calls `extract_event` and then keeps the existing persist and failure behavior. A second successful extraction of the same document is still skipped. The shootout never opens a write session, because the fingerprint unique key would collapse two models into one row.

Prices, per million tokens in and out: nano $0.10 / $0.40, mini $0.40 / $1.60, gpt-4.1 $2.00 / $8.00. Mini remains the desk default.

### Grader, locked first

`app/evals/day02.py` reuses the type-plus-entity match from the existing scorer: case-insensitive entity containment. That match was not changed after seeing outputs.

A case is correct only when the parse succeeded and the extracted set equals the labeled pairs. Irrelevant documents are correct only when the model returns nothing. An errored call keeps whatever usage came back and counts as incorrect.

### The pre-routing desk

The 10 Oct live run, recorded before this exam, used `gpt-4.1-mini` on 30 RSS documents: 53 events, 0 extraction failures, 2.8 s mean latency, about $0.0805, schema validity 100%, grounded events 98%. That figure is not reproduced by running the pipeline again, because a document that already has a successful extractor run is skipped. It is a different measurement from the 30-case exam. The live documents are longer and were not hand-labeled, which is why that run’s dollars sit well above the exam’s mini cost.

## Router

`choose_model` sees the document only. No model picks the model. The first draft used length and name-count. The failure notes killed the length rule and kept the name-count tail, then added the phrases that showed up on nano misses and not on nano successes.

| Signal | Route | Why it is in the rule |
|---|---|---|
| “benchmark” or “scored” | gpt-4.1 | d02-08. Mini mistyped it. Strong got the benchmark type right. This is the one paid upgrade. |
| More than 4 organization-like names | gpt-4.1-mini | d02-25, nine names, total nano miss. No correct nano case exceeded four. Capitalized phrases, stop-words removed, not a model call. |
| Miss-only phrases | gpt-4.1-mini | generally available, sampling, packaging, invoice, new financing, will spend, correction. Plus megawatt when the text does not already say “data center”, and the pair “capital expenditure” plus “new data center”. |
| Everything else | gpt-4.1-nano | Includes d02-27. No tier was strict-correct there, so a more expensive first call does not buy the grade. |

### When the first answer is thrown out

`extract_routed` accepts the first result when the schema is valid, every evidence quote is a substring of the body, there is at most one event, no event is typed OTHER, and every confidence is at least 0.6. An empty list is accepted on purpose. Escalating every empty parse would re-bill the documents that correctly have no event. A failed check triggers one gpt-4.1 call, unless the first call was already gpt-4.1. There is no third model. The returned result uses the last model name, marks escalated, stores the reason, and sums tokens, latency, and cost across both calls. A validation retry inside one call is not escalation.

First-call mix on the 30 router runs:

| First call | Documents |
|---|---:|
| gpt-4.1-nano | 19 |
| gpt-4.1-mini | 9 |
| gpt-4.1 | 2 |
| Escalated | 4 of 30, all multi-event |

The two direct strong routes are d02-08 (benchmark) and d02-24 (the H200 note says “scored”). All four escalations fired because the first model returned more than one event, and all four of those grades stayed correct.

### Router against strong-only

Strong-only numbers are the gpt-4.1 rows already in the shootout CSV. Those 30 calls were not paid for again.

| | Strong only | Router |
|---|---:|---:|
| Strict accuracy | 96.7% (29/30) | 90.0% (27/30) |
| Total cost | $0.048180 | $0.017081 |
| Mean latency | 1,369 ms | 1,586 ms |
| Escalation rate | — | 13.3% (4 of 30) |
| Savings | — | $0.031099 |

Mean latency is higher because four documents paid for two calls. Escalation did not cause the accuracy gap. The four escalated grades were correct.

### The three router misses

| Case | Route | What happened |
|---|---|---|
| d02-02 | Nano, accepted | Second nano call labeled the Blackwell Ultra launch a model release. The shootout, same document and same model, had called it a chip release and was correct. Temperature 0 did not hold the answer still. |
| d02-07 | Nano, accepted | Second nano call returned nothing for the Gemini launch. The shootout extracted a model release and was correct. Same instability. |
| d02-27 | Nano, accepted | Nano returned nothing. In the shootout, mini and gpt-4.1 both added an Anthropic price change the text says did not happen. Sending this case up a tier does not buy a strict pass. |

## What the dollars do at volume

Scaled from the exam’s measured mean per document, not from the rate card. A few RSS feeds a day do not feel a few cents. A continuous multi-source ingest does. At one million documents the gap is about $1,606 versus about $569. The thing to watch at that scale is the two cheap-model answers that moved between runs.

| Documents | Strong only | Router | Difference |
|---:|---:|---:|---:|
| 1,000 | $1.61 | $0.57 | $1.04 |
| 100,000 | $160.60 | $56.94 | $103.66 |
| 1,000,000 | $1,606.00 | $569.37 | $1,036.63 |

## Tests and what stayed out

pytest does not touch the network. `extract_event` with the fake client returns tokens, cost, and a draft, and does not need a database session. Grader fixtures cover an irrelevant document, an exact match, an extra event, and a two-event case. Router fixtures cover a short clean note staying on nano, an invalid parse escalating with cost equal to both fake calls, two extracted events escalating, and an empty draft staying put.

The system prompt was not edited after the misses. The 53 stored live events were not used as labels. Eval fixtures do not move hypothesis confidence.

## Operating point

Expensive calls belong on benchmark wording, a crowded list of names, subtle phrasing the cheap model dropped, and any first result that is invalid, ungrounded, multi-event, typed OTHER, or below 0.6 confidence. Short single-claim notes stay on nano. The router kept 27 of the strong tier’s 29 correct cases and spent about a third of the money. The two cases it gave up were nano answers that had been correct an hour earlier.
