"""Day 2 extraction grades. Match rules are fixed before the paid runs."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.evals.score import ExpectedEvent, ExtractedEvent, _matches
from app.inference.models import InferenceResult
from app.models.schemas import ExtractionDraft

LABELS_PATH = Path("evals/day02_event_extraction.jsonl")


@dataclass(frozen=True)
class Day2Label:
    document_id: str
    bucket: str
    title: str
    body: str
    expected_event: bool
    expected: tuple[ExpectedEvent, ...]
    source_url: str
    published_at: None = None


@dataclass(frozen=True)
class Grade:
    correct: bool
    schema_valid: bool
    event_type_correct: bool
    entity_correct: bool
    pairs_found: bool
    emitted_event: bool


@dataclass(frozen=True)
class Summary:
    cases: int
    correct: int
    accuracy: float
    schema_validity: float
    recall: float | None
    precision: float | None
    mean_latency_ms: float
    mean_cost_usd: Decimal | None
    total_cost_usd: Decimal | None
    cost_per_correct: Decimal | None


def load_labels(path: Path = LABELS_PATH) -> list[Day2Label]:
    labels: list[Day2Label] = []
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
        document_id = str(record["document_id"])
        labels.append(
            Day2Label(
                document_id=document_id,
                bucket=record["bucket"],
                title=record["title"],
                body=record["body"],
                expected_event=bool(record["expected_event"]),
                expected=expected,
                source_url=record.get("source_url") or f"https://eval.local/{document_id}",
            )
        )
    return labels


def grade_case(label: Day2Label, result: InferenceResult) -> Grade:
    schema_valid = result.success and isinstance(result.output, ExtractionDraft)
    if not schema_valid or result.output is None:
        return Grade(False, False, False, False, False, False)

    extracted = tuple(
        ExtractedEvent(event.event_type.value, tuple(event.entities)) for event in result.output.events
    )
    emitted = len(extracted) > 0
    if not label.expected_event:
        quiet = not emitted
        return Grade(quiet, True, quiet, quiet, False, emitted)

    type_found = _all_types_found(label.expected, extracted)
    pairs_found = _all_pairs_found(label.expected, extracted)
    extras = _extras(label.expected, extracted)
    correct = pairs_found and extras == 0 and len(extracted) == len(label.expected)
    return Grade(correct, True, type_found, pairs_found, pairs_found, emitted)


def summarize(grades: list[Grade], costs: list[Decimal | None], latencies: list[int], expected_flags: list[bool]) -> Summary:
    cases = len(grades)
    if cases == 0:
        return Summary(0, 0, 0.0, 0.0, None, None, 0.0, None, None, None)
    correct = sum(1 for grade in grades if grade.correct)
    valid = sum(1 for grade in grades if grade.schema_valid)
    positive = [index for index, flag in enumerate(expected_flags) if flag]
    recall = None
    if positive:
        found = sum(1 for index in positive if grades[index].pairs_found)
        recall = found / len(positive)
    emitted = [index for index, grade in enumerate(grades) if grade.emitted_event]
    precision = None
    if emitted:
        hits = sum(1 for index in emitted if expected_flags[index])
        precision = hits / len(emitted)
    known_costs = [cost for cost in costs if cost is not None]
    total = sum(known_costs, Decimal("0")) if known_costs else None
    mean_cost = (total / Decimal(len(known_costs))) if known_costs else None
    per_correct = None
    if correct and total is not None:
        per_correct = total / Decimal(correct)
    mean_latency = sum(latencies) / cases
    return Summary(
        cases=cases,
        correct=correct,
        accuracy=correct / cases,
        schema_validity=valid / cases,
        recall=recall,
        precision=precision,
        mean_latency_ms=mean_latency,
        mean_cost_usd=mean_cost,
        total_cost_usd=total,
        cost_per_correct=per_correct,
    )


def format_comparison(by_model: dict[str, Summary]) -> str:
    headers = ["Metric", *by_model.keys()]
    rows = [
        ("Accuracy", [_percent(item.accuracy) for item in by_model.values()]),
        ("Schema validity", [_percent(item.schema_validity) for item in by_model.values()]),
        ("Recall", [_optional_percent(item.recall) for item in by_model.values()]),
        ("Precision", [_optional_percent(item.precision) for item in by_model.values()]),
        ("Avg latency", [_latency(item.mean_latency_ms) for item in by_model.values()]),
        ("Cost/run", [_money(item.mean_cost_usd) for item in by_model.values()]),
        ("Cost/correct", [_money(item.cost_per_correct) for item in by_model.values()]),
    ]
    widths = [len(headers[0])]
    for index, header in enumerate(headers):
        if index == 0:
            continue
        widths.append(max(len(header), *(len(row[1][index - 1]) for row in rows)))
    widths[0] = max(len(headers[0]), *(len(label) for label, _ in rows))
    lines = [_pad(headers[0], widths[0]) + "".join(_pad(header, width) for header, width in zip(headers[1:], widths[1:]))]
    for label, values in rows:
        lines.append(_pad(label, widths[0]) + "".join(_pad(value, width) for value, width in zip(values, widths[1:])))
    return "\n".join(lines)


def _all_types_found(expected: tuple[ExpectedEvent, ...], extracted: tuple[ExtractedEvent, ...]) -> bool:
    remaining = list(extracted)
    for wanted in expected:
        index = next((i for i, got in enumerate(remaining) if got.event_type == wanted.event_type), None)
        if index is None:
            return False
        remaining.pop(index)
    return True


def _all_pairs_found(expected: tuple[ExpectedEvent, ...], extracted: tuple[ExtractedEvent, ...]) -> bool:
    remaining = list(extracted)
    for wanted in expected:
        index = next((i for i, got in enumerate(remaining) if _matches(wanted, got)), None)
        if index is None:
            return False
        remaining.pop(index)
    return True


def _extras(expected: tuple[ExpectedEvent, ...], extracted: tuple[ExtractedEvent, ...]) -> int:
    remaining = list(extracted)
    for wanted in expected:
        index = next((i for i, got in enumerate(remaining) if _matches(wanted, got)), None)
        if index is None:
            continue
        remaining.pop(index)
    return len(remaining)


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _optional_percent(value: float | None) -> str:
    return "undefined" if value is None else _percent(value)


def _latency(value: float) -> str:
    return f"{value:.0f} ms"


def _money(value: Decimal | None) -> str:
    if value is None:
        return "undefined"
    return f"${value:.6f}"


def _pad(value: str, width: int) -> str:
    return value.ljust(width + 2)
