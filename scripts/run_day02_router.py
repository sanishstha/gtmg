"""Score the router on the same 30 cases. Strong-only numbers come from the shootout CSV."""

import csv
import sys
from decimal import Decimal
from pathlib import Path

from app.evals.day02 import grade_case, load_labels, summarize
from app.extraction.llm import OpenAIStructuredClient
from app.inference.models import STRONG_MODEL
from app.inference.router import extract_routed

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "experiments" / "day02" / "model_benchmark.csv"
RUNS_PATH = ROOT / "experiments" / "day02" / "router_runs.csv"
REPORT_PATH = ROOT / "experiments" / "day02" / "router_results.md"
COLUMNS = [
    "case_id",
    "bucket",
    "route",
    "model",
    "escalated",
    "escalation_reason",
    "correct",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "error",
]
VOLUMES = (1_000, 100_000, 1_000_000)


def main() -> None:
    labels = load_labels(ROOT / "evals" / "day02_event_extraction.jsonl")
    strong = _strong_rows(CSV_PATH)
    if len(strong) != len(labels):
        print("Strong-only rows do not match the label file.", file=sys.stderr)
        sys.exit(1)
    client = OpenAIStructuredClient()
    rows: list[dict[str, str]] = []
    grades = []
    costs = []
    latencies = []
    flags = []
    for label in labels:
        result = extract_routed(label, client)
        print(
            f"{label.document_id} route={result.route} model={result.model} escalated={result.escalated}",
            flush=True,
        )
        if not rows and _auth_failed(result.error):
            print("First model call failed authentication. Stopped before writing results.", file=sys.stderr)
            sys.exit(1)
        grade = grade_case(label, result)
        grades.append(grade)
        costs.append(result.cost_usd)
        latencies.append(result.latency_ms)
        flags.append(label.expected_event)
        rows.append(
            {
                "case_id": label.document_id,
                "bucket": label.bucket,
                "route": result.route or "",
                "model": result.model,
                "escalated": "true" if result.escalated else "false",
                "escalation_reason": result.escalation_reason or "",
                "correct": "true" if grade.correct else "false",
                "latency_ms": str(result.latency_ms),
                "input_tokens": str(result.input_tokens),
                "output_tokens": str(result.output_tokens),
                "cost_usd": "" if result.cost_usd is None else f"{result.cost_usd:.6f}",
                "error": _public_error(result.error),
            }
        )

    with RUNS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    router = summarize(grades, costs, latencies, flags)
    strong_summary = summarize(
        [_GradeView(row["correct"] == "true") for row in strong],
        [_money(row["cost_usd"]) for row in strong],
        [int(row["latency_ms"]) for row in strong],
        [label.expected_event for label in labels],
    )
    escalated = sum(1 for row in rows if row["escalated"] == "true")
    REPORT_PATH.write_text(_report(router, strong_summary, escalated, len(labels)), encoding="utf-8")
    print(REPORT_PATH.read_text(encoding="utf-8"))


class _GradeView:
    """Strong-only accuracy uses the shootout CSV, which stores the strict correct bit."""

    def __init__(self, correct: bool) -> None:
        self.correct = correct
        self.schema_valid = True
        self.pairs_found = correct
        self.emitted_event = False


def _strong_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row["model"] == STRONG_MODEL]


def _report(router, strong, escalated: int, cases: int) -> str:
    rate = escalated / cases if cases else 0
    savings = None
    if strong.total_cost_usd is not None and router.total_cost_usd is not None:
        savings = strong.total_cost_usd - router.total_cost_usd
    strong_each = _per_doc(strong.total_cost_usd, cases)
    router_each = _per_doc(router.total_cost_usd, cases)
    lines = [
        "# Router versus strong-only",
        "",
        "Baseline A is the `gpt-4.1` rows already stored in `model_benchmark.csv`. "
        "System B is `extract_routed` on the same 30 documents. Escalation cost is included.",
        "",
        f"- Strong-only accuracy: {_pct(strong.accuracy)}",
        f"- Strong-only cost: {_usd(strong.total_cost_usd)}",
        f"- Strong-only mean latency: {strong.mean_latency_ms:.0f} ms",
        f"- Router accuracy: {_pct(router.accuracy)}",
        f"- Router cost: {_usd(router.total_cost_usd)}",
        f"- Router mean latency: {router.mean_latency_ms:.0f} ms",
        f"- Escalation rate: {_pct(rate)} ({escalated} of {cases})",
        f"- Savings versus strong-only: {_usd(savings)}",
        "",
        "Measured cost per document, scaled. These are the exam's average dollars, not the rate card.",
        "",
        "| Documents | Strong-only | Router |",
        "|---:|---:|---:|",
    ]
    for volume in VOLUMES:
        lines.append(f"| {volume:,} | {_usd(_scale(strong_each, volume))} | {_usd(_scale(router_each, volume))} |")
    lines.extend(
        [
            "",
            "## Where the money matters",
            "",
            "A desk that ingests a few RSS feeds a day does not feel a difference of a few cents. "
            "The same gap, multiplied by a continuous multi-source ingest, becomes a standing cost. "
            "The expensive model is reserved for benchmark wording, because that was the one case "
            "the mid model mistyped. Subtle wording, a crowded list of names, a buried financing line, "
            "and a document that states both capex and a data center go to the mid model. "
            "A second strong call is paid only when the first result is invalid, ungrounded, "
            "multi-event, typed OTHER, or below 0.6 confidence. Short single-claim notes stay cheap.",
            "",
        ]
    )
    return "\n".join(lines)


def _money(value: str) -> Decimal | None:
    if not value:
        return None
    return Decimal(value)


def _per_doc(total: Decimal | None, cases: int) -> Decimal | None:
    if total is None or cases == 0:
        return None
    return total / Decimal(cases)


def _scale(each: Decimal | None, volume: int) -> Decimal | None:
    if each is None:
        return None
    return each * Decimal(volume)


def _usd(value: Decimal | None) -> str:
    if value is None:
        return "undefined"
    return f"${value:.6f}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


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
        print(f"Router benchmark failed: {message}", file=sys.stderr)
        sys.exit(1)
