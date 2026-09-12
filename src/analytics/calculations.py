"""Deterministic statistics over complete, aggregated query results."""

from __future__ import annotations

from decimal import Decimal
import math
import statistics
from typing import Any


MISSING_LABELS = {"", "N/A", "NA", "N/D", "ND", "NULL", "NONE", "UNKNOWN", "DESCONOCIDO", "SIN INFORMACIÓN", "SIN INFORMACION"}


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def percentage(value: Any, total: Any) -> float | None:
    numerator, denominator = number(value), number(total)
    return None if numerator is None or denominator in (None, 0) else numerator / denominator * 100


def compare(a: Any, b: Any) -> dict[str, Any]:
    valid = number(a) is not None and number(b) is not None
    delta = a - b if valid else None
    return {"difference": delta, "difference_pct": percentage(delta, b),
            "ratio_a_over_b": None if not valid or not b else a / b}


def describe_series(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe observed periods; missing observations are never imputed as zero."""
    valid = [r for r in rows if number(r.get("value")) is not None]
    if not valid:
        return {"observations": 0, "anomalies": [], "limitations": ["Sin valores numéricos utilizables."]}
    values = [number(r["value"]) for r in valid]
    total = sum(values)
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    ordered = sorted(valid, key=lambda r: r["value"], reverse=True)
    for index, row in enumerate(valid):
        row["share_of_total_pct"] = percentage(row["value"], total)
        row["rank"] = 1 + len({v for v in values if v > number(row["value"])})
        row["is_peak"] = row["rank"] == 1
        if index:
            row['change_from_previous_observation'] = compare(row['value'], valid[index-1]['value'])
    anomalies = []
    if len(values) >= 6 and mad > 0:
        for row in valid:
            score = 0.67448975 * (number(row["value"]) - median) / mad
            if abs(score) > 3.5:
                anomalies.append({**row, "robust_z_score": score})
    xmean = (len(values) - 1) / 2
    denominator = sum((i - xmean) ** 2 for i in range(len(values)))
    slope = sum((i - xmean) * (v - mean) for i, v in enumerate(values)) / denominator if denominator else None
    changes = [compare(valid[i]["value"], valid[i - 1]["value"])["difference"] for i in range(1, len(valid))]
    return {"observations": len(valid), "total": total, "mean": mean, "median": median,
            "stddev": std, "coefficient_variation_pct": percentage(std, abs(mean)),
            "slope_per_observed_period": slope, "peak": dict(ordered[0]), "minimum": dict(ordered[-1]),
            "first_to_last": compare(valid[-1]["value"], valid[0]["value"]),
            "last_acceleration": changes[-1] - changes[-2] if len(changes) >= 2 else None,
            "anomaly_method": "MAD robust z", "anomaly_threshold": 3.5, "minimum_observations": 6,
            "anomaly_testable": len(values) >= 6 and mad > 0,
            "anomalies": anomalies, "limitations": ["Picos descriptivos no demuestran causalidad ni estacionalidad."]}


def composition_summary(rows: list[dict[str, Any]], *, total: Any = None) -> dict[str, Any]:
    """Use the full-universe denominator supplied by SQL, never the displayed top N."""
    if total is None:
        return {"denominator_known": False}
    valid = [r for r in rows if number(r.get("value")) is not None]
    return {"denominator_known": True, "total": total,
            "shown_share_pct": percentage(sum(r["value"] for r in valid), total),
            "top3_share_pct": percentage(sum(r["value"] for r in valid[:3]), total) if len(valid) >= 3 else None}
