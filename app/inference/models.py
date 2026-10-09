"""Tiers and the result every model call returns."""

from dataclasses import dataclass
from decimal import Decimal

from app.models.schemas import ExtractionDraft

CHEAP_MODEL = "gpt-4.1-nano"
MID_MODEL = "gpt-4.1-mini"
STRONG_MODEL = "gpt-4.1"


@dataclass
class InferenceResult:
    output: ExtractionDraft | None
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: Decimal | None
    success: bool
    error: str | None
    attempts: int = 1
    escalated: bool = False
    escalation_reason: str | None = None
    route: str | None = None
    raw_text: str = ""
