"""Calendar resolution, coverage and equivalent comparison windows."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any


def iso(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def window(start: Any, end: Any) -> dict[str, str]:
    a, b = iso(start), iso(end)
    if a > b:
        raise ValueError("El inicio del periodo debe ser anterior o igual al fin.")
    return {"start": a.isoformat(), "end": b.isoformat()}


def shift_month(day: date, offset: int) -> date:
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def shift_year(day: date, offset: int) -> date:
    return date(day.year + offset, day.month, min(day.day, calendar.monthrange(day.year + offset, day.month)[1]))


def resolve_period(spec: dict[str, Any] | None, *, today: date,
                   available: dict[str, Any] | None = None,
                   previous: dict[str, Any] | None = None,
                   peak: dict[str, Any] | None = None) -> dict[str, str]:
    if not spec or spec.get("kind") == "inherit":
        return dict(previous or {})
    kind = spec.get("kind", "range")
    reference = min(today, iso(available["end"])) if available and available.get("end") else today
    if spec.get("anchor") in {"focus", "reference", "peak"} and previous and previous.get("end"):
        reference = iso(previous["end"])
    if kind == "all":
        return {}
    if kind == "range":
        return window(spec["start"], spec["end"])
    if kind == "year":
        year = int(spec.get("year", reference.year))
        return window(date(year, 1, 1), date(year, 12, 31))
    if kind == "month":
        inherited_year = iso(previous["start"]).year if previous and previous.get("start") else reference.year
        year, month = int(spec.get("year", inherited_year)), int(spec["month"])
        return window(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))
    if kind == "ytd":
        year = int(spec.get("year", reference.year))
        return window(date(year, 1, 1), shift_year(reference, year - reference.year))
    if kind == "recent_months":
        count = int(spec.get("count", 6))
        if not 1 <= count <= 120:
            raise ValueError("El número de meses debe estar entre 1 y 120.")
        return window(shift_month(reference.replace(day=1), 1 - count), reference)
    if kind in {"current_month", "previous_month"}:
        base = iso(previous["start"]) if kind == "previous_month" and previous else reference
        start = base.replace(day=1)
        if kind == "previous_month":
            return window(shift_month(start, -1), start - timedelta(days=1))
        return window(start, reference)
    if kind == "previous_year":
        base = previous or window(date(reference.year, 1, 1), reference)
        return window(shift_year(iso(base["start"]), -1), shift_year(iso(base["end"]), -1))
    if kind == "previous_period":
        if not previous:
            raise ValueError("Falta el periodo actual para resolver el anterior.")
        a, b = iso(previous["start"]), iso(previous["end"])
        if a.day == 1 and b.day == calendar.monthrange(b.year, b.month)[1]:
            months = (b.year - a.year) * 12 + b.month - a.month + 1
            return window(shift_month(a, -months), a - timedelta(days=1))
        return window(a - (b - a) - timedelta(days=1), a - timedelta(days=1))
    if kind == "peak":
        if not peak or not peak.get("period"):
            raise ValueError("No hay un pico calculado en el contexto anterior.")
        day = iso(str(peak["period"])[:10])
        granularity = peak.get("granularity", "month")
        end = day if granularity == "day" else day + timedelta(days=6) if granularity == "week" else date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])
        return window(day, end)
    raise ValueError(f"Tipo de periodo no soportado: {kind}")


def coverage(requested: dict[str, Any], available: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    available = {k: available[k] for k in ('start', 'end') if available.get(k)}
    known = bool(available.get("start") and available.get("end"))
    effective = {}
    if known:
        a = max(iso(requested.get("start") or available["start"]), iso(available["start"]))
        b = min(iso(requested.get("end") or available["end"]), iso(available["end"]))
        if a <= b:
            effective = window(a, b)
    partial = bool(known and requested and (not effective or any(requested.get(k) and requested[k] != effective.get(k) for k in ("start", "end"))))
    return {"requested_period": requested, "available_period": available, "observed_period": observed,
            "effective_period": effective, "is_partial": partial, "known": known,
            "basis": "límites temporales de la tabla; no certifica completitud de cada día"}


def equivalent_periods(a: dict[str, str], b: dict[str, str], available: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Clip both windows to corresponding calendar positions, including leap years."""
    a, b = window(**a), window(**b)
    if not available.get("start") or not available.get("end"):
        raise ValueError("No se puede confirmar cobertura para comparar periodos.")
    a0, a1, b0, b1 = iso(a["start"]), iso(a["end"]), iso(b["start"]), iso(b["end"])
    lo, hi = iso(available["start"]), iso(available["end"])
    if a0.month == b0.month and a0.day == b0.day and a1.month == b1.month and a1.day == b1.day:
        offset = a0.year - b0.year
        start = max(a0, lo, shift_year(lo, offset))
        end = min(a1, hi, shift_year(hi, offset))
        return window(start, end), window(shift_year(start, -offset), shift_year(end, -offset))
    # Complete calendar months are comparable even when day counts differ.
    full_months = all(x.day == 1 and y.day == calendar.monthrange(y.year, y.month)[1] for x, y in ((a0, a1), (b0, b1)))
    if full_months and lo <= min(a0, b0) and hi >= max(a1, b1):
        if (a1.year-a0.year)*12+a1.month-a0.month != (b1.year-b0.year)*12+b1.month-b0.month:
            raise ValueError("Los periodos abarcan cantidades distintas de meses.")
        return a, b
    start_offset = max(0, (lo - a0).days, (lo - b0).days)
    end_offset = min((a1-a0).days, (b1-b0).days, (hi-a0).days, (hi-b0).days)
    if end_offset < start_offset:
        raise ValueError("No hay ventanas equivalentes con datos disponibles.")
    return window(a0+timedelta(days=start_offset), a0+timedelta(days=end_offset)), window(b0+timedelta(days=start_offset), b0+timedelta(days=end_offset))
