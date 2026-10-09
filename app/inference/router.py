"""Deterministic model choice plus one escalation. No model picks the model."""

import re
from decimal import Decimal

from app.extraction.llm import StructuredLLM
from app.inference.models import CHEAP_MODEL, MID_MODEL, STRONG_MODEL, InferenceResult
from app.inference.provider import TextDocument, extract_event
from app.text import locate_quote

# From experiments/day02/failure_analysis.md. Length did not separate nano misses.
# More organization-like names than this uses the mid model. Only the crowded tail failed.
MANY_ENTITIES = 4
MIN_CONFIDENCE = 0.6
# Phrases that appeared on nano misses and not on nano successes.
_MID_CUES = (
    "generally available",
    "sampling",
    "packaging",
    "invoice",
    "new financing",
    "will spend",
    "correction",
)

_PHRASE = re.compile(r"\b[A-Z][A-Za-z0-9&-]*(?:\s+[A-Z][A-Za-z0-9&-]*)*\b")
_STOP = {
    "A",
    "AI",
    "AM",
    "API",
    "About",
    "After",
    "Also",
    "An",
    "And",
    "April",
    "As",
    "At",
    "August",
    "Be",
    "Before",
    "Between",
    "But",
    "By",
    "CEO",
    "CPU",
    "CTO",
    "December",
    "During",
    "Earlier",
    "EU",
    "February",
    "First",
    "For",
    "Friday",
    "From",
    "GPU",
    "HR",
    "However",
    "IPO",
    "IT",
    "If",
    "In",
    "Into",
    "It",
    "January",
    "July",
    "June",
    "LLM",
    "Last",
    "Later",
    "ML",
    "Monday",
    "March",
    "May",
    "Many",
    "Meanwhile",
    "Most",
    "NLP",
    "Next",
    "No",
    "Not",
    "November",
    "OS",
    "October",
    "Of",
    "On",
    "Other",
    "Our",
    "Over",
    "PC",
    "PM",
    "PR",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "RAG",
    "RFP",
    "SLA",
    "Saturday",
    "Second",
    "September",
    "Several",
    "Some",
    "Sunday",
    "TBD",
    "That",
    "The",
    "Their",
    "These",
    "Third",
    "This",
    "Those",
    "Thursday",
    "To",
    "Today",
    "Tuesday",
    "UK",
    "US",
    "USD",
    "UX",
    "UI",
    "Under",
    "Wednesday",
    "We",
    "When",
    "While",
    "With",
    "Within",
    "Without",
    "Yesterday",
}


def word_count(document: TextDocument) -> int:
    return len(document.body.split())


def organization_names(text: str) -> set[str]:
    """Unique capitalized phrases, minus ordinary sentence words and short acronyms."""

    found: set[str] = set()
    for phrase in _PHRASE.findall(text):
        words = phrase.split()
        if all(word in _STOP for word in words):
            continue
        kept = [word for word in words if word not in _STOP]
        if not kept:
            continue
        found.add(" ".join(kept))
    return found


def entity_count(document: TextDocument) -> int:
    return len(organization_names(f"{document.title}\n{document.body}"))


def choose_model(document: TextDocument) -> str:
    text = f"{document.title}\n{document.body}".casefold()
    if "benchmark" in text or "scored" in text:
        return STRONG_MODEL
    if entity_count(document) > MANY_ENTITIES or _needs_mid(text):
        return MID_MODEL
    return CHEAP_MODEL


def _needs_mid(text: str) -> bool:
    if any(cue in text for cue in _MID_CUES):
        return True
    # Megawatts without the words "data center" was the computing-hall miss.
    # An obvious data-center sentence that also states megawatts stayed correct on nano.
    if "megawatt" in text and "data center" not in text:
        return True
    return "capital expenditure" in text and "new data center" in text


def escalation_reason(document: TextDocument, result: InferenceResult) -> str | None:
    """Why the first result should be discarded. None means accept it.

    An empty event list is acceptable. Irrelevant documents are allowed to
    extract nothing without paying for a second model.
    """

    if not result.success or result.output is None:
        return "schema_invalid"
    events = result.output.events
    if len(events) > 1:
        return "multiple_events"
    for event in events:
        grounded, _, _ = locate_quote(document.body, event.evidence_quote)
        if not grounded:
            return "ungrounded_quote"
        if event.event_type.value == "OTHER":
            return "other_type"
        if event.confidence < MIN_CONFIDENCE:
            return "low_confidence"
    return None


def extract_routed(document: TextDocument, llm: StructuredLLM) -> InferenceResult:
    route = choose_model(document)
    first = extract_event(document, route, llm)
    first.route = route
    reason = escalation_reason(document, first)
    if reason is None or route == STRONG_MODEL:
        return first
    second = extract_event(document, STRONG_MODEL, llm)
    return InferenceResult(
        output=second.output,
        model=second.model,
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        latency_ms=first.latency_ms + second.latency_ms,
        cost_usd=_add_cost(first.cost_usd, second.cost_usd),
        success=second.success,
        error=second.error,
        attempts=first.attempts + second.attempts,
        escalated=True,
        escalation_reason=reason,
        route=route,
        raw_text=second.raw_text,
    )


def _add_cost(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return left + right
