"""Tool execution boundary: normalized scope, deduplication, cache and traces."""

from __future__ import annotations
import time
from typing import Any
from src.agent.cache import QueryResultCache
from src.agent.analysis_context import AnalysisContext
from src.agent.planner import PlanStep


class ToolExecutor:
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
