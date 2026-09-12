from datetime import date
import pytest
from src.agent.analysis_context import AnalysisContext
from src.agent.planner import AnalyticalPlanner, InvalidToolPlanError
from src.tools.registry import ToolRegistry
from tests.test_agent_service import payload, step, FakeRepository


def planner():
    return AnalyticalPlanner({s['function']['name'] for s in ToolRegistry(FakeRepository()).schemas})


def test_symbolic_comparison_lifted_and_bound_without_orientation_change():
    p = payload('period_comparison', steps=[step('comparar_periodos_bicomp', {
        'periodo_a': {'kind': 'year', 'year': 2026}, 'periodo_b': {'kind': 'year', 'year': 2025}})])
    p['period'] = None
    plan = planner().plan('Compara las inversiones.', payload=p)
    context = AnalysisContext.resolve(plan.scope, {}, today=date(2026, 9, 10))
    args = context.bind(plan.steps[0].arguments, {'periodo_a': {}, 'periodo_b': {}})
    assert args['periodo_a']['start'] == '2026-01-01'
    assert args['periodo_b']['start'] == '2025-01-01'
    with pytest.raises(ValueError, match='orientación'):
        context.bind({'periodo_a': args['periodo_b'], 'periodo_b': args['periodo_a']}, {'periodo_a': {}, 'periodo_b': {}})


def test_explicit_period_inheritance_is_independent_of_filter_replacement():
    p = payload('comparison', mode='replace', filters={}, period={'kind': 'inherit'},
                steps=[step('comparar_entidades_bicomp', {'dimension': 'marca', 'valor_a': 'A', 'valor_b': 'B'})])
    context = AnalysisContext.resolve(p, {'analysis_context': {'filters': {'marca': 'A'},
        'requested_period': {'start': '2024-01-01', 'end': '2024-12-31'}}}, today=date(2026, 9, 10))
    assert context.filters == {} and context.requested_period['start'] == '2024-01-01'


def test_diagnostic_can_use_one_tool_with_comparison_and_drivers():
    p = payload('diagnostic', steps=[step('analizar_drivers_bicomp', {'dimension': 'medio'})])
    assert planner().plan('Explica el cambio.', payload=p).budget == 5


@pytest.mark.parametrize('spec', [{'kind': 'invented'}, {'kind': 'month', 'month': 13}, {'kind': 'range', 'start': '2025-01-01'}])
def test_invalid_period_is_repaired_at_planning_boundary(spec):
    with pytest.raises(InvalidToolPlanError): planner().plan('Inversión.', payload=payload(period=spec))


def test_implicit_entity_cannot_silently_become_advertiser():
    p = payload(filters={'anunciante': 'Entidad arbitraria'})
    with pytest.raises(InvalidToolPlanError, match='nombre comercial'):
        planner().plan('Cuánto invirtió Entidad arbitraria.', payload=p)
    assert planner().plan('Cuánto invirtió el anunciante Entidad arbitraria.', payload=p)


def test_relative_comparison_resolves_previous_year_only_once():
    context = AnalysisContext.resolve({'intent': 'period_comparison', 'scope_mode': 'replace',
        'period': {'kind': 'ytd'}, 'comparison_period': {'kind': 'previous_year'}, 'filters': {}}, {},
        today=date(2026, 9, 10), available={'start': '2019-01-01', 'end': '2026-07-31'})
    args = context.bind({'periodo_a': {'kind': 'ytd'}, 'periodo_b': {'kind': 'previous_year'}}, {'periodo_a': {}, 'periodo_b': {}})
    assert args['periodo_a'] == {'start': '2026-01-01', 'end': '2026-07-31'}
    assert args['periodo_b'] == {'start': '2025-01-01', 'end': '2025-07-31'}


def test_period_operation_preserves_open_analysis_objective():
    p = payload('period_comparison', period={'kind': 'year', 'year': 2026})
    p['operation'] = 'change_period'
    with pytest.raises(InvalidToolPlanError, match='open_analysis'):
        planner().plan('Otro año.', {'analysis_context': {'intent': 'open_analysis'}}, payload=p)


def test_breakdown_after_comparison_cannot_be_replaced_by_a_mix():
    p = payload('composition', steps=[step('analizar_medios')]); p['operation'] = 'breakdown'; p['scope_mode'] = 'inherit'
    plan = planner().plan('Desglosa.', {'analysis_context': {'intent': 'period_comparison',
        'comparison_period': {'start': '2024-01-01', 'end': '2024-12-31'}}}, payload=p)
    assert plan.intent == 'diagnostic' and plan.steps[0].tool == 'analizar_drivers_bicomp'


def test_inspecting_a_peak_requires_calculated_peak_scope():
    p = payload('diagnostic'); p['operation'] = 'inspect_peak'
    with pytest.raises(InvalidToolPlanError, match='peak'):
        planner().plan('Inspecciona el máximo.', payload=p)


def test_shared_initial_filters_become_memory_scope():
    p = payload('open_analysis', filters={}, steps=[step('serie_temporal_bicomp', {'granularidad': 'month', 'filtros': {'marca': 'A'}}),
        step('ranking_por_dimension', {'dimension': 'medio', 'filtros': {'marca': 'A'}})])
    plan = planner().plan('Analiza A.', payload=p)
    assert plan.scope['filters'] == {'marca': 'A'}


