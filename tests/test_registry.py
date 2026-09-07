from dataclasses import replace
from unittest.mock import Mock

import pytest

from src.tools.registry import ToolRegistry


class FakeRepository:
    source = "bigquery"
    def consultar_inversion(self, **kwargs):
        raise RuntimeError("BigQuery no está configurado")


def test_registry_has_only_bicomp_tools():
    registry = ToolRegistry(FakeRepository())
    names = {item["function"]["name"] for item in registry.schemas}
    assert len(names) == 13


def test_bicomp_tools_are_registered():
    names = {item["function"]["name"] for item in ToolRegistry(FakeRepository()).schemas}
    assert {"consultar_inversion_publicitaria", "comparar_marcas", "ranking_anunciantes", "ranking_marcas", "analizar_medios", "analizar_vehiculos", "ranking_por_dimension", "consultar_inserciones_bicomp", "obtener_catalogo_bicomp", "obtener_cobertura_bicomp", "serie_temporal_bicomp"} <= names


def test_bicomp_without_repository_returns_controlled_error():
    result = ToolRegistry(FakeRepository(), bicomp_repository=None).execute("consultar_inversion_publicitaria", {})
    assert result["success"] is False
    assert "BigQuery no está configurado" in result["error"]

@pytest.mark.parametrize("name,arguments", [
    ("comparar_periodos_bicomp", {"periodo_a": "enero", "periodo_b": {"start": "2026-02-01", "end": "2026-02-28"}}),
    ("comparar_marcas", {"marca_a": "VOLVO"}),
    ("ranking_por_dimension", {"dimension": "inventada"}),
    ("consultar_inversion_publicitaria", {"fecha_inicio": "2026-02-30"}),
    ("ranking_marcas", {"limite": 101}),
])
def test_invalid_arguments_never_execute_handler(name, arguments):
    registry = ToolRegistry(FakeRepository())
    handler = Mock(side_effect=AssertionError("El handler no debe ejecutarse"))
    registry._tools[name] = replace(registry._tools[name], handler=handler)
    result = registry.execute(name, arguments)
    assert result["success"] is False
    assert result["source"] == "bigquery"
    assert result["error"].startswith(f"Argumentos inválidos para '{name}':")
    handler.assert_not_called()


def test_valid_arguments_execute_handler_unchanged():
    registry = ToolRegistry(FakeRepository())
    expected = {"success": True, "value_a": 10, "value_b": 20}
    handler = Mock(return_value=expected)
    registry._tools["comparar_marcas"] = replace(registry._tools["comparar_marcas"], handler=handler)
    arguments = {"marca_a": "VOLVO", "marca_b": "RENAULT"}
    assert registry.execute("comparar_marcas", arguments) == expected
    handler.assert_called_once_with(arguments)


def test_handler_attribute_error_is_controlled():
    registry = ToolRegistry(FakeRepository())
    handler = Mock(side_effect=AttributeError("Resultado inesperado"))
    registry._tools["comparar_marcas"] = replace(registry._tools["comparar_marcas"], handler=handler)
    result = registry.execute("comparar_marcas", {"marca_a": "VOLVO", "marca_b": "RENAULT"})
    assert result == {"success": False, "source": "bigquery", "error": "Resultado inesperado"}
    handler.assert_called_once()


@pytest.mark.parametrize("incorrect_filter", [
    {"filters": {"marca": "Volvo"}},
    {"filters": '{"marca": "Volvo"}'},
    {"filters": '{"anunciante": "Volvo"}'},
    {"marca": "Volvo"},
])
def test_misplaced_filters_do_not_execute_unfiltered_query(incorrect_filter):
    repository = FakeRepository()
    repository.consultar_inversion = Mock(side_effect=AssertionError("No debe consultar"))
    registry = ToolRegistry(repository)
    result = registry.execute("consultar_inversion_publicitaria", {
        **incorrect_filter, "fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-31",
    })
    assert result["success"] is False
    assert result["source"] == "bigquery"
    assert "Argumentos inválidos para 'consultar_inversion_publicitaria'" in result["error"]
    assert "Additional properties are not allowed" in result["error"]
    assert next(iter(incorrect_filter)) in result["error"]
    repository.consultar_inversion.assert_not_called()


