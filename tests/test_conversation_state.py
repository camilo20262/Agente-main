from copy import deepcopy
from datetime import date
from types import SimpleNamespace as NS
import pytest
from evaluations.state_evaluator import assess_state, assess_record
from src.agent.analysis_context import AnalysisContext
from src.agent.memory import AnalyticalMemory
from src.agent.planner import AnalyticalPlanner, InvalidToolPlanError
from src.agent.sufficiency import evidence_sufficient
from src.agent.transitions import compile_transition
from src.data.comparative import ranking_change, temporal_extrema
from src.tools.registry import ToolRegistry
from tests.test_agent_service import FakeRepository, payload, step, service


def planner():
    return AnalyticalPlanner({s['function']['name'] for s in ToolRegistry(FakeRepository()).schemas})


@pytest.mark.parametrize('dimension', ['medio', 'vehiculo', 'formato', 'sector', 'anunciante', 'marca'])
def test_promotion_removes_only_its_filter(dimension):
    p = payload('composition', filters={dimension: 'VALOR', 'pais': 'PAIS'}, mode='inherit', steps=[step('ranking_por_dimension', {'dimension': dimension, 'filtros': {dimension: 'VALOR'}})])
    p.update(operation='breakdown', dimensions=[dimension])
    memory = {'analysis_context': {'filters': {dimension: 'VALOR', 'pais': 'PAIS'}}}
    transformed = compile_transition(p, memory)
    context = AnalysisContext.resolve(transformed, memory, today=date(2026, 9, 11))
    assert context.filters == {'pais': 'PAIS'}
    assert dimension not in transformed['steps'][0]['arguments']['filtros']


def test_breakdown_retains_unrelated_filter():
    p = payload('composition', filters={}, mode='inherit', steps=[step('ranking_por_dimension', {'dimension': 'formato'})])
    p.update(operation='breakdown', dimensions=['formato'])
    memory = {'analysis_context': {'filters': {'medio': 'DIGITAL', 'marca': 'RENAULT'}}}
    context = AnalysisContext.resolve(compile_transition(p, memory), memory, today=date(2026, 9, 11))
    assert context.filters == memory['analysis_context']['filters']


@pytest.mark.parametrize('kind', ['no_data', 'infrastructure', 'arguments', 'schema'])
def test_failed_turn_followup_one_service_retains_requested_scope(kind):
    class Repo(FakeRepository):
        def ranking(self, **kw):
            if kw.get('start_date') == '2025-01-01':
                return {'success': False, 'error_type': kind}
            return super().ranking(**kw)
    first = payload(filters={'marca': 'RENAULT'})
    failed = payload('ranking', filters={'medio': 'RADIO'}, steps=[step('ranking_por_dimension', {'dimension': 'anunciante'})])
    failed['dimensions'] = ['anunciante']
    following = payload('ranking', filters={}, mode='inherit', period={'kind': 'year', 'year': 2026}, steps=[step('ranking_por_dimension', {'dimension': 'anunciante'})])
    following.update(operation='change_period', dimensions=['anunciante'])
    responses = [first, failed]
    if kind in {'arguments', 'schema'}:
        responses.append({'stop': True, 'reason': 'No se puede corregir.', 'steps': []})
    responses.extend([following, 'La inversión fue 100.'])
    s, _, _ = service(responses, repo=Repo())
    history = []
    for question in ['Total Renault.', 'Top anunciantes radio.', 'Ahora otro año.']:
        history.append({'role': 'user', 'content': question})
        result = s.run(history)
        history.append({'role': 'assistant', 'content': result.answer})
        if len(history) == 4:
            assert s.memory.last_requested_scope['filters'] == {'medio': 'RADIO'}
            assert s.memory.last_confirmed_evidence_scope['filters'] == {'marca': 'RENAULT'}
    assert result.plan['resolved_context']['filters'] == {'medio': 'RADIO'}
    assert result.plan['resolved_context']['dimensions'] == ['anunciante']
    assert result.plan['resolved_context']['requested_period']['start'] == '2026-01-01'


def test_chained_previous_uses_logical_focus_once():
    memory = {'analysis_context': {'requested_period': {'start': '2024-03-01', 'end': '2024-03-31'}, 'intent': 'ranking_change', 'dimensions': ['marca']}}
    p = payload('ranking_change', mode='inherit', filters={}, period={'kind': 'previous_period'})
    p.update(operation='shift_period', dimensions=['marca'], comparison_period={'kind': 'previous_period'}, steps=[])
    for focus, reference in [('2024-02-01', '2024-01-01'), ('2024-01-01', '2023-12-01')]:
        plan = planner().plan('Seguimiento temporal', memory, payload=p)
        context = AnalysisContext.resolve(plan.scope, memory, today=date(2026, 9, 11))
        assert context.requested_period['start'] == focus
        assert context.comparison_period['start'] == reference
        memory['analysis_context'] = context.as_dict()


