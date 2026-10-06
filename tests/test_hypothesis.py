from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.agents.hypothesis import judge_event
from app.agents.seed import seed_hypotheses
from app.extraction.service import extract_document
from app.ingestion.rss import NormalizedDocument
from app.ingestion.service import ingest_documents
from app.models.orm import AgentRun, Evidence, Hypothesis, HypothesisRevision, SourceDocument
from tests.fakes import FakeLLM


def _event_payload(quote: str) -> dict:
    return {
        "events": [
            {
                "event_type": "PRICE_CHANGE",
                "entities": ["OpenAI"],
                "claim": "OpenAI lowered the API price.",
                "occurred_at": None,
                "magnitude": None,
                "unit": None,
                "evidence_quote": quote,
                "confidence": 0.7,
            }
        ]
    }


def _ingest(session, url: str, body: str) -> SourceDocument:
    ingest_documents(
        session,
        [
            NormalizedDocument(
                source_type="rss",
                source_url=url,
                title="Note",
                body=body,
                published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
            )
        ],
    )
    return session.scalar(select(SourceDocument).where(SourceDocument.source_url == url))


def test_support_uses_the_code_rule_and_stores_the_model_suggestion(session):
    seed_hypotheses(session)
    body = "OpenAI lowered the API price."
    document = _ingest(session, "https://example.test/price", body)
    extract_document(session, document, FakeLLM([_event_payload("lowered the API price")]), "gpt-4.1-mini")
    evidence = session.scalar(select(Evidence))
    hypothesis = session.scalar(select(Hypothesis).order_by(Hypothesis.created_at))
    llm = FakeLLM(
        [
            {
                "updates": [
                    {
                        "hypothesis_id": str(hypothesis.id),
                        "action": "SUPPORT",
                        "reasoning": "The price cut matches provider competition.",
                        "evidence_ids": [str(evidence.id)],
                        "suggested_confidence": 0.99,
                        "proposed_hypothesis": None,
                    }
                ]
            }
        ]
    )
    from app.models.orm import EconomicEvent

    event = session.scalar(select(EconomicEvent))
    outcome = judge_event(session, event, llm, "gpt-4.1-mini")
    assert outcome.failed is False
    assert outcome.hypotheses_updated == 1
    revision = session.scalar(
        select(HypothesisRevision).where(
            HypothesisRevision.hypothesis_id == hypothesis.id,
            HypothesisRevision.event_id == event.id,
        )
    )
    assert revision.action == "SUPPORT"
    assert revision.confidence_before == Decimal("0.50")
    assert revision.confidence_after == Decimal("0.56")
    assert revision.model_suggested_confidence == Decimal("0.99")
    assert revision.evidence_links[0].evidence_id == evidence.id


def test_evidence_from_another_event_fails_the_run(session):
    seed_hypotheses(session)
    first = _ingest(session, "https://example.test/one", "OpenAI lowered the API price.")
    second = _ingest(session, "https://example.test/two", "NVIDIA lowered the chip price.")
    extract_document(session, first, FakeLLM([_event_payload("lowered the API price")]), "gpt-4.1-mini")
    extract_document(
        session,
        second,
        FakeLLM([_event_payload("lowered the chip price")]),
        "gpt-4.1-mini",
    )
    from app.models.orm import EconomicEvent

    events = list(session.scalars(select(EconomicEvent).order_by(EconomicEvent.created_at)))
    other_evidence = session.scalar(select(Evidence).where(Evidence.event_id == events[1].id))
    hypothesis = session.scalar(select(Hypothesis).order_by(Hypothesis.created_at))
    outcome = judge_event(
        session,
        events[0],
        FakeLLM(
            [
                {
                    "updates": [
                        {
                            "hypothesis_id": str(hypothesis.id),
                            "action": "SUPPORT",
                            "reasoning": "Cites the wrong quote.",
                            "evidence_ids": [str(other_evidence.id)],
                            "suggested_confidence": 0.8,
                            "proposed_hypothesis": None,
                        }
                    ]
                }
            ]
        ),
        "gpt-4.1-mini",
    )
    assert outcome.failed is True
    assert outcome.hypotheses_updated == 0
    run = session.scalar(select(AgentRun).where(AgentRun.agent == "hypothesis"))
    assert run.status == "error"
    revision = session.scalar(
        select(HypothesisRevision).where(HypothesisRevision.event_id == events[0].id)
    )
    assert revision is None
