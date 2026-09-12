"""Single registry for tool schemas and their deterministic handlers."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import GoogleAuthError
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
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


class ToolRegistry:
    def __init__(self, repository: DataRepository, bicomp_repository: Any | None = None):
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
        return [tool.schema() for tool in self._tools.values()]

    @property
    def planning_catalog(self) -> list[dict[str, Any]]:
        """Avoid repeating the common scope schema for every planning capability."""
        common = {"metrica", "agregacion", "filtros", "fecha_inicio", "fecha_fin", "periodo_a", "periodo_b", "periodo_actual", "periodo_anterior"}
        # Legacy wrappers remain executable, but do not compete with generic capabilities.
        legacy = {'comparar_marcas', 'ranking_marcas', 'ranking_anunciantes', 'analizar_medios',
                  'analizar_vehiculos', 'consultar_inserciones_bicomp', 'explicar_variacion_bicomp',
                  'obtener_catalogo_bicomp'}
        return [{"name": tool.name, "description": tool.description,
                 "scope_arguments": sorted(common & set(tool.parameters.get("properties", {}))),
                 "required": [k for k in tool.parameters.get("required", []) if k not in common],
                 "parameters": {k: v for k, v in tool.parameters.get("properties", {}).items() if k not in common}}
                for tool in self._tools.values() if tool.name not in legacy]

    def normalize_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Normalize aliases without dropping conflicting filters or unknown fields."""
        if not isinstance(arguments, dict):
            raise ValueError("Los argumentos deben ser un objeto JSON.")
        args = deepcopy(arguments)
        properties = self._tools[name].parameters.get("properties", {}) if name in self._tools else {}
        aliases = {"metric": "metrica", "aggregation": "agregacion", "filters": "filtros",
                   "start_date": "fecha_inicio", "end_date": "fecha_fin", "limit": "limite", "top": "limite",
                   "granularity": "granularidad"}
        for alias, official in aliases.items():
            if alias in args and official in properties:
                if official in args:
                    raise ValueError(f"Argumentos contradictorios: {alias} y {official}; no se descarta ninguno silenciosamente.")
                args[official] = args.pop(alias)
        if isinstance(args.get("filtros"), str):
            args["filtros"] = json.loads(args["filtros"])
        for key in ("limite", "limite_drivers"):
            if isinstance(args.get(key), str) and args[key].isdigit():
                args[key] = int(args[key])
        return args

    _normalize_arguments = normalize_arguments

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"success": False, "error": f"Herramienta desconocida: {name}"}
        try:
            arguments = self.normalize_arguments(name, arguments)
            validate(arguments, tool.parameters, format_checker=FormatChecker())
        except (ValidationError, ValueError, TypeError) as exc:
            path = ".".join(str(part) for part in getattr(exc, "absolute_path", [])) or "arguments"
            return {"success": False, "source": self.repository.source,
                    "error_type": "arguments", "retryable": True,
                    "error": f"Argumentos inválidos para '{name}': {path}: {getattr(exc, 'message', str(exc))}"}
        try:
            result = tool.handler(arguments)
            if "success" not in result:
                result = {"success": "error" not in result, "source": self.repository.source, **result}
            return result
        except (GoogleAPICallError, GoogleAuthError, TimeoutError, ConnectionError, ImportError, ValueError, TypeError, RuntimeError, KeyError, AttributeError) as exc:
            name = type(exc).__name__
            kind = "schema" if name in {"BadRequest", "NotFound", "AttributeError", "KeyError"} else "arguments" if isinstance(exc, (ValueError, TypeError)) else "infrastructure"
            return {"success": False, "source": self.repository.source, "error": str(exc)[:800],
                    "error_type": kind, "retryable": kind in {"arguments", "schema"}}

    def _register_defaults(self) -> None:
        self._register_bicomp_tools()
        self._register_analytical_tools()

    def _register_bicomp_tools(self) -> None:
        metrics = list(self.semantic["metrics"])

        common = {"metrica": {"type": "string", "enum": metrics}, "agregacion": {"type": "string", "enum": ["sum"]},
                  "filtros": {"type": "object", "propertyNames": {"enum": list(self.semantic["dimensions"])}, "additionalProperties": {"oneOf": [
                      {"type": "string"}, {"type": "number"}, {"type": "boolean"},
                      {"type": "array", "items": {"type": "string"}},
                  ]}},
                  "fecha_inicio": {"type": "string", "format": "date"}, "fecha_fin": {"type": "string", "format": "date"}}
        self.register(RegisteredTool("consultar_inversion_publicitaria", "Suma inversión publicitaria real en BICOMP. Nunca calcules la suma manualmente.",
            {"type": "object", "additionalProperties": False, "properties": common}, lambda a: self._bicomp("consultar_inversion", a)))
        self.register(RegisteredTool("comparar_marcas", "Compara dos marcas con cálculos reales de BICOMP.",
            {"type": "object", "additionalProperties": False, "properties": {**common, "marca_a": {"type": "string"}, "marca_b": {"type": "string"}}, "required": ["marca_a", "marca_b"]}, lambda a: self._bicomp("comparar_marcas", a)))
        ranking = {**common, "limite": {"type": "integer", "minimum": 1, "maximum": 100}}
        self.register(RegisteredTool("ranking_anunciantes", "Ranking de anunciantes calculado por BigQuery.", {"type": "object", "additionalProperties": False, "properties": ranking}, lambda a: self._bicomp("ranking_anunciantes", a)))
        self.register(RegisteredTool("ranking_marcas", "Ranking de marcas calculado por BigQuery.", {"type": "object", "additionalProperties": False, "properties": ranking}, lambda a: self._bicomp("ranking_marcas", a)))
        self.register(RegisteredTool("analizar_medios", "Distribuye inversión u otra métrica BICOMP por medio.", {"type": "object", "additionalProperties": False, "properties": ranking}, lambda a: self._bicomp("analizar_medios", a)))
        self.register(RegisteredTool("analizar_vehiculos", "Distribuye inversión u otra métrica BICOMP por vehículo.", {"type": "object", "additionalProperties": False, "properties": ranking}, lambda a: self._bicomp("analizar_vehiculos", a)))
        # Generic dimension-agnostic ranking tool: reads valid dimensions from
        # the semantic layer (dimensions.yaml) so it works for any dimension
        # (region, sector, holding, ciudad, agencia, etc.), not just the four
        # hardcoded above. This makes the pattern reusable for future clients
        # too, since it adapts automatically to whatever dimensions.yaml lists.
        dimensiones_disponibles = list(self.semantic["dimensions"].keys())
        ranking_generico = {**common, "dimension": {"type": "string", "enum": dimensiones_disponibles}, "limite": {"type": "integer", "minimum": 1, "maximum": 100}}
        self.register(RegisteredTool(
            "ranking_por_dimension",
            "Ranking de una métrica BICOMP agrupado por CUALQUIER dimensión disponible (region, sector, holding, ciudad, agencia, etc.), calculado por BigQuery. Usa esta herramienta cuando se pida un desglose por una dimensión que no sea anunciante, marca, medio o vehículo.",
            {"type": "object", "additionalProperties": False, "properties": ranking_generico, "required": ["dimension"]},
            lambda a: self._bicomp_repository_call(
                "ranking", dimension=a["dimension"], metric=a.get("metrica", "inv_neta"),
                filters=a.get("filtros"), start_date=a.get("fecha_inicio"), end_date=a.get("fecha_fin"),
                limit=a.get("limite", 10))))
        self.register(RegisteredTool("consultar_inserciones_bicomp", "Consulta el total real de inserciones BICOMP.", {"type": "object", "additionalProperties": False, "properties": {k: v for k, v in common.items() if k != "metrica"}}, lambda a: self._bicomp("consultar_inserciones", a)))
        self.register(RegisteredTool("obtener_catalogo_bicomp", "Obtiene anunciantes, marcas, medios, rango de fechas o esquema disponibles en BICOMP.",
            {"type": "object", "additionalProperties": False, "properties": {"catalogo": {"type": "string", "enum": ["anunciantes", "marcas", "medios", "medios_agrupados", "vehiculos", "formatos", "dispositivos", "ciudades", "regiones", "tipos_pauta", "rango_fechas", "esquema"]}, "filtros": {"type": "object"}, "limite": {"type": "integer", "minimum": 1, "maximum": 5000}}, "required": ["catalogo"]}, self._bicomp_catalog))
        self.register(RegisteredTool("obtener_cobertura_bicomp", "Obtiene periodo, filas y esquema real disponible en BICOMP.", {"type": "object", "additionalProperties": False, "properties": {}}, lambda _a: self._bicomp_repository_call("obtener_cobertura_bicomp")))
        self.register(RegisteredTool("serie_temporal_bicomp", "Devuelve inversión o volumen BICOMP por día, semana o mes para tendencias y gráficos.",
            {"type": "object", "additionalProperties": False, "properties": {**common, "granularidad": {"type": "string", "enum": ["day", "week", "month"]}}, "required": ["granularidad"]}, self._bicomp_series))
        period = {"type": "object", "additionalProperties": False, "properties": {"start": {"type": "string", "format": "date"}, "end": {"type": "string", "format": "date"}}, "required": ["start", "end"]}
        self.register(RegisteredTool("comparar_periodos_bicomp", "Compara dos periodos BICOMP equivalentes con diferencias calculadas determinísticamente.",
            {"type": "object", "additionalProperties": False, "properties": {"periodo_a": period, "periodo_b": period, "metrica": common["metrica"], "filtros": common["filtros"]}, "required": ["periodo_a", "periodo_b"]}, self._bicomp_compare_periods))
        self.register(RegisteredTool("explicar_variacion_bicomp", "Investiga una variación BICOMP mediante periodo actual/anterior y drivers por medio, vehículo y formato.",
            {"type": "object", "additionalProperties": False, "properties": {"marca": {"type": "string"}, "periodo_actual": period, "periodo_anterior": period,
                "metrica": common["metrica"], "filtros": common["filtros"], "limite_drivers": {"type": "integer", "minimum": 1, "maximum": 50}},
             "required": ["marca", "periodo_actual", "periodo_anterior"]}, self._bicomp_explain_variation))

    def _bicomp_repository_call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        if self.bicomp_repository is None:
            return {"success": False, "source": "bigquery", "error": "BigQuery no está configurado o no se tienen permisos sobre la fuente BICOMP."}
        return getattr(self.bicomp_repository, method)(**kwargs)

    def _bicomp(self, method_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.bicomp_repository is None:
            return self._bicomp_repository_call(method_name)
        if args.get("agregacion", "sum") != "sum":
            raise ValueError("BICOMP solo permite agregacion='sum' para estas métricas.")
        kwargs = {"filters": args.get("filtros"), "start_date": args.get("fecha_inicio"), "end_date": args.get("fecha_fin")}
        if "metrica" in args:
            kwargs["metric"] = args["metrica"]
        if method_name == "comparar_marcas":
            kwargs.update(brand_a=args["marca_a"], brand_b=args["marca_b"])
        if method_name in {"ranking_anunciantes", "ranking_marcas", "analizar_medios", "analizar_vehiculos"}:
            kwargs["limit"] = args.get("limite", 10)
        return getattr(self.bicomp_repository, method_name)(**kwargs)

    def _bicomp_series(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._bicomp_repository_call("serie_temporal_bicomp", metric=args.get("metrica", "inv_neta"), granularity=args["granularidad"],
            filters=args.get("filtros"), start_date=args.get("fecha_inicio"), end_date=args.get("fecha_fin"))

    def _bicomp_compare_periods(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._bicomp_repository_call("comparar_periodos_bicomp", period_a=args["periodo_a"], period_b=args["periodo_b"],
            metric=args.get("metrica", "inv_neta"), filters=args.get("filtros"))

    def _bicomp_explain_variation(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._bicomp_repository_call("explicar_variacion_bicomp", brand=args["marca"], current_period=args["periodo_actual"],
            previous_period=args["periodo_anterior"], metric=args.get("metrica", "inv_neta"), filters=args.get("filtros"),
            driver_limit=args.get("limite_drivers", 20))

    def _bicomp_catalog(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.bicomp_repository is None:
            return {"success": False, "source": "bigquery", "error": "BigQuery no está configurado o no se tienen permisos sobre la fuente BICOMP."}
        catalog = args["catalogo"]
        if catalog == "esquema":
            schema = self.bicomp_repository.get_bicomp_schema()
            return {"success": True, "source": "bigquery", "catalog": "esquema", "fields": schema, "row_count": len(schema)}
        if catalog == "rango_fechas":
            return self.bicomp_repository.obtener_rango_fechas()
        method = {"anunciantes": "obtener_anunciantes", "marcas": "obtener_marcas", "medios": "obtener_medios",
                  "medios_agrupados": "obtener_medios_agrupados", "vehiculos": "obtener_vehiculos", "formatos": "obtener_formatos",
                  "dispositivos": "obtener_dispositivos", "ciudades": "obtener_ciudades", "regiones": "obtener_regiones", "tipos_pauta": "obtener_tipos_pauta"}[catalog]
        return getattr(self.bicomp_repository, method)(filters=args.get("filtros"), limit=args.get("limite", 1000))

    def _register_analytical_tools(self) -> None:
        common = deepcopy(self._tools["consultar_inversion_publicitaria"].parameters["properties"])
        dimension = {"type": "string", "enum": list(self.semantic["dimensions"])}
        limit = {"type": "integer", "minimum": 1, "maximum": 100}
        period = {"type": "object", "additionalProperties": False, "properties": {
            "start": {"type": "string", "format": "date"}, "end": {"type": "string", "format": "date"}}, "required": ["start", "end"]}
        def add(name, description, properties, required, handler):
            self.register(RegisteredTool(name, description, {"type": "object", "additionalProperties": False,
                "properties": properties, "required": required}, handler))
        def scope(a):
            return dict(metric=a.get("metrica", "inv_neta"), filters=a.get("filtros"), start_date=a.get("fecha_inicio"), end_date=a.get("fecha_fin"))
        add("ranking_segmentado_bicomp", "Top N de una dimensión DENTRO DE CADA GRUPO de otra dimensión. Shares con denominador por grupo; no es un ranking global.",
            {**common, "dimension": dimension, "dimension_grupo": dimension, "limite": limit},
            ["dimension", "dimension_grupo"],
            lambda a: self._bicomp_repository_call("ranking_segmentado", dimension=a["dimension"], group_dimension=a["dimension_grupo"], limit=a.get("limite", 5), **scope(a)))
        add("comparar_entidades_bicomp", "Compara dos valores de cualquier dimensión; diferencias y ratios deterministas.",
            {**common, "dimension": dimension, "valor_a": {"type": "string"}, "valor_b": {"type": "string"}},
            ["dimension", "valor_a", "valor_b"],
            lambda a: self._bicomp_repository_call("comparar_entidades", dimension=a["dimension"], value_a=a["valor_a"], value_b=a["valor_b"], **scope(a)))
        add("analizar_drivers_bicomp", "Compara periodos equivalentes y calcula contribuciones por UNA dimensión, sin exigir marca. Útil para caídas, crecimiento y cambios de mix.",
            {"metrica": common["metrica"], "filtros": common["filtros"], "dimension": dimension, "periodo_a": period, "periodo_b": period, "limite": limit},
            ["dimension", "periodo_a", "periodo_b"],
            lambda a: self._bicomp_repository_call("analizar_drivers", dimension=a["dimension"], period_a=a["periodo_a"], period_b=a["periodo_b"], metric=a.get("metrica", "inv_neta"), filters=a.get("filtros"), limit=a.get("limite", 10)))
        add("explicar_diferencia_entidades_bicomp", "Explica la diferencia entre dos entidades en el MISMO periodo mediante contribuciones y mix por otra dimensión. No compara años.",
            {**common, "dimension_entidad": dimension, "dimension": dimension,
             "valor_a": {"type": "string"}, "valor_b": {"type": "string"}, "limite": limit},
            ["dimension_entidad", "dimension", "valor_a", "valor_b"],
            lambda a: self._bicomp_repository_call("explicar_diferencia_entidades", entity_dimension=a["dimension_entidad"],
                dimension=a["dimension"], value_a=a["valor_a"], value_b=a["valor_b"], limit=a.get("limite", 10), **scope(a)))
        add("analizar_anomalias_bicomp", "Serie temporal con picos, dispersión, cambios, pendiente y anomalías MAD calculadas por Python. No demuestra causalidad ni estacionalidad.",
            {**common, "granularidad": {"enum": ["day", "week", "month"]}}, ["granularidad"], self._bicomp_series)
        add("obtener_valores_dimension_bicomp", "Descubre valores normalizados de CUALQUIER dimensión semántica. No devuelve inversión ni shares.",
            {"dimension": dimension, "filtros": common["filtros"], "fecha_inicio": common["fecha_inicio"], "fecha_fin": common["fecha_fin"], "limite": {"type": "integer", "minimum": 1, "maximum": 1000}}, ["dimension"],
            lambda a: self._bicomp_repository_call("catalogo", dimension=a["dimension"], filters=a.get("filtros"), limit=a.get("limite", 100), start_date=a.get("fecha_inicio"), end_date=a.get("fecha_fin")))
        add("calcular_ratio_bicomp", "Calcula un cociente de dos métricas en el mismo alcance (por ejemplo coste por inserción), sin matemática del LLM.",
            {**{k:v for k,v in common.items() if k not in {"metrica", "agregacion"}}, "numerador": common["metrica"], "denominador": common["metrica"]},
            ["numerador", "denominador"],
            lambda a: self._bicomp_repository_call("calcular_ratio", numerator=a["numerador"], denominator=a["denominador"], filters=a.get("filtros"), start_date=a.get("fecha_inicio"), end_date=a.get("fecha_fin")))
        from src.data.comparative import ranking_change, temporal_extrema, dimension_search
        comparison_args = {'metrica': common['metrica'], 'filtros': common['filtros'], 'periodo_a': period, 'periodo_b': period}
        def compare_scope(a):
            return dict(metric=a.get('metrica', 'inv_neta'), filters=a.get('filtros'), period_a=a['periodo_a'], period_b=a['periodo_b'])
        add('ranking_cambio_bicomp', 'Ordena entidades por cambio absoluto/porcentual entre dos ventanas equivalentes; aceleración requiere tres. No ordena por nivel.',
            {**comparison_args, 'dimension': dimension, 'criterio': {'enum': ['absolute', 'percent']},
             'orden': {'enum': ['asc', 'desc']}, 'aceleracion': {'type': 'boolean'}, 'limite': limit},
            ['dimension', 'periodo_a', 'periodo_b'],
            lambda a: ranking_change(self.bicomp_repository, dimension=a['dimension'], criterion=a.get('criterio', 'absolute'),
                direction=a.get('orden', 'desc'), acceleration=a.get('aceleracion', False), limit=a.get('limite', 10), **compare_scope(a)))
        add('extremos_temporales_bicomp', 'Descubre máximo o mínimo y empates de una serie; no requiere un pico conocido ni detector de anomalías.',
            {**common, 'granularidad': {'enum': ['day', 'week', 'month']}, 'extremo': {'enum': ['max', 'min']}}, ['granularidad'],
            lambda a: temporal_extrema(self.bicomp_repository, granularity=a['granularidad'], extreme=a.get('extremo', 'max'), **scope(a)))
        add('diagnosticar_dimensiones_bicomp', 'Compara hasta tres dimensiones no redundantes elegibles del modelo semántico con contribuciones completas; selecciona mayor concentración del cambio, no causas.',
            {**comparison_args, 'dimensiones': {'type': 'array', 'items': dimension, 'minItems': 2, 'maxItems': 3}, 'limite': limit},
            ['periodo_a', 'periodo_b'],
            lambda a: dimension_search(self.bicomp_repository, dimensions=a.get('dimensiones'), limit=a.get('limite', 5), **compare_scope(a)))
        add("consultar_participacion_bicomp", "Calcula participación conjunta de valores de una dimensión sobre todo el universo filtrado. Úsala antes de sumar shares de filas.",
            {**common, "dimension": dimension, "valores": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
            ["dimension", "valores"],
            lambda a: self._bicomp_repository_call("consultar_participacion", dimension=a["dimension"], values=a["valores"], **scope(a)))
