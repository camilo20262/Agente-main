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
    analysis_context: dict[str, Any] = field(default_factory=dict)
    recent_scopes: list[dict[str, Any]] = field(default_factory=list)
    last_peak: dict[str, Any] = field(default_factory=dict)
    last_strategy: list[dict[str, Any]] = field(default_factory=list)

    last_requested_scope: dict[str, Any] = field(default_factory=dict)
    last_successful_scope: dict[str, Any] = field(default_factory=dict)
    last_confirmed_evidence_scope: dict[str, Any] = field(default_factory=dict)
    last_analysis_strategy: list[dict[str, Any]] = field(default_factory=list)
    last_request: dict[str, Any] = field(default_factory=dict)
    recent_entities: list[dict[str, str]] = field(default_factory=list)

    def remember_request(self, context, strategy, *, request=None):
        previous = self.last_requested_scope or self.analysis_context
        if previous and previous != context:
            self.recent_scopes = (self.recent_scopes + [{**deepcopy(previous), 'strategy': deepcopy(self.last_analysis_strategy)}])[-12:]
        # A peak belongs to its original metric/filter/window, not every later request.
        if self.last_peak and any(previous.get(k) != context.get(k) for k in ('metric', 'filters', 'requested_period')):
            self.last_peak = {}
        self.last_requested_scope = deepcopy(context)
        self.last_analysis_strategy = deepcopy(strategy)
        self.last_strategy = deepcopy(strategy)  # Compatibility facade for transition compiler.
        if request is not None:
            self.last_request = deepcopy(request)
        from src.semantic import load_semantic_layer
        dimensions = load_semantic_layer()['business_rules']['entity_dimensions']
        entities = []
        for dimension, values in context.get('filters', {}).items():
            if dimension in dimensions:
                entities.extend({'dimension': dimension, 'value': v} for v in (values if isinstance(values, list) else [values]))
        entities += context.get('analysis', {}).get('entity_set', [])
        for entity in entities:
            entity = {'dimension': entity['dimension'], 'value': str(entity['value']).strip().upper()}
            self.recent_entities = [e for e in self.recent_entities if e != entity] + [deepcopy(entity)]
        self.recent_entities = self.recent_entities[-8:]

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
        result = {key: value for key, value in asdict(self).items()
                  if key not in {"analysis_context", "recent_scopes", "last_peak", "last_strategy", "last_requested_scope", "last_successful_scope", "last_confirmed_evidence_scope",
                                 "last_analysis_strategy", "last_request", "recent_entities"} or value}
        if self.last_requested_scope:
            result['analysis_context'] = deepcopy(self.last_requested_scope)
        return result

    def remember_analysis(self, context: dict[str, Any], evidence: list[dict[str, Any]]) -> None:
        """Commit the base scope, not the narrower last drill-down query."""
        successful = [item["result"] for item in evidence if item["result"].get("success") is True]
        if not successful:
            return
        scope_keys = ('metric', 'filters', 'requested_period', 'comparison_period', 'dimensions', 'intent')
        if not self.last_requested_scope and self.analysis_context and any(self.analysis_context.get(k) != context.get(k) for k in scope_keys):
            self.recent_scopes = (self.recent_scopes + [deepcopy(self.analysis_context)])[-4:]
            self.last_peak = {}
        self.last_confirmed_evidence_scope = deepcopy(context)
        self.analysis_context = deepcopy(context)
        self.last_domain, self.last_metric = "bicomp", context["metric"]
        self.last_filters = deepcopy(context["filters"])
        self.last_period = deepcopy(context["requested_period"])
        brand = self.last_filters.get("marca")
        self.last_entities = {"brands": [brand] if isinstance(brand, str) else brand} if brand else {}
        for result in successful:
            if result.get("peak"):
                self.last_peak = {**deepcopy(result.get("selected_extreme") or result["peak"]), "granularity": result.get("granularity", "month")}
            dimension = result.get('entity_dimension') or result.get('dimension')
            a = result.get('brand_a') or result.get('value_a_label')
            b = result.get('brand_b') or result.get('value_b_label')
            if a and b:
                self.last_entities = {'dimension': dimension or 'marca', 'values': [a, b]}

    def clear(self) -> None:
        self.last_domain = self.last_metric = None
        self.last_period.clear(); self.last_entities.clear(); self.last_filters.clear()
        self.analysis_context.clear(); self.recent_scopes.clear(); self.last_peak.clear()
        self.last_strategy.clear()
        self.last_requested_scope.clear(); self.last_successful_scope.clear()
        self.last_confirmed_evidence_scope.clear(); self.last_analysis_strategy.clear()
        self.last_request.clear(); self.recent_entities.clear()
