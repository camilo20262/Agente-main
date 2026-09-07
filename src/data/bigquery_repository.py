"""Parameterized, read-only BigQuery repository with query evidence."""

from __future__ import annotations

from datetime import date
from dataclasses import dataclass
from functools import lru_cache
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
        self._catalog_cache: dict[str, dict[str, Any]] = {}
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
        rows = [dict(row.items()) for row in job.result()]
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "success": True, "source": self.source, "rows": rows, "row_count": len(rows),
            "evidence": {"sql": sql, "query_parameters": {n: str(v) for n, _, v in spec.parameters},
                         "bytes_processed": int(getattr(job, "total_bytes_processed", estimated) or estimated),
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
        return field

    def _bicomp_filters(self, filters: dict[str, Any] | None, start_date: str | date | None, end_date: str | date | None) -> tuple[str, list[tuple[str, str, Any]]]:
        if filters is not None and not isinstance(filters, dict):
            raise TypeError(f"'filtros' debe ser un objeto JSON (diccionario), se recibió {type(filters).__name__}: {filters!r}")
        clauses: list[str] = []
        parameters: list[tuple[str, str, Any]] = []
        for index, (field, value) in enumerate((filters or {}).items()):
            self._bicomp_field(field)
            name = f"filter_{index}"
            if isinstance(value, (list, tuple)):
                clauses.append(f"UPPER(CAST(`{field}` AS STRING)) IN UNNEST(@{name})")
                parameters.append((name, "STRING", [str(item).upper() for item in value]))
            else:
                clauses.append(f"UPPER(CAST(`{field}` AS STRING)) = @{name}")
                parameters.append((name, "STRING", str(value).upper()))
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

    def consultar_inversion(self, *, metric: str = "inv_neta", filters: dict[str, Any] | None = None, start_date: str | date | None = None, end_date: str | date | None = None) -> dict[str, Any]:
        self._bicomp_field(metric, metric=True)
        where, parameters = self._bicomp_filters(filters, start_date, end_date)
        result = self._execute_bicomp(QuerySpec(f"SELECT SUM(`{metric}`) AS value, COUNT(*) AS source_rows FROM `{self.bicomp_table}`{where}", parameters))
        row = result["rows"][0] if result["rows"] else {"value": None, "source_rows": 0}
        has_data = bool(row.get("source_rows"))
        return {"success": has_data, "domain": "bicomp", "source": "bigquery", "project": self.settings.gcp_project_id,
                "dataset": self.settings.bigquery_dataset, "table": self.settings.bigquery_bicomp_table,
                "metric": metric, "aggregation": "sum", "filters": filters or {}, "period": {"start": str(start_date) if start_date else None, "end": str(end_date) if end_date else None},
                "value": row.get("value"), "row_count": row.get("source_rows", 0),
                **({"error": "La consulta BICOMP no produjo resultados."} if not has_data else {}),
                "query_metadata": {"bytes_processed": result["evidence"]["bytes_processed"], "duration_ms": result["evidence"]["duration_ms"]},
                "evidence": result["evidence"]}

    def comparar_marcas(self, *, brand_a: str, brand_b: str, metric: str = "inv_neta", filters: dict[str, Any] | None = None, start_date: str | date | None = None, end_date: str | date | None = None) -> dict[str, Any]:
        first = self.consultar_inversion(metric=metric, filters={**(filters or {}), "marca": brand_a}, start_date=start_date, end_date=end_date)
        second = self.consultar_inversion(metric=metric, filters={**(filters or {}), "marca": brand_b}, start_date=start_date, end_date=end_date)
        a, b = first["value"], second["value"]
        difference = None if a is None or b is None else a - b
        return {"success": True, "domain": "bicomp", "source": "bigquery", "metric": metric, "aggregation": "sum", "brand_a": brand_a, "brand_b": brand_b,
                "value_a": a, "value_b": b, "difference": difference, "difference_pct": None if difference is None or not b else difference / b * 100,
                "ratio_a_over_b": None if a is None or not b else a / b,
                "row_count": first["row_count"] + second["row_count"], "evidence": [first["evidence"], second["evidence"]]}

    def comparar_periodos_bicomp(self, *, period_a: dict[str, str], period_b: dict[str, str], metric: str = "inv_neta", filters: dict[str, Any] | None = None) -> dict[str, Any]:
        for period in (period_a, period_b):
            if not period.get("start") or not period.get("end"):
                raise ValueError("Cada periodo debe incluir start y end en formato ISO.")
        a = self.consultar_inversion(metric=metric, filters=filters, start_date=period_a["start"], end_date=period_a["end"])
        b = self.consultar_inversion(metric=metric, filters=filters, start_date=period_b["start"], end_date=period_b["end"])
        va, vb = a.get("value"), b.get("value")
        difference = None if va is None or vb is None else va - vb
        return {"success": difference is not None, "domain": "bicomp", "source": "bigquery", "metric": metric, "aggregation": "sum",
                "period_a": period_a, "period_b": period_b, "value_a": va, "value_b": vb, "difference": difference,
                "difference_pct": None if difference is None or not vb else difference / vb * 100,
                "ratio_a_over_b": None if va is None or not vb else va / vb, "filters": filters or {},
                "row_count": a.get("row_count", 0) + b.get("row_count", 0), "evidence": [a.get("evidence"), b.get("evidence")]}

    def explicar_variacion_bicomp(self, *, brand: str, current_period: dict[str, str], previous_period: dict[str, str], metric: str = "inv_neta", filters: dict[str, Any] | None = None, driver_limit: int = 20) -> dict[str, Any]:
        if not 1 <= driver_limit <= 100:
            raise ValueError("limit debe estar entre 1 y 100.")
        base_filters = {**(filters or {}), "marca": brand}
        comparison = self.comparar_periodos_bicomp(period_a=current_period, period_b=previous_period, metric=metric, filters=base_filters)
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
                "drivers": drivers[:driver_limit], "row_count": comparison["row_count"], "evidence": evidence}

    def _totales_dimension_bicomp(self, *, dimension: str, metric: str, filters: dict[str, Any] | None, start_date: str | date | None, end_date: str | date | None) -> dict[str, Any]:
        """Return complete dimension totals for variation drivers."""
        self._bicomp_field(dimension); self._bicomp_field(metric, metric=True)
        where, parameters = self._bicomp_filters(filters, start_date, end_date)
        # Do not cap categories before subtraction: that would distort drivers.
        # _execute_bicomp uses _execute's dry-run check and maximum_bytes_billed
        # to enforce the configured cost limit on these full aggregations.
        sql = f"SELECT `{dimension}` AS dimension, SUM(`{metric}`) AS value FROM `{self.bicomp_table}`{where} GROUP BY dimension"
        return self._execute_bicomp(QuerySpec(sql, parameters))

    def _ranking_bicomp(self, *, dimension: str, metric: str, filters: dict[str, Any] | None, start_date: str | date | None, end_date: str | date | None, limit: int) -> dict[str, Any]:
        self._bicomp_field(dimension); self._bicomp_field(metric, metric=True)
        if not 1 <= limit <= 100:
            raise ValueError("limit debe estar entre 1 y 100.")
        where, parameters = self._bicomp_filters(filters, start_date, end_date)
        parameters.append(("limit", "INT64", limit))
        sql = f"SELECT `{dimension}` AS dimension, SUM(`{metric}`) AS value, COUNT(*) AS source_rows FROM `{self.bicomp_table}`{where} GROUP BY dimension ORDER BY value DESC LIMIT @limit"
        result = self._execute_bicomp(QuerySpec(sql, parameters))
        return {"success": bool(result["rows"]), "domain": "bicomp", "source": "bigquery", "project": self.settings.gcp_project_id,
                "dataset": self.settings.bigquery_dataset, "table": self.settings.bigquery_bicomp_table,
                "metric": metric, "aggregation": "sum", "dimension": dimension, "filters": filters or {}, "rows": result["rows"], "row_count": len(result["rows"]),
                "query_metadata": {"bytes_processed": result["evidence"]["bytes_processed"], "duration_ms": result["evidence"]["duration_ms"]}, "evidence": result["evidence"]}

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

    def _catalog(self, dimension: str, *, filters: dict[str, Any] | None = None, limit: int = 1000) -> dict[str, Any]:
        self._bicomp_field(dimension)
        if not 1 <= limit <= 5000:
            raise ValueError("limit debe estar entre 1 y 5000.")
        cache_key = json.dumps([dimension, filters or {}, limit], sort_keys=True, default=str)
        if cache_key in self._catalog_cache:
            return self._catalog_cache[cache_key]
        where, parameters = self._bicomp_filters(filters, None, None)
        parameters.append(("limit", "INT64", limit))
        result = self._execute_bicomp(QuerySpec(f"SELECT DISTINCT `{dimension}` AS value FROM `{self.bicomp_table}`{where} ORDER BY value LIMIT @limit", parameters))
        response = {"success": bool(result["rows"]), "domain": "bicomp", "source": "bigquery", "dimension": dimension, "values": [row["value"] for row in result["rows"]], "row_count": len(result["rows"]),
                **({"error": "La consulta BICOMP no produjo resultados."} if not result["rows"] else {}), "evidence": result["evidence"]}
        self._catalog_cache[cache_key] = response
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
        self._bicomp_field("fecha")
        result = self._execute_bicomp(QuerySpec(f"SELECT MIN(DATE(`fecha`)) AS `start`, MAX(DATE(`fecha`)) AS `end`, COUNT(*) AS source_rows FROM `{self.bicomp_table}`", []))
        row = result["rows"][0]
        return {"success": True, "source": "bigquery", "start": str(row["start"]), "end": str(row["end"]), "row_count": row["source_rows"], "evidence": result["evidence"]}

    def obtener_cobertura_bicomp(self) -> dict[str, Any]:
        period = self.obtener_rango_fechas()
        return {"success": True, "domain": "bicomp", "source": "bigquery", "project": self.settings.gcp_project_id,
                "dataset": self.settings.bigquery_dataset, "table": self.settings.bigquery_bicomp_table,
                "period": {"start": period["start"], "end": period["end"]}, "row_count": period["row_count"],
                "schema": self.get_bicomp_schema(), "evidence": period["evidence"]}

    def serie_temporal_bicomp(self, *, metric: str = "inv_neta", granularity: str = "month", filters: dict[str, Any] | None = None, start_date: str | date | None = None, end_date: str | date | None = None) -> dict[str, Any]:
        self._bicomp_field(metric, metric=True)
        expressions = {"day": "DATE(`fecha`)", "week": "DATE_TRUNC(DATE(`fecha`), WEEK(MONDAY))", "month": "DATE_TRUNC(DATE(`fecha`), MONTH)"}
        expression = expressions.get(granularity)
        if expression is None:
            raise ValueError("granularity debe ser day, week o month.")
        where, parameters = self._bicomp_filters(filters, start_date, end_date)
        sql = f"SELECT {expression} AS period, SUM(`{metric}`) AS value, COUNT(*) AS source_rows FROM `{self.bicomp_table}`{where} GROUP BY period ORDER BY period"
        result = self._execute_bicomp(QuerySpec(sql, parameters))
        return {"success": bool(result["rows"]), "domain": "bicomp", "source": "bigquery", "metric": metric,
                "aggregation": "sum", "granularity": granularity, "rows": result["rows"], "row_count": len(result["rows"]), "evidence": result["evidence"]}

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

    def catalogo(self, *, dimension: str, filters: dict[str, Any] | None = None, limit: int = 1000) -> dict[str, Any]:
        if dimension == "esquema":
            schema = self.get_bicomp_schema()
            return {"success": True, "source": "bigquery", "dimension": "esquema", "values": list(schema.keys()), "row_count": len(schema)}
        if dimension == "rango_fechas":
            return self.obtener_rango_fechas()
        return self._catalog(dimension, filters=filters, limit=limit)

    def comparar_entidades(self, *, dimension: str, value_a: str, value_b: str, metric: str = "inv_neta",
                            filters: dict[str, Any] | None = None, start_date: str | date | None = None,
                            end_date: str | date | None = None) -> dict[str, Any]:
        self._bicomp_field(dimension)
        first = self.consultar_inversion(metric=metric, filters={**(filters or {}), dimension: value_a}, start_date=start_date, end_date=end_date)
        second = self.consultar_inversion(metric=metric, filters={**(filters or {}), dimension: value_b}, start_date=start_date, end_date=end_date)
        a, b = first["value"], second["value"]
        difference = None if a is None or b is None else a - b
        return {"success": True, "domain": "bicomp", "source": "bigquery", "metric": metric, "aggregation": "sum",
                "dimension": dimension, "value_a_label": value_a, "value_b_label": value_b,
                "value_a": a, "value_b": b, "difference": difference,
                "difference_pct": None if difference is None or not b else difference / b * 100,
                "ratio_a_over_b": None if a is None or not b else a / b,
                "row_count": first["row_count"] + second["row_count"], "evidence": [first["evidence"], second["evidence"]]}

    def comparar_periodos(self, *, period_a: dict[str, str], period_b: dict[str, str], metric: str = "inv_neta", filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.comparar_periodos_bicomp(period_a=period_a, period_b=period_b, metric=metric, filters=filters)

    def explicar_variacion(self, *, entity_dimension: str = "marca", entity_value: str, current_period: dict[str, str], previous_period: dict[str, str], metric: str = "inv_neta", filters: dict[str, Any] | None = None, driver_limit: int = 20) -> dict[str, Any]:
        # TODO: hoy solo soporta entity_dimension="marca" y drivers fijos
        # (medio, vehiculo, formato) porque explicar_variacion_bicomp está
        # hardcodeado así. Generalizar cuando haya un segundo caso de uso real.
        return self.explicar_variacion_bicomp(brand=entity_value, current_period=current_period, previous_period=previous_period, metric=metric, filters=filters, driver_limit=driver_limit)