class Partitions:
    source = 'fixture'
    def obtener_rango_fechas(self):
        return {'success': True, 'start': '2023-01-01', 'end': '2026-07-31'}
    def _full_dimension(self, dimension, metric, filters, period):
        values = {'2025-03-01': [1200, 250, 100], '2025-02-01': [1100, 50, 0], '2025-01-01': [1000, 25, 0]}[period['start']]
        return {'rows': [{'dimension': label, 'value': value} for label, value in zip(['LARGE', 'GROWER', 'NEW'], values)], 'evidence': {'sql': 'fixture'}}


@pytest.mark.parametrize('criterion,acceleration,leader', [('absolute', False, 'GROWER'), ('percent', False, 'GROWER'), ('absolute', True, 'GROWER')])
def test_change_ranking_is_not_size(criterion, acceleration, leader):
    result = ranking_change(Partitions(), dimension='marca', period_a={'start': '2025-03-01', 'end': '2025-03-31'},
                            period_b={'start': '2025-02-01', 'end': '2025-02-28'}, criterion=criterion, acceleration=acceleration)
    assert result['rows'][0]['dimension'] == leader
    assert result['rows'][0]['difference'] == 200
    if criterion == 'percent':
        assert 'NEW' in result['excluded_entities']


@pytest.mark.parametrize('intent', ['ranking_change', 'ranking_acceleration', 'temporal_extrema', 'diagnostic_search', 'joint_share', 'diagnostic'])
def test_totals_and_mix_do_not_prove_other_capabilities(intent):
    evidence = [{'result': {'success': True, 'value': 999, 'dimension': 'marca', 'rows': [{'dimension': 'X', 'value': 999}], 'data_quality': {'known_share_pct': 100}}}]
    assert not evidence_sufficient(intent, evidence)


def test_joint_rejects_incompatible_typed_entities():
    p = payload('joint_share', steps=[])
    p['analysis'] = {'entity_set': [{'dimension': 'marca', 'value': 'X'}, {'dimension': 'anunciante', 'value': 'Y'}]}
    with pytest.raises(InvalidToolPlanError, match='dimensiones distintas'):
        planner().plan('Combina las entidades', payload=p)


@pytest.mark.parametrize('count', [2, 3])
def test_joint_compiles_recent_typed_entities(count):
    p = payload('joint_share', steps=[], filters={})
    p['analysis'] = {'entity_reference': 'recent', 'entity_count': count}
    memory = {'recent_entities': [{'dimension': 'marca', 'value': v} for v in ['RENAULT', 'FORD', 'TOYOTA']]}
    plan = planner().plan('Juntas', memory, payload=p)
    assert plan.steps[0].arguments['valores'] == ['RENAULT', 'FORD', 'TOYOTA'][-count:]


@pytest.mark.parametrize('expected', [
    {'capability': 'rank_change'},
    {'removed_filters': ['medio']},
    {'filters': {'medio': 'RADIO'}, 'dimensions': ['anunciante']},
    {'capability': 'joint_share'},
    {'capability': 'peak'},
    {'capability': 'comparison'},
    {'dimension': 'anunciante'},
])
def test_evaluator_seven_negative_controls(expected):
    bogus = {'answer': 'Creció y juntas representan 60%, el pico fue ayer.', 'is_partial': False,
             'plan': {'intent': 'ranking', 'resolved_context': {'filters': {'medio': 'DIGITAL', 'marca': 'X'}, 'dimensions': ['marca']}},
             'evidence': [{'result': {'success': True, 'dimension': 'marca', 'filters': {'medio': 'DIGITAL'}, 'rows': [{'dimension': 'X', 'value': 100}]}}]}
    assert not assess_state(bogus, expected)['passed']


