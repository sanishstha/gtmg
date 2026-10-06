"""Read models for the API. Writes stay in the pipeline."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.orm import AgentRun, EconomicEvent, Hypothesis, HypothesisRevision, RevisionEvidence
from app.models.schemas import (
    AgentRunOut,
    EventOut,
    EvidenceOut,
    HypothesisOut,
    HypothesisSummary,
    RevisionOut,
)


def list_events(session: Session) -> list[EventOut]:
    rows = session.scalars(
        select(EconomicEvent)
        .options(selectinload(EconomicEvent.evidence))
        .order_by(EconomicEvent.created_at.desc())
    ).all()
    return [_event_out(row) for row in rows]


def get_event(session: Session, event_id: UUID) -> EventOut | None:
    row = session.scalar(
        select(EconomicEvent)
        .options(selectinload(EconomicEvent.evidence))
        .where(EconomicEvent.id == event_id)
    )
    if row is None:
        return None
    return _event_out(row)


def list_hypotheses(session: Session) -> list[HypothesisSummary]:
    rows = session.scalars(
        select(Hypothesis)
        .options(selectinload(Hypothesis.revisions))
        .order_by(Hypothesis.created_at)
    ).all()
    return [
        HypothesisSummary(
            id=row.id,
            statement=row.statement,
            confidence=_confidence(row),
            created_at=row.created_at,
        )
        for row in rows
    ]


def get_hypothesis(session: Session, hypothesis_id: UUID) -> HypothesisOut | None:
    row = _load_hypothesis(session, hypothesis_id)
    if row is None:
        return None
    return HypothesisOut(
        id=row.id,
        statement=row.statement,
        confidence=_confidence(row),
        created_at=row.created_at,
        revisions=[_revision_out(revision) for revision in row.revisions],
    )


def hypothesis_evidence(session: Session, hypothesis_id: UUID) -> list[EvidenceOut] | None:
    row = _load_hypothesis(session, hypothesis_id)
    if row is None:
        return None
    seen: set[UUID] = set()
    evidence: list[EvidenceOut] = []
    for revision in row.revisions:
        for link in revision.evidence_links:
            if link.evidence.id in seen:
                continue
            seen.add(link.evidence.id)
            evidence.append(EvidenceOut.model_validate(link.evidence))
    return evidence


def list_runs(session: Session) -> list[AgentRunOut]:
    rows = session.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).all()
    return [AgentRunOut.model_validate(row) for row in rows]


def _load_hypothesis(session: Session, hypothesis_id: UUID) -> Hypothesis | None:
    return session.scalar(
        select(Hypothesis)
        .options(
            selectinload(Hypothesis.revisions)
            .selectinload(HypothesisRevision.evidence_links)
            .selectinload(RevisionEvidence.evidence)
        )
        .where(Hypothesis.id == hypothesis_id)
    )


def _event_out(row: EconomicEvent) -> EventOut:
    return EventOut(
        id=row.id,
        source_document_id=row.source_document_id,
        event_type=row.event_type,
        entities=list(row.entities),
        claim=row.claim,
        occurred_at=row.occurred_at,
        magnitude=row.magnitude,
        unit=row.unit,
        confidence=row.confidence,
        created_at=row.created_at,
        evidence=[EvidenceOut.model_validate(item) for item in row.evidence],
    )


def _revision_out(revision: HypothesisRevision) -> RevisionOut:
    return RevisionOut(
        id=revision.id,
        action=revision.action,
        reasoning=revision.reasoning,
        statement_before=revision.statement_before,
        statement_after=revision.statement_after,
        confidence_before=revision.confidence_before,
        confidence_after=revision.confidence_after,
        model_suggested_confidence=revision.model_suggested_confidence,
        event_id=revision.event_id,
        agent_run_id=revision.agent_run_id,
        evidence_ids=[link.evidence_id for link in revision.evidence_links],
        created_at=revision.created_at,
    )


def _confidence(hypothesis: Hypothesis):
    if not hypothesis.revisions:
        return None
    return hypothesis.revisions[-1].confidence_after
