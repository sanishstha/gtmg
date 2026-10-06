"""Confidence moves by a fixed rule. The model does not own the number."""

from decimal import Decimal

CONFIDENCE_MIN = Decimal("0.05")
CONFIDENCE_MAX = Decimal("0.95")
CREATE_CONFIDENCE = Decimal("0.50")

_DELTAS = {
    "SUPPORT": Decimal("0.06"),
    "CONTRADICT": Decimal("-0.08"),
    "MODIFY": Decimal("0.02"),
    "IGNORE": Decimal("0"),
}


def next_confidence(before: Decimal | None, action: str) -> Decimal:
    if action == "CREATE":
        value = CREATE_CONFIDENCE
    else:
        base = CREATE_CONFIDENCE if before is None else before
        try:
            delta = _DELTAS[action]
        except KeyError as exc:
            raise ValueError(f"Unknown hypothesis action: {action}") from exc
        value = base + delta
    if value < CONFIDENCE_MIN:
        return CONFIDENCE_MIN
    if value > CONFIDENCE_MAX:
        return CONFIDENCE_MAX
    return value.quantize(Decimal("0.01"))
