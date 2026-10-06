import json
from pathlib import Path

from app.evals.score import ExpectedEvent, ExtractedEvent, load_labels, score_detection


def test_format_examples_are_not_counted_as_labels():
    labels = load_labels(Path("evals/day1_event_extraction.jsonl"))
    assert labels == []
    score = score_detection([])
    assert score.recall is None
    assert score.false_positive_rate is None


def test_recall_and_false_positives_score_once_twenty_labels_exist():
    expected = (ExpectedEvent("PRICE_CHANGE", ("OpenAI",)),)
    hit = (ExtractedEvent("PRICE_CHANGE", ("OpenAI",)),)
    miss = (ExtractedEvent("FUNDING", ("OpenAI",)),)
    cases = [(expected, hit)] * 19
    assert score_detection(cases).recall is None
    cases.append((expected, miss))
    score = score_detection(cases)
    assert score.labeled == 20
    assert score.recall == 19 / 20
    assert score.false_positive_rate == 1 / 20


def test_jsonl_examples_parse():
    rows = [
        json.loads(line)
        for line in Path("evals/day1_event_extraction.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2
    assert {row["label_status"] for row in rows} == {"format_example"}
    assert rows[0]["expected_events"][0]["event_type"] == "PRICE_CHANGE"
