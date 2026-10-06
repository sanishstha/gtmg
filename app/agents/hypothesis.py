"""Decide how one event changes the belief log. Confidence is applied in code."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.agents.confidence import next_confidence
from app.config import compute_cost
from app.extraction.llm import StructuredLLM, complete_with_retry
from app.models.orm import AgentRun, EconomicEvent, Evidence, Hypothesis, HypothesisRevision, RevisionEvidence
from app.models.schemas import HypothesisBatchDraft
from app.text import statement_hash

HYPOTHESIS_AGENT = "hypothesis"
_CHANGING_ACTIONS = {"SUPPORT", "CONTRADICT", "MODIFY"}

SYSTEM_PROMPT = """You compare one extracted event with the hypotheses you are given.
Return one update for every hypothesis id in the input.
Use CREATE only for a new belief that none of the existing hypotheses cover.
CREATE requires hypothesis_id null and a proposed_hypothesis.
SUPPORT, CONTRADICT, MODIFY, and IGNORE require a hypothesis_id from the input.
MODIFY requires proposed_hypothesis, the replacement statement.
evidence_ids must be chosen only from the evidence ids in the input. Use an empty list when you cite nothing.
suggested_confidence is advisory. The system computes the stored confidence.
Do not invent evidence ids."""


class ApplyError(Exception):
    pass


@dataclass
class HypothesisOutcome:
    hypotheses_created: int
    hypotheses_updated: int
    failed: bool
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: Decimal | None
    skipped: bool = False


@dataclass
class _Prepared:
    action: str
    hypothesis_id: UUID | None
    reasoning: str
    evidence_ids: list[UUID]
    suggested_confidence: Decimal | None
    proposed_hypothesis: str | None
    synthetic: bool


def event_already_judged(session: Session, event_id: UUID) -> bool:
    existing = session.scalar(
        select(AgentRun.id).where(
            AgentRun.agent == HYPOTHESIS_AGENT,
            AgentRun.status == "success",
            AgentRun.input["event_id"].as_string() == str(event_id),
        )
    )
    return existing is not None


def judge_event(
    session: Session,
    event: EconomicEvent,
    llm: StructuredLLM,
    model: str,
) -> HypothesisOutcome:
    if event_already_judged(session, event.id):
        return HypothesisOutcome(0, 0, False, 0, 0, 0, Decimal("0"), skipped=True)

    hypotheses = list(
        session.scalars(select(Hypothesis).options(selectinload(Hypothesis.revisions)).order_by(Hypothesis.created_at))
    )
    evidence = list(session.scalars(select(Evidence).where(Evidence.event_id == event.id)))
    payload = _prompt_payload(event, hypotheses, evidence)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload)},
    ]
    attempt = complete_with_retry(llm, messages=messages, schema=HypothesisBatchDraft, model=model)
    cost = compute_cost(model, attempt.tokens_in, attempt.tokens_out)
    run_input = {"event_id": str(event.id), "source_document_id": str(event.source_document_id)}

    if not attempt.ok:
        _error_run(session, model, run_input, attempt.response.raw_text, " | ".join(attempt.errors), attempt, cost)
        return HypothesisOutcome(0, 0, True, attempt.tokens_in, attempt.tokens_out, attempt.latency_ms, cost)

    draft = attempt.response.parsed
    assert isinstance(draft, HypothesisBatchDraft)
    try:
        prepared = _prepare(draft, hypotheses, {row.id for row in evidence})
        with session.begin_nested():
            run = AgentRun(
                id=uuid4(),
                agent=HYPOTHESIS_AGENT,
                model=model,
                input=run_input,
                output=None,
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
            created, updated, applied = _apply(session, event, hypotheses, prepared, run.id)
            run.output = {
                "updates": [item.model_dump(mode="json") for item in draft.updates],
                "applied": applied,
                "attempts": attempt.attempts,
            }
            session.flush()
    except (ApplyError, IntegrityError) as exc:
        _error_run(session, model, run_input, attempt.response.raw_text, str(exc), attempt, cost)
        return HypothesisOutcome(0, 0, True, attempt.tokens_in, attempt.tokens_out, attempt.latency_ms, cost)

    return HypothesisOutcome(
        hypotheses_created=created,
        hypotheses_updated=updated,
        failed=False,
        tokens_in=attempt.tokens_in,
        tokens_out=attempt.tokens_out,
        latency_ms=attempt.latency_ms,
        cost_usd=cost,
    )


def _prompt_payload(event: EconomicEvent, hypotheses: list[Hypothesis], evidence: list[Evidence]) -> dict:
    return {
        "event": {
            "id": str(event.id),
            "event_type": event.event_type,
            "entities": event.entities,
            "claim": event.claim,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "magnitude": None if event.magnitude is None else str(event.magnitude),
            "unit": event.unit,
        },
        "evidence": [
            {"id": str(row.id), "quote": row.quote, "grounded": row.grounded}
            for row in evidence
        ],
        "hypotheses": [
            {
                "id": str(hypothesis.id),
                "statement": hypothesis.statement,
                "confidence": str(_current_confidence(hypothesis)),
            }
            for hypothesis in hypotheses
        ],
    }


def _prepare(draft: HypothesisBatchDraft, hypotheses: list[Hypothesis], evidence_ids: set[UUID]) -> list[_Prepared]:
    known = {hypothesis.id: hypothesis for hypothesis in hypotheses}
    seen: set[UUID] = set()
    prepared: list[_Prepared] = []
    for update in draft.updates:
        cited = _evidence_ids(update.evidence_ids, evidence_ids)
        suggested = None if update.suggested_confidence is None else Decimal(str(update.suggested_confidence))
        if update.action == "CREATE":
            if update.hypothesis_id:
                raise ApplyError("CREATE updates cannot include a hypothesis_id")
            proposed = (update.proposed_hypothesis or "").strip()
            if not proposed:
                raise ApplyError("CREATE requires proposed_hypothesis")
            prepared.append(
                _Prepared("CREATE", None, update.reasoning, cited, suggested, proposed, False)
            )
            continue
        if not update.hypothesis_id:
            raise ApplyError(f"{update.action} requires a hypothesis_id")
        try:
            hypothesis_id = UUID(update.hypothesis_id)
        except ValueError as exc:
            raise ApplyError(f"Invalid hypothesis id: {update.hypothesis_id}") from exc
        if hypothesis_id not in known:
            raise ApplyError(f"Unknown hypothesis id: {hypothesis_id}")
        if hypothesis_id in seen:
            raise ApplyError(f"Duplicate update for hypothesis {hypothesis_id}")
        seen.add(hypothesis_id)
        proposed = (update.proposed_hypothesis or "").strip() or None
        if update.action == "MODIFY" and not proposed:
            raise ApplyError("MODIFY requires proposed_hypothesis")
        prepared.append(
            _Prepared(update.action, hypothesis_id, update.reasoning, cited, suggested, proposed, False)
        )
    for hypothesis in hypotheses:
        if hypothesis.id in seen:
            continue
        prepared.append(
            _Prepared(
                "IGNORE",
                hypothesis.id,
                "Model returned no update for this hypothesis.",
                [],
                None,
                None,
                True,
            )
        )
    return prepared


def _evidence_ids(raw_ids: list[str], allowed: set[UUID]) -> list[UUID]:
    parsed: list[UUID] = []
    for raw in raw_ids:
        try:
            evidence_id = UUID(raw)
        except ValueError as exc:
            raise ApplyError(f"Invalid evidence id: {raw}") from exc
        if evidence_id not in allowed:
            raise ApplyError(f"Evidence id {evidence_id} does not belong to this event")
        parsed.append(evidence_id)
    return parsed


def _apply(
    session: Session,
    event: EconomicEvent,
    hypotheses: list[Hypothesis],
    prepared: list[_Prepared],
    agent_run_id: UUID,
) -> tuple[int, int, list[dict]]:
    by_id = {hypothesis.id: hypothesis for hypothesis in hypotheses}
    created = 0
    updated = 0
    applied: list[dict] = []
    stamp = datetime.now(timezone.utc)
    for index, item in enumerate(prepared):
        created_at = stamp + timedelta(microseconds=index)
        if item.action == "CREATE":
            assert item.proposed_hypothesis is not None
            digest = statement_hash(item.proposed_hypothesis)
            if session.scalar(select(Hypothesis.id).where(Hypothesis.statement_hash == digest)):
                applied.append({"action": "CREATE", "skipped": "duplicate statement"})
                continue
            hypothesis = Hypothesis(
                id=uuid4(),
                statement=item.proposed_hypothesis,
                statement_hash=digest,
                created_at=created_at,
            )
            session.add(hypothesis)
            session.flush()
            revision = _revision(
                hypothesis_id=hypothesis.id,
                action="CREATE",
                reasoning=item.reasoning,
                statement_before=None,
                statement_after=item.proposed_hypothesis,
                confidence_before=None,
                confidence_after=next_confidence(None, "CREATE"),
                model_suggested_confidence=item.suggested_confidence,
                event_id=event.id,
                agent_run_id=agent_run_id,
                created_at=created_at,
            )
            session.add(revision)
            session.flush()
            _link(session, revision.id, item.evidence_ids)
            created += 1
            applied.append({"action": "CREATE", "hypothesis_id": str(hypothesis.id)})
            continue

        assert item.hypothesis_id is not None
        hypothesis = by_id[item.hypothesis_id]
        before = _current_confidence(hypothesis)
        after = next_confidence(before, item.action)
        statement_before = hypothesis.statement
        statement_after = hypothesis.statement
        if item.action == "MODIFY":
            assert item.proposed_hypothesis is not None
            digest = statement_hash(item.proposed_hypothesis)
            conflict = session.scalar(
                select(Hypothesis.id).where(
                    Hypothesis.statement_hash == digest,
                    Hypothesis.id != hypothesis.id,
                )
            )
            if conflict is not None:
                raise ApplyError("MODIFY collided with an existing hypothesis statement")
            hypothesis.statement = item.proposed_hypothesis
            hypothesis.statement_hash = digest
            statement_after = item.proposed_hypothesis
        revision = _revision(
            hypothesis_id=hypothesis.id,
            action=item.action,
            reasoning=item.reasoning,
            statement_before=statement_before,
            statement_after=statement_after,
            confidence_before=before,
            confidence_after=after,
            model_suggested_confidence=item.suggested_confidence,
            event_id=event.id,
            agent_run_id=agent_run_id,
            created_at=created_at,
        )
        session.add(revision)
        session.flush()
        _link(session, revision.id, item.evidence_ids)
        hypothesis.revisions.append(revision)
        if item.action in _CHANGING_ACTIONS:
            updated += 1
        applied.append({"action": item.action, "hypothesis_id": str(hypothesis.id), "synthetic": item.synthetic})
    return created, updated, applied


def _revision(**kwargs) -> HypothesisRevision:
    return HypothesisRevision(id=uuid4(), **kwargs)


def _link(session: Session, revision_id: UUID, evidence_ids: list[UUID]) -> None:
    for evidence_id in evidence_ids:
        session.add(RevisionEvidence(revision_id=revision_id, evidence_id=evidence_id))


def _current_confidence(hypothesis: Hypothesis) -> Decimal:
    if not hypothesis.revisions:
        return next_confidence(None, "CREATE")
    return max(hypothesis.revisions, key=lambda revision: revision.created_at).confidence_after


def _error_run(session, model, run_input, raw_text, error, attempt, cost) -> None:
    session.add(
        AgentRun(
            id=uuid4(),
            agent=HYPOTHESIS_AGENT,
            model=model,
            input=run_input,
            output={"raw_text": raw_text, "attempts": attempt.attempts},
            tokens_in=attempt.tokens_in,
            tokens_out=attempt.tokens_out,
            latency_ms=attempt.latency_ms,
            cost_usd=cost,
            status="error",
            error=error,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.flush()
