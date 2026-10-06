from datetime import datetime, timezone

from sqlalchemy import func, select

from app.extraction.service import extract_document
from app.ingestion.rss import NormalizedDocument
from app.ingestion.service import ingest_documents
from app.models.orm import EconomicEvent, Evidence, ExtractionFailure, SourceDocument
from tests.fakes import FakeLLM


def _document(session, body: str) -> SourceDocument:
    ingest_documents(
        session,
        [
            NormalizedDocument(
                source_type="rss",
                source_url="https://example.test/doc",
                title="Desk note",
                body=body,
                published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
            )
        ],
    )
    return session.scalar(select(SourceDocument))


def test_invalid_model_output_is_stored(session):
    document = _document(session, "OpenAI lowered the API price by 20 percent.")
    llm = FakeLLM(["not json", "still not json"])
    outcome = extract_document(session, document, llm, "gpt-4.1-mini")
    assert outcome.failed is True
    assert llm.calls == 2
    failure = session.scalar(select(ExtractionFailure))
    assert failure is not None
    assert failure.source_document_id == document.id
    assert "invalid output" in failure.error


def test_extracting_a_document_twice_does_not_duplicate_events(session):
    body = "OpenAI lowered the API price by 20 percent."
    document = _document(session, body)
    payload = {
        "events": [
            {
                "event_type": "PRICE_CHANGE",
                "entities": ["OpenAI"],
                "claim": "OpenAI lowered the API price by 20 percent.",
                "occurred_at": None,
                "magnitude": 20,
                "unit": "percent",
                "evidence_quote": "lowered the API price by 20 percent",
                "confidence": 0.8,
            }
        ]
    }
    first = extract_document(session, document, FakeLLM([payload]), "gpt-4.1-mini")
    second = extract_document(session, document, FakeLLM([payload]), "gpt-4.1-mini")
    assert first.events_created == 1
    assert first.grounded_events == 1
    assert second.skipped is True
    assert session.scalar(select(func.count()).select_from(EconomicEvent)) == 1
    evidence = session.scalar(select(Evidence))
    assert evidence.grounded is True
    assert evidence.char_start == body.find(evidence.quote)


def test_ungrounded_quote_is_kept_and_marked(session):
    document = _document(session, "The blog post discussed general progress.")
    payload = {
        "events": [
            {
                "event_type": "FUNDING",
                "entities": ["OpenAI"],
                "claim": "OpenAI raised a new round.",
                "occurred_at": None,
                "magnitude": None,
                "unit": None,
                "evidence_quote": "raised a new round",
                "confidence": 0.4,
            }
        ]
    }
    outcome = extract_document(session, document, FakeLLM([payload]), "gpt-4.1-mini")
    assert outcome.events_created == 1
    assert outcome.grounded_events == 0
    evidence = session.scalar(select(Evidence))
    assert evidence.grounded is False