def conversation_plans(additional=False):
    def plan(intent, operation='new_analysis', filters=None, dims=None, period=None, steps=None, **extra):
        p = payload(intent, filters=filters or {}, period=period or {'kind': 'inherit'}, steps=steps or [],
                    mode='replace' if operation == 'new_analysis' else 'inherit')
        p.update(operation=operation, dimensions=dims or [], **extra)
        return p
    year = {'kind': 'year', 'year': 2025}
    ranking = lambda d: [step('ranking_por_dimension', {'dimension': d})]
    total = [step('consultar_inversion_publicitaria')]
    tv = {'medio_agrupado': ['TV ABIERTA', 'TV CABLE']}
    pair = {'entity_set': [{'dimension': 'marca', 'value': v} for v in ['BMW', 'VOLVO']]}
    if not additional:
        return [
            plan('ranking_change', dims=['marca'], period={'kind': 'current_month'}),
            plan('ranking_change', 'shift_period', period={'kind': 'previous_period'}),
            plan('diagnostic_search', 'explain_difference'),
            plan('lookup', filters={'marca': 'BMW'}, period=year, steps=total),
            plan('lookup', filters={'marca': 'BMW', 'medio': 'DIGITAL'}, period=year, steps=total),
            plan('temporal_extrema', 'discover_extreme', filters={'marca': 'BMW'}, period=year, scope_mode='replace'),
            plan('composition', 'breakdown', dims=['medio'], period=year, steps=ranking('medio')),
            plan('ranking', 'breakdown', dims=['vehiculo'], period=year, steps=ranking('vehiculo')),
            plan('ranking', filters={'medio': 'DIGITAL'}, dims=['marca'], period=year, steps=ranking('marca')),
            plan('ranking', filters=tv, dims=['anunciante'], period=year, steps=ranking('anunciante')),
            plan('ranking', 'change_period', dims=['anunciante'], period={'kind': 'year', 'year': 2026}, steps=ranking('anunciante')),
            plan('joint_share', 'joint_entities', analysis=pair),
        ]
    return [
        plan('open_analysis', filters={'marca': 'BMW'}, period=year, steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), *ranking('medio')]),
        plan('open_analysis', 'filter_scope', filters={'medio': 'DIGITAL'}, steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), *ranking('medio')]),
        plan('composition', 'breakdown', dims=['medio'], steps=ranking('medio')),
        plan('temporal_extrema', 'discover_extreme'),
        plan('lookup', 'shift_period', period={'kind': 'previous_period', 'anchor': 'peak'}, steps=total),
        plan('diagnostic_search', 'explain_difference'),
        plan('diagnostic_search', 'change_entity', filters={'marca': 'VOLVO'}),
        plan('joint_share', 'joint_entities', analysis={'entity_reference': 'recent', 'entity_count': 2}),
        plan('ranking', filters=tv, dims=['anunciante'], steps=ranking('anunciante')),
        plan('ranking', 'change_period', dims=['anunciante'], period={'kind': 'year', 'year': 2026}, steps=ranking('anunciante')),
        plan('diagnostic_search', 'restore_scope', filters={'marca': 'BMW'}),
        plan('diagnostic', 'breakdown', dims=['vehiculo'], steps=ranking('vehiculo')),
    ]


@pytest.mark.parametrize('additional', [False, True])
def test_full_twelve_turn_conversation_one_session(additional):
    from src.data.bigquery_repository import BigQueryRepository
    from evaluations.conversation_state import ORIGINAL, ADDITIONAL
    from src.agent.periods import resolve_period
    class Repo(FakeRepository):
        _coverage_cache = {'coverage': {'start': '2019-01-01', 'end': '2026-07-31'}}
        _partition_difference = BigQueryRepository._partition_difference
        analizar_drivers = BigQueryRepository.analizar_drivers
        consultar_participacion = BigQueryRepository.consultar_participacion
        def obtener_rango_fechas(self):
            return {'success': True, **self._coverage_cache['coverage']}
        def _full_dimension(self, dimension, metric, filters, period):
            multiplier = 2 if period['start'].endswith('-01-01') else 1
            return {'success': True, 'rows': [{'dimension': label, 'value': v*multiplier} for label, v in [('BMW', 20), ('VOLVO', 30), ('OTHER', 50)]],
                    'metric': metric, 'filters': filters or {}, 'period': period, 'evidence': {'sql': 'fixture'}}
        def serie_temporal_bicomp(self, **kw):
            r = super().serie_temporal_bicomp(**kw)
            r['granularity'] = kw.get('granularity', 'month')
            return r
    plans = iter(conversation_plans(additional))
    s, _, _ = service([], repo=Repo())
    s.planner = AnalyticalPlanner({x['function']['name'] for x in s.registry.schemas}, interpreter=lambda q, m: next(plans))
    def gateway(*args, **kw):
        if kw.get('stage') in {'deepening', 'correction'}:
            return {'stop': True, 'reason': 'Evidencia suficiente.', 'steps': []}
        import json
        ids = [f['id'] for f in args[1]['facts'][:3]]
        return json.dumps({'findings': [{'title': 'Resultado', 'fact_ids': ids}], 'hypotheses': []}), 'stop'
    s.gateway.complete = gateway
    results, history = [], []
    for question in ADDITIONAL if additional else ORIGINAL:
        history.append({'role': 'user', 'content': question})
        r = s.run(history); results.append(r)
        history.append({'role': 'assistant', 'content': r.answer})
        assert r.steps <= 3
        assert not r.is_partial, (question, r.metrics['errors'], r.metrics['events'])
        assert s.memory.last_requested_scope['filters'] == r.plan['resolved_context']['filters']
        assert any(e['stage'] == 'request_contract' for e in r.metrics['events'])
    scopes = [r.plan['resolved_context'] for r in results]
    if additional:
        assert scopes[1]['intent'] == 'open_analysis' and scopes[1]['filters']['medio'] == 'DIGITAL'
        assert scopes[2]['filters'] == {'marca': 'BMW'}
        assert scopes[4]['requested_period'] == {'start': '2025-10-01', 'end': '2025-10-31'}
        assert scopes[6]['filters'] == {'marca': 'VOLVO'} and scopes[6]['comparison_period']['start'] == '2025-09-01'
        assert scopes[7]['filters'] == {}
        assert scopes[10]['filters'] == {'marca': 'BMW'} and scopes[10]['requested_period']['start'] == '2025-10-01'
        assert scopes[11]['dimensions'] == ['vehiculo'] and scopes[11]['intent'] == 'diagnostic'
    else:
        assert scopes[0]['requested_period']['start'] == '2026-07-01'
        assert scopes[1]['requested_period']['start'] == '2026-06-01'
        assert scopes[1]['comparison_period']['start'] == '2026-05-01'
        assert scopes[4]['filters'] == {'marca': 'BMW', 'medio': 'DIGITAL'}
        assert scopes[6]['filters'] == {'marca': 'BMW'}
        assert scopes[9]['filters'] == scopes[10]['filters']
        assert scopes[10]['dimensions'] == ['anunciante']
        assert scopes[11]['dimensions'] == ['marca']


