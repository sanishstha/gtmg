# Router versus strong-only

Baseline A is the `gpt-4.1` rows already stored in `model_benchmark.csv`. System B is `extract_routed` on the same 30 documents. Escalation cost is included.

- Strong-only accuracy: 96.7%
- Strong-only cost: $0.048180
- Strong-only mean latency: 1369 ms
- Router accuracy: 90.0%
- Router cost: $0.017081
- Router mean latency: 1586 ms
- Escalation rate: 13.3% (4 of 30)
- Savings versus strong-only: $0.031099

Measured cost per document, scaled. These are the exam's average dollars, not the rate card.

| Documents | Strong-only | Router |
|---:|---:|---:|
| 1,000 | $1.606000 | $0.569367 |
| 100,000 | $160.600000 | $56.936667 |
| 1,000,000 | $1606.000000 | $569.366667 |

## Where the money matters

A desk that ingests a few RSS feeds a day does not feel a difference of a few cents. The same gap, multiplied by a continuous multi-source ingest, becomes a standing cost. The expensive model is reserved for benchmark wording, because that was the one case the mid model mistyped. Subtle wording, a crowded list of names, a buried financing line, and a document that states both capex and a data center go to the mid model. A second strong call is paid only when the first result is invalid, ungrounded, multi-event, typed OTHER, or below 0.6 confidence. Short single-claim notes stay cheap.

## What the 90% is made of

Three cases missed. Four cases escalated, all because the first model returned more than one event, and all four of those grades stayed correct. Escalation did not cause the accuracy gap.

- d02-02. Nano called the Blackwell Ultra launch a `MODEL_RELEASE`. The shootout, on the same document and the same model, had called it a `CHIP_RELEASE` and was correct. Temperature 0 did not hold the answer still.
- d02-07. Nano returned no event for the Gemini launch. The shootout extracted `MODEL_RELEASE` and was correct. Same instability.
- d02-27. Nano returned nothing. In the shootout, mini and `gpt-4.1` both added a price change for Anthropic, whose prices the document says were unchanged. Sending this case up a tier does not buy a strict pass.

The router is about 65% cheaper than strong-only on this exam ($0.017081 versus $0.048180) and 6.7 points less accurate. Mean latency is higher (1586 ms versus 1369 ms) because four documents paid for two calls. At a few dozen documents a day the dollar gap is noise. At a million documents it is about a thousand dollars versus about five hundred and seventy, and the misses are the thing to watch: two of them are the cheap model changing its mind on documents the route correctly left cheap.
