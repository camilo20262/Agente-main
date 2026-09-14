"""Deterministic factual sentences selected, never recomputed, by the narrator."""
from __future__ import annotations
import json
import re
from src.analytics.calculations import MISSING_LABELS, number


def display(value):
    if number(value) is not None:
        return f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return 'Sin información' if value is None or str(value).upper() in MISSING_LABELS else str(value)


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
        scope = ', '.join(f'{k}: {display(v)}' for k, v in r.get('filters', {}).items()) or 'alcance consultado'
        period = r.get('effective_period') or r.get('period') or {}
        interval = f" ({period['start']} a {period['end']})" if period.get('start') and period.get('end') else ''
        prefix = f'{metric}, {scope}{interval}'
        joint_share = r.get('values') and number(r.get('share_pct')) is not None
        if r.get('capability') in {'rank_change', 'rank_acceleration'}:
            a, b = r['period_a'], r['period_b']
            add(f"Criterio: cambio {'absoluto' if r['criterion'] == 'absolute' else 'porcentual'}, orden {r['direction']}; foco {a['start']} a {a['end']}, referencia {b['start']} a {b['end']}.", record, mandatory=True)
            for row in r['rows'][:10]:
                text = (f"{prefix}, {r['dimension']}={row['dimension']}: actual {display(row['current_value'])}, referencia {display(row['previous_value'])}; "
                        f"cambio absoluto {display(row['difference'])}; cambio porcentual {display(row['difference_pct'])}" + (' %.' if row['difference_pct'] is not None else ' (base no positiva).'))
                if r['capability'] == 'rank_acceleration':
                    c = r['period_c']
                    text += f" Segunda referencia {c['start']} a {c['end']}: {display(row['previous_previous_value'])}; cambio previo {display(row['previous_difference'])}."
                    text += f" Aceleración absoluta {display(row['acceleration'])}; aceleración porcentual {display(row['acceleration_pp'])} puntos porcentuales."
                add(text, record)
            continue
        if r.get('capability') == 'temporal_extrema':
            for row in r['extrema']:
                add(f"{prefix}: {'máximo' if r['extreme'] == 'max' else 'mínimo'} observado en {row['period']}, {display(row['value'])}; granularidad {r['granularity']}. Se evaluaron {r['evaluated_periods']} periodos observados.", record, mandatory=True)
            continue
        if r.get('capability') == 'dimension_search':
            add('Dimensión seleccionada entre las evaluadas: ' + r['selected_dimension'] + '. El criterio mide concentración del cambio observado, no causalidad.', record, mandatory=True)
            for candidate in r['candidate_evaluations']:
                if candidate.get('eligible'):
                    add(f"{candidate['dimension']}: concentración del cambio absoluto en categorías informadas principales {display(candidate['score_pct'])} %; cambio con etiqueta informada {display(candidate['known_change_pct'])} %.", record)
        if joint_share:
            add(f"{prefix}, {r.get('dimension', 'dimensión')}=" + ', '.join(display(v) for v in r['values'])
                + f": valor conjunto {display(r['value'])} de un total de {display(r['total'])}; participación conjunta {display(r['share_pct'])} %.", record)
        elif number(r.get('value')) is not None:
            add(f"{prefix}: {display(r['value'])}.", record)
        if number(r.get('value_a')) is not None and number(r.get('value_b')) is not None:
            def label(key, fallback):
                p = r.get('period_' + key, {})
                return r.get('brand_' + key) or r.get('value_' + key + '_label') or (f"{p['start']} a {p['end']}" if p.get('start') else fallback)
            a, b = label('a', 'Actual'), label('b', 'Anterior')
            change = f"; variación de {display(r['difference_pct'])} % sobre {b}" if r.get('difference_pct') is not None else ''
            add(f"{prefix}: {a} registra {display(r['value_a'])}; {b}, {display(r['value_b'])}. Diferencia de {display(r.get('difference'))}{change}.", record)
        rows = r.get('rows', [])
        if r.get('granularity'):
            stats = r.get('statistics', {})
            if stats.get('total') is not None:
                add(f"{prefix}: acumulado observado {display(stats['total'])}; promedio por periodo observado {display(stats['mean'])}; coeficiente de variación {display(stats['coefficient_variation_pct'])} %.", record)
            selected = [r.get('peak'), stats.get('minimum'), *rows[-2:]]
            seen = set()
            for row in selected:
                if not row or row.get('period') in seen: continue
                seen.add(row['period'])
                share = row.get('share_of_total_pct', row.get('share_pct'))
                add(f"{prefix}: {row['period']} registra {display(row['value'])}" + (f" y representa {display(share)} % del acumulado consultado" if share is not None else '') + ("; es el máximo observado." if row.get('is_peak') else '.'), record)
                change = row.get('change_from_previous_observation', {})
                if change.get('difference') is not None:
                    add(f"{prefix}: en {row['period']}, el cambio frente a la observación anterior es {display(change['difference'])}" + (f" ({display(change['difference_pct'])} %)" if change.get('difference_pct') is not None else '') + '.', record)
            anomalies = stats.get('anomalies', [])
            if stats.get('anomaly_testable'):
                if anomalies:
                    for anomaly in anomalies[:4]:
                        add(f"{prefix}: señal atípica en {anomaly['period']}, valor {display(anomaly['value'])}, puntuación robusta {display(anomaly['robust_z_score'])}; umbral {display(stats['anomaly_threshold'])} en valor absoluto.", record)
                else:
                    add(f'{prefix}: el detector MAD no señaló anomalías en las observaciones disponibles.', record)
            else:
                add(f'{prefix}: no hay observaciones o dispersión suficientes para aplicar el detector MAD; el máximo sigue siendo descriptivo.', record)
        else:
            for row in rows[:10]:
                if row.get('value') is None: continue
                missing_label = row.get('dimension') is None or str(row.get('dimension')).strip().upper() in MISSING_LABELS
                if missing_label and r.get('data_quality', {}).get('unknown_share_pct') is not None:
                    continue  # The combined quality fact describes absence without ranking it as a business category.
                label = display(row.get('dimension'))
                share = row.get('share_pct')
                segment = f", {r['segment_dimension']}={display(row.get('segment'))}" if r.get('segment_dimension') else ''
                denominator = 'grupo' if segment else 'universo consultado'
                category = 'grouped_ranking' if segment else 'ranking'
                add(f"{prefix}{segment}, {r.get('dimension', 'dimensión')}={label}: {display(row['value'])}" + (f" ({display(share)} % del {denominator})" if share is not None else '') + '.', record, category=category)
        drivers = r.get('drivers', [])
        displayed_drivers = drivers[:4]
        drivers_total = int(r.get('drivers_total', len(drivers)) or len(drivers))
        needs_closure = drivers_total > len(displayed_drivers)
        for row in displayed_drivers:
            def driver_scope(key, fallback):
                p = r.get('period_' + key, {})
                return r.get('brand_' + key) or r.get('value_' + key + '_label') or (f"{p['start']} a {p['end']}" if p.get('start') else fallback)
            add(f"{prefix}, {row['dimension']}={display(row['value'])}: {display(row['current_value'])} en {driver_scope('a', 'A')} frente a {display(row['previous_value'])} en {driver_scope('b', 'B')}; contribución a la diferencia {display(row['contribution'])}" + (f" ({display(row['contribution_pct'])} % de la diferencia neta)" if row.get('contribution_pct') is not None else '') + '.', record,
                mandatory=needs_closure, category='driver')
        net_difference = number(r.get('difference'))
        contributions = [number(row.get('contribution')) for row in displayed_drivers]
        if needs_closure and net_difference is not None and all(value is not None for value in contributions):
            shown_total = sum(contributions)
            residual = net_difference - shown_total
            residual_pct = None if not net_difference else residual / net_difference * 100
            omitted = max(0, drivers_total - len(displayed_drivers))
            add(f"Las {len(displayed_drivers)} contribuciones principales suman {display(shown_total)}; "
                f"el resto neto de {omitted} categorías no mostradas es {display(residual)}"
                + (f" ({display(residual_pct)} % de la diferencia neta)." if residual_pct is not None else '.'),
                record, mandatory=True, category='driver_closure')
        quality = r.get('data_quality', {})
        if quality.get('unknown_share_pct') is not None:
            add(f"{prefix}: valores sin información en {r.get('dimension')} representan {display(quality['unknown_share_pct'])} %; valores informados, {display(quality['known_share_pct'])} %. Las etiquetas ausentes no son categorías de negocio.", record,
                mandatory=quality['unknown_share_pct'] > 0)
        if r.get('values') and not joint_share:
            add('Valores disponibles (muestra): ' + ', '.join(display(v) for v in r['values'][:10]) + '.', record)
        if r.get('start') and r.get('end'):
            add(f"Cobertura disponible: {r['start']} a {r['end']}.", record)
        if r.get('is_partial'):
            add(f"Cobertura parcial: acumulado disponible hasta {r.get('effective_period', {}).get('end') or r.get('available_period', {}).get('end')}; no es un total anual completo.", record)
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
    lines = ['### Resumen ejecutivo', qualitative(content.get('summary'))]
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
        lines.extend(['**Otros resultados del desglose solicitado**', *omitted_rows])
    hypotheses = content.get('hypotheses', [])[:2]
    if hypotheses:
        lines.append('### Hipótesis')
        for h in hypotheses:
            if not h.get('validation'): raise ValueError('La hipótesis necesita cómo validarla.')
            lines.append(str(h.get('hypothesis', '')) + ' Validación: ' + str(h['validation']))
    selected_text = set(lines)
    driver_closure = list(dict.fromkeys(f['text'] for f in facts
        if f.get('mandatory') and f.get('category') in {'driver', 'driver_closure'} and f['text'] not in selected_text))
    if driver_closure:
        lines.extend(['**Cierre del desglose**', *driver_closure])
    mandatory = list(dict.fromkeys(f['text'] for f in facts
        if f.get('mandatory') and f.get('category') not in {'driver', 'driver_closure'} and f['text'] not in selected_text))
    limitations = list(dict.fromkeys(str(w) for e in evidence for w in e.get('result', {}).get('warnings', [])))
    partial = list(dict.fromkeys(f['text'] for f in facts if f['text'].startswith('Cobertura parcial:')))
    if limitations or partial or mandatory:
        lines.extend(['### Advertencias', *partial, *mandatory, *limitations])
    return '\n\n'.join(line.strip() for line in lines if line.strip())
