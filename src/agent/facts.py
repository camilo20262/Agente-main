"""Deterministic factual sentences selected, never recomputed, by the narrator."""
from __future__ import annotations
import calendar
from datetime import date
import json
import re
from src.analytics.calculations import MISSING_LABELS, number


def display(value):
    if number(value) is not None:
        return f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return 'Sin información' if value is None or str(value).upper() in MISSING_LABELS else str(value)


def metric_value(value, result):
    """Render a measured value with its contractual unit when one exists."""
    rendered = display(value)
    if result.get('unit') == 'currency':
        unit = result.get('display_unit') or 'unidades monetarias con moneda y escala pendientes de confirmar'
        return f'{rendered} {unit}'
    if result.get('unit') == 'count':
        return f'{rendered} inserciones'
    return rendered


MONTH_NAMES = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
               'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')


def period_label(period):
    """Present an ISO analytical window in natural Spanish when it is unambiguous."""
    if not isinstance(period, dict) or not period.get('start') or not period.get('end'):
        return ''
    try:
        start, end = date.fromisoformat(str(period['start'])), date.fromisoformat(str(period['end']))
    except (TypeError, ValueError):
        return f"{period['start']} a {period['end']}"
    if start.year == end.year and start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31:
        return str(start.year)
    if (start.year == end.year and start.month == end.month and start.day == 1
            and end.day == calendar.monthrange(end.year, end.month)[1]):
        return f'{MONTH_NAMES[start.month - 1]} de {start.year}'
    if start == end:
        return f'{start.day} de {MONTH_NAMES[start.month - 1]} de {start.year}'
    return (f'del {start.day} de {MONTH_NAMES[start.month - 1]} de {start.year} '
            f'al {end.day} de {MONTH_NAMES[end.month - 1]} de {end.year}')


def observation_period_label(value, granularity=None):
    try:
        observed = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return str(value)
    if granularity == 'month':
        return f'{MONTH_NAMES[observed.month - 1]} de {observed.year}'
    natural = f'{observed.day} de {MONTH_NAMES[observed.month - 1]} de {observed.year}'
    return f'la semana del {natural}' if granularity == 'week' else natural


def scope_label(filters):
    parts = []
    labels = {'marca': 'la marca', 'anunciante': 'el anunciante', 'medio': 'el medio',
              'medio_agrupado': 'el grupo de medios', 'vehiculo': 'el vehículo',
              'formato': 'el formato', 'region': 'la región', 'ciudad': 'la ciudad',
              'sector': 'el sector', 'producto': 'el producto'}
    for key, value in (filters or {}).items():
        rendered = ', '.join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
        if key == 'marca':
            parts.append(rendered)
        else:
            parts.append(f'{labels.get(key, key.replace("_", " "))} {rendered}')
    return ', '.join(parts)


def analytical_context(filters, period):
    scope, interval = scope_label(filters), period_label(period)
    if scope and interval:
        return f'Para {scope}, durante {interval}'
    if scope:
        return f'Para {scope}'
    if interval:
        return f'Durante {interval}'
    return 'En el alcance analizado'


def dimension_label(value):
    return str(value or 'categoría').replace('_', ' ')


def dimension_phrase(value):
    key = str(value or 'categoría')
    return {'medio': 'el medio', 'medio_agrupado': 'el grupo de medios',
            'vehiculo': 'el vehículo', 'formato': 'el formato',
            'marca': 'la marca', 'anunciante': 'el anunciante',
            'region': 'la región', 'ciudad': 'la ciudad',
            'sector': 'el sector', 'producto': 'el producto'}.get(key, 'la ' + dimension_label(key))


