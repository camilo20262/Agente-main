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
