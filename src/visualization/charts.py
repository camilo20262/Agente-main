"""Create small serializable chart specs from structured tool results."""

from __future__ import annotations

from typing import Any


def build_chart_spec(tool: str, result: dict[str, Any]) -> dict[str, Any] | None:
    if tool == "comparar_marcas" and result.get("success"):
        rows = [{"label": result.get("brand_a"), "value": result.get("value_a")}, {"label": result.get("brand_b"), "value": result.get("value_b")}]
        return {"type": "comparison", "title": "Comparación de marcas", "data": rows, "x": "label", "y": "value"}
    if tool == "comparar_periodos_bicomp" and result.get("success"):
        rows = [{"label": "Periodo A", "value": result.get("value_a")}, {"label": "Periodo B", "value": result.get("value_b")}]
        return {"type": "comparison", "title": "Comparación de periodos", "data": rows, "x": "label", "y": "value"}
    if tool == "explicar_variacion_bicomp" and result.get("drivers"):
        rows = [{"driver": f"{item['dimension']}: {item['value']}", "contribution": item["contribution"]} for item in result["drivers"][:10]]
        return {"type": "bar", "title": "Principales contribuciones al cambio", "data": rows, "x": "driver", "y": "contribution"}
    rows = result.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    if tool == "serie_temporal_bicomp":
        return {"type": "line", "title": f"Evolución de {result.get('metric', 'métrica')}", "data": rows, "x": "period", "y": "value"}
    if tool in {"ranking_anunciantes", "ranking_marcas", "analizar_medios", "analizar_vehiculos", "ranking_por_dimension"}:
        title = f"Ranking por {result.get('metric', 'métrica')}"
        if result.get("dimension"):
            title = f"Ranking por {result['dimension']} — {result.get('metric', 'métrica')}"
        return {"type": "ranking", "title": title, "data": rows, "x": "value", "y": "dimension"}
    return None


def render_plotly(spec: dict[str, Any]):
    import plotly.express as px
    data, kind = spec["data"], spec["type"]
    if kind == "line":
        return px.line(data, x=spec["x"], y=spec["y"], color=spec.get("color"), markers=True, title=spec.get("title"))
    if kind in {"bar", "ranking", "comparison"}:
        figure = px.bar(data, x=spec["x"], y=spec["y"], orientation="h" if kind == "ranking" else "v", title=spec.get("title"))
        if kind == "ranking":
            figure.update_layout(yaxis={"categoryorder": "total ascending"})
        return figure
    raise ValueError(f"Tipo de gráfica no soportado: {kind}")
