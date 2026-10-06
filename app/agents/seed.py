"""Four seed beliefs. Re-running the seed inserts nothing new."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.agents.confidence import CREATE_CONFIDENCE
from app.models.orm import Hypothesis, HypothesisRevision
from app.text import statement_hash

SEED_STATEMENTS = (
    "Falling inference prices are increasingly driven by provider competition rather than solely by improvements in base models.",
    "Datacenter capital expenditure is accelerating faster than inference revenue, widening the gap between spend and utilization.",
    "Open-model releases are compressing API prices for equivalent capability within one quarter.",
    "Chip supply, rather than power, remains the binding constraint on new training clusters.",
)


def seed_hypotheses(session: Session) -> int:
    created = 0
    now = datetime.now(timezone.utc)
    for index, statement in enumerate(SEED_STATEMENTS):
        hypothesis_id = uuid4()
        inserted = session.execute(
            pg_insert(Hypothesis)
            .values(
                id=hypothesis_id,
                statement=statement,
                statement_hash=statement_hash(statement),
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_hypotheses_statement_hash")
            .returning(Hypothesis.id)
        ).scalar_one_or_none()
        if inserted is None:
            continue
        session.add(
            HypothesisRevision(
                id=uuid4(),
                hypothesis_id=inserted,
                action="CREATE",
                reasoning="Seeded belief for the intelligence desk.",
                statement_before=None,
                statement_after=statement,
                confidence_before=None,
                confidence_after=CREATE_CONFIDENCE,
                model_suggested_confidence=None,
                event_id=None,
                agent_run_id=None,
                created_at=now + timedelta(microseconds=index),
            )
        )
        created += 1
    session.flush()
    return created