def test_correct_brand_filter_reaches_repository():
    repository = FakeRepository()
    expected = {"success": True, "metric": "inv_neta", "value": 80}
    repository.consultar_inversion = Mock(return_value=expected)
    result = ToolRegistry(repository).execute("consultar_inversion_publicitaria", {
        "filtros": {"marca": "Volvo"}, "fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-31",
    })
    assert result == expected
    repository.consultar_inversion.assert_called_once_with(
        filters={"marca": "Volvo"}, start_date="2026-01-01", end_date="2026-01-31")


COMMON_ARGUMENTS = {
    "metrica": "inv_neta", "agregacion": "sum",
    "filtros": {"marca": "Volvo", "medio": ["TV", "DIGITAL"], "region": "ANDINA"},
    "fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-31",
}
PERIOD = {"start": "2026-01-01", "end": "2026-01-31"}
VALID_TOOL_ARGUMENTS = {
    "consultar_inversion_publicitaria": COMMON_ARGUMENTS,
    "comparar_marcas": {**COMMON_ARGUMENTS, "marca_a": "Volvo", "marca_b": "Renault"},
    "ranking_anunciantes": {**COMMON_ARGUMENTS, "limite": 10},
    "ranking_marcas": {**COMMON_ARGUMENTS, "limite": 10},
    "analizar_medios": {**COMMON_ARGUMENTS, "limite": 10},
    "analizar_vehiculos": {**COMMON_ARGUMENTS, "limite": 10},
    "ranking_por_dimension": {**COMMON_ARGUMENTS, "dimension": "region", "limite": 10},
    "consultar_inserciones_bicomp": {k: v for k, v in COMMON_ARGUMENTS.items() if k != "metrica"},
    "obtener_catalogo_bicomp": {"catalogo": "marcas", "filtros": COMMON_ARGUMENTS["filtros"], "limite": 10},
    "obtener_cobertura_bicomp": {},
    "serie_temporal_bicomp": {**COMMON_ARGUMENTS, "granularidad": "month"},
    "comparar_periodos_bicomp": {"periodo_a": PERIOD, "periodo_b": PERIOD, "metrica": "inv_neta", "filtros": COMMON_ARGUMENTS["filtros"]},
    "explicar_variacion_bicomp": {"marca": "Volvo", "periodo_actual": PERIOD, "periodo_anterior": PERIOD,
                                  "metrica": "inv_neta", "filtros": COMMON_ARGUMENTS["filtros"], "limite_drivers": 10},
}


@pytest.mark.parametrize("name,arguments", VALID_TOOL_ARGUMENTS.items())
def test_all_tool_schemas_reject_only_undeclared_top_level_properties(name, arguments):
    registry = ToolRegistry(FakeRepository())
    schemas = {item["function"]["name"]: item["function"]["parameters"] for item in registry.schemas}
    assert set(schemas) == set(VALID_TOOL_ARGUMENTS)
    assert len(schemas) == 13
    assert schemas[name]["additionalProperties"] is False
    # Exercise every declared property, including merged common/ranking fields.
    assert set(arguments) == set(schemas[name]["properties"])
    handler = Mock(return_value={"success": True})
    registry._tools[name] = replace(registry._tools[name], handler=handler)
    assert registry.execute(name, arguments)["success"] is True
    handler.assert_called_once_with(arguments)
    handler.reset_mock()
    result = registry.execute(name, {**arguments, "filters": {"marca": "Volvo"}})
    assert result["success"] is False
    assert "Additional properties are not allowed" in result["error"]
    handler.assert_not_called()
