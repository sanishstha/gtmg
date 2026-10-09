"""Inference interface. Callers pass a model name and receive a measured result."""

from app.inference.models import CHEAP_MODEL, MID_MODEL, STRONG_MODEL, InferenceResult
from app.inference.provider import extract_event
from app.inference.router import choose_model, extract_routed

__all__ = [
    "CHEAP_MODEL",
    "MID_MODEL",
    "STRONG_MODEL",
    "InferenceResult",
    "choose_model",
    "extract_event",
    "extract_routed",
]
