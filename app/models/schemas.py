"""Pydantic schemas for model output and the read API."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    MODEL_RELEASE = "MODEL_RELEASE"
    PRICE_CHANGE = "PRICE_CHANGE"
    CAPEX_ANNOUNCEMENT = "CAPEX_ANNOUNCEMENT"
    CHIP_RELEASE = "CHIP_RELEASE"
    DATACENTER_EXPANSION = "DATACENTER_EXPANSION"
    ACQUISITION = "ACQUISITION"
    FUNDING = "FUNDING"
    BENCHMARK_CHANGE = "BENCHMARK_CHANGE"
    OTHER = "OTHER"


class EconomicEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    entities: list[str]
    claim: str = Field(min_length=1)
    occurred_at: datetime | None
    magnitude: float | None
    unit: str | None
    evidence_quote: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ExtractionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EconomicEventDraft]


class HypothesisUpdateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str | None
    action: Literal["CREATE", "SUPPORT", "CONTRADICT", "MODIFY", "IGNORE"]
    reasoning: str = Field(min_length=1)
    evidence_ids: list[str]
    suggested_confidence: float | None
    proposed_hypothesis: str | None


class HypothesisBatchDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updates: list[HypothesisUpdateDraft]


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    source_document_id: UUID
    quote: str
    char_start: int | None
    char_end: int | None
    grounded: bool
    created_at: datetime


class EventOut(BaseModel):
    id: UUID
    source_document_id: UUID
    event_type: str
    entities: list[str]
    claim: str
    occurred_at: datetime | None
    magnitude: Decimal | None
    unit: str | None
    confidence: Decimal
    created_at: datetime
    evidence: list[EvidenceOut]


class RevisionOut(BaseModel):
    id: UUID
    action: str
    reasoning: str
    statement_before: str | None
    statement_after: str | None
    confidence_before: Decimal | None
    confidence_after: Decimal
    model_suggested_confidence: Decimal | None
    event_id: UUID | None
    agent_run_id: UUID | None
    evidence_ids: list[UUID]
    created_at: datetime


class HypothesisOut(BaseModel):
    id: UUID
    statement: str
    confidence: Decimal | None
    created_at: datetime
    revisions: list[RevisionOut]


class HypothesisSummary(BaseModel):
    id: UUID
    statement: str
    confidence: Decimal | None
    created_at: datetime


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent: str
    model: str
    input: dict
    output: dict | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int | None
    cost_usd: Decimal | None
    status: str
    error: str | None
    created_at: datetime


class HealthOut(BaseModel):
    status: str
