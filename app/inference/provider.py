"""One extraction call. The OpenAI SDK stays in app.extraction.llm."""

from datetime import datetime
from typing import Protocol

from app.config import compute_cost
from app.extraction.llm import StructuredLLM, complete_with_retry
from app.inference.models import InferenceResult
from app.models.schemas import ExtractionDraft

MAX_PROMPT_CHARS = 12_000

SYSTEM_PROMPT = """You extract structured economic events about AI infrastructure from one source document.
Do not summarize the document.
Return an event only when the document states it.
evidence_quote must be copied from the document, not paraphrased.
If the document states no such event, return an empty events list.
occurred_at is null when the document does not give a time.
magnitude and unit are null when the document does not quantify the event.
confidence is how sure you are that the event is stated, from 0 to 1."""


class TextDocument(Protocol):
    title: str
    body: str
    source_url: str
    published_at: datetime | None


def extraction_messages(document: TextDocument) -> list[dict[str, str]]:
    published = document.published_at.isoformat() if document.published_at else "null"
    body = document.body[:MAX_PROMPT_CHARS]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"title: {document.title}\n"
                f"source_url: {document.source_url}\n"
                f"published_at: {published}\n\n"
                f"{body}"
            ),
        },
    ]


def extract_event(document: TextDocument, model: str, llm: StructuredLLM) -> InferenceResult:
    """Run the extractor. Does not write to the database."""

    attempt = complete_with_retry(
        llm,
        messages=extraction_messages(document),
        schema=ExtractionDraft,
        model=model,
    )
    parsed = attempt.response.parsed
    draft = parsed if isinstance(parsed, ExtractionDraft) else None
    success = attempt.ok and draft is not None
    error = None
    if not success:
        error = " | ".join(attempt.errors) or "extraction failed"
    return InferenceResult(
        output=draft if success else None,
        model=model,
        input_tokens=attempt.tokens_in,
        output_tokens=attempt.tokens_out,
        latency_ms=attempt.latency_ms,
        cost_usd=compute_cost(model, attempt.tokens_in, attempt.tokens_out),
        success=success,
        error=error,
        attempts=attempt.attempts,
        raw_text=attempt.response.raw_text,
    )
