"""Compact per-session analytical memory; never stores large query results."""

from __future__ import annotations

from copy import deepcopy
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
        if result.get("success") is not True:
            return
        # Metadata discovery does not replace the last analytical query.
        if tool in {"obtener_catalogo_bicomp", "obtener_cobertura_bicomp", "obtener_rango_fechas", "catalogo"}:
            return
        domain = result.get("domain")
        if domain:
            self.last_domain = domain
        self.last_metric = result.get("metric") or arguments.get("metrica") or self.last_metric

        # Result context is authoritative; arguments fill fields omitted by wrappers.
        # An absent scope in both sources means the executed query was unrestricted.
        if "period" in result:
            period = result["period"]
        elif "current_period" in result or "periodo_actual" in arguments:
            period = result.get("current_period", arguments.get("periodo_actual"))
        elif "period_a" in result or "periodo_a" in arguments:
            period = {"period_a": result.get("period_a", arguments.get("periodo_a")),
                      "period_b": result.get("period_b", arguments.get("periodo_b"))}
        else:
            period = {"start": arguments.get("fecha_inicio", arguments.get("start_date")),
                      "end": arguments.get("fecha_fin", arguments.get("end_date"))}
        self.last_period = deepcopy({k: v for k, v in period.items() if v is not None}) if isinstance(period, dict) else {}

        filters = result.get("filters") if "filters" in result else arguments.get("filtros", arguments.get("filters"))
        self.last_filters = deepcopy(filters) if isinstance(filters, dict) else {}
        brands = [result.get("brand_a", arguments.get("marca_a", arguments.get("brand_a"))),
                  result.get("brand_b", arguments.get("marca_b", arguments.get("brand_b"))),
                  result.get("brand", arguments.get("marca", arguments.get("brand")))]
        if result.get("dimension", arguments.get("dimension")) == "marca":
            brands.extend([result.get("value_a_label", arguments.get("value_a")),
                           result.get("value_b_label", arguments.get("value_b"))])
        brands = [value for value in brands if isinstance(value, str) and value]
        if not brands:
            brand_filter = self.last_filters.get("marca")
            brands = [brand_filter] if isinstance(brand_filter, str) else brand_filter if isinstance(brand_filter, list) else []
        brands = list(dict.fromkeys(value for value in brands if isinstance(value, str) and value))
        self.last_entities = {"brands": brands} if brands else {}

    def context(self) -> dict[str, Any]:
        return asdict(self)

    def clear(self) -> None:
        self.last_domain = self.last_metric = None
        self.last_period.clear(); self.last_entities.clear(); self.last_filters.clear()