def present_limitation(value):
    text = str(value or '').strip().rstrip('.')
    lowered = text.lower()
    if 'contribuciones contables entre entidades' in lowered:
        return ('El desglose muestra cómo cada categoría participa en la diferencia observada entre las entidades; '
                'no permite atribuir causas comerciales')
    if 'contribuciones contables de una dimensión' in lowered:
        return ('El desglose cuantifica la participación de cada categoría en el cambio observado; '
                'no demuestra por sí solo una causa comercial')
    if 'periodo solicitado parcialmente disponible' in lowered:
        return 'El periodo solicitado tiene cobertura parcial; la lectura corresponde al acumulado disponible'
    if 'cobertura temporal no verificada' in lowered:
        return 'La cobertura temporal de la fuente requiere validación antes de utilizar el resultado externamente'
    if 'moneda y la escala de la métrica no están configuradas' in lowered:
        return ('La moneda y la escala de la métrica están pendientes de confirmación por el propietario de la fuente; '
                'los importes no deben utilizarse externamente hasta completar esa configuración')
    if 'taxonomía' in lowered and 'no' in lowered:
        return text
    if 'integridad' in lowered:
        return text
    if 'comparación ajustada a ventanas equivalentes' in lowered:
        return 'La comparación utiliza ventanas equivalentes dentro de la cobertura disponible'
    if 'ausencia de una categoría en una ventana con datos se trata como cero' in lowered:
        return ('Una categoría sin registros dentro de una ventana con información se considera cero únicamente '
                'para calcular el cambio; esto no acredita actividad fuera de la fuente')
    return text


