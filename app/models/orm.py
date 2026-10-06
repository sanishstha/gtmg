"""SQLAlchemy models. Confidence lives on revisions, not on hypotheses."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_source_documents_content_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    events: Mapped[list["EconomicEvent"]] = relationship(back_populates="document")


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("status IN ('success', 'error')", name="ck_agent_runs_status"),
        Index("ix_agent_runs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSONB)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class EconomicEvent(Base):
    __tablename__ = "economic_events"
    __table_args__ = (
        UniqueConstraint(
            "source_document_id",
            "event_fingerprint",
            name="uq_economic_events_document_fingerprint",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_economic_events_confidence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_documents.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    entities: Mapped[list] = mapped_column(JSONB, nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    magnitude: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    unit: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    event_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    document: Mapped[SourceDocument] = relationship(back_populates="events")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="event")


class ExtractionFailure(Base):
    __tablename__ = "extraction_failures"
    __table_args__ = (
        Index("ix_extraction_failures_source_document_id", "source_document_id"),
        Index("ix_extraction_failures_agent_run_id", "agent_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_documents.id"), nullable=False
    )
    raw_output: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("agent_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_event_id", "event_id"),
        Index("ix_evidence_source_document_id", "source_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("economic_events.id"), nullable=False)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_documents.id"), nullable=False
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    grounded: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    event: Mapped[EconomicEvent] = relationship(back_populates="evidence")


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (UniqueConstraint("statement_hash", name="uq_hypotheses_statement_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    statement_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    revisions: Mapped[list["HypothesisRevision"]] = relationship(
        back_populates="hypothesis",
        order_by="HypothesisRevision.created_at",
    )


class HypothesisRevision(Base):
    __tablename__ = "hypothesis_revisions"
    __table_args__ = (
        CheckConstraint(
            "action IN ('CREATE', 'SUPPORT', 'CONTRADICT', 'MODIFY', 'IGNORE')",
            name="ck_hypothesis_revisions_action",
        ),
        CheckConstraint(
            "confidence_after >= 0.05 AND confidence_after <= 0.95",
            name="ck_hypothesis_revisions_confidence",
        ),
        Index(
            "uq_hypothesis_revisions_hypothesis_event",
            "hypothesis_id",
            "event_id",
            unique=True,
            postgresql_where=text("event_id IS NOT NULL"),
        ),
        Index("ix_hypothesis_revisions_hypothesis_id", "hypothesis_id"),
        Index("ix_hypothesis_revisions_event_id", "event_id"),
        Index("ix_hypothesis_revisions_agent_run_id", "agent_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("hypotheses.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    statement_before: Mapped[str | None] = mapped_column(Text)
    statement_after: Mapped[str | None] = mapped_column(Text)
    confidence_before: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    confidence_after: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    model_suggested_confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("economic_events.id"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("agent_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    hypothesis: Mapped[Hypothesis] = relationship(back_populates="revisions")
    evidence_links: Mapped[list["RevisionEvidence"]] = relationship(back_populates="revision")


class RevisionEvidence(Base):
    __tablename__ = "revision_evidence"
    __table_args__ = (Index("ix_revision_evidence_evidence_id", "evidence_id"),)

    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("hypothesis_revisions.id"), primary_key=True
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("evidence.id"), primary_key=True)

    revision: Mapped[HypothesisRevision] = relationship(back_populates="evidence_links")
    evidence: Mapped[Evidence] = relationship()