def test_independent_ranking_after_comparison_replaces_scope():
    p = payload('ranking', filters={'medio_agrupado': ['TV ABIERTA', 'TV CABLE']}, steps=[step('ranking_por_dimension', {'dimension': 'anunciante'})])
    p.update(operation='breakdown', dimensions=['anunciante'])
    memory = {'analysis_context': {'intent': 'period_comparison', 'filters': {'marca': 'RENAULT', 'medio': 'DIGITAL'},
              'comparison_period': {'start': '2023-01-01', 'end': '2023-12-31'}}}
    plan = planner().plan('Ranking de anunciantes', memory, payload=p)
    context = AnalysisContext.resolve(plan.scope, memory, today=date(2026, 9, 11))
    assert context.filters == {'medio_agrupado': ['TV ABIERTA', 'TV CABLE']}
    assert plan.intent == 'ranking' and context.comparison_period == {}


def test_shift_declared_with_inherit_does_not_repeat_focus():
    previous = {'requested_period': {'start': '2025-03-01', 'end': '2025-03-31'},
                'comparison_period': {'start': '2025-02-01', 'end': '2025-02-28'}, 'intent': 'ranking_change'}
    p = payload('ranking_change', period={'kind': 'inherit'}, filters={}, mode='inherit', steps=[])
    p.update(operation='shift_period', dimensions=['marca'])
    plan = planner().plan('Retrocede', {'analysis_context': previous}, payload=p)
    context = AnalysisContext.resolve(plan.scope, {'analysis_context': previous}, today=date(2026, 9, 11))
    assert context.requested_period['start'] == '2025-02-01'
    assert context.comparison_period['start'] == '2025-01-01'


def test_diagnosis_does_not_shift_focus_a_second_time():
    previous = {'requested_period': {'start': '2025-10-01', 'end': '2025-10-31'}, 'intent': 'lookup'}
    p = payload('diagnostic_search', period={'kind': 'previous_period'}, filters={}, mode='inherit', steps=[])
    p.update(operation='explain_difference')
    plan = planner().plan('Explica el cambio', {'analysis_context': previous}, payload=p)
    context = AnalysisContext.resolve(plan.scope, {'analysis_context': previous}, today=date(2026, 9, 11))
    assert context.requested_period['start'] == '2025-10-01'
    assert context.comparison_period['start'] == '2025-09-01'


def test_changing_extrema_granularity_is_not_rejected_as_rediscovery():
    previous = {'intent': 'temporal_extrema', 'analysis': {'granularity': 'month', 'extreme': 'min'}}
    p = payload('temporal_extrema', period={'kind': 'inherit'}, steps=[])
    p.update(operation='discover_extreme', analysis={'granularity': 'week', 'extreme': 'min'})
    result = planner().plan('El mínimo semanal', {'analysis_context': previous, 'last_peak': {'period': '2025-01-01'}}, payload=p)
    assert result.steps[0].arguments == {'granularidad': 'week', 'extremo': 'min'}


