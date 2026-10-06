"""Extract events from one document and keep both successes and failures."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import compute_cost
from app.extraction.llm import AttemptResult, StructuredLLM, complete_with_retry
from app.models.orm import AgentRun, EconomicEvent, Evidence, ExtractionFailure, SourceDocument
from app.models.schemas import ExtractionDraft
from app.text import event_fingerprint, locate_quote

MAX_PROMPT_CHARS = 12_000
EXTRACTOR_AGENT = "extractor"

SYSTEM_PROMPT = """You extract structured economic events about AI infrastructure from one source document.
Do not summarize the document.
Return an event only when the document states it.
evidence_quote must be copied from the document, not paraphrased.
If the document states no such event, return an empty events list.
occurred_at is null when the document does not give a time.
magnitude and unit are null when the document does not quantify the event.
confidence is how sure you are that the event is stated, from 0 to 1."""


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

    body = document.body[:MAX_PROMPT_CHARS]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"title: {document.title}\n"
                f"source_url: {document.source_url}\n"
                f"published_at: {document.published_at.isoformat() if document.published_at else 'null'}\n\n"
                f"{body}"
            ),
        },
    ]
    attempt = complete_with_retry(llm, messages=messages, schema=ExtractionDraft, model=model)
    cost = compute_cost(model, attempt.tokens_in, attempt.tokens_out)
    if not attempt.ok:
        _persist_failure(session, document, attempt, model, cost)
        return ExtractionOutcome(
            events_created=0,
            failed=True,
            grounded_events=0,
            evidence_created=0,
            tokens_in=attempt.tokens_in,
            tokens_out=attempt.tokens_out,
            latency_ms=attempt.latency_ms,
            cost_usd=cost,
        )

    draft = attempt.response.parsed
    assert isinstance(draft, ExtractionDraft)
    created, grounded = _persist_events(session, document, draft, attempt, model, cost)
    return ExtractionOutcome(
        events_created=created,
        failed=False,
        grounded_events=grounded,
        evidence_created=created,
        tokens_in=attempt.tokens_in,
        tokens_out=attempt.tokens_out,
        latency_ms=attempt.latency_ms,
        cost_usd=cost,
    )


def _persist_failure(
    session: Session,
    document: SourceDocument,
    attempt: AttemptResult,
    model: str,
    cost: Decimal | None,
) -> None:
    run = AgentRun(
        id=uuid4(),
        agent=EXTRACTOR_AGENT,
        model=model,
        input={"source_document_id": str(document.id), "title": document.title},
        output={"raw_text": attempt.response.raw_text, "attempts": attempt.attempts},
        tokens_in=attempt.tokens_in,
        tokens_out=attempt.tokens_out,
        latency_ms=attempt.latency_ms,
        cost_usd=cost,
        status="error",
        error=" | ".join(attempt.errors) or "extraction failed",
        created_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    session.add(
        ExtractionFailure(
            id=uuid4(),
            source_document_id=document.id,
            raw_output=attempt.response.raw_text,
            error=run.error or "extraction failed",
            agent_run_id=run.id,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.flush()


def _persist_events(
    session: Session,
    document: SourceDocument,
    draft: ExtractionDraft,
    attempt: AttemptResult,
    model: str,
    cost: Decimal | None,
) -> tuple[int, int]:
    run = AgentRun(
        id=uuid4(),
        agent=EXTRACTOR_AGENT,
        model=model,
        input={"source_document_id": str(document.id), "title": document.title},
        output={"events": [event.model_dump(mode="json") for event in draft.events], "attempts": attempt.attempts},
        tokens_in=attempt.tokens_in,
        tokens_out=attempt.tokens_out,
        latency_ms=attempt.latency_ms,
        cost_usd=cost,
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