def fact_catalog(evidence):
    facts = []
    def add(text, record, *, mandatory=False, category=None):
        facts.append({'id': f'F{len(facts)+1}', 'text': text, 'evidence_id': record.get('id'),
                      'tool': record.get('tool'), 'mandatory': mandatory, 'category': category})
    for record in evidence:
        r = record.get('result', {})
        if r.get('success') is not True or record.get('historical'):
            continue
        metric = r.get('metric_label') or r.get('metric', 'Resultado')
        period = r.get('effective_period') or r.get('period') or {}
        context = analytical_context(r.get('filters', {}), period)
        joint_share = r.get('values') and number(r.get('share_pct')) is not None
        if r.get('capability') in {'rank_change', 'rank_acceleration'}:
            a, b = r['period_a'], r['period_b']
            ordering = 'de mayor a menor' if r['direction'] == 'desc' else 'de menor a mayor'
            add(f"El ranking se ordena por cambio {'absoluto' if r['criterion'] == 'absolute' else 'porcentual'}, {ordering}. El periodo analizado es {period_label(a)} y la referencia es {period_label(b)}.", record, mandatory=True)
            for row in r['rows'][:10]:
                text = (f"{context}, {dimension_phrase(r['dimension'])} {row['dimension']} registró {metric_value(row['current_value'], r)}, "
                        f"frente a {metric_value(row['previous_value'], r)} en la referencia. El cambio absoluto fue {metric_value(row['difference'], r)}; "
                        f"el cambio porcentual fue {display(row['difference_pct'])}" + (' %.' if row['difference_pct'] is not None else ' y no se expresa en porcentaje porque la base no fue positiva.'))
                if r['capability'] == 'rank_acceleration':
                    c = r['period_c']
                    text += f" En la segunda referencia, {period_label(c)}, registró {metric_value(row['previous_previous_value'], r)}, con un cambio previo de {metric_value(row['previous_difference'], r)}."
                    text += f" La aceleración absoluta fue de {metric_value(row['acceleration'], r)}; la aceleración porcentual, de {display(row['acceleration_pp'])} puntos porcentuales."
                add(text, record)
            continue
        if r.get('capability') == 'temporal_extrema':
            for row in r['extrema']:
                observed = observation_period_label(row['period'], r.get('granularity'))
                add(f"{context}, el {'máximo' if r['extreme'] == 'max' else 'mínimo'} se registró en {observed}, con {metric_value(row['value'], r)}. La evaluación consideró {r['evaluated_periods']} periodos con información disponible.", record, mandatory=True)
            continue
        if r.get('capability') == 'dimension_search':
            add('Dimensión seleccionada entre las evaluadas: ' + r['selected_dimension'] + '. El criterio mide concentración del cambio observado, no causalidad.', record, mandatory=True)
            for candidate in r['candidate_evaluations']:
                if candidate.get('eligible'):
                    add(f"{candidate['dimension']}: concentración del cambio absoluto en categorías informadas principales {display(candidate['score_pct'])} %; cambio con etiqueta informada {display(candidate['known_change_pct'])} %.", record)
        if joint_share:
            add(f"{context}, " + ', '.join(display(v) for v in r['values'])
                + f" alcanzaron en conjunto {metric_value(r['value'], r)}, sobre un total analizado de {metric_value(r['total'], r)}. Su participación combinada fue {display(r['share_pct'])} %.", record)
        elif number(r.get('value')) is not None:
            add(f"{context}, {metric.lower()} fue de {metric_value(r['value'], r)}.", record)
        if number(r.get('value_a')) is not None and number(r.get('value_b')) is not None:
            def label(key, fallback):
                p = r.get('period_' + key, {})
                return r.get('brand_' + key) or r.get('value_' + key + '_label') or (f"{p['start']} a {p['end']}" if p.get('start') else fallback)
            a, b = label('a', 'Actual'), label('b', 'Anterior')
            pct = number(r.get('difference_pct'))
            if pct is None:
                relative = ''
            elif pct < 0:
                relative = f" {a} se ubicó {display(abs(pct))} % por debajo de {b}."
            elif pct > 0:
                relative = f" {a} se ubicó {display(pct)} % por encima de {b}."
            else:
                relative = f' Ambas entidades registraron el mismo nivel.'
            add(f"{context}, {a} registró {metric_value(r['value_a'], r)} en {metric.lower()}, frente a {metric_value(r['value_b'], r)} de {b}. La diferencia fue de {metric_value(r.get('difference'), r)}.{relative}", record)
        rows = r.get('rows', [])
        if r.get('granularity'):
            stats = r.get('statistics', {})
            if stats.get('total') is not None:
                add(f"{context}, el acumulado fue de {metric_value(stats['total'], r)}, con un promedio de {metric_value(stats['mean'], r)} por periodo observado y un coeficiente de variación de {display(stats['coefficient_variation_pct'])} %.", record)
            selected = [r.get('peak'), stats.get('minimum'), *rows[-2:]]
            seen = set()
            for row in selected:
                if not row or row.get('period') in seen: continue
                seen.add(row['period'])
                share = row.get('share_of_total_pct', row.get('share_pct'))
                observed = observation_period_label(row['period'], r.get('granularity'))
                add(f"{context}, {observed} registró {metric_value(row['value'], r)}" + (f" y representó {display(share)} % del acumulado" if share is not None else '') + ("; fue el máximo del periodo analizado." if row.get('is_peak') else '.'), record)
                change = row.get('change_from_previous_observation', {})
                if change.get('difference') is not None:
                    add(f"En {observed}, el cambio frente al periodo observado anterior fue de {metric_value(change['difference'], r)}" + (f" ({display(change['difference_pct'])} %)" if change.get('difference_pct') is not None else '') + '.', record)
            anomalies = stats.get('anomalies', [])
            if stats.get('anomaly_testable'):
                if anomalies:
                    for anomaly in anomalies[:4]:
                        observed = observation_period_label(anomaly['period'], r.get('granularity'))
                        add(f"{context}, se identificó una señal atípica en {observed}, con un valor de {metric_value(anomaly['value'], r)}. La puntuación robusta fue de {display(anomaly['robust_z_score'])}, frente a un umbral absoluto de {display(stats['anomaly_threshold'])}.", record)
                else:
                    add(f'{context}, el análisis robusto no identificó anomalías en las observaciones disponibles.', record)
            else:
                add(f'{context}, la cantidad o dispersión de las observaciones no permite evaluar anomalías con suficiente solidez; el máximo conserva un carácter descriptivo.', record)
        else:
            for row in rows[:10]:
                if row.get('value') is None: continue
                missing_label = row.get('dimension') is None or str(row.get('dimension')).strip().upper() in MISSING_LABELS
                if missing_label and r.get('data_quality', {}).get('unknown_share_pct') is not None:
                    continue  # The combined quality fact describes absence without ranking it as a business category.
                label = display(row.get('dimension'))
                share = row.get('share_pct')
                grouped = bool(r.get('segment_dimension'))
                denominator = 'grupo' if grouped else 'universo analizado'
                category = 'grouped_ranking' if grouped else 'ranking'
                group_context = f" dentro de {dimension_label(r['segment_dimension'])} {display(row.get('segment'))}" if grouped else ''
                add(f"{context}, {dimension_phrase(r.get('dimension'))} {label}{group_context} registró {metric_value(row['value'], r)}" + (f" y representó {display(share)} % del {denominator}" if share is not None else '') + '.', record, category=category)
        drivers = r.get('drivers', [])
        closure = r.get('driver_closure') or {}
        shown_count = int(closure.get('shown_count', min(4, len(drivers))))
        displayed_drivers = drivers[:shown_count]
        needs_closure = int(closure.get('omitted_count', 0) or 0) > 0
        for row in displayed_drivers:
            def driver_scope(key, fallback):
                p = r.get('period_' + key, {})
                return r.get('brand_' + key) or r.get('value_' + key + '_label') or (f"{p['start']} a {p['end']}" if p.get('start') else fallback)
            contribution_pct = number(row.get('contribution_pct'))
            if contribution_pct is None:
                contribution_reading = ''
            elif contribution_pct < 0:
                contribution_reading = f' y compensó {display(abs(contribution_pct))} % de la diferencia total'
            else:
                contribution_reading = f' y explicó {display(contribution_pct)} % de la diferencia total'
            add(f"En {dimension_phrase(row['dimension'])} {display(row['value'])}, {driver_scope('a', 'A')} registró {metric_value(row['current_value'], r)}, frente a {metric_value(row['previous_value'], r)} de {driver_scope('b', 'B')}. Su aporte neto a la diferencia fue de {metric_value(row['contribution'], r)}{contribution_reading}.", record,
                mandatory=needs_closure, category='driver')
        if needs_closure and all(number(closure.get(key)) is not None for key in
                                 ('shown_contribution', 'residual_contribution', 'omitted_count')):
            residual_pct = closure.get('residual_contribution_pct')
            add(f"Las {shown_count} categorías con mayor contribución suman {metric_value(closure['shown_contribution'], r)}. "
                f"Las {int(closure['omitted_count'])} categorías restantes aportan, en términos netos, {metric_value(closure['residual_contribution'], r)}"
                + (f" ({display(residual_pct)} % de la diferencia neta)." if residual_pct is not None else '.'),
                record, mandatory=True, category='driver_closure')
        quality = r.get('data_quality', {})
        if quality.get('unknown_share_pct') is not None:
            add(f"{context}, los registros sin clasificación en {dimension_label(r.get('dimension'))} representan {display(quality['unknown_share_pct'])} %; la información clasificada representa {display(quality['known_share_pct'])} %. Los valores no informados no se interpretan como categorías de negocio.", record,
                mandatory=quality['unknown_share_pct'] > 0)
        if r.get('values') and not joint_share:
            add('Como referencia, los valores disponibles incluyen: ' + ', '.join(display(v) for v in r['values'][:10]) + '.', record)
        if r.get('start') and r.get('end'):
            add(f"La fuente dispone de información {period_label({'start': r['start'], 'end': r['end']})}.", record)
        if r.get('is_partial'):
            cutoff = r.get('effective_period', {}).get('end') or r.get('available_period', {}).get('end')
            add(f"La información disponible llega hasta {period_label({'start': cutoff, 'end': cutoff})}; los resultados corresponden al acumulado observado y no a un año completo.", record)
    return facts


