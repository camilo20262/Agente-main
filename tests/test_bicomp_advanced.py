from src.config import Settings
from src.data.bigquery_repository import BigQueryRepository


def repository():
    return BigQueryRepository(Settings(), client=object())


def test_compare_periods_calculates_all_differences(monkeypatch):
    repo = repository()
    values = iter([120.0, 100.0])
    monkeypatch.setattr(repo, "consultar_inversion", lambda **kwargs: {"success": True, "value": next(values), "row_count": 5, "evidence": {}})
    result = repo.comparar_periodos_bicomp(period_a={"start": "2026-02-01", "end": "2026-02-28"}, period_b={"start": "2026-01-01", "end": "2026-01-31"})
    assert result["difference"] == 20
    assert result["difference_pct"] == 20
    assert result["ratio_a_over_b"] == 1.2


def test_explain_variation_builds_deterministic_drivers(monkeypatch):
    repo = repository()
    monkeypatch.setattr(repo, "comparar_periodos_bicomp", lambda **kwargs: {"success": True, "value_a": 80, "value_b": 100, "difference": -20, "difference_pct": -20, "row_count": 8, "evidence": []})
    calls = {"medio": 0, "vehiculo": 0, "formato": 0}
    def ranking(**kwargs):
        dimension = kwargs["dimension"]
        calls[dimension] += 1
        value = 30 if calls[dimension] == 1 else 50
        return {"rows": [{"dimension": "X", "value": value}], "evidence": {}}
    monkeypatch.setattr(repo, "_ranking_bicomp", ranking)
    result = repo.explicar_variacion_bicomp(brand="VOLVO", current_period={"start": "2026-02-01", "end": "2026-02-28"}, previous_period={"start": "2026-01-01", "end": "2026-01-31"})
    assert result["change"] == -20
    assert len(result["drivers"]) == 3
    assert all(item["contribution"] == -20 for item in result["drivers"])
