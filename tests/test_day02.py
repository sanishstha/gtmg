from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.config import compute_cost
from app.evals.day02 import Day2Label, grade_case, load_labels, summarize
from app.evals.score import ExpectedEvent
from app.inference.models import CHEAP_MODEL, MID_MODEL, STRONG_MODEL, InferenceResult
from app.inference.provider import extract_event
from app.inference.router import MANY_ENTITIES, choose_model, extract_routed, organization_names
from app.models.schemas import ExtractionDraft
from tests.fakes import FakeLLM


def _label(expected_event: bool, expected: tuple[ExpectedEvent, ...] = ()) -> Day2Label:
    return Day2Label(
        document_id="case",
        bucket="obvious",
        title="Desk note",
        body="OpenAI lowered the API price by 20 percent.",
        expected_event=expected_event,
        expected=expected,
        source_url="https://eval.local/case",
    )


def _result(events: list[dict] | None, *, success: bool = True) -> InferenceResult:
    draft = None
    if events is not None:
        draft = ExtractionDraft.model_validate({"events": events})
    return InferenceResult(
        output=draft if success else None,
        model=CHEAP_MODEL,
        input_tokens=10,
        output_tokens=4,
        latency_ms=20,
        cost_usd=Decimal("0.000010"),
        success=success and draft is not None,
        error=None if success else "invalid output",
    )


def _event(event_type: str = "PRICE_CHANGE", entity: str = "OpenAI", quote: str | None = None, confidence: float = 0.9):
    return {
        "event_type": event_type,
        "entities": [entity],
        "claim": f"{entity} changed the commercial terms.",
        "occurred_at": None,
        "magnitude": None,
        "unit": None,
        "evidence_quote": quote or "OpenAI lowered the API price by 20 percent.",
        "confidence": confidence,
    }


