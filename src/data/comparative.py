"""Deterministic analytical capabilities over complete repository partitions."""
from src.agent.periods import equivalent_periods, resolve_period, iso, coverage, shift_year, window
from src.analytics.calculations import percentage, MISSING_LABELS
from src.semantic import load_semantic_layer


def ranking_change(repo, *, dimension, period_a, period_b, metric='inv_neta', filters=None,
                   criterion='absolute', direction='desc', acceleration=False, limit=10):
    available = repo.obtener_rango_fechas()
    a, b = equivalent_periods(period_a, period_b, available)
    periods = [a, b]
    if acceleration:
        if a['start'][5:] == b['start'][5:] and a['end'][5:] == b['end'][5:]:
            offset = iso(b['start']).year - iso(a['start']).year
            c = window(shift_year(iso(b['start']), offset), shift_year(iso(b['end']), offset))
        else:
            c = resolve_period({'kind': 'previous_period'}, today=iso(b['end']), previous=b)
        # The third window must be fully available; never compare differently clipped changes.
        bb, cc = equivalent_periods(b, c, available)
        if bb != b or cc != c:
            raise ValueError('No hay tres ventanas equivalentes completas para aceleración.')
        periods.append(c)
    results = [repo._full_dimension(dimension, metric, filters, p) for p in periods]
    evidence = [r['evidence'] for r in results]
    if any(not r.get('rows') or any(row.get('value') is None for row in r['rows']) for r in results):
        return {'success': False, 'error_type': 'no_data', 'error': 'Faltan valores numéricos en una ventana de comparación.', 'evidence': evidence}
    maps = [{str(row['dimension']): row['value'] for row in r['rows']} for r in results]
    rows = []
    keys = set().union(*(m.keys() for m in maps))
    excluded = []
    for key in sorted(keys):
        if key.strip().upper() in MISSING_LABELS:
            excluded.append(key)
            continue
        x, y = maps[0].get(key, 0), maps[1].get(key, 0)
        change = x-y
        pct = percentage(change, y) if y > 0 else None
        row = {'dimension': key, 'value': x, 'current_value': x, 'previous_value': y,
               'difference': change, 'difference_pct': pct, 'new_in_window': key not in maps[1]}
        if acceleration:
            z = maps[2].get(key, 0)
            prior_pct = percentage(y-z, z) if z > 0 else None
            row.update(previous_previous_value=z, previous_difference=y-z,
                       acceleration=change-(y-z), acceleration_pp=pct-prior_pct if pct is not None and prior_pct is not None else None)
        order_key = ('acceleration' if criterion == 'absolute' else 'acceleration_pp') if acceleration else ('difference' if criterion == 'absolute' else 'difference_pct')
        row['order_value'] = row[order_key]
        if row['order_value'] is None:
            excluded.append(key)
        else:
            rows.append(row)
    rows.sort(key=lambda r: ((-1 if direction == 'desc' else 1)*r['order_value'], r['dimension']))
    for rank, row in enumerate(rows, 1):
        row['rank'] = rank
    return {'success': bool(rows), 'error_type': None if rows else 'no_data',
            'source': repo.source, 'domain': 'bicomp', 'metric': metric, 'filters': filters or {},
            'dimension': dimension, 'rows': rows[:limit], 'ranked_entities': len(rows), 'excluded_entities': excluded,
            'capability': 'rank_acceleration' if acceleration else 'rank_change',
            'criterion': criterion, 'direction': direction, 'period_a': a, 'period_b': b,
            'period_c': periods[2] if acceleration else None, 'comparison_equivalent': True,
            'evidence': evidence, **coverage(period_a, available, results[0].get('observed_period', {})),
            'warnings': ['Orden por ' + ('aceleración del cambio' if acceleration else 'cambio') +
                (' absoluto.' if criterion == 'absolute' else ' porcentual; bases cero o negativas excluidas.'),
                'Ausencia de una categoría en una ventana con datos se trata como cero; no acredita actividad fuera de la fuente.']}


