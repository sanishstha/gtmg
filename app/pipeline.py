"""One function runs fetch, ingest, extraction, and belief update."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.hypothesis import event_already_judged, judge_event
from app.agents.seed import seed_hypotheses
from app.config import get_settings
from app.extraction.llm import OpenAIStructuredClient, StructuredLLM
from app.extraction.service import document_already_extracted, extract_document
from app.ingestion.rss import NormalizedDocument, fetch_feeds
from app.ingestion.service import ingest_documents
from app.models.orm import EconomicEvent, SourceDocument


@dataclass
class PipelineReport:
    fetched: int = 0
    new_documents: int = 0
    events_extracted: int = 0
    extraction_failures: int = 0
    hypotheses_created: int = 0
    hypotheses_updated: int = 0
    schema_valid_rate: float | None = None
    grounded_rate: float | None = None
    mean_latency_ms: float | None = None
    cost_usd: Decimal | None = None
    feed_errors: list[str] | None = None
    model_skipped_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "new_documents": self.new_documents,
            "events_extracted": self.events_extracted,
            "extraction_failures": self.extraction_failures,
            "hypotheses_created": self.hypotheses_created,
            "hypotheses_updated": self.hypotheses_updated,
            "schema_validity": None if self.schema_valid_rate is None else round(self.schema_valid_rate, 4),
            "grounded_events": None if self.grounded_rate is None else round(self.grounded_rate, 4),
            "mean_latency_seconds": None if self.mean_latency_ms is None else round(self.mean_latency_ms / 1000, 3),
            "cost_usd": None if self.cost_usd is None else float(self.cost_usd),
            "feed_errors": self.feed_errors or [],
            "model_skipped_reason": self.model_skipped_reason,
        }

    def format(self) -> str:
        rows = [
            ("Fetched:", self.fetched),
            ("New documents:", self.new_documents),
            ("Events extracted:", self.events_extracted),
            ("Extraction failures:", self.extraction_failures),
            ("Hypotheses created:", self.hypotheses_created),
            ("Hypotheses updated:", self.hypotheses_updated),
            ("Schema validity:", _percent(self.schema_valid_rate)),
            ("Grounded events:", _percent(self.grounded_rate)),
            ("Mean latency:", _latency(self.mean_latency_ms)),
            ("Cost:", _cost(self.cost_usd)),
        ]
        width = max(len(label) for label, _ in rows) + 2
        return "\n".join(f"{label:<{width}}{value}" for label, value in rows)


def run_pipeline(
    session: Session,
    *,
    llm: StructuredLLM | None = None,
    documents: list[NormalizedDocument] | None = None,
    fetch: bool = True,
) -> PipelineReport:
    settings = get_settings()
    report = PipelineReport()
    report.hypotheses_created += seed_hypotheses(session)
    session.commit()

    feed_errors: list[str] = []
    if documents is not None:
        incoming = documents
        report.fetched = len(documents)
    elif fetch:
        fetched = fetch_feeds(settings.feed_urls(), items_per_feed=settings.rss_items_per_feed)
        incoming = fetched.documents
        report.fetched = fetched.fetched
        feed_errors = fetched.errors
    else:
        incoming = []
    report.feed_errors = feed_errors

    if incoming:
        ingested = ingest_documents(session, incoming)
        report.new_documents = ingested.documents_created
        session.commit()

    pending_documents = [
        document
        for document in session.scalars(select(SourceDocument).order_by(SourceDocument.fetched_at))
        if not document_already_extracted(session, document.id)
    ]
    client = llm
    if client is None and (pending_documents or _unjudged_events(session)):
        if not settings.openai_api_key:
            report.model_skipped_reason = (
                "OPENAI_API_KEY is not set; extraction and hypothesis updates did not run."
            )
            return report
        client = OpenAIStructuredClient(settings.openai_api_key)
    model = settings.openai_model

    successes = 0
    grounded_events = 0
    evidence_created = 0
    latencies: list[int] = []
    costs: list[Decimal] = []
    missing_price = False

    def _record_call(latency_ms: int, cost: Decimal | None) -> None:
        nonlocal missing_price
        latencies.append(latency_ms)
        if cost is None:
            missing_price = True
        else:
            costs.append(cost)

    if client is not None:
        for document in pending_documents:
            outcome = extract_document(session, document, client, model)
            session.commit()
            if outcome.skipped:
                continue
            if outcome.failed:
                report.extraction_failures += 1
            else:
                successes += 1
                report.events_extracted += outcome.events_created
                grounded_events += outcome.grounded_events
                evidence_created += outcome.evidence_created
            _record_call(outcome.latency_ms, outcome.cost_usd)

        for event in _unjudged_events(session):
            outcome = judge_event(session, event, client, model)
            session.commit()
            if outcome.skipped:
                continue
            report.hypotheses_created += outcome.hypotheses_created
            report.hypotheses_updated += outcome.hypotheses_updated
            _record_call(outcome.latency_ms, outcome.cost_usd)

    attempts = successes + report.extraction_failures
    report.schema_valid_rate = None if attempts == 0 else successes / attempts
    report.grounded_rate = None if evidence_created == 0 else grounded_events / evidence_created
    report.mean_latency_ms = None if not latencies else sum(latencies) / len(latencies)
    report.cost_usd = None if not costs or missing_price else sum(costs, Decimal("0"))
    return report


def _unjudged_events(session: Session) -> list[EconomicEvent]:
    return [
        event
        for event in session.scalars(
            select(EconomicEvent)
            .join(SourceDocument)
            .order_by(
                SourceDocument.published_at.asc().nulls_last(),
                SourceDocument.fetched_at.asc(),
                EconomicEvent.created_at.asc(),
            )
        )
        if not event_already_judged(session, event.id)
    ]


def _percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"


def _latency(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value / 1000:.1f}s"


def _cost(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.4f}"
