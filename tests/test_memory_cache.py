import pytest

from src.agent.cache import QueryResultCache
from src.agent.memory import AnalyticalMemory


def test_memory_keeps_only_compact_analytical_context():
    memory = AnalyticalMemory()
    memory.update_from_result("comparar_marcas", {"marca_a": "VOLVO", "marca_b": "RENAULT", "filtros": {"medio": "DIGITAL"}},
                              {"success": True, "domain": "bicomp", "metric": "inv_neta", "period": {"start": "2026-01-01", "end": "2026-01-31"}, "rows": list(range(10000))})
    context = memory.context()
    assert context["last_entities"]["brands"] == ["VOLVO", "RENAULT"]
    assert context["last_filters"] == {"medio": "DIGITAL"}
    assert "rows" not in context


@pytest.mark.parametrize("unsuccessful_result", [
    {"success": False, "error": "Consulta fallida"},
    {"error": "Falta success"},
    {"success": None},
    {"success": 1},
    {"success": "true"},
    {"success": False, "domain": "attachments", "metric": "total_insercion",
     "period": {"start": "2026-03-01", "end": "2026-03-31"}},
])
def test_unsuccessful_result_preserves_confirmed_memory(unsuccessful_result):
    memory = AnalyticalMemory()
    memory.update_from_result("consultar_inversion_publicitaria",
        {"metrica": "inv_neta", "filtros": {"marca": "VOLVO", "medio": "DIGITAL"}},
        {"success": True, "domain": "bicomp", "period": {"start": "2026-01-01", "end": "2026-01-31"}})
    confirmed_context = memory.context()
    assert confirmed_context == {
        "last_domain": "bicomp", "last_metric": "inv_neta",
        "last_period": {"start": "2026-01-01", "end": "2026-01-31"},
        "last_filters": {"marca": "VOLVO", "medio": "DIGITAL"},
        "last_entities": {"brands": ["VOLVO"]},
    }

    memory.update_from_result("consultar_inserciones_bicomp",
        {"metrica": "total_insercion", "filtros": {"marca": "RENAULT", "medio": "TV"},
         "marca_a": "CHEVROLET", "marca_b": "FORD"}, unsuccessful_result)
    assert memory.context() == confirmed_context


def test_cache_normalizes_arguments_and_does_not_store_errors():
    cache = QueryResultCache(ttl_seconds=300)
    cache.put("tool", {"b": 2, "a": 1}, {"success": True, "value": 5})
    assert cache.get("tool", {"a": 1, "b": 2})["value"] == 5
    cache.put("bad", {}, {"success": False, "error": "x"})
    assert cache.get("bad", {}) is None
