# Cheap-model failure analysis

Source: the 30 `gpt-4.1-nano` rows in `model_outputs.jsonl`. Twelve cases were strict-incorrect. Schema validity was 100%, so F5 is empty. No extracted entity was wrong on its own, so F3 is empty. Nano did not emit an event on any document that had none, so F4 is empty for the cheap model.

Categories map onto `failure_taxonomy.md` as in the Day 2 plan. F6 is new. Each miss has one primary category.

## F1 missed event

Nano returned an empty event list. The document states one event.

- d02-08, obvious, 34 words, 2 names. DeepSeek's MATH score moved from 71 to 89. No event returned.
- d02-09, subtle, 30 words, 3 names. Mistral made Magistral generally available. The word "release" is absent. No event returned.
- d02-10, subtle, 41 words, 1 name. OpenAI's token bundle fell from $1.50 to $0.75. The word "price" is absent. No event returned.
- d02-13, subtle, 39 words, 2 names. AMD is sampling the MI400. The word "release" is absent. No event returned.
- d02-14, subtle, 47 words, 2 names. Cohere's financing is one sentence inside a partnership note. No event returned.

## F2 wrong event type

The entity was right. The type was not.

- d02-11, subtle, 351 words, 2 names. "Amazon told investors it will spend 25 billion dollars" was labeled `FUNDING` instead of `CAPEX_ANNOUNCEMENT`. Quote is grounded. Confidence 1.0.
- d02-12, subtle, 47 words, 3 names. A 150 megawatt computing hall was labeled `OTHER` instead of `DATACENTER_EXPANSION`. The word "data center" is absent.

## F6 multiple-event confusion

The document states more than one event. Nano did not return that set.

- d02-22, multiple, 34 words, 2 names. Returned only the Microsoft capex. Dropped the Wisconsin data center.
- d02-24, multiple, 38 words, 3 names. Returned nothing for the H200 launch and the MMLU gain.
- d02-25, multiple, 53 words, 9 names. Returned nothing for three CoreWeave announcements, after a sentence that says six other companies announced nothing.

## F7 ambiguity or reasoning failure

- d02-28, messy, 51 words, 2 names. The article corrects a 20 percent cut to 5 percent and still states that OpenAI cut the price. Nano returned nothing rather than pick a figure.
- d02-27, messy, 34 words, 4 names. Anthropic's prices are unchanged and OpenAI cut by 10 percent. Nano returned nothing. Mid and strong both returned the OpenAI cut and an extra Anthropic price change. Strict accuracy fails all three tiers on this case. Nano's failure is a miss. Theirs is an invented second event (F4 on those tiers).

## What predicts a cheap miss

Compared across the 30 cases:

- Subtle wording predicts failure. All 6 subtle documents failed. 7 of 8 obvious documents succeeded. The obvious miss was the benchmark score (d02-08), which never uses a release or price verb.
- Multiple stated events predict failure. 3 of 5 multiple-event documents failed. The two that succeeded name both events with "released" and "lowered", or "raised" and "acquired".
- A contradiction or a two-company contrast predicts failure (d02-27, d02-28).
- Length does not. Incorrect cases averaged 67 words and correct cases averaged 53. The long irrelevant essay (d02-19, 358 words) was correct. The one long miss (d02-11) is the "will spend" sentence, and the same sentence would fail at any length. A length cutoff would also send the essay that nano already got right to the strong model.
- Mean organization count does not. Incorrect cases averaged 2.9 names and correct cases averaged 2.7. The tail does: d02-25 has 9 names and was a total miss, and no correct case has more than 4. That single threshold is worth keeping. The average is not.

Nano's errors are misses and type mistakes, not hallucinations. Precision was 100% on every tier. Recall is where the cheap model falls over: 45.5% versus 95.5% for mini and 100% for `gpt-4.1`.

## Routing signals taken from this file

`choose_model` does not use length. It uses the features above:

- `benchmark` or `scored` goes to `gpt-4.1`. Mini labeled d02-08 as a model release. The strong model got the benchmark type right. This is the one case where the strong tier earned its price.
- More than 4 organization-like names goes to `gpt-4.1-mini` (d02-25).
- A short list of phrases that showed up on nano misses and not on nano successes goes to `gpt-4.1-mini`: "generally available", "sampling", "packaging", "invoice", "new financing", "will spend", "correction", "megawatt" when the text does not already say "data center", and the pair "capital expenditure" plus "new data center". The narrower phrases avoid the obvious capex note, the obvious data-center note, and the Adept round, all of which nano already got right.
- Everything else stays on `gpt-4.1-nano`, including d02-27. No tier was strict-correct there, so a more expensive call does not buy a better grade.

Escalation is unchanged: invalid schema, an ungrounded quote, more than one extracted event, type `OTHER`, or confidence below 0.6. An empty list is still accepted. Escalating empties would re-bill the eight documents that correctly have no event.
