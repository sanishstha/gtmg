"""Normalization, hashes, and quote grounding."""

import hashlib
import json


def normalize_ws(value: str) -> str:
    return " ".join(value.split())


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_hash(title: str, body: str) -> str:
    return sha256_text(normalize_ws(title) + "\n" + normalize_ws(body))


def statement_hash(statement: str) -> str:
    return sha256_text(normalize_ws(statement).casefold())


def event_fingerprint(event_type: str, claim: str, entities: list[str]) -> str:
    payload = json.dumps(
        {
            "event_type": event_type,
            "claim": normalize_ws(claim).casefold(),
            "entities": sorted(normalize_ws(entity).casefold() for entity in entities),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256_text(payload)


def locate_quote(body: str, quote: str) -> tuple[bool, int | None, int | None]:
    """Return whether the quote is grounded and a best-effort character span.

    Grounded means the whitespace-normalized quote is a substring of the
    whitespace-normalized body. Spans are set only when the raw quote appears
    unchanged in the raw body.
    """

    if not quote or not quote.strip():
        return False, None, None
    exact = body.find(quote)
    if exact >= 0:
        return True, exact, exact + len(quote)
    normalized_body = normalize_ws(body)
    normalized_quote = normalize_ws(quote)
    if normalized_quote and normalized_quote in normalized_body:
        return True, None, None
    return False, None, None
