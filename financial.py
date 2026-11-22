"""Exact decimal helpers for financial inputs, storage, and calculations."""
from decimal import Decimal, InvalidOperation, localcontext


def to_decimal(value, *, default=None):
    """Convert user/API/SQLite values without introducing binary-float arithmetic."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError("Boolean values are not valid financial amounts.")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, float):
        result = Decimal(str(value))
    else:
        text = str(value).strip().replace(",", "").replace("LKR", "").strip()
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1].strip()
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid financial amount: {value!r}") from exc
        if negative:
            result = -result
    if not result.is_finite():
        raise ValueError("Financial amounts must be finite numbers.")
    return result


def divide(numerator, denominator):
    """Return a high-precision Decimal ratio, or None when it is undefined."""
    numerator = to_decimal(numerator)
    denominator = to_decimal(denominator)
    if numerator is None or denominator is None or denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 34
        return numerator / denominator


def decimal_text(value):
    """Serialize a Decimal for lossless SQLite TEXT storage."""
    number = to_decimal(value)
    return None if number is None else format(number, "f")