def test_extract_event_returns_draft_without_a_session():
    document = SimpleNamespace(
        title="Desk note",
        body="OpenAI lowered the API price by 20 percent.",
        source_url="https://example.test/doc",
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    llm = FakeLLM([{"events": [_event()]}])
    result = extract_event(document, CHEAP_MODEL, llm)
    assert result.success is True
    assert result.output is not None
    assert result.output.events[0].event_type.value == "PRICE_CHANGE"
    assert result.input_tokens == 100
    assert result.output_tokens == 40
    assert result.latency_ms == 200
    assert result.cost_usd == compute_cost(CHEAP_MODEL, 100, 40)
    assert llm.calls == 1


def test_exact_match_is_correct():
    label = _label(True, (ExpectedEvent("PRICE_CHANGE", ("OpenAI",)),))
    grade = grade_case(label, _result([_event()]))
    assert grade.correct is True
    assert grade.schema_valid is True
    assert grade.event_type_correct is True
    assert grade.entity_correct is True


def test_extra_event_is_incorrect_but_the_pair_was_found():
    label = _label(True, (ExpectedEvent("PRICE_CHANGE", ("OpenAI",)),))
    grade = grade_case(label, _result([_event(), _event("FUNDING", "Anthropic", quote="Anthropic raised a round.")]))
    assert grade.correct is False
    assert grade.event_type_correct is True
    assert grade.entity_correct is True
    assert grade.pairs_found is True


def test_irrelevant_document_must_return_nothing():
    label = _label(False)
    quiet = grade_case(label, _result([]))
    assert quiet.correct is True
    assert quiet.event_type_correct is True
    assert quiet.entity_correct is True
    noisy = grade_case(label, _result([_event()]))
    assert noisy.correct is False
    assert noisy.event_type_correct is False
    assert noisy.entity_correct is False


def test_two_event_case_requires_both_pairs_and_no_extras():
    label = _label(
        True,
        (ExpectedEvent("PRICE_CHANGE", ("OpenAI",)), ExpectedEvent("MODEL_RELEASE", ("OpenAI",))),
    )
    both = grade_case(
        label,
        _result([_event(), _event("MODEL_RELEASE", quote="OpenAI released Harbor.")]),
    )
    assert both.correct is True
    missing = grade_case(label, _result([_event()]))
    assert missing.correct is False
    assert missing.pairs_found is False


def test_invalid_schema_is_incorrect():
    label = _label(True, (ExpectedEvent("PRICE_CHANGE", ("OpenAI",)),))
    grade = grade_case(label, _result(None, success=False))
    assert grade.correct is False
    assert grade.schema_valid is False
    assert grade.event_type_correct is False


def test_cost_per_correct_uses_total_spend():
    grades = [
        grade_case(_label(True, (ExpectedEvent("PRICE_CHANGE", ("OpenAI",)),)), _result([_event()])),
        grade_case(_label(False), _result([_event()])),
    ]
    summary = summarize(grades, [Decimal("0.10"), Decimal("0.10")], [10, 30], [True, False])
    assert summary.correct == 1
    assert summary.accuracy == 0.5
    assert summary.cost_per_correct == Decimal("0.20")
    assert summary.recall == 1.0
    assert summary.precision == 0.5


def test_dataset_has_thirty_hand_labeled_cases():
    labels = load_labels()
    assert len(labels) == 30
    counts: dict[str, int] = {}
    for label in labels:
        counts[label.bucket] = counts.get(label.bucket, 0) + 1
        if label.expected_event:
            assert label.expected
        else:
            assert label.expected == ()
    assert counts == {"obvious": 8, "subtle": 6, "irrelevant": 6, "multiple": 5, "messy": 5}


def test_short_clean_result_stays_on_the_cheap_model():
    document = SimpleNamespace(
        title="Desk note",
        body="OpenAI lowered the API price by 20 percent.",
        source_url="https://example.test/doc",
        published_at=None,
    )
    llm = FakeLLM([{"events": [_event()]}])
    result = extract_routed(document, llm)
    assert result.model == CHEAP_MODEL
    assert result.escalated is False
    assert result.route == CHEAP_MODEL
    assert llm.calls == 1


def test_invalid_parse_escalates_and_sums_both_calls():
    document = SimpleNamespace(
        title="Desk note",
        body="OpenAI lowered the API price by 20 percent.",
        source_url="https://example.test/doc",
        published_at=None,
    )
    llm = FakeLLM(["not json", "still not json", {"events": [_event()]}])
    result = extract_routed(document, llm)
    cheap = compute_cost(CHEAP_MODEL, 10, 2)
    strong = compute_cost(STRONG_MODEL, 100, 40)
    assert result.escalated is True
    assert result.escalation_reason == "schema_invalid"
    assert result.model == STRONG_MODEL
    assert result.route == CHEAP_MODEL
    assert result.cost_usd == cheap + strong
    assert result.latency_ms == 250
    assert result.input_tokens == 110
    assert result.output_tokens == 42
    assert llm.calls == 3


def test_two_events_escalate():
    document = SimpleNamespace(
        title="Desk note",
        body="OpenAI lowered the API price by 20 percent. OpenAI released Harbor.",
        source_url="https://example.test/doc",
        published_at=None,
    )
    llm = FakeLLM([
        {"events": [_event(), _event("MODEL_RELEASE", quote="OpenAI released Harbor.")]},
        {"events": [_event()]},
    ])
    result = extract_routed(document, llm)
    assert result.escalated is True
    assert result.escalation_reason == "multiple_events"
    assert llm.calls == 2


def test_empty_draft_does_not_escalate():
    document = SimpleNamespace(
        title="Desk note",
        body="The team booked a room for Thursday.",
        source_url="https://example.test/doc",
        published_at=None,
    )
    llm = FakeLLM([{"events": []}])
    result = extract_routed(document, llm)
    assert result.success is True
    assert result.escalated is False
    assert result.output is not None
    assert result.output.events == []
    assert llm.calls == 1


def test_choose_model_follows_the_failure_notes():
    long_body = " ".join(["context"] * 500)
    long_doc = SimpleNamespace(title="Note", body=long_body, source_url="", published_at=None)
    assert choose_model(long_doc) == CHEAP_MODEL
    names = "OpenAI, Anthropic, Google, Microsoft, Amazon, and Meta attended a forum."
    assert len(organization_names(names)) > MANY_ENTITIES
    crowded = SimpleNamespace(title="Forum", body=names, source_url="", published_at=None)
    assert choose_model(crowded) == MID_MODEL
    scored = SimpleNamespace(
        title="Score",
        body="DeepSeek scored 89 percent on the MATH benchmark.",
        source_url="",
        published_at=None,
    )
    assert choose_model(scored) == STRONG_MODEL
    subtle = SimpleNamespace(
        title="Access",
        body="Mistral said the model is now generally available.",
        source_url="",
        published_at=None,
    )
    assert choose_model(subtle) == MID_MODEL
