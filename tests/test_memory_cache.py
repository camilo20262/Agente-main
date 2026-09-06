from src.agent.cache import QueryResultCache
from src.agent.memory import AnalyticalMemory


def test_memory_keeps_only_compact_analytical_context():
    memory = AnalyticalMemory()
    memory.update_from_result("comparar_marcas", {"marca_a": "VOLVO", "marca_b": "RENAULT", "filtros": {"medio": "DIGITAL"}},
                              {"domain": "bicomp", "metric": "inv_neta", "period": {"start": "2026-01-01", "end": "2026-01-31"}, "rows": list(range(10000))})
    context = memory.context()
    assert context["last_entities"]["brands"] == ["VOLVO", "RENAULT"]
    assert context["last_filters"] == {"medio": "DIGITAL"}
    assert "rows" not in context


def test_cache_normalizes_arguments_and_does_not_store_errors():
    cache = QueryResultCache(ttl_seconds=300)
    cache.put("tool", {"b": 2, "a": 1}, {"success": True, "value": 5})
    assert cache.get("tool", {"a": 1, "b": 2})["value"] == 5
    cache.put("bad", {}, {"success": False, "error": "x"})
    assert cache.get("bad", {}) is None
