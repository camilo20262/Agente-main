"""Parameterized, read-only BigQuery repository with query evidence."""

from __future__ import annotations

from datetime import date
from dataclasses import dataclass
from functools import lru_cache
from copy import deepcopy
from src.agent.cache import QueryResultCache
from src.agent.periods import coverage, equivalent_periods, window
from src.analytics.calculations import compare, describe_series, composition_summary, percentage, MISSING_LABELS
import json
import time
from typing import Any

from src.config import Settings
from src.data.sql_guard import validate_read_only_sql
from src.semantic import load_semantic_layer


@dataclass(frozen=True)
class QuerySpec:
    sql: str
    parameters: list[tuple[str, str, Any]]


class BigQueryRepository:
    source = "bigquery"

    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self._client = client
        self._catalog_cache = QueryResultCache(settings.query_cache_ttl_seconds)
        self._coverage_cache = QueryResultCache(settings.query_cache_ttl_seconds)
        self.query_count = 0
        self.bytes_processed = 0
        semantic = load_semantic_layer()
        self.allowed_metrics = set(semantic["metrics"].keys())
        self.allowed_dimensions = set(semantic["dimensions"].keys())


    @property
    def client(self) -> Any:
        """Create the Google client lazily."""
        if self._client is None:
            try:
                from google.cloud import bigquery
            except ImportError as exc:
                raise RuntimeError("BigQuery no está configurado: falta google-cloud-bigquery.") from exc
            try:
                self._client = bigquery.Client(project=self.settings.gcp_project_id, location=self.settings.bigquery_location)
            except Exception as exc:
                if exc.__class__.__name__ in {"DefaultCredentialsError", "RefreshError"}:
                    raise RuntimeError("BigQuery no está configurado o no se tienen permisos sobre la fuente BICOMP.") from exc
                raise
        return self._client

    @property
    def bicomp_table(self) -> str:
        values = (self.settings.gcp_project_id, self.settings.bigquery_dataset, self.settings.bigquery_bicomp_table)
        if not all(values):
            raise ValueError("BigQuery no está configurado. Completa GCP_PROJECT_ID, BIGQUERY_DATASET y BIGQUERY_BICOMP_TABLE.")
        return ".".join(values)  # type: ignore[arg-type]

    def _execute(self, spec: QuerySpec, *, allowed_tables: set[str] | None = None) -> dict[str, Any]:
        from google.cloud import bigquery
        allowed = allowed_tables or {self.bicomp_table}
        sql = validate_read_only_sql(spec.sql, allowed)
        parameters = [
            bigquery.ArrayQueryParameter(name, typ, value)
            if isinstance(value, (list, tuple))
            else bigquery.ScalarQueryParameter(name, typ, value)
            for name, typ, value in spec.parameters
        ]
        dry_config = bigquery.QueryJobConfig(query_parameters=parameters, dry_run=True, use_query_cache=False)
        dry_job = self.client.query(sql, job_config=dry_config, location=self.settings.bigquery_location)
        estimated = int(getattr(dry_job, "total_bytes_processed", 0) or 0)
        if estimated > self.settings.bigquery_max_bytes_billed:
            raise RuntimeError(f"Consulta bloqueada: {estimated} bytes exceden el límite configurado.")
        config = bigquery.QueryJobConfig(query_parameters=parameters, maximum_bytes_billed=self.settings.bigquery_max_bytes_billed, use_query_cache=True)
        started = time.perf_counter()
        job = self.client.query(sql, job_config=config, location=self.settings.bigquery_location)
        self.query_count += 1
        rows = [dict(row.items()) for row in job.result(timeout=self.settings.bigquery_timeout_seconds)]
        processed = getattr(job, "total_bytes_processed", None)
        processed = estimated if processed is None else int(processed)
        self.bytes_processed += processed
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "success": True, "source": self.source, "rows": rows, "row_count": len(rows),
            "evidence": {"sql": sql, "query_parameters": {n: str(v) for n, _, v in spec.parameters},
                         "bytes_processed": processed, "job_id": getattr(job, "job_id", None),
                         "cache_hit": bool(getattr(job, "cache_hit", False)), "executed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                         "duration_ms": duration_ms, "rows": len(rows)},
        }

    def _execute_bicomp(self, spec: QuerySpec) -> dict[str, Any]:
        """Execute BICOMP SQL and normalize common Google API failures."""
        try:
            return self._execute(spec, allowed_tables={self.bicomp_table})
        except Exception as exc:
            name = exc.__class__.__name__
            detail = str(exc).lower()
            if "serviceusage.services.use" in detail or "quota project" in detail:
                raise RuntimeError("BigQuery rechazó el proyecto de cuota. Solicita serviceusage.services.use sobre nexuslatam-master o configura un proyecto de cuota autorizado.") from exc
            if name in {"DefaultCredentialsError", "RefreshError", "Forbidden", "PermissionDenied"}:
                raise RuntimeError("BigQuery no está configurado o no se tienen permisos sobre la fuente BICOMP.") from exc
            if name in {"NotFound"}:
                raise RuntimeError("La tabla BICOMP no existe o no es visible para estas credenciales.") from exc
            if name in {"DeadlineExceeded", "TimeoutError"}:
                raise RuntimeError("La consulta BICOMP excedió el tiempo permitido.") from exc
            raise

    @lru_cache(maxsize=1)
    def get_bicomp_schema(self) -> dict[str, str]:
        """Read real field names/types from BigQuery; no types are assumed."""
        try:
            table = self.client.get_table(self.bicomp_table)
        except Exception as exc:
            name = exc.__class__.__name__
            if name in {"DefaultCredentialsError", "RefreshError", "Forbidden", "PermissionDenied"}:
                raise RuntimeError("BigQuery no está configurado o no se tienen permisos sobre la fuente BICOMP.") from exc
            if name == "NotFound":
                raise RuntimeError("La tabla BICOMP no existe o no es visible para estas credenciales.") from exc
            raise
        return {field.name: field.field_type for field in table.schema}

    def _bicomp_field(self, field: str, *, metric: bool = False) -> str:
        allowed = self.allowed_metrics if metric else self.allowed_dimensions
        if field not in allowed:
            raise ValueError(f"Campo BICOMP no permitido: {field}")
        schema = self.get_bicomp_schema()
        if field not in schema:
            raise ValueError(f"El campo '{field}' no existe en el esquema real de BICOMP.")
        if metric and schema[field] not in {"INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC", "DECIMAL"}:
            raise ValueError(f"La métrica {field} no es numérica.")
        return field

    def _dimension_group_expression(self, dimension: str) -> str:
        """Return a safe grouping expression for categorical dimensions.

        Only case/whitespace normalization is applied. Semantic aliases such as
        "TV NAL" and "TELEVISION NACIONAL" are intentionally left separate.
        """
        self._bicomp_field(dimension)
        if self.get_bicomp_schema().get(dimension) == "STRING":
            return f"UPPER(TRIM(CAST(`{dimension}` AS STRING)))"
        return f"`{dimension}`"

    def _bicomp_filters(self, filters: dict[str, Any] | None, start_date: str | date | None, end_date: str | date | None) -> tuple[str, list[tuple[str, str, Any]]]:
        if filters is not None and not isinstance(filters, dict):
            raise TypeError(f"'filtros' debe ser un objeto JSON (diccionario), se recibió {type(filters).__name__}: {filters!r}")
        if start_date is not None and end_date is not None:
            window(str(start_date), str(end_date))
        clauses: list[str] = []
        parameters: list[tuple[str, str, Any]] = []
        for index, (field, value) in enumerate((filters or {}).items()):
            self._bicomp_field(field)
            name = f"filter_{index}"
            if isinstance(value, (list, tuple)):
                clauses.append(f"UPPER(TRIM(CAST(`{field}` AS STRING))) IN UNNEST(@{name})")
                parameters.append((name, "STRING", [str(item).strip().upper() for item in value]))
            else:
                clauses.append(f"UPPER(TRIM(CAST(`{field}` AS STRING))) = @{name}")
                parameters.append((name, "STRING", str(value).strip().upper()))
        if start_date is not None or end_date is not None:
            self._bicomp_field("fecha")
        for name, operator, value in (("start_date", ">=", start_date), ("end_date", "<=", end_date)):
            if value is not None:
                parsed = date.fromisoformat(value) if isinstance(value, str) else value
                clauses.append(f"DATE(`fecha`) {operator} @{name}")
                parameters.append((name, "DATE", parsed))
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters

    def test_connection(self) -> list[dict[str, Any]]:
        spec = QuerySpec(f"SELECT * FROM `{self.bicomp_table}` LIMIT 5", [])
        return self._execute_bicomp(spec)["rows"]

    def _scoped_execute(self, spec: QuerySpec) -> dict[str, Any]:
        """Obtain scope and global cutoff in one billed query on a cold cache."""
        if self._coverage_cache.get("coverage", {}) is None:
            sql = (f"WITH analytical_result AS ({spec.sql}), source_coverage AS ("
                   f"SELECT MIN(DATE(`fecha`)) AS _available_start, MAX(DATE(`fecha`)) AS _available_end "
                   f"FROM `{self.bicomp_table}`) "
                   "SELECT analytical_result.*, source_coverage.* FROM analytical_result CROSS JOIN source_coverage")
            result = self._execute_bicomp(QuerySpec(sql, spec.parameters))
            if result.get("rows"):
                row = result["rows"][0]
                if row.get("_available_start") and row.get("_available_end"):
                    self._coverage_cache.put("coverage", {}, {"success": True, "start": str(row["_available_start"]), "end": str(row["_available_end"])})
            return result
        return self._execute_bicomp(spec)

    def _context(self, result: dict[str, Any], *, metric: str, filters: dict[str, Any] | None,
                 start_date: Any, end_date: Any) -> dict[str, Any]:
        rows = result.get("rows", [])
        starts = [str(r["_observed_start"]) for r in rows if r.get("_observed_start")]
        ends = [str(r["_observed_end"]) for r in rows if r.get("_observed_end")]
        observed = {"start": min(starts), "end": max(ends)} if starts and ends else {}
        requested = {k: str(v) for k, v in (("start", start_date), ("end", end_date)) if v is not None}
        available = self._coverage_cache.get("coverage", {}) or {}
        available = {k: available[k] for k in ("start", "end") if available.get(k)}
        info = coverage(requested, available, observed)
        for row in rows:
            for key in list(row):
                if key.startswith("_observed_") or key.startswith("_available_"):
                    row.pop(key)
        warnings = []
        if info["is_partial"]:
            warnings.append("Periodo solicitado parcialmente disponible; usar el acumulado disponible y declarar el corte, no un total anual completo.")
        if not info["known"]:
            warnings.append("Cobertura temporal no verificada.")
        return {"domain": "bicomp", "source": self.source, "metric": metric, "aggregation": "sum",
                "filters": filters or {}, "period": requested, **info, "warnings": warnings,
                "unit": load_semantic_layer()["metrics"][metric].get("unit"),
                "metric_label": load_semantic_layer()["metrics"][metric].get("description", metric)}

    def consultar_inversion(self, *, metric: str = "inv_neta", filters: dict[str, Any] | None = None,
                            start_date: str | date | None = None, end_date: str | date | None = None) -> dict[str, Any]:
        self._bicomp_field(metric, metric=True)
        where, parameters = self._bicomp_filters(filters, start_date, end_date)
        result = self._scoped_execute(QuerySpec(
            f"SELECT SUM(`{metric}`) AS value, COUNT(*) AS source_rows, COUNT(`{metric}`) AS valid_values, "
            f"MIN(DATE(`fecha`)) AS _observed_start, MAX(DATE(`fecha`)) AS _observed_end "
            f"FROM `{self.bicomp_table}`{where}", parameters))
        context = self._context(result, metric=metric, filters=filters, start_date=start_date, end_date=end_date)
        row = result["rows"][0] if result["rows"] else {}
        has_data = bool(row.get("source_rows")) and row.get("value") is not None
        return {**context, "success": has_data, "value": row.get("value"), "row_count": row.get("source_rows", 0),
                "valid_values": row.get("valid_values"),
                **({"error": "La consulta BICOMP no produjo resultados utilizables.", "error_type": "no_data"} if not has_data else {}),
                "evidence": result["evidence"]}

    @staticmethod
    def _entity_gap(observations: list[dict[str, Any]]) -> dict[str, Any]:
        unavailable = [item['label'] for item in observations if item['status'] != 'observed']
        if not unavailable:
            return {}
        without_rows = [item['label'] for item in observations if item['status'] == 'no_rows']
        without_numbers = [item['label'] for item in observations if item['status'] == 'non_numeric']
        details = []
        if without_rows:
            details.append('No se observaron filas para ' + ', '.join(map(str, without_rows)))
        if without_numbers:
            details.append('No se obtuvieron valores numéricos para ' + ', '.join(map(str, without_numbers)))
        return {
            'error_type': 'no_data',
            'usable_partial_evidence': True,
            'comparison_status': 'incomplete_entity_observation',
            'entity_observations': observations,
            'missing_entities': unavailable,
            'error': '; '.join(details) + ' en el alcance solicitado; no se asume inversión cero.',
        }

    def comparar_marcas(self, *, brand_a: str, brand_b: str, metric: str = "inv_neta", filters: dict[str, Any] | None = None, start_date: str | date | None = None, end_date: str | date | None = None) -> dict[str, Any]:
        first = self.consultar_inversion(metric=metric, filters={**(filters or {}), "marca": brand_a}, start_date=start_date, end_date=end_date)
        second = self.consultar_inversion(metric=metric, filters={**(filters or {}), "marca": brand_b}, start_date=start_date, end_date=end_date)
        a, b = first["value"], second["value"]
        difference = None if a is None or b is None else a - b
        missing = [brand for brand, value in ((brand_a, a), (brand_b, b)) if value is None]
        observations = [
            {'label': label, 'status': 'observed' if value is not None else ('no_rows' if not result.get('row_count') else 'non_numeric'),
             'source_rows': int(result.get('row_count') or 0), 'observed_value': value}
            for label, value, result in ((brand_a, a, first), (brand_b, b, second))
        ]
        return {"success": a is not None and b is not None, "domain": "bicomp", "source": "bigquery", "metric": metric, "aggregation": "sum", "brand_a": brand_a, "brand_b": brand_b,
                **({"error": "La consulta BICOMP no produjo resultados para las marcas: " + ", ".join(missing) + "."} if missing else {}),
                **self._entity_gap(observations),
                "filters": filters or {}, "period": first.get("period", {}), "coverage_a": first.get("effective_period"), "coverage_b": second.get("effective_period"),
                "requested_period": first.get("requested_period", {}), "effective_period": first.get("effective_period", {}), "is_partial": first.get("is_partial", False),
                "warnings": first.get("warnings", []) + second.get("warnings", []),
                "value_a": a, "value_b": b, "difference": difference, "difference_pct": None if difference is None or not b else difference / b * 100,
                "ratio_a_over_b": None if a is None or not b else a / b,
                "row_count": first["row_count"] + second["row_count"], "evidence": [first["evidence"], second["evidence"]]}

    def comparar_periodos_bicomp(self, *, period_a: dict[str, str], period_b: dict[str, str], metric: str = "inv_neta", filters: dict[str, Any] | None = None) -> dict[str, Any]:
        requested_a, requested_b = window(**period_a), window(**period_b)
        cached = self._coverage_cache.get("coverage", {})
        temporal_coverage = cached or self.obtener_rango_fechas()
        if not temporal_coverage.get("success"):
            return {"success": False, "error_type": "no_data", "error": "Sin cobertura temporal para comparar.", "evidence": temporal_coverage.get("evidence", [])}
        period_a, period_b = equivalent_periods(requested_a, requested_b, temporal_coverage)
        a = self.consultar_inversion(metric=metric, filters=filters, start_date=period_a["start"], end_date=period_a["end"])
        b = self.consultar_inversion(metric=metric, filters=filters, start_date=period_b["start"], end_date=period_b["end"])
        va, vb = a.get("value"), b.get("value")
        difference = None if va is None or vb is None else va - vb
        return {"success": difference is not None, "domain": "bicomp", "source": "bigquery", "metric": metric, "aggregation": "sum",
                "period_a": period_a, "period_b": period_b, "requested_period_a": requested_a, "requested_period_b": requested_b,
                "comparison_equivalent": True, "periods_adjusted": period_a != requested_a or period_b != requested_b,
                "warnings": (["Comparación ajustada a ventanas equivalentes con cobertura disponible."] if period_a != requested_a or period_b != requested_b else []), "value_a": va, "value_b": vb, "difference": difference,
                "difference_pct": None if difference is None or not vb else difference / vb * 100,
                "ratio_a_over_b": None if va is None or not vb else va / vb, "filters": filters or {},
                "row_count": a.get("row_count", 0) + b.get("row_count", 0), "evidence": [*([temporal_coverage["evidence"]] if not cached and temporal_coverage.get("evidence") else []), a.get("evidence"), b.get("evidence")]}

    def explicar_variacion_bicomp(self, *, brand: str, current_period: dict[str, str], previous_period: dict[str, str], metric: str = "inv_neta", filters: dict[str, Any] | None = None, driver_limit: int = 20) -> dict[str, Any]:
        if not 1 <= driver_limit <= 100:
            raise ValueError("limit debe estar entre 1 y 100.")
        base_filters = {**(filters or {}), "marca": brand}
        comparison = self.comparar_periodos_bicomp(period_a=current_period, period_b=previous_period, metric=metric, filters=base_filters)
        if not comparison["success"]:
            return {**comparison, "drivers": []}
        current_period = comparison.get("period_a", current_period)
        previous_period = comparison.get("period_b", previous_period)
        drivers: list[dict[str, Any]] = []
        evidence = list(comparison.get("evidence", []))
        for dimension in ("medio", "vehiculo", "formato"):
            current = self._totales_dimension_bicomp(dimension=dimension, metric=metric, filters=base_filters,
                start_date=current_period["start"], end_date=current_period["end"])
            previous = self._totales_dimension_bicomp(dimension=dimension, metric=metric, filters=base_filters,
                start_date=previous_period["start"], end_date=previous_period["end"])
            current_map = {str(row["dimension"]): row["value"] or 0 for row in current["rows"]}
            previous_map = {str(row["dimension"]): row["value"] or 0 for row in previous["rows"]}
            for value in sorted(current_map.keys() | previous_map.keys()):
                contribution = current_map.get(value, 0) - previous_map.get(value, 0)
                drivers.append({"dimension": dimension, "value": value, "current_value": current_map.get(value, 0),
                                "previous_value": previous_map.get(value, 0), "contribution": contribution})
            evidence.extend([current["evidence"], previous["evidence"]])
        drivers.sort(key=lambda item: abs(item["contribution"]), reverse=True)
        return {"success": comparison["success"], "domain": "bicomp", "source": "bigquery", "brand": brand, "metric": metric,
                "current_period": current_period, "previous_period": previous_period, "current_value": comparison["value_a"],
                "previous_value": comparison["value_b"], "change": comparison["difference"], "change_pct": comparison["difference_pct"],
                "filters": base_filters, "drivers": drivers[:driver_limit], "drivers_by_dimension": {d: [r for r in drivers if r["dimension"] == d][:driver_limit] for d in ("medio", "vehiculo", "formato")},
                "warnings": comparison.get("warnings", []) + ["Las dimensiones son descomposiciones alternativas; no sumar contribuciones entre ellas."],
                "row_count": comparison["row_count"], "evidence": evidence}

    def _totales_dimension_bicomp(
        self,
        *,
        dimension: str,
        metric: str,
        filters: dict[str, Any] | None,
        start_date: str | date | None,
        end_date: str | date | None,
    ) -> dict[str, Any]:
        """Return complete dimension totals for variation drivers."""
        self._bicomp_field(metric, metric=True)
        dimension_expression = self._dimension_group_expression(dimension)
        where, parameters = self._bicomp_filters(filters, start_date, end_date)

        # Do not cap categories before subtraction: that would distort drivers.
        # Normalize only case/whitespace for selected categorical dimensions.
        sql = (
            f"SELECT {dimension_expression} AS dimension, "
            f"SUM(`{metric}`) AS value "
            f"FROM `{self.bicomp_table}`{where} "
            "GROUP BY dimension"
        )
        return self._execute_bicomp(QuerySpec(sql, parameters))

    def _ranking_bicomp(
        self,
        *,
        dimension: str,
        metric: str,
        filters: dict[str, Any] | None,
        start_date: str | date | None,
        end_date: str | date | None,
        limit: int,
    ) -> dict[str, Any]:
        self._bicomp_field(metric, metric=True)
        dimension_expression = self._dimension_group_expression(dimension)

        if not 1 <= limit <= 100:
            raise ValueError("limit debe estar entre 1 y 100.")

        missing_labels_sql = ', '.join("'" + label.replace("'", "''") + "'" for label in sorted(MISSING_LABELS))

        where, parameters = self._bicomp_filters(
            filters,
            start_date,
            end_date,
        )
        parameters.append(("limit", "INT64", limit))

        # El total para share_pct se calcula ANTES del LIMIT, de modo que la
        # participación corresponde al universo completo filtrado, no solo al top N.
        sql = f"""
        WITH grouped AS (
            SELECT
                {dimension_expression} AS dimension,
                SUM(`{metric}`) AS value,
                COUNT(*) AS source_rows,
                MIN(DATE(`fecha`)) AS _observed_start, MAX(DATE(`fecha`)) AS _observed_end
            FROM `{self.bicomp_table}`
            {where}
            GROUP BY dimension
        ),
        scored AS (
            SELECT
                dimension,
                value,
                source_rows,
                DENSE_RANK() OVER (ORDER BY value DESC) AS rank,
                SUM(value) OVER () AS total,
                MIN(_observed_start) OVER () AS _observed_start, MAX(_observed_end) OVER () AS _observed_end,
                SAFE_MULTIPLY(
                    SAFE_DIVIDE(value, SUM(value) OVER ()),
                    100
                ) AS share_pct
            FROM grouped
            WHERE value IS NOT NULL
        )
        SELECT
            dimension,
            value,
            source_rows,
            rank,
            share_pct, total, _observed_start, _observed_end,
            SUM(POW(SAFE_DIVIDE(value, total), 2)) OVER () * 10000 AS concentration_hhi,
            SUM(IF(dimension IS NULL OR CAST(dimension AS STRING) IN ({missing_labels_sql}), value, 0)) OVER () AS unknown_value
        FROM scored
        ORDER BY value DESC, CAST(dimension AS STRING)
        LIMIT @limit
        """

        result = self._scoped_execute(QuerySpec(sql, parameters))
        context = self._context(result, metric=metric, filters=filters, start_date=start_date, end_date=end_date)

        rows = sorted(result["rows"], key=lambda row: (-(row.get("value") or 0), str(row.get("dimension"))))
        has_data = bool(rows)

        return {
            **context,
            "success": has_data,
            "domain": "bicomp",
            "source": "bigquery",
            "project": self.settings.gcp_project_id,
            "dataset": self.settings.bigquery_dataset,
            "table": self.settings.bigquery_bicomp_table,
            "metric": metric,
            "aggregation": "sum",
            "dimension": dimension,
            "filters": filters or {},
            "period": {
                "start": str(start_date) if start_date else None,
                "end": str(end_date) if end_date else None,
            },
            "composition": composition_summary(rows, total=rows[0].get("total") if rows else None),
            "data_quality": {"unknown_share_pct": percentage(rows[0].get("unknown_value"), rows[0].get("total")),
                             "unknown_value": rows[0].get("unknown_value"),
                             "known_value": rows[0].get("total", 0) - rows[0].get("unknown_value", 0),
                             "known_share_pct": percentage(rows[0].get("total", 0) - rows[0].get("unknown_value", 0), rows[0].get("total"))} if rows else {},
            "rows": rows,
            "row_count": len(rows),
            **(
                {"error": "La consulta BICOMP no produjo resultados utilizables."}
                if not has_data
                else {}
            ),
            "query_metadata": {
                "bytes_processed": result["evidence"]["bytes_processed"],
                "duration_ms": result["evidence"]["duration_ms"],
            },
            "evidence": result["evidence"],
        }

    def ranking_anunciantes(self, **kwargs: Any) -> dict[str, Any]:
        return self._ranking_bicomp(dimension="anunciante", metric=kwargs.pop("metric", "inv_neta"), **kwargs)

    def ranking_marcas(self, **kwargs: Any) -> dict[str, Any]:
        return self._ranking_bicomp(dimension="marca", metric=kwargs.pop("metric", "inv_neta"), **kwargs)

    def analizar_medios(self, **kwargs: Any) -> dict[str, Any]:
        return self._ranking_bicomp(dimension="medio", metric=kwargs.pop("metric", "inv_neta"), **kwargs)

    def analizar_vehiculos(self, **kwargs: Any) -> dict[str, Any]:
        return self._ranking_bicomp(dimension="vehiculo", metric=kwargs.pop("metric", "inv_neta"), **kwargs)

    def consultar_inserciones(self, *, filters: dict[str, Any] | None = None, start_date: str | date | None = None, end_date: str | date | None = None) -> dict[str, Any]:
        return self.consultar_inversion(metric="total_insercion", filters=filters, start_date=start_date, end_date=end_date)

    def _catalog(self, dimension: str, *, filters: dict[str, Any] | None = None, limit: int = 1000, start_date=None, end_date=None) -> dict[str, Any]:
        self._bicomp_field(dimension)
        if not 1 <= limit <= 5000:
            raise ValueError("limit debe estar entre 1 y 5000.")
        cache_args = {"dimension": dimension, "filters": filters or {}, "limit": limit, "start_date": start_date, "end_date": end_date}
        cached = self._catalog_cache.get("catalog", cache_args)
        if cached is not None:
            return {**cached, "cache_hit": True}
        where, parameters = self._bicomp_filters(filters, start_date, end_date)
        parameters.append(("limit", "INT64", limit))
        result = self._execute_bicomp(QuerySpec(f"SELECT DISTINCT {self._dimension_group_expression(dimension)} AS value FROM `{self.bicomp_table}`{where} ORDER BY value LIMIT @limit", parameters))
        response = {"success": bool(result["rows"]), "domain": "bicomp", "source": "bigquery", "dimension": dimension, "values": [row["value"] for row in result["rows"]], "row_count": len(result["rows"]),
                **({"error": "La consulta BICOMP no produjo resultados."} if not result["rows"] else {}), "evidence": result["evidence"]}
        self._catalog_cache.put("catalog", cache_args, response)
        return response

    def obtener_anunciantes(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("anunciante", **kwargs)
    def obtener_marcas(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("marca", **kwargs)
    def obtener_medios(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("medio", **kwargs)
    def obtener_medios_agrupados(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("medio_agrupado", **kwargs)
    def obtener_vehiculos(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("vehiculo", **kwargs)
    def obtener_formatos(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("formato", **kwargs)
    def obtener_dispositivos(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("dispositivo", **kwargs)
    def obtener_ciudades(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("ciudad", **kwargs)
    def obtener_regiones(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("region", **kwargs)
    def obtener_tipos_pauta(self, **kwargs: Any) -> dict[str, Any]: return self._catalog("tipo_pauta", **kwargs)

    def obtener_rango_fechas(self) -> dict[str, Any]:
        cached = self._coverage_cache.get("coverage", {})
        if cached is not None:
            return {**cached, "cache_hit": True}
        self._bicomp_field("fecha")
        result = self._execute_bicomp(QuerySpec(f"SELECT MIN(DATE(`fecha`)) AS `start`, MAX(DATE(`fecha`)) AS `end`, COUNT(*) AS source_rows FROM `{self.bicomp_table}`", []))
        row = result["rows"][0] if result["rows"] else {"start": None, "end": None, "source_rows": 0}
        has_data = bool(row.get("source_rows")) and row.get("start") is not None and row.get("end") is not None
        response = {
            "success": has_data,
            "source": "bigquery",
            "start": str(row["start"]) if row.get("start") is not None else None,
            "end": str(row["end"]) if row.get("end") is not None else None,
            "row_count": row.get("source_rows", 0),
            **({"error": "BICOMP no tiene cobertura temporal utilizable."} if not has_data else {}),
            "evidence": result["evidence"],
        }

        self._coverage_cache.put("coverage", {}, response)
        return response

    def obtener_cobertura_bicomp(self) -> dict[str, Any]:
        period = self.obtener_rango_fechas()
        return {**period, "domain": "bicomp", "period": {"start": period.get("start"), "end": period.get("end")},
                "schema": self.get_bicomp_schema()}

    def serie_temporal_bicomp(
        self,
        *,
        metric: str = "inv_neta",
        granularity: str = "month",
        filters: dict[str, Any] | None = None,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> dict[str, Any]:
        self._bicomp_field(metric, metric=True)

        expressions = {
            "day": "DATE(`fecha`)",
            "week": "DATE_TRUNC(DATE(`fecha`), WEEK(MONDAY))",
            "month": "DATE_TRUNC(DATE(`fecha`), MONTH)",
        }
        expression = expressions.get(granularity)

        if expression is None:
            raise ValueError(
                "granularity debe ser day, week o month."
            )

        where, parameters = self._bicomp_filters(
            filters,
            start_date,
            end_date,
        )

        sql = f"""
        WITH grouped AS (
            SELECT
                {expression} AS period,
                SUM(`{metric}`) AS value,
                COUNT(*) AS source_rows,
                MIN(DATE(`fecha`)) AS _observed_start, MAX(DATE(`fecha`)) AS _observed_end
            FROM `{self.bicomp_table}`
            {where}
            GROUP BY period
        ),
        scored AS (
            SELECT
                period,
                value,
                source_rows,
                DENSE_RANK() OVER (ORDER BY value DESC) AS rank,
                SUM(value) OVER () AS total,
                MIN(_observed_start) OVER () AS _observed_start, MAX(_observed_end) OVER () AS _observed_end,
                SAFE_MULTIPLY(
                    SAFE_DIVIDE(value, SUM(value) OVER ()),
                    100
                ) AS share_of_total_pct
            FROM grouped
            WHERE value IS NOT NULL
        )
        SELECT
            period,
            value,
            source_rows,
            rank,
            share_of_total_pct,
            rank = 1 AS is_peak, total, _observed_start, _observed_end
        FROM scored
        ORDER BY period
        """

        result = self._scoped_execute(QuerySpec(sql, parameters))
        context = self._context(result, metric=metric, filters=filters, start_date=start_date, end_date=end_date)

        rows = sorted(result["rows"], key=lambda row: str(row.get("period", "")))
        has_data = bool(rows)

        statistics = describe_series(rows)
        peak_row = next(
            (
                row
                for row in rows
                if row.get("is_peak") is True
            ),
            None,
        )

        peak = None
        if peak_row is not None:
            peak = {
                "period": str(peak_row.get("period")),
                "value": peak_row.get("value"),
                "share_of_total_pct": peak_row.get(
                    "share_of_total_pct"
                ),
                "rank": peak_row.get("rank"),
            }

        return {
            **context,
            "success": has_data,
            "domain": "bicomp",
            "source": "bigquery",
            "metric": metric,
            "aggregation": "sum",
            "granularity": granularity,
            "filters": filters or {},
            "period": {
                "start": str(start_date) if start_date else None,
                "end": str(end_date) if end_date else None,
            },
            "rows": rows,
            "row_count": len(rows),
            "peak": peak, "statistics": statistics,
            **(
                {"error": "La consulta BICOMP no produjo resultados utilizables."}
                if not has_data
                else {}
            ),
            "query_metadata": {
                "bytes_processed": result["evidence"]["bytes_processed"],
                "duration_ms": result["evidence"]["duration_ms"],
            },
            "evidence": result["evidence"],
        }

    # ---- Generic DataRepository protocol methods (thin wrappers) ----
    # Added to satisfy the new source-agnostic contract without touching
    # the existing BICOMP-specific methods still used by the current registry.

    def consultar_metrica(self, *, metric: str = "inv_neta", filters: dict[str, Any] | None = None,
                           start_date: str | date | None = None, end_date: str | date | None = None) -> dict[str, Any]:
        return self.consultar_inversion(metric=metric, filters=filters, start_date=start_date, end_date=end_date)

    def ranking(self, *, dimension: str, metric: str = "inv_neta", filters: dict[str, Any] | None = None,
                start_date: str | date | None = None, end_date: str | date | None = None, limit: int = 10) -> dict[str, Any]:
        return self._ranking_bicomp(dimension=dimension, metric=metric, filters=filters, start_date=start_date, end_date=end_date, limit=limit)

    def serie_temporal(self, *, metric: str = "inv_neta", granularity: str = "month", filters: dict[str, Any] | None = None,
                        start_date: str | date | None = None, end_date: str | date | None = None) -> dict[str, Any]:
        return self.serie_temporal_bicomp(metric=metric, granularity=granularity, filters=filters, start_date=start_date, end_date=end_date)

    def catalogo(self, *, dimension: str, filters: dict[str, Any] | None = None, limit: int = 1000, start_date=None, end_date=None) -> dict[str, Any]:
        if dimension == "esquema":
            schema = self.get_bicomp_schema()
            return {"success": True, "source": "bigquery", "dimension": "esquema", "values": list(schema.keys()), "row_count": len(schema)}
        if dimension == "rango_fechas":
            return self.obtener_rango_fechas()
        return self._catalog(dimension, filters=filters, limit=limit, start_date=start_date, end_date=end_date)

    def comparar_entidades(self, *, dimension: str, value_a: str, value_b: str, metric: str = "inv_neta",
                            filters: dict[str, Any] | None = None, start_date: str | date | None = None,
                            end_date: str | date | None = None) -> dict[str, Any]:
        self._bicomp_field(dimension)
        first = self.consultar_inversion(metric=metric, filters={**(filters or {}), dimension: value_a}, start_date=start_date, end_date=end_date)
        second = self.consultar_inversion(metric=metric, filters={**(filters or {}), dimension: value_b}, start_date=start_date, end_date=end_date)
        a, b = first["value"], second["value"]
        difference = None if a is None or b is None else a - b
        missing = [label for label, value in ((value_a, a), (value_b, b)) if value is None]
        observations = [
            {'label': label, 'status': 'observed' if value is not None else ('no_rows' if not result.get('row_count') else 'non_numeric'),
             'source_rows': int(result.get('row_count') or 0), 'observed_value': value}
            for label, value, result in ((value_a, a, first), (value_b, b, second))
        ]
        clarification = {}
        if missing:
            catalog = self._catalog(dimension, filters=filters, start_date=start_date, end_date=end_date, limit=21)
            candidates = [v for v in catalog.get('values', []) if v is not None]
            if candidates and len(candidates) <= 20:
                clarification = {'dimension': dimension, 'missing_values': missing, 'available_values': candidates}
        return {"success": a is not None and b is not None, "domain": "bicomp", "source": "bigquery", "metric": metric,
                "metric_label": first.get("metric_label"), "unit": first.get("unit"), "aggregation": "sum",
                "clarification_options": clarification,
                **({"error": f"La consulta BICOMP no produjo resultados para {dimension}: " + ", ".join(missing) + "."} if missing else {}),
                **self._entity_gap(observations),
                "dimension": dimension, "value_a_label": value_a, "value_b_label": value_b,
                "filters": filters or {}, "period": first.get("period", {}), "coverage_a": first.get("effective_period"), "coverage_b": second.get("effective_period"),
                "requested_period": first.get("requested_period", {}), "effective_period": first.get("effective_period", {}), "is_partial": first.get("is_partial", False),
                "warnings": first.get("warnings", []) + second.get("warnings", []),
                "value_a": a, "value_b": b, "difference": difference,
                "difference_pct": None if difference is None or not b else difference / b * 100,
                "ratio_a_over_b": None if a is None or not b else a / b,
                "row_count": first["row_count"] + second["row_count"], "evidence": [first["evidence"], second["evidence"]] + ([catalog['evidence']] if missing else [])}

    def comparar_periodos(self, *, period_a: dict[str, str], period_b: dict[str, str], metric: str = "inv_neta", filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.comparar_periodos_bicomp(period_a=period_a, period_b=period_b, metric=metric, filters=filters)

    def explicar_variacion(self, *, entity_dimension: str = "marca", entity_value: str, current_period: dict[str, str], previous_period: dict[str, str], metric: str = "inv_neta", filters: dict[str, Any] | None = None, driver_limit: int = 20) -> dict[str, Any]:
        if entity_dimension != "marca":
            raise ValueError("Use analizar_drivers para una dimensión de entidad distinta de marca.")
        # Legacy brand-specific entry point; generic drivers are available separately.
        # TODO: hoy solo soporta entity_dimension="marca" y drivers fijos
        # (medio, vehiculo, formato) porque explicar_variacion_bicomp está
        # hardcodeado así. Generalizar cuando haya un segundo caso de uso real.
        return self.explicar_variacion_bicomp(brand=entity_value, current_period=current_period, previous_period=previous_period, metric=metric, filters=filters, driver_limit=driver_limit)

    def _full_dimension(self, dimension, metric, filters, period):
        self._bicomp_field(metric, metric=True)
        expression = self._dimension_group_expression(dimension)
        where, parameters = self._bicomp_filters(filters, period.get('start'), period.get('end'))
        sql = (f'SELECT {expression} AS dimension, SUM(`{metric}`) AS value, COUNT(*) AS source_rows, '
               f'MIN(DATE(`fecha`)) AS _observed_start, MAX(DATE(`fecha`)) AS _observed_end '
               f'FROM `{self.bicomp_table}`{where} GROUP BY dimension')
        result = self._scoped_execute(QuerySpec(sql, parameters))
        return {**result, **self._context(result, metric=metric, filters=filters, start_date=period.get('start'), end_date=period.get('end'))}

    def analizar_drivers(self, *, dimension, period_a, period_b, metric='inv_neta', filters=None, limit=10):
        """One partition of the change, with equivalent windows and complete categories."""
        if not 1 <= limit <= 100:
            raise ValueError('limit debe estar entre 1 y 100.')
        available = self.obtener_rango_fechas()
        a, b = equivalent_periods(period_a, period_b, available)
        current = self._full_dimension(dimension, metric, filters, a)
        previous = self._full_dimension(dimension, metric, filters, b)
        evidence = [current['evidence'], previous['evidence']]
        if not available.get('cache_hit') and available.get('evidence'):
            evidence.insert(0, available['evidence'])
        calculated = self._partition_difference(current, previous, dimension, limit)
        if not calculated['success']:
            return calculated
        return {**calculated, 'success': True, 'source': self.source, 'domain': 'bicomp', 'metric': metric, 'filters': filters or {},
                'dimension': dimension, 'period_a': a, 'period_b': b, 'current_period': a, 'previous_period': b,
                'requested_period_a': period_a, 'requested_period_b': period_b, 'comparison_equivalent': True,
                'evidence': evidence, **coverage(period_a, available, current.get('observed_period', {})),
                'warnings': ['Contribuciones contables de una dimensión; no demuestran causas de negocio.']}

    def _partition_difference(self, current, previous, dimension, limit):
        if not current['rows'] or not previous['rows'] or any(r['value'] is None for r in current['rows'] + previous['rows']):
            return {'success': False, 'source': self.source, 'error_type': 'no_data',
                    'error': 'No hay datos numéricos completos en ambos periodos; no se asume cero.', 'drivers': [], 'evidence': [current['evidence'], previous['evidence']]}
        cm = {str(r['dimension']): r['value'] for r in current['rows']}
        pm = {str(r['dimension']): r['value'] for r in previous['rows']}
        va, vb = sum(cm.values()), sum(pm.values())
        summary = compare(va, vb)
        rows = []
        for key in cm.keys() | pm.keys():
            x, y = cm.get(key, 0), pm.get(key, 0)
            delta = x - y
            rows.append({'dimension': dimension, 'value': key, 'current_value': x, 'previous_value': y,
                         'difference': delta, 'difference_pct': percentage(delta, y), 'contribution': delta,
                         'contribution_pct': percentage(delta, summary['difference']),
                         'current_share_pct': percentage(x, va), 'previous_share_pct': percentage(y, vb),
                         'mix_change_pp': None if not va or not vb else percentage(x, va) - percentage(y, vb)})
        rows.sort(key=lambda r: (-abs(r['contribution']), r['value']))
        narrative_rows = rows[:min(limit, 4)]
        shown_contribution = sum(row['contribution'] for row in narrative_rows)
        residual_contribution = summary['difference'] - shown_contribution
        driver_closure = {
            'shown_count': len(narrative_rows),
            'shown_contribution': shown_contribution,
            'omitted_count': len(rows) - len(narrative_rows),
            'residual_contribution': residual_contribution,
            'residual_contribution_pct': percentage(residual_contribution, summary['difference']),
        }
        return {'success': True, 'value_a': va, 'value_b': vb, 'current_value': va, 'previous_value': vb,
                **summary, 'change': summary['difference'], 'change_pct': summary['difference_pct'],
                'drivers': rows[:limit], 'drivers_total': len(rows), 'driver_closure': driver_closure}

    def explicar_diferencia_entidades(self, *, entity_dimension, value_a, value_b, dimension,
                                     metric='inv_neta', filters=None, start_date=None, end_date=None, limit=10):
        """Partition an entity difference within the same period; no temporal inference."""
        self._bicomp_field(entity_dimension)
        if entity_dimension == dimension:
            raise ValueError('El desglose debe ser distinto de la dimensión comparada.')
        if entity_dimension in (filters or {}):
            raise ValueError('El filtro limita la entidad comparada; retire ese filtro.')
        if not 1 <= limit <= 100:
            raise ValueError('Límite fuera de rango.')
        period = {'start': start_date, 'end': end_date}
        current = self._full_dimension(dimension, metric, {**(filters or {}), entity_dimension: value_a}, period)
        previous = self._full_dimension(dimension, metric, {**(filters or {}), entity_dimension: value_b}, period)
        calculated = self._partition_difference(current, previous, dimension, limit)
        if calculated.get('success') is not True:
            observations = []
            for label, partition in ((value_a, current), (value_b, previous)):
                rows = partition.get('rows') or []
                numeric = bool(rows) and all(row.get('value') is not None for row in rows)
                observations.append({
                    'label': label,
                    'status': 'observed' if numeric else ('no_rows' if not rows else 'non_numeric'),
                    'source_rows': sum(int(row.get('source_rows') or 0) for row in rows),
                    'group_count': len(rows),
                    'observed_value': sum(row['value'] for row in rows) if numeric else None,
                })
            calculated.update(self._entity_gap(observations))
        return {**calculated, 'source': self.source, 'domain': 'bicomp', 'metric': metric,
                'metric_label': current.get('metric_label'), 'filters': filters or {},
                'entity_dimension': entity_dimension, 'dimension': dimension,
                'value_a_label': value_a, 'value_b_label': value_b, 'comparison_type': 'entities',
                **{k: current.get(k) for k in ('requested_period', 'effective_period', 'observed_period', 'available_period', 'is_partial')},
                'evidence': [current['evidence'], previous['evidence']],
                'warnings': ['Contribuciones contables entre entidades en el mismo periodo; no representan crecimiento temporal ni causas de negocio.']}

    def calcular_ratio(self, *, numerator, denominator, filters=None, start_date=None, end_date=None):
        self._bicomp_field(numerator, metric=True)
        self._bicomp_field(denominator, metric=True)
        where, parameters = self._bicomp_filters(filters, start_date, end_date)
        sql = (f'SELECT SUM(`{numerator}`) AS numerator, SUM(`{denominator}`) AS denominator, '
               f'SAFE_DIVIDE(SUM(`{numerator}`), SUM(`{denominator}`)) AS value, COUNT(*) AS source_rows, '
               f'MIN(DATE(`fecha`)) AS _observed_start, MAX(DATE(`fecha`)) AS _observed_end FROM `{self.bicomp_table}`{where}')
        result = self._scoped_execute(QuerySpec(sql, parameters))
        context = self._context(result, metric=numerator, filters=filters, start_date=start_date, end_date=end_date)
        row = result['rows'][0] if result['rows'] else {}
        success = row.get('value') is not None
        metrics = load_semantic_layer()['metrics']
        return {**context, **row, 'success': success, 'metric': f'{numerator}/{denominator}',
                'metric_label': f"Cociente {metrics[numerator]['description']} / {metrics[denominator]['description']}",
                'unit': 'ratio',
                'numerator_metric': numerator, 'denominator_metric': denominator,
                **({} if success else {'error_type': 'no_data', 'error': 'Cociente no definido: denominador cero/nulo o sin datos.'}),
                'evidence': result['evidence']}

    def consultar_participacion(self, *, dimension, values, metric='inv_neta', filters=None, start_date=None, end_date=None):
        if dimension in (filters or {}):
            raise ValueError('El filtro de la dimensión del share limitaría el denominador. Use valores para el numerador.')
        result = self._full_dimension(dimension, metric, filters, {'start': start_date, 'end': end_date})
        valid = [r for r in result['rows'] if r.get('value') is not None]
        total = sum(r['value'] for r in valid)
        wanted = {v.strip().upper() for v in values}
        matched = [r for r in valid if str(r['dimension']).strip().upper() in wanted]
        value = sum(r['value'] for r in matched)
        missing = sorted(wanted - {str(r['dimension']).strip().upper() for r in matched})
        success = bool(matched) and bool(total) and not missing and len(valid) == len(result['rows'])
        return {**{k: v for k, v in result.items() if k != 'rows'}, 'success': success, 'missing_values': missing,
                'dimension': dimension, 'values': values, 'value': value, 'total': total,
                'share_pct': percentage(value, total), 'denominator_scope': filters or {},
                **({} if success else {'error_type': 'no_data', 'error': 'Faltan entidades exactas o un denominador completo para participación.',
                    'clarification_options': {'dimension': dimension, 'missing_values': missing, 'available_values': [r['dimension'] for r in valid[:10]]}})}

    def ranking_segmentado(self, *, dimension, group_dimension, metric='inv_neta', filters=None,
                           start_date=None, end_date=None, limit=5):
        """Top N within each group, with denominators computed before filtering ranks."""
        if dimension == group_dimension:
            raise ValueError('La dimensión clasificada y la agrupadora deben ser distintas.')
        if not 1 <= limit <= 100:
            raise ValueError('Límite fuera de rango.')
        self._bicomp_field(metric, metric=True)
        ranked = self._dimension_group_expression(dimension)
        grouped = self._dimension_group_expression(group_dimension)
        where, parameters = self._bicomp_filters(filters, start_date, end_date)
        parameters.append(('limit', 'INT64', limit))
        sql = f'''WITH grouped AS (
            SELECT {grouped} AS segment, {ranked} AS dimension, SUM(`{metric}`) AS value,
                   MIN(DATE(fecha)) AS _observed_start, MAX(DATE(fecha)) AS _observed_end
            FROM `{self.bicomp_table}`{where} GROUP BY segment, dimension
        ), scored AS (
            SELECT *, SUM(value) OVER (PARTITION BY segment) AS group_total,
                   DENSE_RANK() OVER (PARTITION BY segment ORDER BY value DESC) AS rank,
                   MIN(_observed_start) OVER () AS _scope_start,
                   MAX(_observed_end) OVER () AS _scope_end
            FROM grouped WHERE value IS NOT NULL
        )
        SELECT segment, dimension, value, group_total, rank,
               SAFE_DIVIDE(value, group_total) * 100 AS share_pct,
               _scope_start AS _observed_start, _scope_end AS _observed_end,
               COUNT(*) OVER () AS ranked_rows_total
        FROM scored WHERE rank <= @limit
        ORDER BY CAST(segment AS STRING), rank, CAST(dimension AS STRING)
        LIMIT 500'''
        result = self._scoped_execute(QuerySpec(sql, parameters))
        context = self._context(result, metric=metric, filters=filters, start_date=start_date, end_date=end_date)
        rows = sorted(result['rows'], key=lambda r: (str(r['segment']), r['rank'], str(r['dimension'])))
        truncated = bool(rows and rows[0]['ranked_rows_total'] > len(rows))
        warnings = [*context.get('warnings', []), 'Participaciones calculadas dentro de cada grupo; los porcentajes de grupos diferentes no se suman.',
                    'La respuesta selecciona hallazgos; el ranking devuelto por grupo está disponible en la evidencia.']
        if any(row.get('segment') is None or str(row.get('segment')).strip().upper() in MISSING_LABELS for row in rows):
            warnings.append(f'Hay grupos sin información en {group_dimension}; no representan una entidad identificada.')
        if truncated:
            warnings.append('El resultado excede el límite de presentación de filas; requiere acotar el alcance para verlo completo.')
        return {**context, 'success': bool(rows), 'dimension': dimension, 'segment_dimension': group_dimension,
                'dimensions': [group_dimension, dimension], 'rows': rows, 'ranking_truncated': truncated,
                'row_count': len(rows), 'warnings': warnings, 'evidence': result['evidence'],
                **({} if rows else {'error_type': 'no_data', 'error': 'No hay grupos con datos numéricos.'})}
