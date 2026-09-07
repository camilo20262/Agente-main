from datetime import date

import pytest

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
    monkeypatch.setattr(repo, "_totales_dimension_bicomp", ranking)
    result = repo.explicar_variacion_bicomp(brand="VOLVO", current_period={"start": "2026-02-01", "end": "2026-02-28"}, previous_period={"start": "2026-01-01", "end": "2026-01-31"})
    assert result["change"] == -20
    assert len(result["drivers"]) == 3
    assert all(item["contribution"] == -20 for item in result["drivers"])


@pytest.mark.parametrize("previous,current,expected", [
    ({"A": 80, "B": 90}, {"A": 100, "B": 70}, [("A", 20), ("B", -20)]),
    ({"A": 80, "B": 90}, {"A": 100, "B": 40}, [("B", -50), ("A", 20)]),
    ({"old": 30, "same": 10}, {"new": 40, "same": 10}, [("new", 40), ("old", -30), ("same", 0)]),
])
def test_explain_variation_limits_after_subtraction(monkeypatch, previous, current, expected):
    repo = BigQueryRepository(Settings(gcp_project_id="project", bigquery_dataset="dataset", bigquery_bicomp_table="bicomp"), client=object())
    monkeypatch.setattr(repo, "get_bicomp_schema", lambda: {
        "medio": "STRING", "vehiculo": "STRING", "formato": "STRING",
        "marca": "STRING", "fecha": "DATE", "inv_neta": "NUMERIC",
    })
    monkeypatch.setattr(repo, "comparar_periodos_bicomp", lambda **kwargs: {
        "success": True, "value_a": sum(current.values()), "value_b": sum(previous.values()),
        "difference": sum(current.values()) - sum(previous.values()), "difference_pct": 0,
        "row_count": 4, "evidence": [],
    })
    specs = []

    def execute(spec):
        specs.append(spec)
        parameters = {name: value for name, _, value in spec.parameters}
        values = current if parameters["start_date"] == date(2026, 2, 1) else previous
        rows = [{"dimension": key, "value": value} for key, value in values.items()]
        rows.sort(key=lambda row: row["value"], reverse=True)
        if "LIMIT @limit" in spec.sql:
            rows = rows[:parameters["limit"]]
        return {"rows": rows, "evidence": {"bytes_processed": 0, "duration_ms": 0}}

    monkeypatch.setattr(repo, "_execute_bicomp", execute)
    kwargs = dict(brand="VOLVO", current_period={"start": "2026-02-01", "end": "2026-02-28"},
                  previous_period={"start": "2026-01-01", "end": "2026-01-31"})
    result = repo.explicar_variacion_bicomp(**kwargs, driver_limit=1)
    key, contribution = expected[0]
    assert result["drivers"] == [{"dimension": "medio", "value": key,
        "current_value": current.get(key, 0), "previous_value": previous.get(key, 0),
        "contribution": contribution}]
    assert len(specs) == 6
    assert all("LIMIT" not in spec.sql for spec in specs)
    assert all("limit" not in {name for name, _, _ in spec.parameters} for spec in specs)

    result = repo.explicar_variacion_bicomp(**kwargs, driver_limit=20)
    assert len(result["drivers"]) == 3 * len(expected)
    for dimension in ("medio", "vehiculo", "formato"):
        assert [(row["value"], row["contribution"]) for row in result["drivers"]
                if row["dimension"] == dimension] == expected


def test_top_n_ranking_still_limits_in_sql(monkeypatch):
    repo = BigQueryRepository(Settings(gcp_project_id="project", bigquery_dataset="dataset", bigquery_bicomp_table="bicomp"), client=object())
    monkeypatch.setattr(repo, "get_bicomp_schema", lambda: {"medio": "STRING", "inv_neta": "NUMERIC"})
    specs = []

    def execute(spec):
        specs.append(spec)
        return {"rows": [], "evidence": {"bytes_processed": 0, "duration_ms": 0}}

    monkeypatch.setattr(repo, "_execute_bicomp", execute)
    repo.analizar_medios(metric="inv_neta", filters=None, start_date=None, end_date=None, limit=1)
    assert "ORDER BY value DESC LIMIT @limit" in specs[0].sql
    assert ("limit", "INT64", 1) in specs[0].parameters
