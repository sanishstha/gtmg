from decimal import Decimal

from app.agents.confidence import next_confidence
from app.config import compute_cost
from app.text import locate_quote


def test_support_and_contradict_ignore_the_shape_of_a_suggested_float():
    assert next_confidence(Decimal("0.50"), "SUPPORT") == Decimal("0.56")
    assert next_confidence(Decimal("0.50"), "CONTRADICT") == Decimal("0.42")
    assert next_confidence(Decimal("0.94"), "SUPPORT") == Decimal("0.95")
    assert next_confidence(Decimal("0.10"), "CONTRADICT") == Decimal("0.05")
    assert next_confidence(None, "CREATE") == Decimal("0.50")
    assert next_confidence(Decimal("0.50"), "IGNORE") == Decimal("0.50")


def test_known_model_has_a_price_and_unknown_model_does_not():
    assert compute_cost("gpt-4.1-mini", 1_000_000, 0) == Decimal("0.400000")
    assert compute_cost("missing-model", 10, 10) is None


def test_quote_grounding_uses_whitespace_normalization():
    body = "OpenAI lowered the API price."
    assert locate_quote(body, "lowered the API price") == (True, 7, 28)
    grounded, start, end = locate_quote(body, "lowered\nthe   API price")
    assert grounded is True
    assert start is None and end is None
    assert locate_quote(body, "announced a datacenter") == (False, None, None)
