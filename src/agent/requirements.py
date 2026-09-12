"""Analytical contracts: interpretation selects an objective, evidence must prove it.

This module never reads natural-language questions. Tools implement capabilities;
non-empty rows are not a substitute for the capability the user requested.
"""
from copy import deepcopy

CAPABILITIES = {
    'ranking_change': ('rank_change', 'ranking_cambio_bicomp'),
    'ranking_acceleration': ('rank_acceleration', 'ranking_cambio_bicomp'),
    'temporal_extrema': ('temporal_extrema', 'extremos_temporales_bicomp'),
    'diagnostic_search': ('dimension_search', 'diagnosticar_dimensiones_bicomp'),
    'joint_share': ('joint_share', 'consultar_participacion_bicomp'),
}


def compile_requirements(payload, memory):
    p = deepcopy(payload)
    intent = p.get('intent')
    analysis = p.setdefault('analysis', {})
    previous = memory.get('analysis_context', {})
    if p.get('operation') in {'change_period', 'change_entity', 'continue_analysis'}:
        analysis = {**previous.get('analysis', {}), **analysis}
        p['analysis'] = analysis
    if intent == 'diagnostic' and p.get('operation') != 'inspect_peak':
        dims = p.get('dimensions') or list(dict.fromkeys(s.get('arguments', {}).get('dimension')
            for s in p.get('steps', []) if s.get('arguments', {}).get('dimension')))
        temporal = p.get('comparison_period') or (p.get('scope_mode') == 'inherit' and previous.get('comparison_period'))
        if temporal and dims:
            p['dimensions'] = dims
            p['steps'] = [{'tool': 'analizar_drivers_bicomp', 'arguments': {'dimension': d},
                'purpose': 'Desglosar la comparación temporal declarada por la dimensión solicitada.'} for d in dims]
        elif not dims and temporal:
            intent = p['intent'] = 'diagnostic_search'
    if intent not in CAPABILITIES:
        return p
    capability, tool = CAPABILITIES[intent]
    prior_args = next((s.get('arguments', {}) for s in p.get('steps', []) if s.get('tool') == tool), {})
    dims = p.get('dimensions') or previous.get('dimensions') or []
    args = {}
    if intent in {'ranking_change', 'ranking_acceleration'}:
        if p.get('scope_mode') == 'inherit' and previous.get('intent') in {'ranking_change', 'ranking_acceleration'}:
            analysis = {**previous.get('analysis', {}), **analysis}
            p['analysis'] = analysis
        if not dims:
            from src.semantic import load_semantic_layer
            dims = [load_semantic_layer()['business_rules']['default_entity_dimension']]
        if len(dims) != 1:
            raise ValueError('El ranking de cambio requiere una dimensión de entidad explícita.')
        p['dimensions'] = dims
        from src.semantic import load_semantic_layer
        policy = load_semantic_layer()['business_rules']['change_ranking']
        args = {'dimension': dims[0], 'criterio': analysis.get('change_basis', prior_args.get('criterio', policy['default_basis'])),
                'orden': analysis.get('direction', prior_args.get('orden', 'desc')),
                'aceleracion': intent == 'ranking_acceleration', 'limite': analysis.get('limit', prior_args.get('limite', 10))}
        analysis.update(change_basis=args['criterio'], direction=args['orden'], limit=args['limite'])
        if not p.get('period') or (p['period'].get('kind') in {'all', 'inherit'} and not previous.get('requested_period')):
            p['period'] = {'kind': policy['default_focus']}
        p['comparison_period'] = p.get('comparison_period') or {'kind': policy['default_reference']}
    elif intent == 'temporal_extrema':
        p['dimensions'] = []  # Time axis is represented by granularity, not categorical breakdown.
        args = {'granularidad': analysis.get('granularity', prior_args.get('granularidad', 'month')),
                'extremo': analysis.get('extreme', prior_args.get('extremo', 'max'))}
        if p.get('operation') == 'inspect_peak' and not memory.get('last_peak'):
            p['operation'] = 'discover_extreme'
            if (p.get('period') or {}).get('kind') == 'peak':
                p['period'] = {'kind': 'inherit'}
    elif intent == 'diagnostic_search':
        if (p.get('comparison_period') or {}).get('kind') == 'inherit' and (p.get('period') or {}).get('kind') in {'previous_period', 'previous_month', 'previous_year'} and p.get('operation') != 'shift_period':
            p['period'] = {'kind': 'inherit'}
        p['comparison_period'] = p.get('comparison_period') or ({'kind': 'range', **previous['comparison_period']}
            if previous.get('comparison_period') else {'kind': 'previous_period'})
        args = {'limite': analysis.get('limit', 5)}
        candidates = analysis.get('candidate_dimensions') or prior_args.get('dimensiones')
        if candidates:
            analysis['candidate_dimensions'] = candidates[:3]
        if analysis.get('candidate_dimensions'):
            from src.semantic import load_semantic_layer
            if set(analysis['candidate_dimensions']) - set(load_semantic_layer()['business_rules']['diagnostic_dimensions']):
                raise ValueError('Solo son candidatas las diagnostic_dimensions del modelo semántico; omite candidate_dimensions para selección automática.')
            args['dimensiones'] = analysis['candidate_dimensions']
    elif intent == 'joint_share':
        entities = analysis.get('entity_set')
        if not entities and prior_args.get('valores'):
            entities = [{'dimension': prior_args.get('dimension'), 'value': v} for v in prior_args['valores']]
        if analysis.get('entity_reference') == 'recent' and not entities:
            entities = memory.get('recent_entities', [])[-analysis.get('entity_count', 2):]
        if not entities or len(entities) < 2:
            raise ValueError('La participación conjunta requiere al menos dos entidades confirmadas; pide aclaración si falta el referente.')
        if len({e['dimension'] for e in entities}) != 1:
            raise ValueError('No se combinan entidades de dimensiones distintas en un numerador. Pide aclaración.')
        dim = entities[0]['dimension']
        p['analysis']['entity_set'] = entities
        p['dimensions'] = [dim]
        args = {'dimension': dim, 'valores': list(dict.fromkeys(e['value'] for e in entities))}
        p.setdefault('filters', {}).pop(dim, None)
        p['remove_filters'] = list(dict.fromkeys([*p.get('remove_filters', []), dim]))
        p['comparison_period'] = None
    p['steps'] = [{'tool': tool, 'arguments': args, 'purpose': 'Obtener evidencia determinística exigida por la capacidad ' + capability + '.'}]
    return p


def requirements_for(intent, scope=None):
    scope = scope or {}
    capability = CAPABILITIES.get(intent, (intent,))[0]
    if intent == 'diagnostic' and scope.get('operation') == 'inspect_peak':
        capability = 'peak_distribution'
    return {'capability': capability, 'dimension': (scope.get('dimensions') or [None])[0],
            'analysis': scope.get('analysis', {}),
            'requires_reference': intent in {'ranking_change', 'ranking_acceleration', 'diagnostic_search', 'period_comparison'},
            'requires_series': intent in {'temporal_extrema', 'trend', 'anomaly'}}
