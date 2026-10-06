# Failure taxonomy

Observed failures from extraction and hypothesis runs go here. A category stays empty until a run is reviewed. Prompt changes wait until a category has a counted example.

## F1 missed event

An event stated in the source was not extracted.

Observed:

## F2 hallucinated event

An extracted event is not stated in the source.

Observed:

## F3 wrong entity

The event is real, and an entity on it is not.

Observed:

## F4 wrong event type

The event is real, and the type is not.

Observed:

## F5 unsupported claim

The claim does not follow from the evidence quote.

Observed:

## F6 malformed output

The model output failed schema validation after the retry.

Observed:

## F7 duplicate event

The same event was stored more than once.

Observed:

## F8 confidence badly calibrated

The suggested confidence and the later belief path disagree with the evidence, or the code step is too coarse for the claim.

Observed:
