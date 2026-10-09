"""Extract events from one document and keep both successes and failures."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.extraction.llm import StructuredLLM
from app.inference.models import InferenceResult
from app.inference.provider import extract_event
from app.models.orm import AgentRun, EconomicEvent, Evidence, ExtractionFailure, SourceDocument
from app.models.schemas import ExtractionDraft
from app.text import event_fingerprint, locate_quote

EXTRACTOR_AGENT = "extractor"


@dataclass
class ExtractionOutcome:
    events_created: int
    failed: bool
    grounded_events: int
    evidence_created: int
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: Decimal | None
    skipped: bool = False


def document_already_extracted(session: Session, document_id) -> bool:
    existing = session.scalar(
        select(AgentRun.id).where(
            AgentRun.agent == EXTRACTOR_AGENT,
            AgentRun.status == "success",
            AgentRun.input["source_document_id"].as_string() == str(document_id),
        )
    )
    return existing is not None


def extract_document(
    session: Session,
    document: SourceDocument,
    llm: StructuredLLM,
    model: str,
) -> ExtractionOutcome:
    if document_already_extracted(session, document.id):
        return ExtractionOutcome(0, False, 0, 0, 0, 0, 0, Decimal("0"), skipped=True)

    result = extract_event(document, model, llm)
    if not result.success or result.output is None:
        _persist_failure(session, document, result)
        return ExtractionOutcome(
            events_created=0,
            failed=True,
            grounded_events=0,
            evidence_created=0,
            tokens_in=result.input_tokens,
            tokens_out=result.output_tokens,
            latency_ms=result.latency_ms,
            cost_usd=result.cost_usd,
        )

    created, grounded = _persist_events(session, document, result)
    return ExtractionOutcome(
        events_created=created,
        failed=False,
        grounded_events=grounded,
        evidence_created=created,
        tokens_in=result.input_tokens,
        tokens_out=result.output_tokens,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
    )


def _persist_failure(session: Session, document: SourceDocument, result: InferenceResult) -> None:
    run = AgentRun(
        id=uuid4(),
        agent=EXTRACTOR_AGENT,
        model=result.model,
        input={"source_document_id": str(document.id), "title": document.title},
        output={"raw_text": result.raw_text, "attempts": result.attempts},
        tokens_in=result.input_tokens,
        tokens_out=result.output_tokens,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        status="error",
        error=result.error or "extraction failed",
        created_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    session.add(
        ExtractionFailure(
            id=uuid4(),
            source_document_id=document.id,
            raw_output=result.raw_text,
            error=run.error or "extraction failed",
            agent_run_id=run.id,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.flush()


def _persist_events(session: Session, document: SourceDocument, result: InferenceResult) -> tuple[int, int]:
    draft = result.output
    assert isinstance(draft, ExtractionDraft)
    run = AgentRun(
        id=uuid4(),
        agent=EXTRACTOR_AGENT,
        model=result.model,
        input={"source_document_id": str(document.id), "title": document.title},
        output={"events": [event.model_dump(mode="json") for event in draft.events], "attempts": result.attempts},
        tokens_in=result.input_tokens,
        tokens_out=result.output_tokens,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        status="success",
        error=None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()

    created = 0
    grounded_events = 0
    for event in draft.events:
        fingerprint = event_fingerprint(event.event_type.value, event.claim, event.entities)
        event_id = uuid4()
        inserted = session.execute(
            pg_insert(EconomicEvent)
            .values(
                id=event_id,
                source_document_id=document.id,
                event_type=event.event_type.value,
                entities=event.entities,
                claim=event.claim,
                occurred_at=event.occurred_at,
                magnitude=None if event.magnitude is None else Decimal(str(event.magnitude)),
                unit=event.unit,
                confidence=Decimal(str(event.confidence)).quantize(Decimal("0.0001")),
                event_fingerprint=fingerprint,
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(constraint="uq_economic_events_document_fingerprint")
            .returning(EconomicEvent.id)
        ).scalar_one_or_none()
        if inserted is None:
            continue
        grounded, start, end = locate_quote(document.body, event.evidence_quote)
        session.add(
            Evidence(
                id=uuid4(),
                event_id=inserted,
                source_document_id=document.id,
                quote=event.evidence_quote,
                char_start=start,
                char_end=end,
                grounded=grounded,
                created_at=datetime.now(timezone.utc),
            )
        )
        created += 1
        if grounded:
            grounded_events += 1
    session.flush()
    return created, grounded_events
