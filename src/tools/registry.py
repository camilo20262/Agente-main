"""Single registry for tool schemas and their deterministic handlers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from jsonschema import FormatChecker, ValidationError, validate

from src.data.repository import DataRepository
from src.semantic import load_semantic_layer


Handler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(
        self,
        repository: DataRepository,
        bicomp_repository: Any | None = None,
    ):
        self.repository = repository
        self.bicomp_repository = bicomp_repository or repository
        self.semantic = load_semantic_layer()
        self._tools: dict[str, RegisteredTool] = {}
        self._register_defaults()

    def register(self, tool: RegisteredTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Herramienta duplicada: {tool.name}")
        self._tools[tool.name] = tool

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [
            tool.schema()
            for tool in self._tools.values()
        ]

    def _normalize_arguments(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Normaliza errores frecuentes de serialización o nombres de argumentos
        producidos por el LLM antes de validar el JSON Schema.

        Esto NO cambia el contrato oficial de las tools: simplemente tolera
        aliases frecuentes como limit/top y filtros serializados como string.
        """
        normalized = dict(arguments)

        # ------------------------------------------------------------------
        # 1. Aliases frecuentes en inglés -> nombres oficiales en español.
        # ------------------------------------------------------------------
        common_aliases = {
            "metric": "metrica",
            "aggregation": "agregacion",
            "filters": "filtros",
            "start_date": "fecha_inicio",
            "end_date": "fecha_fin",
        }

        for alias, official in common_aliases.items():
            if alias in normalized:
                if official not in normalized:
                    normalized[official] = normalized[alias]
                normalized.pop(alias, None)

        # ------------------------------------------------------------------
        # 2. Algunos modelos envían filtros como JSON serializado:
        #    '{"marca": "Volvo"}'
        #    La tool requiere un objeto:
        #    {"marca": "Volvo"}
        # ------------------------------------------------------------------
        filtros = normalized.get("filtros")

        if isinstance(filtros, str):
            try:
                parsed = json.loads(filtros)
                if isinstance(parsed, dict):
                    normalized["filtros"] = parsed
            except json.JSONDecodeError:
                # Si no es JSON válido, dejamos el valor original para que
                # jsonschema produzca un error claro y trazable.
                pass

        # ------------------------------------------------------------------
        # 3. Normalización de limite.
        #    El contrato oficial usa "limite", pero algunos modelos intentan
        #    "limit" o "top".
        # ------------------------------------------------------------------
        tools_with_limit = {
            "ranking_anunciantes",
            "ranking_marcas",
            "analizar_medios",
            "analizar_vehiculos",
            "ranking_por_dimension",
            "obtener_catalogo_bicomp",
        }

        if name in tools_with_limit:
            if "limite" not in normalized:
                if "limit" in normalized:
                    normalized["limite"] = normalized["limit"]
                elif "top" in normalized:
                    normalized["limite"] = normalized["top"]

            # Eliminar aliases para no chocar con additionalProperties=False.
            normalized.pop("limit", None)
            normalized.pop("top", None)

        # Algunos proveedores serializan enteros como strings, por ejemplo "5".
        if "limite" in normalized and isinstance(normalized["limite"], str):
            value = normalized["limite"].strip()
            if value.isdigit():
                normalized["limite"] = int(value)

        if (
            "limite_drivers" in normalized
            and isinstance(normalized["limite_drivers"], str)
        ):
            value = normalized["limite_drivers"].strip()
            if value.isdigit():
                normalized["limite_drivers"] = int(value)

        return normalized

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        tool = self._tools.get(name)

        if tool is None:
            return {
                "success": False,
                "error": f"Herramienta desconocida: {name}",
            }

        # Normalizar antes de validar.
        arguments = self._normalize_arguments(
            name,
            arguments,
        )

        try:
            validate(
                arguments,
                tool.parameters,
                format_checker=FormatChecker(),
            )
        except ValidationError as exc:
            path = (
                ".".join(
                    str(part)
                    for part in exc.absolute_path
                )
                or "arguments"
            )

            return {
                "success": False,
                "source": self.repository.source,
                "error": (
                    f"Argumentos inválidos para '{name}': "
                    f"{path}: {exc.message}"
                ),
            }

        try:
            result = tool.handler(arguments)

            if "success" not in result:
                result = {
                    "success": "error" not in result,
                    "source": self.repository.source,
                    **result,
                }

            return result

        except (
            ValueError,
            TypeError,
            RuntimeError,
            KeyError,
            AttributeError,
        ) as exc:
            return {
                "success": False,
                "source": self.repository.source,
                "error": str(exc),
            }

    def _register_defaults(self) -> None:
        self._register_bicomp_tools()

    def _register_bicomp_tools(self) -> None:
        metrics = [
            "inv_bruta",
            "inv_neta",
            "inv_bruta_usd",
            "inv_neta_usd",
            "total_insercion",
            "total_duracion",
        ]

        dimensions = [
            "pais",
            "sector",
            "subsector",
            "categoria",
            "anunciante",
            "anunciante_agrupado",
            "holding",
            "central",
            "agencia",
            "marca",
            "marca_agrupada",
            "producto",
            "medio",
            "medio_agrupado",
            "vehiculo",
            "soporte",
            "franja",
            "genero",
            "region",
            "ciudad",
            "formato",
            "dispositivo",
            "tipo_pauta",
        ]

        common = {
            "metrica": {
                "type": "string",
                "enum": metrics,
            },
            "agregacion": {
                "type": "string",
                "enum": ["sum"],
            },
            "filtros": {
                "type": "object",
                "additionalProperties": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "number"},
                        {"type": "boolean"},
                        {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    ]
                },
            },
            "fecha_inicio": {
                "type": "string",
                "format": "date",
            },
            "fecha_fin": {
                "type": "string",
                "format": "date",
            },
        }

        self.register(
            RegisteredTool(
                "consultar_inversion_publicitaria",
                (
                    "Suma inversión publicitaria real en BICOMP. "
                    "Nunca calcules la suma manualmente. "
                    "Usa 'filtros' como objeto JSON, por ejemplo "
                    '{"marca": "Volvo"}.'
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": common,
                },
                lambda a: self._bicomp(
                    "consultar_inversion",
                    a,
                ),
            )
        )

        self.register(
            RegisteredTool(
                "comparar_marcas",
                (
                    "Compara dos marcas con cálculos reales de BICOMP. "
                    "Mantén el mismo periodo y métrica para ambas marcas."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        **common,
                        "marca_a": {"type": "string"},
                        "marca_b": {"type": "string"},
                    },
                    "required": [
                        "marca_a",
                        "marca_b",
                    ],
                },
                lambda a: self._bicomp(
                    "comparar_marcas",
                    a,
                ),
            )
        )

        ranking = {
            **common,
            "limite": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
            },
        }

        self.register(
            RegisteredTool(
                "ranking_anunciantes",
                (
                    "Ranking de anunciantes calculado por BigQuery. "
                    "Para controlar la cantidad de resultados usa "
                    "exclusivamente el parámetro 'limite' (1 a 100). "
                    "No uses 'limit' ni 'top'."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": ranking,
                },
                lambda a: self._bicomp(
                    "ranking_anunciantes",
                    a,
                ),
            )
        )

        self.register(
            RegisteredTool(
                "ranking_marcas",
                (
                    "Ranking de marcas calculado por BigQuery. "
                    "Para controlar la cantidad de resultados usa "
                    "exclusivamente el parámetro 'limite' (1 a 100). "
                    "No uses 'limit' ni 'top'."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": ranking,
                },
                lambda a: self._bicomp(
                    "ranking_marcas",
                    a,
                ),
            )
        )

        self.register(
            RegisteredTool(
                "analizar_medios",
                (
                    "Distribuye inversión u otra métrica BICOMP por medio. "
                    "Para controlar la cantidad de resultados usa "
                    "exclusivamente 'limite' (1 a 100). "
                    "No uses 'limit' ni 'top'. "
                    "Conserva los filtros de la pregunta original."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": ranking,
                },
                lambda a: self._bicomp(
                    "analizar_medios",
                    a,
                ),
            )
        )

        self.register(
            RegisteredTool(
                "analizar_vehiculos",
                (
                    "Distribuye inversión u otra métrica BICOMP por vehículo. "
                    "Para controlar la cantidad de resultados usa "
                    "exclusivamente 'limite' (1 a 100). "
                    "No uses 'limit' ni 'top'. "
                    "Conserva los filtros de la pregunta original."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": ranking,
                },
                lambda a: self._bicomp(
                    "analizar_vehiculos",
                    a,
                ),
            )
        )

        # Generic dimension-agnostic ranking tool: reads valid dimensions from
        # the semantic layer (dimensions.yaml) so it works for any dimension
        # (region, sector, holding, ciudad, agencia, etc.), not just the four
        # hardcoded above. This makes the pattern reusable for future clients
        # too, since it adapts automatically to whatever dimensions.yaml lists.
        dimensiones_disponibles = list(
            self.semantic["dimensions"].keys()
        )

        ranking_generico = {
            **common,
            "dimension": {
                "type": "string",
                "enum": dimensiones_disponibles,
            },
            "limite": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
            },
        }

        self.register(
            RegisteredTool(
                "ranking_por_dimension",
                (
                    "Ranking de una métrica BICOMP agrupado por CUALQUIER "
                    "dimensión disponible (region, sector, holding, ciudad, "
                    "agencia, etc.), calculado por BigQuery. Usa esta "
                    "herramienta cuando se pida un desglose por una dimensión "
                    "que no sea anunciante, marca, medio o vehículo. "
                    "Para limitar resultados usa 'limite', no 'limit' ni 'top'."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": ranking_generico,
                    "required": ["dimension"],
                },
                lambda a: self._bicomp_repository_call(
                    "ranking",
                    dimension=a["dimension"],
                    metric=a.get(
                        "metrica",
                        "inv_neta",
                    ),
                    filters=a.get("filtros"),
                    start_date=a.get("fecha_inicio"),
                    end_date=a.get("fecha_fin"),
                    limit=a.get("limite", 10),
                ),
            )
        )

        self.register(
            RegisteredTool(
                "consultar_inserciones_bicomp",
                (
                    "Consulta el total real de inserciones BICOMP. "
                    "Usa 'filtros' como objeto JSON y conserva el alcance "
                    "de la pregunta original."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        k: v
                        for k, v in common.items()
                        if k != "metrica"
                    },
                },
                lambda a: self._bicomp(
                    "consultar_inserciones",
                    a,
                ),
            )
        )

        self.register(
            RegisteredTool(
                "obtener_catalogo_bicomp",
                (
                    "Obtiene anunciantes, marcas, medios, rango de fechas "
                    "o esquema disponibles en BICOMP. "
                    "Para limitar resultados usa 'limite'."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "catalogo": {
                            "type": "string",
                            "enum": [
                                "anunciantes",
                                "marcas",
                                "medios",
                                "medios_agrupados",
                                "vehiculos",
                                "formatos",
                                "dispositivos",
                                "ciudades",
                                "regiones",
                                "tipos_pauta",
                                "rango_fechas",
                                "esquema",
                            ],
                        },
                        "filtros": {
                            "type": "object",
                        },
                        "limite": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5000,
                        },
                    },
                    "required": ["catalogo"],
                },
                self._bicomp_catalog,
            )
        )

        self.register(
            RegisteredTool(
                "obtener_cobertura_bicomp",
                (
                    "Obtiene periodo, filas y esquema real disponible "
                    "en BICOMP."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
                lambda _a: self._bicomp_repository_call(
                    "obtener_cobertura_bicomp"
                ),
            )
        )

        self.register(
            RegisteredTool(
                "serie_temporal_bicomp",
                (
                    "Devuelve inversión o volumen BICOMP por día, semana "
                    "o mes para tendencias y gráficos. Conserva los filtros, "
                    "métrica y periodo de la pregunta original salvo que "
                    "la comparación requiera explícitamente otro alcance."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        **common,
                        "granularidad": {
                            "type": "string",
                            "enum": [
                                "day",
                                "week",
                                "month",
                            ],
                        },
                    },
                    "required": ["granularidad"],
                },
                self._bicomp_series,
            )
        )

        period = {
            "type": "object",
            "properties": {
                "start": {
                    "type": "string",
                    "format": "date",
                },
                "end": {
                    "type": "string",
                    "format": "date",
                },
            },
            "required": [
                "start",
                "end",
            ],
        }

        self.register(
            RegisteredTool(
                "comparar_periodos_bicomp",
                (
                    "Compara dos periodos BICOMP equivalentes con diferencias "
                    "calculadas determinísticamente. Conserva la misma métrica "
                    "y filtros entre ambos periodos."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "periodo_a": period,
                        "periodo_b": period,
                        "metrica": common["metrica"],
                        "filtros": common["filtros"],
                    },
                    "required": [
                        "periodo_a",
                        "periodo_b",
                    ],
                },
                self._bicomp_compare_periods,
            )
        )

        self.register(
            RegisteredTool(
                "explicar_variacion_bicomp",
                (
                    "Investiga una variación BICOMP mediante periodo "
                    "actual/anterior y drivers por medio, vehículo y formato. "
                    "Usa esta herramienta cuando ya exista una variación que "
                    "necesite explicación, no para una consulta básica."
                ),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "marca": {
                            "type": "string",
                        },
                        "periodo_actual": period,
                        "periodo_anterior": period,
                        "metrica": common["metrica"],
                        "filtros": common["filtros"],
                        "limite_drivers": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                    "required": [
                        "marca",
                        "periodo_actual",
                        "periodo_anterior",
                    ],
                },
                self._bicomp_explain_variation,
            )
        )

    def _bicomp_repository_call(
        self,
        method: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self.bicomp_repository is None:
            return {
                "success": False,
                "source": "bigquery",
                "error": (
                    "BigQuery no está configurado o no se tienen "
                    "permisos sobre la fuente BICOMP."
                ),
            }

        return getattr(
            self.bicomp_repository,
            method,
        )(**kwargs)

    def _bicomp(
        self,
        method_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        if self.bicomp_repository is None:
            return self._bicomp_repository_call(
                method_name
            )

        if args.get("agregacion", "sum") != "sum":
            raise ValueError(
                "BICOMP solo permite agregacion='sum' "
                "para estas métricas."
            )

        kwargs = {
            "filters": args.get("filtros"),
            "start_date": args.get("fecha_inicio"),
            "end_date": args.get("fecha_fin"),
        }

        if "metrica" in args:
            kwargs["metric"] = args["metrica"]

        if method_name == "comparar_marcas":
            kwargs.update(
                brand_a=args["marca_a"],
                brand_b=args["marca_b"],
            )

        if method_name in {
            "ranking_anunciantes",
            "ranking_marcas",
            "analizar_medios",
            "analizar_vehiculos",
        }:
            kwargs["limit"] = args.get(
                "limite",
                10,
            )

        return getattr(
            self.bicomp_repository,
            method_name,
        )(**kwargs)

    def _bicomp_series(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        return self._bicomp_repository_call(
            "serie_temporal_bicomp",
            metric=args.get(
                "metrica",
                "inv_neta",
            ),
            granularity=args["granularidad"],
            filters=args.get("filtros"),
            start_date=args.get("fecha_inicio"),
            end_date=args.get("fecha_fin"),
        )

    def _bicomp_compare_periods(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        return self._bicomp_repository_call(
            "comparar_periodos_bicomp",
            period_a=args["periodo_a"],
            period_b=args["periodo_b"],
            metric=args.get(
                "metrica",
                "inv_neta",
            ),
            filters=args.get("filtros"),
        )

    def _bicomp_explain_variation(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        return self._bicomp_repository_call(
            "explicar_variacion_bicomp",
            brand=args["marca"],
            current_period=args["periodo_actual"],
            previous_period=args["periodo_anterior"],
            metric=args.get(
                "metrica",
                "inv_neta",
            ),
            filters=args.get("filtros"),
            driver_limit=args.get(
                "limite_drivers",
                20,
            ),
        )

    def _bicomp_catalog(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        if self.bicomp_repository is None:
            return {
                "success": False,
                "source": "bigquery",
                "error": (
                    "BigQuery no está configurado o no se tienen "
                    "permisos sobre la fuente BICOMP."
                ),
            }

        catalog = args["catalogo"]

        if catalog == "esquema":
            schema = (
                self.bicomp_repository.get_bicomp_schema()
            )

            return {
                "success": True,
                "source": "bigquery",
                "catalog": "esquema",
                "fields": schema,
                "row_count": len(schema),
            }

        if catalog == "rango_fechas":
            return (
                self.bicomp_repository.obtener_rango_fechas()
            )

        method = {
            "anunciantes": "obtener_anunciantes",
            "marcas": "obtener_marcas",
            "medios": "obtener_medios",
            "medios_agrupados": "obtener_medios_agrupados",
            "vehiculos": "obtener_vehiculos",
            "formatos": "obtener_formatos",
            "dispositivos": "obtener_dispositivos",
            "ciudades": "obtener_ciudades",
            "regiones": "obtener_regiones",
            "tipos_pauta": "obtener_tipos_pauta",
        }[catalog]

        return getattr(
            self.bicomp_repository,
            method,
        )(
            filters=args.get("filtros"),
            limit=args.get(
                "limite",
                1000,
            ),
        )
