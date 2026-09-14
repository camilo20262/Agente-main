"""JSON-safe normalization at the data access boundary."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


def json_value(value: Any) -> Any:
    """Convert BigQuery/Python scalar containers into stable JSON values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value
