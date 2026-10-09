"""Run the 30-case exam on the cheap, mid, and strong models. No database writes."""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from app.evals.day02 import format_comparison, grade_case, load_labels, summarize
from app.extraction.llm import OpenAIStructuredClient
from app.inference.models import CHEAP_MODEL, MID_MODEL, STRONG_MODEL
from app.inference.provider import extract_event
from app.inference.router import entity_count, word_count

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "experiments" / "day02" / "model_benchmark.csv"
LOG_PATH = ROOT / "experiments" / "day02" / "model_outputs.jsonl"
TABLE_PATH = ROOT / "experiments" / "day02" / "shootout.md"
COLUMNS = [
    "case_id",
    "bucket",
    "model",
    "correct",
    "schema_valid",
    "event_type_correct",
    "entity_correct",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "error",
]
MODELS = (CHEAP_MODEL, MID_MODEL, STRONG_MODEL)
DISPLAY = {CHEAP_MODEL: "Cheap", MID_MODEL: "Mid", STRONG_MODEL: "Strong"}


def main() -> None:
    labels = load_labels(ROOT / "evals" / "day02_event_extraction.jsonl")
    if len(labels) != 30:
        print(f"Expected 30 labels, found {len(labels)}.", file=sys.stderr)
        sys.exit(1)
    client = OpenAIStructuredClient()
    rows: list[dict[str, str]] = []
    logs: list[dict] = []
    grouped: dict[str, list] = defaultdict(list)

    for label in labels:
        for model in MODELS:
            result = extract_event(label, model, client)
            print(f"{label.document_id} {model} {result.latency_ms}ms", flush=True)
            if not rows and _auth_failed(result.error):
                print("First model call failed authentication. Stopped before writing results.", file=sys.stderr)
                sys.exit(1)
            grade = grade_case(label, result)
            rows.append(
                {
                    "case_id": label.document_id,
                    "bucket": label.bucket,
                    "model": model,
                    "correct": _flag(grade.correct),
                    "schema_valid": _flag(grade.schema_valid),
                    "event_type_correct": _flag(grade.event_type_correct),
                    "entity_correct": _flag(grade.entity_correct),
                    "latency_ms": str(result.latency_ms),
                    "input_tokens": str(result.input_tokens),
                    "output_tokens": str(result.output_tokens),
                    "cost_usd": "" if result.cost_usd is None else f"{result.cost_usd:.6f}",
                    "error": _public_error(result.error),
                }
            )
            events = []
            if result.output is not None:
                events = [
                    {
                        "event_type": event.event_type.value,
                        "entities": event.entities,
                        "claim": event.claim,
                        "evidence_quote": event.evidence_quote,
                        "confidence": event.confidence,
                    }
                    for event in result.output.events
                ]
            logs.append(
                {
                    "case_id": label.document_id,
                    "bucket": label.bucket,
                    "model": model,
                    "correct": grade.correct,
                    "schema_valid": grade.schema_valid,
                    "event_type_correct": grade.event_type_correct,
                    "entity_correct": grade.entity_correct,
                    "pairs_found": grade.pairs_found,
                    "emitted_event": grade.emitted_event,
                    "expected_event": label.expected_event,
                    "expected": [
                        {"event_type": item.event_type, "entities": list(item.entities)} for item in label.expected
                    ],
                    "events": events,
                    "error": _public_error(result.error),
                    "word_count": word_count(label),
                    "entity_count": entity_count(label),
                    "latency_ms": result.latency_ms,
                    "cost_usd": None if result.cost_usd is None else float(result.cost_usd),
                }
            )
            grouped[model].append((grade, result.cost_usd, result.latency_ms, label.expected_event))

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with LOG_PATH.open("w", encoding="utf-8") as handle:
        for record in logs:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summaries = {}
    for model in MODELS:
        grades, costs, latencies, flags = zip(*grouped[model])
        summaries[DISPLAY[model]] = summarize(list(grades), list(costs), list(latencies), list(flags))
    table = format_comparison(summaries)
    TABLE_PATH.write_text(
        "# Day 2 model shootout\n\n"
        "Thirty hand-labeled documents, three models, ninety calls. "
        "The exam does not write to Postgres.\n\n"
        "```\n"
        f"{table}\n"
        "```\n\n"
        "Accuracy is strict: the extracted set must match the labeled pairs with nothing left over. "
        "Recall ignores extra events. Precision asks only whether a document that produced an event "
        "was a document that had one. Cost per correct is total spend divided by strict correct cases.\n",
        encoding="utf-8",
    )
    print(table)


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _public_error(error: str | None) -> str:
    if not error:
        return ""
    if "sk-" in error:
        return "authentication failed"
    return " ".join(error.split())[:500]


def _auth_failed(error: str | None) -> bool:
    if not error:
        return False
    text = error.lower()
    return any(token in text for token in ("api key", "unauthorized", "401", "authentication", "incorrect api key"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        message = str(exc)
        if "sk-" in message:
            message = "authentication failed"
        print(f"Benchmark failed: {message}", file=sys.stderr)
        sys.exit(1)