def temporal_extrema(repo, *, granularity='month', extreme='max', **scope):
    result = repo.serie_temporal_bicomp(granularity=granularity, **scope)
    if result.get('success') is not True:
        return result
    rows = [r for r in result.get('rows', []) if r.get('value') is not None]
    if not rows:
        return {**result, 'success': False, 'error_type': 'no_data'}
    value = (max if extreme == 'max' else min)(r['value'] for r in rows)
    ties = [r for r in rows if r['value'] == value]
    return {**result, 'capability': 'temporal_extrema', 'extreme': extreme, 'extrema': ties,
            'selected_extreme': ties[0], 'evaluated_periods': len(rows),
            'warnings': [*result.get('warnings', []), 'Extremo entre periodos observados; periodos sin filas no se imputan como cero.']}


def dimension_search(repo, *, period_a, period_b, metric='inv_neta', filters=None, dimensions=None, limit=5):
    semantic = load_semantic_layer()
    policy = semantic['business_rules']['diagnostic_dimensions']
    candidates, families = [], set()
    for dimension in dimensions or list(policy):
        if dimension not in policy:
            raise ValueError('Dimensión no habilitada para diagnóstico: ' + dimension)
        family = policy[dimension]['family']
        if dimension in (filters or {}) or family in families:
            continue
        candidates.append(dimension); families.add(family)
        if len(candidates) == 3:
            break
    if len(candidates) < 2:
        raise ValueError('Se necesitan al menos dos dimensiones no redundantes y no fijadas por filtros.')
    available = repo.obtener_rango_fechas()
    a, b = equivalent_periods(period_a, period_b, available)
    results = []
    for dimension in candidates:
        current = repo._full_dimension(dimension, metric, filters, a)
        previous = repo._full_dimension(dimension, metric, filters, b)
        calculated = repo._partition_difference(current, previous, dimension, len(current.get('rows', [])) + len(previous.get('rows', [])))
        results.append({**calculated, 'source': repo.source, 'domain': 'bicomp', 'metric': metric,
            'filters': filters or {}, 'dimension': dimension, 'period_a': a, 'period_b': b,
            'comparison_equivalent': True, 'evidence': [current.get('evidence'), previous.get('evidence')],
            **coverage(period_a, available, current.get('observed_period', {}))})
    evaluations = []
    for dimension, result in zip(candidates, results):
        rows = result.get('drivers', [])
        # Fetch complete partitions when >100 categories: truncated top drivers cannot define the score.
        if result.get('drivers_total', 0) > len(rows):
            evaluations.append({'dimension': dimension, 'eligible': False, 'reason': 'La partición excede el límite de evaluación completa.'})
            continue
        magnitude = sum(abs(r['contribution']) for r in rows)
        known = [r for r in rows if str(r['value']).strip().upper() not in MISSING_LABELS]
        known_abs = sum(abs(r['contribution']) for r in known)
        top = sum(sorted((abs(r['contribution']) for r in known), reverse=True)[:3])
        score = percentage(top, magnitude) if magnitude else 0
        evaluations.append({'dimension': dimension, 'eligible': result.get('success') is True and len(known) > 1,
                            'score_pct': score, 'known_change_pct': percentage(known_abs, magnitude),
                            'categories': len(rows), 'absolute_change': magnitude})
    eligible = [e for e in evaluations if e['eligible']]
    if len(eligible) < 2:
        return {'success': False, 'error_type': 'no_data', 'error': 'No hay dos particiones completas con datos suficientes para comparar dimensiones.',
                'candidate_evaluations': evaluations, 'evidence': [r.get('evidence') for r in results]}
    best = sorted(eligible, key=lambda e: (-e['score_pct'], e['dimension']))[0]
    result = results[candidates.index(best['dimension'])]
    return {**result, 'capability': 'dimension_search', 'candidate_evaluations': evaluations,
            'selected_dimension': best['dimension'], 'drivers': result['drivers'][:limit],
            'evidence': [r.get('evidence') for r in results],
            'warnings': ['Criterio: concentración del cambio absoluto en las tres categorías informadas principales, penalizada por datos ausentes. Mayor puntuación indica un desglose más concentrado entre las dimensiones evaluadas; no demuestra causalidad ni superioridad estadística.']}