def render_narrative(raw, facts, evidence):
    """Render only existing fact IDs; prose remains subject to grounding validation."""
    normalized = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
    try:
        content = json.loads(normalized)
    except (json.JSONDecodeError, TypeError):
        if normalized.startswith(('{', '[')):
            raise ValueError('JSON de narrativa incompleto o inválido.')
        return raw  # Compatibility with providers returning plain text; still validated.
    if not isinstance(content, dict) or not isinstance(content.get('findings'), list) or not content['findings']:
        raise ValueError('La narrativa requiere hallazgos con fact_ids válidos.')
    by_id = {f['id']: f['text'] for f in facts}
    metadata_by_id = {f['id']: f for f in facts}
    labels = [str(r.get('dimension', '')) for e in evidence for r in e.get('result', {}).get('rows', [])]
    labels += [str(v) for e in evidence for v in e.get('result', {}).get('filters', {}).values()]
    def qualitative(value):
        text = str(value or '')
        without_labels = text
        for label in labels:
            if label:
                without_labels = re.sub(re.escape(label), '', without_labels, flags=re.I)
        # Quantitative prose is redundant with selected facts and can introduce fresh arithmetic.
        # Omit that optional prose instead of changing any asserted amount.
        return '' if re.search(r'\d|\b(?:mitad|tercios?|cuartos?|quintos?|sextos?|séptimos?|octavos?|novenos?|décimos?|doble|triple|cuádruple|\w+\s+partes?|\w+\s+veces|por\s+ciento)\b', without_labels, re.I) else text
    lines = ['### Lectura ejecutiva', qualitative(content.get('summary')), '### Hallazgos clave']
    for finding in content['findings'][:5]:
        ids = finding.get('fact_ids', [])
        if not ids or any(key not in by_id for key in ids):
            raise ValueError('Referencia factual ausente o desconocida.')
        lines.append('**' + (qualitative(finding.get('title')) or 'Hallazgo') + '**')
        lines.extend(by_id[key] for key in list(dict.fromkeys(ids))[:3])
        selected_categories = {metadata_by_id[key].get('category') for key in ids}
        if finding.get('interpretation') and 'driver' not in selected_categories:
            lines.append(qualitative(finding['interpretation']))
    omitted_rows = [f['text'] for f in facts if f.get('category') == 'ranking' and f['text'] not in lines]
    if omitted_rows:
        lines.extend(['**Detalle complementario**', *omitted_rows])
    hypotheses = content.get('hypotheses', [])[:2]
    if hypotheses:
        lines.append('### Hipótesis de trabajo')
        for h in hypotheses:
            if not h.get('validation'): raise ValueError('La hipótesis necesita cómo validarla.')
            lines.append(str(h.get('hypothesis', '')) + ' Validación: ' + str(h['validation']))
    selected_text = set(lines)
    driver_closure = list(dict.fromkeys(f['text'] for f in facts
        if f.get('mandatory') and f.get('category') in {'driver', 'driver_closure'} and f['text'] not in selected_text))
    if driver_closure:
        lines.extend(['**Cobertura del desglose**', *driver_closure])
    mandatory = list(dict.fromkeys(f['text'] for f in facts
        if f.get('mandatory') and f.get('category') not in {'driver', 'driver_closure'} and f['text'] not in selected_text))
    limitations = list(dict.fromkeys(present_limitation(w).rstrip('.') + '.' for e in evidence
                                      for w in e.get('result', {}).get('warnings', [])))
    partial = list(dict.fromkeys(f['text'] for f in facts if f['text'].startswith('Cobertura parcial:')))
    if limitations or partial or mandatory:
        lines.extend(['### Consideraciones del análisis', *partial, *mandatory, *limitations])
    return '\n\n'.join(line.strip() for line in lines if line.strip())
