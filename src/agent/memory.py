"""Compact per-session analytical memory; never stores large query results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AnalyticalMemory:
    last_domain: str | None = None
    last_metric: str | None = None
    last_period: dict[str, Any] = field(default_factory=dict)
    last_entities: dict[str, list[str]] = field(default_factory=dict)
    last_filters: dict[str, Any] = field(default_factory=dict)

    def update_from_result(self, tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        domain = result.get("domain")
        if domain:
            self.last_domain = domain
        self.last_metric = result.get("metric") or arguments.get("metrica") or self.last_metric
        period = result.get("period") or {}
        if period:
            self.last_period = {k: v for k, v in period.items() if v is not None}
        filters = arguments.get("filtros") or result.get("filters") or {}
        if filters:
            self.last_filters = dict(filters)
        brands = [value for value in (arguments.get("marca_a"), arguments.get("marca_b"), filters.get("marca") if isinstance(filters, dict) else None) if isinstance(value, str)]
        if brands:
            self.last_entities["brands"] = brands

    def context(self) -> dict[str, Any]:
        return asdict(self)

    def clear(self) -> None:
        self.last_domain = self.last_metric = None
        self.last_period.clear(); self.last_entities.clear(); self.last_filters.clear()