def test_joint_missing_one_entity_never_claims_full_combined_share():
    from src.data.bigquery_repository import BigQueryRepository
    repo = NS(_full_dimension=lambda *a: {'rows': [{'dimension': 'ONE', 'value': 30}, {'dimension': 'OTHER', 'value': 70}]})
    result = BigQueryRepository.consultar_participacion(repo, dimension='marca', values=['ONE', 'MISSING'])
    assert result['success'] is False and result['missing_values'] == ['MISSING']
    assert not evidence_sufficient('joint_share', [{'result': result}])


def test_failed_catalog_validation_preserves_requested_scope():
    class Repo(FakeRepository):
        def catalogo(self, dimension, **kw):
            return {'success': True, 'values': ['ACTUAL_LABEL']}
    p = payload('ranking', filters={'medio': 'NOT_A_LABEL'}, steps=[step('ranking_por_dimension', {'dimension': 'anunciante'})])
    p['dimensions'] = ['anunciante']
    s, _, _ = service([p, p], repo=Repo())
    s.run([{'role': 'user', 'content': 'Clasifica anunciantes con ese medio.'}])
    assert s.memory.last_requested_scope['filters'] == {'medio': 'NOT_A_LABEL'}
    assert s.memory.last_requested_scope['dimensions'] == ['anunciante']
    assert s.memory.last_confirmed_evidence_scope == {}


def test_diagnostic_scores_use_complete_high_cardinality_partition():
    from src.data.comparative import dimension_search
    from src.data.bigquery_repository import BigQueryRepository
    class Repo(Partitions):
        _partition_difference = BigQueryRepository._partition_difference
        def _full_dimension(self, dimension, metric, filters, period):
            current = period['start'] == '2025-03-01'
            return {'rows': [{'dimension': f'V{i}', 'value': (2 if current else 1)} for i in range(150)], 'evidence': {'sql': 'fixture'}}
    r = dimension_search(Repo(), period_a={'start': '2025-03-01', 'end': '2025-03-31'},
                         period_b={'start': '2025-02-01', 'end': '2025-02-28'}, dimensions=['marca', 'medio'])
    assert r['success']
    assert all(c['categories'] == 150 and c['score_pct'] == pytest.approx(2) for c in r['candidate_evaluations'])
    assert len(r['drivers']) == 5


def test_explicit_joint_values_precede_incomplete_recent_memory():
    p = payload('joint_share', filters={}, steps=[step('consultar_participacion_bicomp', {'dimension': 'marca', 'valores': ['A', 'B']})])
    p['analysis'] = {'entity_reference': 'recent', 'entity_count': 2}
    r = planner().plan('Conjunto explícito', {'recent_entities': [{'dimension': 'marca', 'value': 'A'}]}, payload=p)
    assert r.steps[0].arguments['valores'] == ['A', 'B']


def test_explicit_comparison_is_not_overwritten_by_entity_memory():
    p = payload('diagnostic_search', filters={'marca': 'TOYOTA'}, period={'kind': 'year', 'year': 2023}, mode='inherit', steps=[])
    p.update(operation='change_entity', comparison_period={'kind': 'year', 'year': 2022})
    previous = {'intent': 'diagnostic_search', 'requested_period': {'start': '2024-01-01', 'end': '2024-12-31'},
                'comparison_period': {'start': '2023-01-01', 'end': '2023-12-31'}}
    r = planner().plan('Solicitud con ambos periodos', {'analysis_context': previous}, payload=p)
    c = AnalysisContext.resolve(r.scope, {'analysis_context': previous}, today=date(2026, 9, 11))
    assert c.requested_period['start'] == '2023-01-01' and c.comparison_period['start'] == '2022-01-01'


def test_diagnostic_temporal_contract_selects_temporal_driver_capability():
    p = payload('diagnostic', steps=[step('explicar_diferencia_entidades_bicomp', {'dimension': 'medio'})])
    p.update(operation='explain_difference', comparison_period={'kind': 'previous_year'})
    r = planner().plan('Contribuciones por medio', payload=p)
    assert r.steps[0].tool == 'analizar_drivers_bicomp' and r.scope['dimensions'] == ['medio']


def test_restore_with_new_axis_keeps_declared_composition():
    old = {'intent': 'open_analysis', 'filters': {'marca': 'A', 'medio': 'RADIO'}, 'dimensions': ['medio'],
           'requested_period': {'start': '2024-01-01', 'end': '2024-12-31'}}
    p = payload('composition', filters={'marca': 'A'}, period={'kind': 'inherit'}, steps=[step('ranking_por_dimension', {'dimension': 'medio'})])
    p.update(operation='restore_scope', dimensions=['medio'], analysis={'restore_with_breakdown': True})
    r = planner().plan('Composición por medio', {'recent_scopes': [old]}, payload=p)
    assert r.intent == 'composition' and r.scope['filters'] == {'marca': 'A'}


def test_diagnostic_reference_inheritance_does_not_shift_current():
    prior = {'intent': 'ranking_change', 'requested_period': {'start': '2026-06-01', 'end': '2026-06-30'},
             'comparison_period': {'start': '2026-05-01', 'end': '2026-05-31'}}
    p = payload('diagnostic_search', filters={}, period={'kind': 'previous_period', 'anchor': 'focus'}, steps=[])
    p['comparison_period'] = {'kind': 'inherit'}
    r = planner().plan('Analiza la variación vigente', {'analysis_context': prior}, payload=p)
    c = AnalysisContext.resolve(r.scope, {'analysis_context': prior}, today=date(2026, 9, 11))
    assert c.requested_period == prior['requested_period'] and c.comparison_period == prior['comparison_period']


@pytest.mark.parametrize('case', ['growth', 'breakdown', 'failed_followup', 'joint', 'peak', 'comparison', 'advertiser'])
def test_evaluator_accepts_matching_positive_controls(case):
    base = {'is_partial': False, 'plan': {'resolved_context': {}}, 'evidence': []}
    r = {'success': True}
    expected = {}
    if case == 'growth':
        expected = {'capability': 'rank_change'}
        r.update(capability='rank_change', comparison_equivalent=True, period_a={'start': '2025-02-01'}, period_b={'start': '2025-01-01'},
                 rows=[{'current_value': 120, 'previous_value': 100, 'difference': 20}])
    elif case == 'breakdown':
        expected = {'removed_filters': ['medio']}
        r.update(filters={'marca': 'X'}, dimension='medio', rows=[{'dimension': 'A', 'value': 20}, {'dimension': 'B', 'value': 80}])
    elif case == 'failed_followup':
        expected = {'filters': {'medio': 'RADIO'}, 'dimensions': ['anunciante']}
        base['plan']['resolved_context'] = deepcopy(expected)
    elif case == 'joint':
        expected = {'capability': 'joint_share'}
        r.update(values=['A', 'B'], value=30, total=100, share_pct=30)
    elif case == 'peak':
        expected = {'capability': 'peak'}
        r.update(granularity='month', rows=[{'value': 100}], peak={'value': 100})
    elif case == 'comparison':
        expected = {'capability': 'comparison'}
        r.update(comparison_equivalent=True, period_a={'start': '2025-02-01'}, period_b={'start': '2025-01-01'})
    else:
        expected = {'dimension': 'anunciante'}
        r.update(dimension='anunciante', rows=[{'dimension': 'A', 'value': 100}])
    base['evidence'] = [{'result': r}]
    assert assess_state(base, expected)['passed']


def test_current_month_focus_anchor_survives_replacing_filters():
    previous = {'requested_period': {'start': '2026-06-01', 'end': '2026-06-30'}, 'intent': 'ranking_change'}
    p = payload('diagnostic_search', filters={}, steps=[], period={'kind': 'current_month', 'anchor': 'focus'})
    p['comparison_period'] = {'kind': 'previous_period'}
    r = planner().plan('Diagnóstico del foco vigente', {'analysis_context': previous}, payload=p)
    c = AnalysisContext.resolve(r.scope, {'analysis_context': previous}, today=date(2026, 9, 12), available={'start': '2019-01-01', 'end': '2026-07-31'})
    assert c.requested_period == previous['requested_period'] and c.comparison_period['start'] == '2026-05-01'


def test_restore_open_analysis_with_axis_promotes_filter():
    previous = {'intent': 'open_analysis', 'filters': {'marca': 'A', 'medio': 'RADIO'}, 'dimensions': ['medio'],
                'requested_period': {'start': '2024-01-01', 'end': '2024-12-31'}}
    p = payload('open_analysis', filters={'marca': 'A'}, period={'kind': 'inherit'}, steps=[step('ranking_por_dimension', {'dimension': 'medio'}), step('serie_temporal_bicomp', {'granularidad': 'month'})])
    p.update(operation='restore_scope', dimensions=['medio'], analysis={'restore_with_breakdown': True})
    r = planner().plan('Abrir por medio', {'analysis_context': previous}, payload=p)
    assert r.scope['filters'] == {'marca': 'A'} and r.intent == 'open_analysis'


