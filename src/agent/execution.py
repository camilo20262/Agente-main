"""Tool execution boundary: normalized scope, deduplication, cache and traces."""

from __future__ import annotations
import time
from typing import Any
from src.agent.cache import QueryResultCache
from src.agent.analysis_context import AnalysisContext
from src.agent.planner import PlanStep


class ToolExecutor:
    _INTEGRITY_TOOLS = {
        'consultar_inversion_publicitaria', 'comparar_marcas', 'ranking_anunciantes', 'ranking_marcas',
        'analizar_medios', 'analizar_vehiculos', 'ranking_por_dimension', 'serie_temporal_bicomp',
        'comparar_periodos_bicomp', 'explicar_variacion_bicomp', 'comparar_entidades_bicomp',
        'analizar_drivers_bicomp', 'explicar_diferencia_entidades_bicomp', 'consultar_participacion_bicomp',
        'ranking_segmentado_bicomp', 'ranking_cambio_bicomp', 'ranking_aceleracion_bicomp',
        'buscar_dimension_cambio_bicomp', 'extremo_temporal_bicomp', 'analizar_anomalias_bicomp',
    }

    def __init__(self, registry, cache, metrics):
        self.registry, self.cache, self.metrics = registry, cache, metrics
        self.seen: dict[str, dict[str, Any]] = {}

    def execute(self, step: PlanStep, context: AnalysisContext, index: int) -> dict[str, Any]:
        started = time.perf_counter()
        args = step.arguments
        repo = self.registry.repository
        before_queries = getattr(repo, "query_count", 0)
        before_bytes = getattr(repo, "bytes_processed", 0)
        cache_hit = False
        try:
            schemas = {s["function"]["name"]: s["function"]["parameters"] for s in self.registry.schemas}
            if step.tool not in schemas:
                raise ValueError(f"Herramienta no registrada: {step.tool}")
            args = self.registry.normalize_arguments(step.tool, args)
            args = context.bind(args, schemas[step.tool].get("properties", {}))
            if isinstance(args.get("filtros"), dict):
                args["filtros"] = {k: [str(v).strip().upper() for v in value] if isinstance(value, list)
                                  else value.strip().upper() if isinstance(value, str) else value
                                  for k, value in args["filtros"].items()}
            key = QueryResultCache.key(step.tool, args)
            if key in self.seen:
                return {"tool": step.tool, "arguments": args, "step": index, "purpose": step.purpose,
                        "result": {"success": False, "error_type": "duplicate", "error": "Consulta ya ejecutada; usar evidencia existente.",
                                   "existing_evidence_id": self.seen[key]["id"]}}
            cached = self.cache.get(step.tool, args)
            if cached is not None:
                result, cache_hit = cached, True
                self.metrics.cache_hits += 1
            else:
                self.metrics.total_tool_calls += 1
                result = self.registry.execute(step.tool, args)
                self.cache.put(step.tool, args, result)
            integrity_repo = getattr(self.registry, 'bicomp_repository', repo)
            if (step.tool in self._INTEGRITY_TOOLS and result.get('success') is True
                    and hasattr(integrity_repo, 'profile_integrity')):
                period = (result.get('effective_period') or result.get('period') or result.get('current_period')
                          or result.get('period_a') or {})
                integrity_filters = dict(result.get('filters') or args.get('filtros') or {})
                entity_dimension = result.get('entity_dimension')
                labels = [result.get('value_a_label'), result.get('value_b_label')]
                if entity_dimension and all(labels):
                    integrity_filters[entity_dimension] = labels
                elif result.get('brand_a') and result.get('brand_b'):
                    integrity_filters['marca'] = [result['brand_a'], result['brand_b']]
                try:
                    profile = integrity_repo.profile_integrity(
                        metric=result.get('metric') or args.get('metrica', 'inv_neta'),
                        filters=integrity_filters,
                        start_date=period.get('start'), end_date=period.get('end'))
                except Exception:
                    profile = {'status': 'unverified', 'decision_eligible': False}
                    result['warnings'] = [
                        'No fue posible verificar la integridad del alcance consultado; el resultado requiere revisión antes de utilizarse en una decisión.',
                        *result.get('warnings', []),
                    ]
                result['integrity'] = {key: value for key, value in profile.items() if key != 'evidence'}
                result['integrity_status'] = profile.get('status')
                evidence_item = profile.get('evidence')
                if evidence_item:
                    existing = result.get('evidence', [])
                    result['evidence'] = ([existing] if isinstance(existing, dict) else list(existing)) + [evidence_item]
                if profile.get('status') in {'suspect', 'review'}:
                    warning = ('La fuente presenta una concentración inusual de valores idénticos en varias entidades, medios y fechas. '
                               'El resultado requiere revisión de integridad antes de utilizarse en una decisión.')
                    result['warnings'] = [warning, *result.get('warnings', [])]
                    if step.tool != 'consultar_inversion_publicitaria':
                        result['decision_eligible'] = False
                elif profile.get('status') == 'unverified' and step.tool != 'consultar_inversion_publicitaria':
                    result['decision_eligible'] = False
        except (ValueError, TypeError, KeyError) as exc:
            result = {"success": False, "error_type": "arguments", "retryable": True, "error": str(exc)}
            key = QueryResultCache.key(step.tool, args)
        query_evidence = result.get("evidence", [])
        queries = [query_evidence] if isinstance(query_evidence, dict) else [q for q in query_evidence if isinstance(q, dict)]
        self.metrics.bigquery_queries += getattr(repo, "query_count", 0) - before_queries
        self.metrics.bigquery_bytes_processed += getattr(repo, "bytes_processed", 0) - before_bytes
        record = {"id": f"e{index}", "tool": step.tool, "arguments": args, "result": result,
                  "source": result.get("source", repo.source), "metric": result.get("metric"),
                  "filters": result.get("filters", args.get("filtros")), "row_count": result.get("row_count"),
                  "step": index, "purpose": step.purpose, "cache_hit": cache_hit or result.get("cache_hit", False),
                  "queries": queries, "latency_ms": round((time.perf_counter()-started)*1000, 2)}
        self.seen[key] = record
        if result.get("success") is False:
            self.metrics.errors.append(result.get("error_type", "tool_error"))
        self.metrics.events.append({"stage": "tool", "tool": step.tool, "purpose": step.purpose,
                                    "success": result.get("success"), "cache_hit": record["cache_hit"]})
        return record