def test_change_period_reuses_previous_llm_strategy_without_old_scope():
    memory = {'analysis_context': {'intent': 'open_analysis'}, 'last_strategy': [
        step('serie_temporal_bicomp', {'granularidad': 'month', 'fecha_inicio': '2024-01-01', 'filtros': {'marca': 'A'}}),
        step('ranking_por_dimension', {'dimension': 'region'})]}
    p = payload('period_comparison', period={'kind': 'year', 'year': 2026}); p['operation'] = 'change_period'
    plan = planner().plan('Otro año.', memory, payload=p)
    assert plan.intent == 'open_analysis' and len(plan.steps) == 2
    assert 'fecha_inicio' not in plan.steps[0].arguments and plan.scope['comparison_period'] is None


def test_entity_comparison_does_not_create_a_temporal_reference():
    p = payload('comparison', steps=[step('comparar_entidades_bicomp', {'dimension': 'marca', 'valor_a': 'A', 'valor_b': 'B'})])
    p['comparison_period'] = {'kind': 'inherit'}
    plan = planner().plan('Compara las dos marcas.', payload=p)
    assert plan.scope['comparison_period'] is None and 'marca' in plan.scope['remove_filters']


def test_change_entity_inherits_comparison_reference_not_current_period():
    p = payload('comparison', filters={'marca': 'B'}, period={'kind': 'inherit'}, mode='inherit')
    p.update(operation='change_entity', comparison_period={'kind': 'inherit'})
    memory = {'analysis_context': {'intent': 'diagnostic', 'filters': {'marca': 'A'},
        'requested_period': {'start': '2026-01-01', 'end': '2026-12-31'},
        'comparison_period': {'start': '2025-01-01', 'end': '2025-12-31'}},
        'last_strategy': [step('analizar_drivers_bicomp', {'dimension': 'medio'})]}
    plan = planner().plan('Otra entidad.', memory, payload=p)
    context = AnalysisContext.resolve(plan.scope, memory, today=date(2026, 9, 11))
    assert plan.intent == 'diagnostic' and context.filters == {'marca': 'B'}
    assert context.comparison_period['start'] == '2025-01-01'


def test_entity_operation_cannot_turn_into_a_time_difference():
    p = payload('diagnostic', mode='inherit', period={'kind': 'inherit'}, filters={}, steps=[
        step('comparar_entidades_bicomp', {'dimension': 'marca', 'valor_a': 'A', 'valor_b': 'B', 'fecha_inicio': '2024-01-01'}),
        step('analizar_drivers_bicomp', {'dimension': 'medio'})])
    p['operation'] = 'compare_entities'
    plan = planner().plan('Compara ambas.', payload=p)
    assert len(plan.steps) == 1 and plan.steps[0].tool == 'explicar_diferencia_entidades_bicomp'
    assert plan.steps[0].arguments['dimension_entidad'] == 'marca'
    assert 'fecha_inicio' not in plan.steps[0].arguments and plan.scope['comparison_period'] is None


def test_declared_group_dimension_cannot_disappear_from_ranking():
    p = payload('ranking', steps=[step('ranking_por_dimension', {'dimension': 'marca'})])
    p['dimensions'] = ['marca', 'ciudad']
    plan = planner().plan('Ranking dentro de cada grupo.', payload=p)
    assert plan.steps[0].tool == 'ranking_segmentado_bicomp'
    assert plan.steps[0].arguments['dimension_grupo'] == 'ciudad'


def test_known_peak_drilldown_uses_diagnostic_sufficiency_instead_of_requiring_series():
    p = payload('trend', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}),
        step('ranking_por_dimension', {'dimension': 'medio'})])
    p['operation'] = 'inspect_peak'
    plan = planner().plan('Explica el máximo.', {'last_peak': {'period': '2024-03-01'}}, payload=p)
    assert plan.intent == 'diagnostic'
    assert plan.scope['dimensions'] == ['medio']
    assert len(plan.steps) == 1 and plan.steps[0].tool == 'ranking_por_dimension'


def test_entity_change_reuses_reference_even_when_conflicting_plan_clears_it():
    p = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), step('analizar_medios')])
    p.update(operation='change_entity', comparison_period=None, period={'kind': 'inherit'}, filters={'marca': 'B'})
    reference = {'start': '2023-01-01', 'end': '2023-12-31'}
    memory = {'analysis_context': {'intent': 'diagnostic', 'filters': {'marca': 'A'},
        'requested_period': {'start': '2024-01-01', 'end': '2024-12-31'}, 'comparison_period': reference},
        'last_strategy': [step('analizar_drivers_bicomp', {'dimension': 'medio'})]}
    plan = planner().plan('Otra entidad.', memory, payload=p)
    context = AnalysisContext.resolve(plan.scope, memory, today=date(2024, 12, 31))
    assert context.comparison_period == reference and context.filters == {'marca': 'B'}
    assert plan.intent == 'diagnostic' and plan.steps[0].tool == 'analizar_drivers_bicomp'
