from src.visualization import build_chart_spec, render_plotly


def test_time_series_chart_spec_and_plotly_figure():
    result = {"metric": "inv_neta", "rows": [{"period": "2026-01-01", "value": 10}, {"period": "2026-02-01", "value": 20}]}
    spec = build_chart_spec("serie_temporal_bicomp", result)
    assert spec["type"] == "line"
    figure = render_plotly(spec)
    assert len(figure.data) == 1


def test_ranking_chart_spec():
    spec = build_chart_spec("ranking_marcas", {"metric": "inv_neta", "rows": [{"dimension": "VOLVO", "value": 20}]})
    assert spec["type"] == "ranking"
    assert spec["title"] == "Ranking por inv_neta"


def test_generic_dimension_ranking_chart_spec():
    rows = [{"dimension": "ANDINA", "value": 30}, {"dimension": "CARIBE", "value": 20}]
    result = {"success": True, "dimension": "region", "metric": "inv_neta", "rows": rows}
    spec = build_chart_spec("ranking_por_dimension", result)
    assert spec == {"type": "ranking", "title": "Ranking por region — inv_neta",
                    "data": rows, "x": "value", "y": "dimension"}


def test_generic_dimension_ranking_without_rows_has_no_chart():
    assert build_chart_spec("ranking_por_dimension", {"dimension": "region", "rows": []}) is None
