from src.tools.registry import ToolRegistry


class FakeRepository:
    source = "bigquery"
    def consultar_inversion(self, **kwargs):
        raise RuntimeError("BigQuery no está configurado")


def test_registry_has_only_bicomp_tools():
    registry = ToolRegistry(FakeRepository())
    names = {item["function"]["name"] for item in registry.schemas}
    assert len(names) == 12


def test_bicomp_tools_are_registered():
    names = {item["function"]["name"] for item in ToolRegistry(FakeRepository()).schemas}
    assert {"consultar_inversion_publicitaria", "comparar_marcas", "ranking_anunciantes", "ranking_marcas", "analizar_medios", "analizar_vehiculos", "consultar_inserciones_bicomp", "obtener_catalogo_bicomp", "obtener_cobertura_bicomp", "serie_temporal_bicomp"} <= names


def test_bicomp_without_repository_returns_controlled_error():
    result = ToolRegistry(FakeRepository(), bicomp_repository=None).execute("consultar_inversion_publicitaria", {})
    assert result["success"] is False
    assert "BigQuery no está configurado" in result["error"]
