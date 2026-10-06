"""Day-1 extraction scores. Recall stays unscored until 20 human labels exist."""

import json
from dataclasses import dataclass
from pathlib import Path

LABELS_REQUIRED = 20


@dataclass(frozen=True)
class ExpectedEvent:
    event_type: str
    entities: tuple[str, ...]


@dataclass(frozen=True)
class ExtractedEvent:
    event_type: str
    entities: tuple[str, ...]


@dataclass(frozen=True)
class Label:
    title: str
    body: str
    expected: tuple[ExpectedEvent, ...]
    document_id: str | None = None


@dataclass
class DetectionScore:
    labeled: int
    recall: float | None
    false_positive_rate: float | None

    def format(self) -> str:
        recall = "unscored" if self.recall is None else f"{self.recall * 100:.0f}%"
        false_positives = "unscored" if self.false_positive_rate is None else f"{self.false_positive_rate * 100:.0f}%"
        reason = ""
        if self.labeled < LABELS_REQUIRED:
            reason = f" (need {LABELS_REQUIRED} human labels, have {self.labeled})"
        return (
            f"Labeled documents:    {self.labeled}\n"
            f"Event recall:         {recall}{reason}\n"
            f"False-positive rate:  {false_positives}{reason}"
        )


def load_labels(path: Path) -> list[Label]:
    labels: list[Label] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("label_status") != "labeled":
            continue
        expected = tuple(
            ExpectedEvent(event_type=item["event_type"], entities=tuple(item.get("entities", [])))
            for item in record.get("expected_events", [])
        )
        labels.append(
            Label(
                title=record["title"],
                body=record["body"],
                expected=expected,
                document_id=record.get("document_id"),
            )
        )
    return labels


def score_detection(
    cases: list[tuple[tuple[ExpectedEvent, ...], tuple[ExtractedEvent, ...]]],
) -> DetectionScore:
    if len(cases) < LABELS_REQUIRED:
        return DetectionScore(labeled=len(cases), recall=None, false_positive_rate=None)
    expected_total = 0
    matched = 0
    extracted_total = 0
    false_positives = 0
    for expected, extracted in cases:
        remaining = list(extracted)
        expected_total += len(expected)
        extracted_total += len(extracted)
        for wanted in expected:
            index = next((i for i, got in enumerate(remaining) if _matches(wanted, got)), None)
            if index is None:
                continue
            matched += 1
            remaining.pop(index)
        false_positives += len(remaining)
    recall = 0.0 if expected_total == 0 else matched / expected_total
    false_positive_rate = 0.0 if extracted_total == 0 else false_positives / extracted_total
    return DetectionScore(labeled=len(cases), recall=recall, false_positive_rate=false_positive_rate)


def _matches(expected: ExpectedEvent, extracted: ExtractedEvent) -> bool:
    if expected.event_type != extracted.event_type:
        return False
    if not expected.entities:
        return True
    got = {entity.casefold() for entity in extracted.entities}
    return any(entity.casefold() in got for entity in expected.entities)


def cases_for_labels(session, labels: list[Label]) -> list[tuple[tuple[ExpectedEvent, ...], tuple[ExtractedEvent, ...]]]:
    from uuid import UUID

    from sqlalchemy import select

    from app.models.orm import EconomicEvent, SourceDocument
    from app.text import content_hash

    cases = []
    for label in labels:
        document = None
        if label.document_id:
            document = session.get(SourceDocument, UUID(label.document_id))
        if document is None:
            document = session.scalar(
                select(SourceDocument).where(SourceDocument.content_hash == content_hash(label.title, label.body))
            )
        extracted: tuple[ExtractedEvent, ...] = ()
        if document is not None:
            events = session.scalars(
                select(EconomicEvent).where(EconomicEvent.source_document_id == document.id)
            ).all()
            extracted = tuple(ExtractedEvent(event.event_type, tuple(event.entities)) for event in events)
        cases.append((label.expected, extracted))
    return cases


def main() -> None:
    from app.db import get_session_factory

    path = Path("evals/day1_event_extraction.jsonl")
    labels = load_labels(path)
    session = get_session_factory()()
    try:
        score = score_detection(cases_for_labels(session, labels))
    finally:
        session.close()
    print(score.format())
    print("Schema validity, grounding, latency, and cost come from scripts/run_pipeline.py.")


if __name__ == "__main__":
    main()
