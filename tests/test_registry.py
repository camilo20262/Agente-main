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
