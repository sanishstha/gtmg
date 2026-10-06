"""Persist source documents. The content hash is the idempotency key."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.ingestion.rss import NormalizedDocument
from app.models.orm import SourceDocument
from app.text import content_hash


@dataclass(frozen=True)
class IngestResult:
    documents_created: int
    duplicates_skipped: int


def ingest_documents(session: Session, documents: list[NormalizedDocument]) -> IngestResult:
    created = 0
    skipped = 0
    for document in documents:
        digest = content_hash(document.title, document.body)
        statement = (
            pg_insert(SourceDocument)
            .values(
                id=uuid4(),
                source_type=document.source_type,
                source_url=document.source_url,
                title=document.title,
                body=document.body,
                published_at=document.published_at,
                fetched_at=document.fetched_at,
                content_hash=digest,
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(constraint="uq_source_documents_content_hash")
            .returning(SourceDocument.id)
        )
        inserted = session.execute(statement).scalar_one_or_none()
        if inserted is None:
            skipped += 1
        else:
            created += 1
    session.flush()
    return IngestResult(documents_created=created, duplicates_skipped=skipped)
