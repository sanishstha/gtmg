"""Read API. Swagger is the UI."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.extraction.llm import OpenAIStructuredClient, StructuredLLM
from app.models.schemas import AgentRunOut, EventOut, EvidenceOut, HealthOut, HypothesisOut, HypothesisSummary
from app.pipeline import run_pipeline
from app.storage.queries import get_event, get_hypothesis, hypothesis_evidence, list_events, list_hypotheses, list_runs

router = APIRouter()


def get_llm() -> StructuredLLM | None:
    if not get_settings().openai_api_key:
        return None
    return OpenAIStructuredClient()


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/events", response_model=list[EventOut])
def events(session: Session = Depends(get_session)) -> list[EventOut]:
    return list_events(session)


@router.get("/events/{event_id}", response_model=EventOut)
def event_detail(event_id: UUID, session: Session = Depends(get_session)) -> EventOut:
    row = get_event(session, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return row


@router.get("/hypotheses", response_model=list[HypothesisSummary])
def hypotheses(session: Session = Depends(get_session)) -> list[HypothesisSummary]:
    return list_hypotheses(session)


@router.get("/hypotheses/{hypothesis_id}", response_model=HypothesisOut)
def hypothesis_detail(hypothesis_id: UUID, session: Session = Depends(get_session)) -> HypothesisOut:
    row = get_hypothesis(session, hypothesis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found")
    return row


@router.get("/hypotheses/{hypothesis_id}/evidence", response_model=list[EvidenceOut])
def hypothesis_evidence_detail(hypothesis_id: UUID, session: Session = Depends(get_session)) -> list[EvidenceOut]:
    rows = hypothesis_evidence(session, hypothesis_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found")
    return rows


@router.get("/runs", response_model=list[AgentRunOut])
def runs(session: Session = Depends(get_session)) -> list[AgentRunOut]:
    return list_runs(session)


@router.post("/pipeline")
def pipeline(
    fetch: bool = True,
    session: Session = Depends(get_session),
    llm: StructuredLLM | None = Depends(get_llm),
) -> dict:
    try:
        return run_pipeline(session, llm=llm, fetch=fetch).as_dict()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
