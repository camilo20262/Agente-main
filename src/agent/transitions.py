"""Compile LLM-declared conversational operations into consistent scope transitions.

No question text is inspected. The LLM chooses the operation and dimensions; Python
preserves invariants and reuses the previously chosen strategy when requested.
"""
from copy import deepcopy

SCOPE_ARGS = {'metrica', 'metric', 'filtros', 'filters', 'fecha_inicio', 'fecha_fin',
              'start_date', 'end_date', 'periodo_a', 'periodo_b', 'periodo_actual', 'periodo_anterior'}
LEGACY_DIMENSIONS = {'analizar_medios': 'medio', 'analizar_vehiculos': 'vehiculo',
                     'ranking_marcas': 'marca', 'ranking_anunciantes': 'anunciante'}


def compile_transition(payload, memory):
    p = deepcopy(payload)
    steps = p.get('steps', [])
    # A scope repeated in every initial query is part of the declared base scope.
    filter_maps = [s.get('arguments', {}).get('filtros', s.get('arguments', {}).get('filters', {})) for s in steps]
    if filter_maps and all(isinstance(f, dict) for f in filter_maps):
        shared = {k: v for k, v in filter_maps[0].items() if all(f.get(k) == v for f in filter_maps)}
        p['filters'] = {**shared, **p.get('filters', {})}
    previous = memory.get('analysis_context', {})
    if p.get('intent') == 'ranking' and len(p.get('dimensions', [])) == 2:
        for step in p['steps']:
            if step['tool'] == 'ranking_por_dimension' and step['arguments'].get('dimension') in p['dimensions']:
                step['tool'] = 'ranking_segmentado_bicomp'
                step['arguments']['dimension_grupo'] = next(d for d in p['dimensions'] if d != step['arguments']['dimension'])
    operation = p.get('operation')
    if operation == 'restore_scope':
        requested_filters = p.get('filters', {})
        requested_axes, requested_intent, requested_steps = deepcopy(p.get('dimensions', [])), p.get('intent'), deepcopy(p.get('steps', []))
        candidates = [*memory.get('recent_scopes', []), previous]
        restored = next((c for c in reversed(candidates) if requested_filters and all(
            str(c.get('filters', {}).get(k, '')).upper() == str(v).upper() for k, v in requested_filters.items())), None)
        if not restored:
            raise ValueError('No hay un alcance anterior para esa entidad; pide aclaración o declara change_entity.')
        p.update(intent=restored['intent'], scope_mode='replace', filters=deepcopy(restored['filters']),
                 dimensions=deepcopy(restored.get('dimensions', [])), analysis=deepcopy(restored.get('analysis', {})))
        if (p.get('period') or {}).get('kind') in {None, 'inherit'}:
            p['period'] = {'kind': 'range', **restored['requested_period']} if restored.get('requested_period') else {'kind': 'all'}
        p['comparison_period'] = {'kind': 'range', **restored['comparison_period']} if restored.get('comparison_period') else None
        if restored.get('strategy'):
            p['steps'] = deepcopy(restored['strategy'])
            for step in p['steps']:
                step['arguments'] = {k: v for k, v in step['arguments'].items() if k not in SCOPE_ARGS}
        if requested_axes and payload.get('analysis', {}).get('restore_with_breakdown') and requested_intent in {'composition', 'ranking', 'diagnostic', 'open_analysis'}:
            p.update(intent=requested_intent, dimensions=requested_axes, steps=requested_steps)
            if requested_intent != 'diagnostic':
                p['comparison_period'] = None
            for dimension in requested_axes:
                p['filters'].pop(dimension, None)
    if previous and operation in {'change_period', 'change_entity', 'inspect_peak', 'continue_analysis', 'shift_period', 'filter_scope', 'joint_entities'}:
        p['scope_mode'] = 'inherit'
    if previous and operation in {'change_period', 'change_entity', 'continue_analysis', 'filter_scope', 'shift_period'}:
        target = previous.get('intent')
        if operation == 'shift_period' and (p.get('period') or {}).get('anchor') == 'peak':
            target = 'lookup'
            p['intent'] = 'lookup'
            p['steps'] = [{'tool': 'consultar_inversion_publicitaria', 'arguments': {}, 'purpose': 'Consultar el periodo relativo al extremo calculado.'}]
            p['dimensions'] = []
        p['analysis'] = {**previous.get('analysis', {}), **p.get('analysis', {})}
        if operation == 'filter_scope':
            p['dimensions'] = deepcopy(previous.get('dimensions', []))
            p['analysis'] = deepcopy(previous.get('analysis', {}))
            p['period'] = {'kind': 'inherit'}
            p['comparison_period'] = {'kind': 'inherit'} if previous.get('comparison_period') else None
        if not p.get('dimensions'):
            p['dimensions'] = deepcopy(previous.get('dimensions', []))
        if (p.get('intent') != target or operation == 'filter_scope') and memory.get('last_strategy'):
            p['intent'] = target
            p['steps'] = deepcopy(memory['last_strategy'])
            for step in p['steps']:
                step['purpose'] = 'Repetir esta perspectiva del análisis previo en el alcance actualizado.'
                step['arguments'] = {k: v for k, v in step['arguments'].items() if k not in SCOPE_ARGS}
            if target not in {'period_comparison', 'diagnostic'} and operation != 'filter_scope':
                p['comparison_period'] = None
        if operation in {'change_entity', 'continue_analysis'} and previous.get('comparison_period') and (not p.get('comparison_period') or p['comparison_period'].get('kind') == 'inherit'):
            # Reusing the analytical objective also reuses its reference. A null
            # emitted with a contradictory new strategy cannot erase that scope.
            p['comparison_period'] = {'kind': 'range', **previous['comparison_period']}
    if operation == 'explain_difference' and p.get('scope_mode') == 'inherit' and previous.get('requested_period'):
        if (p.get('period') or {}).get('kind') in {'previous_period', 'previous_month', 'previous_year'}:
            p['period'] = {'kind': 'inherit'}
    if operation == 'shift_period':
        if not p.get('period') or p['period'].get('kind') == 'inherit':
            p['period'] = {'kind': 'previous_period', **({'anchor': p['period']['anchor']} if p.get('period', {}).get('anchor') else {})}
        if previous.get('comparison_period'):
            p['comparison_period'] = {'kind': 'previous_period'}
    if operation == 'breakdown':
        # Promote a dimension from a restriction to an axis; unrelated filters survive.
        promoted = set(p.get('dimensions', [])) - set(p.get('analysis', {}).get('retain_filters', []))
        p['remove_filters'] = list(dict.fromkeys([*p.get('remove_filters', []), *sorted(promoted)]))
        for dim in promoted:
            p.setdefault('filters', {}).pop(dim, None)
            for step in p.get('steps', []):
                for key in ('filtros', 'filters'):
                    if isinstance(step.get('arguments', {}).get(key), dict):
                        step['arguments'][key].pop(dim, None)
    if previous.get('comparison_period') and operation == 'breakdown' and p.get('scope_mode') == 'inherit':
        p['intent'] = 'diagnostic'
        converted = []
        for step in p['steps']:
            args = step['arguments']
            dimension = args.get('dimension') or LEGACY_DIMENSIONS.get(step['tool']) or (p.get('dimensions') or [None])[0]
            if dimension:
                converted.append({'tool': 'analizar_drivers_bicomp',
                    'purpose': 'Desglosar la variación previamente comparada por la dimensión solicitada.',
                    'arguments': {'dimension': dimension, 'limite': args.get('limite', 10)}})
        if converted:
            p['steps'] = converted
            p['comparison_period'] = {'kind': 'range', **previous['comparison_period']}
    if operation == 'inspect_peak' and memory.get('last_peak'):
        p['period'] = {'kind': 'peak'}
        # The peak is already computed. Keep proposed drilldowns, avoiding annual rediscovery.
        drilldowns = [s for s in p['steps'] if s['tool'] not in {'serie_temporal_bicomp', 'analizar_anomalias_bicomp'}]
        p['steps'] = drilldowns or p['steps'][:1]
        if drilldowns:
            # Inspecting the already known peak is a diagnosis of that window,
            # not a new trend whose sufficiency would require another series.
            p['intent'] = 'diagnostic'
            p['dimensions'] = list(dict.fromkeys(s['arguments'].get('dimension') or
                LEGACY_DIMENSIONS.get(s['tool']) for s in drilldowns
                if s['arguments'].get('dimension') or LEGACY_DIMENSIONS.get(s['tool'])))
        for step in p['steps']:
            step['arguments'] = {k: v for k, v in step['arguments'].items() if k not in SCOPE_ARGS}
    if operation in {'compare_entities', 'explain_difference'}:
        pair = next((s['arguments'] for s in p['steps'] if s['tool'] in {'comparar_entidades_bicomp', 'explicar_diferencia_entidades_bicomp'}
                     and s['arguments'].get('valor_a') and s['arguments'].get('valor_b')), None)
        remembered = memory.get('last_entities', {})
        if not pair and len(remembered.get('values', [])) == 2:
            pair = {'dimension': remembered['dimension'], 'valor_a': remembered['values'][0], 'valor_b': remembered['values'][1]}
        for step in p['steps']:
            step['arguments'] = {k: v for k, v in step['arguments'].items() if k not in SCOPE_ARGS}
            if pair and step['tool'] == 'analizar_drivers_bicomp':
                step['tool'] = 'explicar_diferencia_entidades_bicomp'
                step['arguments'].update(dimension_entidad=pair.get('dimension_entidad', pair.get('dimension')),
                                         valor_a=pair['valor_a'], valor_b=pair['valor_b'])
                step['purpose'] = 'Desglosar la diferencia entre las entidades comparadas dentro del mismo periodo.'
        if any(s['tool'] == 'explicar_diferencia_entidades_bicomp' for s in p['steps']):
            # The driver result already contains both entity totals and their difference.
            p['steps'] = [s for s in p['steps'] if s['tool'] != 'comparar_entidades_bicomp']
    for step in p.get('steps', []):
        if step['tool'] in {'comparar_entidades_bicomp', 'explicar_diferencia_entidades_bicomp', 'comparar_marcas'}:
            args = step['arguments']
            if not ((args.get('valor_a') and args.get('valor_b')) or (args.get('marca_a') and args.get('marca_b'))):
                continue
            dimension = args.get('dimension_entidad') or args.get('dimension') or 'marca'
            p.setdefault('filters', {}).pop(dimension, None)
            p['remove_filters'] = list(dict.fromkeys([*p.get('remove_filters', []), dimension]))
            p['comparison_period'] = None
    return p
