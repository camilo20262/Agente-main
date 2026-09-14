"""Charts derived only from successful evidence, with scope and units."""
from __future__ import annotations
from typing import Any


def _title(base, result):
    context = []
    if result.get('filters'):
        context.append(', '.join(f'{k}: {v}' for k, v in result['filters'].items()))
    elif result.get('brand'):
        context.append(result['brand'])
    period = result.get('effective_period') or result.get('period') or result.get('current_period')
    if period and period.get('start') and period.get('end'):
        context.append(f"{period['start']} a {period['end']}")
    if result.get('is_partial'):
        context.append('acumulado disponible')
    return ' · '.join([base, *context])


def build_chart_spec(tool: str, result: dict[str, Any]) -> dict[str, Any] | None:
    if result.get('success') is not True:
        return None
    metric = result.get('metric_label') or result.get('metric', 'métrica')
    unit_label = result.get('display_unit')
    if result.get('unit') == 'currency' and not unit_label:
        unit_label = 'unidad monetaria sin confirmar'
    metric_with_unit = f'{metric} ({unit_label})' if unit_label else metric
    unit_spec = {'unit_label': unit_label} if unit_label else {}
    if tool in {'comparar_marcas', 'comparar_entidades_bicomp'}:
        rows = [{'label': result.get('brand_a', result.get('value_a_label')), 'value': result.get('value_a')},
                {'label': result.get('brand_b', result.get('value_b_label')), 'value': result.get('value_b')}]
        return {'type': 'comparison', 'title': _title(f'Comparación de entidades — {metric_with_unit}', result), 'data': rows, 'x': 'label', 'y': 'value', **unit_spec}
    if tool == 'comparar_periodos_bicomp':
        rows = [{'label': f"{p['start']} a {p['end']}", 'value': result.get(key)}
                for p, key in ((result['period_a'], 'value_a'), (result['period_b'], 'value_b'))]
        return {'type': 'comparison', 'title': _title(f'Periodos equivalentes — {metric_with_unit}', result), 'data': rows, 'x': 'label', 'y': 'value', **unit_spec}
    if result.get('drivers'):
        rows = [{'driver': item['value'], 'partition': item['dimension'], 'contribution': item['contribution']} for item in result['drivers'][:15]]
        return {'type': 'bar', 'title': _title(f'Contribuciones por dimensión — {metric_with_unit}', result),
                'data': rows, 'x': 'driver', 'y': 'contribution', 'facet_col': 'partition', **unit_spec}
    rows = result.get('rows')
    if not isinstance(rows, list) or not rows:
        return None
    if tool in {'serie_temporal_bicomp', 'analizar_anomalias_bicomp'}:
        return {'type': 'line', 'title': _title(f'Evolución de {metric_with_unit}', result), 'data': rows, 'x': 'period', 'y': 'value', **unit_spec}
    if tool in {'ranking_anunciantes', 'ranking_marcas', 'analizar_medios', 'analizar_vehiculos', 'ranking_por_dimension'}:
        base = f"Ranking por {result['dimension']} — {metric_with_unit}" if result.get('dimension') else f'Ranking por {metric_with_unit}'
        return {'type': 'ranking', 'title': _title(base, result), 'data': rows, 'x': 'value', 'y': 'dimension', **unit_spec}
    return None


def render_plotly(spec):
    import plotly.express as px
    data, kind = spec['data'], spec['type']
    if kind == 'line':
        figure = px.line(data, x=spec['x'], y=spec['y'], color=spec.get('color'), markers=True, title=spec.get('title'))
        figure.update_layout(margin={'l': 50, 'r': 35, 't': 70, 'b': 55}, yaxis_title=spec.get('unit_label') or spec['y'])
        return figure
    if kind in {'bar', 'ranking', 'comparison'}:
        figure = px.bar(data, x=spec['x'], y=spec['y'], orientation='h' if kind == 'ranking' else 'v',
                        title=spec.get('title'), facet_col=spec.get('facet_col'),
                        text=spec['x'] if kind == 'ranking' else spec['y'])
        figure.update_traces(texttemplate='%{text:,.2f}', textposition='outside', cliponaxis=False)
        figure.update_layout(margin={'l': 60, 'r': 70, 't': 70, 'b': 70},
                             uniformtext_minsize=9, uniformtext_mode='hide')
        if kind == 'ranking':
            figure.update_layout(yaxis={'categoryorder': 'total ascending'})
            figure.update_xaxes(title_text=spec.get('unit_label') or spec['x'])
        else:
            figure.update_yaxes(title_text=spec.get('unit_label') or spec['y'])
        return figure
    raise ValueError(f'Tipo de gráfica no soportado: {kind}')
