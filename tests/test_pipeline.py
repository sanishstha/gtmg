import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session as app_get_session
from app.ingestion.rss import NormalizedDocument
from app.main import create_app
from app.models.orm import Hypothesis, HypothesisRevision
from app.pipeline import run_pipeline
from tests.fakes import FakeLLM


def _hypothesis_response(messages):
    payload = json.loads(messages[-1]["content"])
    evidence_ids = [item["id"] for item in payload["evidence"]]
    updates = []
    for index, hypothesis in enumerate(payload["hypotheses"]):
        updates.append(
            {
                "hypothesis_id": hypothesis["id"],
                "action": "SUPPORT" if index == 0 else "IGNORE",
                "reasoning": "Checked against the quote.",
                "evidence_ids": evidence_ids if index == 0 else [],
                "suggested_confidence": 0.99,
                "proposed_hypothesis": None,
            }
        )
    return {"updates": updates}


class RoutingLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, *, messages, schema, model):
        self.calls += 1
        if schema.__name__ == "ExtractionDraft":
            item = {
                "events": [
                    {
                        "event_type": "PRICE_CHANGE",
                        "entities": ["OpenAI"],
                        "claim": "OpenAI lowered the API price.",
                        "occurred_at": None,
                        "magnitude": None,
                        "unit": None,
                        "evidence_quote": "lowered the API price",
                        "confidence": 0.9,
                    }
                ]
            }
        else:
            item = _hypothesis_response(messages)
        parsed = schema.model_validate(item)
        from app.extraction.llm import LLMResponse

        return LLMResponse(
            parsed=parsed,
            raw_text=parsed.model_dump_json(),
            tokens_in=100,
            tokens_out=40,
            model=model,
            latency_ms=200,
            error=None,
        )


def _document() -> NormalizedDocument:
    return NormalizedDocument(
        source_type="rss",
        source_url="https://example.test/pipeline",
        title="Price note",
        body="OpenAI lowered the API price yesterday.",
        published_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )


def test_pipeline_prints_measured_counts_and_is_idempotent(session):
    report = run_pipeline(session, llm=RoutingLLM(), documents=[_document()], fetch=False)
    text = report.format()
    for label in [
        "Fetched:",
        "New documents:",
        "Events extracted:",
        "Extraction failures:",
        "Hypotheses created:",
        "Hypotheses updated:",
        "Schema validity:",
        "Grounded events:",
        "Mean latency:",
        "Cost:",
    ]:
        assert label in text
    assert report.fetched == 1
    assert report.new_documents == 1
    assert report.events_extracted == 1
    assert report.extraction_failures == 0
    assert report.hypotheses_created == 4
    assert report.hypotheses_updated == 1
    assert report.schema_valid_rate == 1
    assert report.grounded_rate == 1
    hypothesis = session.scalar(select(Hypothesis).order_by(Hypothesis.created_at))
    latest = session.scalar(
        select(HypothesisRevision)
        .where(HypothesisRevision.hypothesis_id == hypothesis.id)
        .order_by(HypothesisRevision.created_at.desc())
    )
    assert latest.confidence_after == __import__("decimal").Decimal("0.56")

    again = run_pipeline(session, llm=FakeLLM([]), documents=[_document()], fetch=False)
    assert again.new_documents == 0
    assert again.events_extracted == 0
    assert again.hypotheses_created == 0
    assert again.hypotheses_updated == 0


def test_missing_api_key_reports_ingest_without_calling_a_model(session):
    report = run_pipeline(session, documents=[_document()], fetch=False)
    assert report.new_documents == 1
    assert report.events_extracted == 0
    assert report.schema_valid_rate is None
    assert report.model_skipped_reason is not None


def test_read_api_exposes_events_hypotheses_and_runs(session):
    run_pipeline(session, llm=RoutingLLM(), documents=[_document()], fetch=False)
    app = create_app()

    def override_session():
        yield session

    app.dependency_overrides[app_get_session] = override_session
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    events = client.get("/events")
    assert events.status_code == 200
    assert len(events.json()) == 1
    event_id = events.json()[0]["id"]
    detail = client.get(f"/events/{event_id}")
    assert detail.status_code == 200
    assert detail.json()["evidence"][0]["grounded"] is True
    assert client.get("/events/00000000-0000-0000-0000-000000000000").status_code == 404

    hypotheses = client.get("/hypotheses")
    assert len(hypotheses.json()) == 4
    hypothesis_id = hypotheses.json()[0]["id"]
    trajectory = client.get(f"/hypotheses/{hypothesis_id}")
    confidences = [item["confidence_after"] for item in trajectory.json()["revisions"]]
    assert confidences[0] == "0.50"
    assert confidences[-1] == "0.56"
    evidence = client.get(f"/hypotheses/{hypothesis_id}/evidence")
    assert evidence.status_code == 200
    assert evidence.json()[0]["quote"] == "lowered the API price"

    runs = client.get("/runs")
    assert {row["agent"] for row in runs.json()} == {"extractor", "hypothesis"}
    assert all(row["cost_usd"] is not None for row in runs.json())