def test_semantic_review_corrects_intent_before_query():
    wrong = payload('ranking', steps=[step('ranking_por_dimension', {'dimension': 'marca'})])
    wrong['dimensions'] = ['marca']
    review = {'valid': False, 'reason': 'Se pidió un total, no un ranking.',
              'corrections': {'intent': 'lookup', 'operation': 'new_analysis', 'dimensions': []}}
    s, client, repo = service([wrong, review], plan_semantic_review=True)
    r = s.run([{'role': 'user', 'content': 'Total de BMW en 2025.'}])
    assert not r.is_partial and r.plan['intent'] == 'lookup'
    assert len(client.calls) == 2 and len(repo.calls) == 1
    assert any(e['stage'] == 'semantic_review' and not e['valid'] for e in r.metrics['events'])


def test_semantic_review_cannot_invent_tool_calls():
    wrong = payload()
    review = {'valid': False, 'reason': 'Cambio.', 'corrections': {'steps': [step('consultar_inversion_publicitaria')]}}
    s, _, repo = service([wrong, review], plan_semantic_review=True)
    r = s.run([{'role': 'user', 'content': 'Total.'}])
    assert r.is_partial and not repo.calls


def test_filter_only_preserves_axes_criterion_and_both_periods():
    previous = {'intent': 'ranking_change', 'dimensions': ['anunciante'], 'analysis': {'change_basis': 'percent'},
                'filters': {}, 'requested_period': {'start': '2024-02-01', 'end': '2024-02-29'},
                'comparison_period': {'start': '2024-01-01', 'end': '2024-01-31'}}
    p = payload('ranking', filters={'medio': 'RADIO'}, steps=[step('ranking_por_dimension', {'dimension': 'vehiculo'})])
    p.update(operation='filter_scope', dimensions=['vehiculo'], analysis={'change_basis': 'absolute'})
    r = planner().plan('Restringir alcance', {'analysis_context': previous, 'last_strategy': [step('ranking_cambio_bicomp', {'dimension': 'anunciante'})]}, payload=p)
    c = AnalysisContext.resolve(r.scope, {'analysis_context': previous}, today=date(2026, 9, 12))
    assert r.intent == 'ranking_change' and r.scope['dimensions'] == ['anunciante']
    assert r.scope['analysis']['change_basis'] == 'percent'
    assert c.requested_period == previous['requested_period'] and c.comparison_period == previous['comparison_period']


def test_restore_without_new_breakdown_cannot_replace_latest_objective():
    previous = {'intent': 'diagnostic_search', 'filters': {'marca': 'A'}, 'dimensions': [],
                'requested_period': {'start': '2024-02-01', 'end': '2024-02-29'},
                'comparison_period': {'start': '2024-01-01', 'end': '2024-01-31'},
                'strategy': [step('diagnosticar_dimensiones_bicomp')]}
    p = payload('open_analysis', filters={'marca': 'A'}, period={'kind': 'inherit'},
                steps=[step('ranking_por_dimension', {'dimension': 'medio'})])
    p.update(operation='restore_scope', dimensions=['medio'])
    r = planner().plan('Retomar entidad', {'recent_scopes': [previous]}, payload=p)
    assert r.intent == 'diagnostic_search' and r.scope['dimensions'] == []
    assert r.scope['comparison_period']['start'] == '2024-01-01'


def test_invalid_review_uses_bounded_plan_repair():
    initial = payload()
    malformed = {'valid': False, 'reason': 'Operación equivocada.', 'corrections': {'operation': 'ranking_change'}}
    s, client, repo = service([initial, malformed, initial], plan_semantic_review=True)
    r = s.run([{'role': 'user', 'content': 'Total.'}])
    assert not r.is_partial and len(client.calls) == 3 and len(repo.calls) == 1
    assert any(e['stage'] == 'plan_validation' and 'Revisión inválida' in e['issue'] for e in r.metrics['events'])


@pytest.mark.parametrize('axis,passes', [('medio', True), ('vehiculo', False)])
def test_evaluator_checks_filter_only_axis_preservation(axis, passes):
    record = {'memory_before': {'analysis_context': {'dimensions': ['medio']}},
              'result': {'plan': {'resolved_context': {'dimensions': [axis]}},
                         'evidence': [{'result': {'success': True}}], 'is_partial': False}}
    assert assess_record(record, {'preserve_fields': ['dimensions']})['passed'] is passes


def test_restoration_cannot_hide_explicit_filtered_breakdown():
    previous = {'intent': 'open_analysis', 'filters': {'marca': 'A', 'medio': 'RADIO'}, 'dimensions': ['medio'],
                'requested_period': {'start': '2024-01-01', 'end': '2024-12-31'},
                'strategy': [step('ranking_por_dimension', {'dimension': 'medio'}), step('serie_temporal_bicomp')]}
    p = payload('open_analysis', filters={'marca': 'A'}, period={'kind': 'inherit'})
    p.update(operation='restore_scope', dimensions=['medio'])
    with pytest.raises(InvalidToolPlanError, match='propio eje'):
        planner().plan('Ahora por medios', {'analysis_context': previous}, payload=p)


def test_failed_review_retains_request_without_confirming_evidence():
    first = payload(filters={'marca': 'A'})
    failed = payload('ranking', filters={'medio': 'RADIO'}, steps=[step('ranking_por_dimension', {'dimension': 'anunciante'})])
    failed['dimensions'] = ['anunciante']
    following = deepcopy(failed)
    following.update(operation='change_period', period={'kind': 'year', 'year': 2026})
    ok = {'valid': True, 'reason': 'Corresponde.', 'corrections': {}}
    s, _, repo = service([first, ok, failed, RuntimeError('review unavailable'), following, ok, 'La inversión fue 100.'], plan_semantic_review=True)
    history = []
    for question in ['Total de A.', 'Top anunciantes en radio.', '¿Y en 2026?']:
        history.append({'role': 'user', 'content': question})
        r = s.run(history)
        history.append({'role': 'assistant', 'content': r.answer})
        if question == 'Top anunciantes en radio.':
            assert r.is_partial
            assert s.memory.last_requested_scope['filters'] == {'medio': 'RADIO'}
            assert s.memory.last_confirmed_evidence_scope['filters'] == {'marca': 'A'}
    assert r.plan['intent'] == 'ranking' and repo.calls[-1]['filters'] == {'medio': 'RADIO'}
    assert repo.calls[-1]['start_date'] == '2026-01-01'


def test_measure_change_cannot_masquerade_as_filter_operation():
    previous = {'intent': 'ranking_change', 'filters': {}, 'analysis': {'change_basis': 'absolute'}}
    p = payload('ranking_change', filters={}, steps=[])
    p.update(operation='filter_scope', analysis={'change_basis': 'percent'})
    with pytest.raises(InvalidToolPlanError, match='criterio de medida'):
        planner().plan('Cambiar el criterio', {'analysis_context': previous}, payload=p)


def test_acceleration_inherits_explicit_percentage_basis():
    previous = {'intent': 'ranking_change', 'dimensions': ['marca'], 'analysis': {'change_basis': 'percent'}}
    p = payload('ranking_acceleration', filters={}, steps=[], mode='inherit', period={'kind': 'inherit'})
    r = planner().plan('Investigar aceleración', {'analysis_context': previous}, payload=p)
    assert r.steps[0].arguments['criterio'] == 'percent'
    p['analysis'] = {'change_basis': 'absolute'}
    r = planner().plan('Cambiar criterio de aceleración', {'analysis_context': previous}, payload=p)
    assert r.steps[0].arguments['criterio'] == 'absolute'


def test_configured_entity_term_is_accepted_by_filter_validation():
    p = payload(filters={'anunciante': 'ENTIDAD NUEVA'})
    r = planner().plan('Total de la empresa ENTIDAD NUEVA.', payload=p)
    assert r.scope['filters'] == {'anunciante': 'ENTIDAD NUEVA'}


def test_unresolved_comparison_preserves_requested_objective_after_rejection():
    first = payload(filters={'marca': 'A'})
    invalid = payload('period_comparison', filters={'marca': 'B'},
        steps=[step('comparar_periodos_bicomp')])
    invalid['comparison_period'] = {'kind': 'year', 'year': 2025}
    s, _, repo = service([first, invalid, invalid])
    history = [{'role': 'user', 'content': 'Total de A.'}]
    first_result = s.run(history)
    history += [{'role': 'assistant', 'content': first_result.answer}, {'role': 'user', 'content': 'Compara periodos de B.'}]
    rejected = s.run(history)
    assert rejected.is_partial and len(repo.calls) == 1
    assert s.memory.last_requested_scope['intent'] == 'period_comparison'
    assert s.memory.last_requested_scope['filters'] == {'marca': 'B'}
    assert s.memory.last_requested_scope['unresolved_fields'] == ['comparison_period']
    assert s.memory.last_confirmed_evidence_scope['filters'] == {'marca': 'A'}
    follow = payload('period_comparison', filters={'marca': 'C'}, mode='inherit', period={'kind': 'inherit'},
        steps=[step('comparar_periodos_bicomp')])
    follow.update(operation='change_entity', comparison_period={'kind': 'previous_year'})
    plan = planner().plan('Ahora C', s.memory.context(), payload=follow)
    context = AnalysisContext.resolve(plan.scope, s.memory.context(), today=date(2026, 9, 12))
    assert context.intent == 'period_comparison' and context.requested_period == {'start': '2025-01-01', 'end': '2025-12-31'}
    assert context.comparison_period == {'start': '2024-01-01', 'end': '2024-12-31'}
    assert not context.unresolved_fields
