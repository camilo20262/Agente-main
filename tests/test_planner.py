"""Plan contracts and scope resolution, independent of any brand or wording router."""
from copy import deepcopy
from datetime import date
import pytest
from src.agent.planner import AnalyticalPlan, AnalyticalPlanner, InvalidToolPlanError, PlanStep, INTENT_BUDGETS
from src.agent.analysis_context import AnalysisContext
from src.semantic import load_semantic_layer
from src.tools.registry import ToolRegistry
from types import SimpleNamespace

TOOLS = {s['function']['name'] for s in ToolRegistry(SimpleNamespace(source='mock')).schemas}
TODAY = date(2026, 9, 10)
MEMORY = {'last_domain': 'bicomp', 'last_metric': 'inv_neta', 'last_entities': {'brands': ['ENTIDAD_A']},
          'last_filters': {'marca': 'ENTIDAD_A'}, 'last_period': {'start': '2025-01-01', 'end': '2025-12-31'}}


def plan_payload(**overrides):
    return {'intent': 'lookup', 'operation': 'new_analysis', 'scope_mode': 'replace', 'metric': 'inv_neta', 'filters': {},
            'period': {'kind': 'all'}, 'dimensions': [], 'analysis_questions': [],
            'steps': [{'tool': 'consultar_inversion_publicitaria', 'arguments': {}, 'purpose': 'Obtener el total solicitado.'}], **overrides}


def test_plans_variation_with_registered_tool():
    payload = plan_payload(intent='diagnostic', steps=[
        {'tool': 'comparar_periodos_bicomp', 'arguments': {}, 'purpose': 'Determinar el cambio entre periodos.'},
        {'tool': 'analizar_drivers_bicomp', 'arguments': {'dimension': 'medio'}, 'purpose': 'Descomponer la variación por medio.'}])
    plan = AnalyticalPlanner(TOOLS).plan('¿Por qué cambió esta entidad?', payload=payload)
    assert plan.intent == 'diagnostic' and plan.budget == 5


def test_follow_up_reuses_memory_domain_and_entities():
    p = plan_payload(scope_mode='inherit', filters={'medio': 'DIGITAL'}, period={'kind': 'inherit'})
    ctx = AnalysisContext.resolve(p, MEMORY, today=TODAY)
    assert ctx.filters == {'marca': 'ENTIDAD_A', 'medio': 'DIGITAL'}
    assert ctx.requested_period == MEMORY['last_period']


def test_invalid_tool_plan_is_rejected():
    with pytest.raises(InvalidToolPlanError):
        AnalyticalPlanner(TOOLS).validate(AnalyticalPlan('lookup', ['bicomp'], [PlanStep('inventada', 'No válida.')]))


@pytest.mark.parametrize('dimension', list(load_semantic_layer()['dimensions']))
def test_every_semantic_dimension_is_available_without_special_routing(dimension):
    p = plan_payload(intent='ranking', dimensions=[dimension], steps=[
        {'tool': 'ranking_por_dimension', 'arguments': {'dimension': dimension}, 'purpose': 'Desglosar la métrica por dimensión solicitada.'}])
    plan = AnalyticalPlanner(TOOLS).plan('Una pregunta no anticipada.', payload=p)
    assert plan.scope['dimensions'] == [dimension]
    assert plan.steps[0].arguments['dimension'] == dimension


@pytest.mark.parametrize('brand', ['BMW', 'VOLVO', 'ENTIDAD_NUEVA'])
@pytest.mark.parametrize('year', [2024, 2026, 2027])
def test_temporal_follow_up_reuses_context_without_modifying_it(brand, year):
    memory = {**deepcopy(MEMORY), 'last_filters': {'marca': brand}}
    original = deepcopy(memory)
    ctx = AnalysisContext.resolve(plan_payload(scope_mode='inherit', period={'kind': 'year', 'year': year}), memory, today=TODAY)
    assert ctx.filters == {'marca': brand} and ctx.requested_period['start'] == f'{year}-01-01'
    assert memory == original


def test_temporal_follow_up_keeps_insertion_metric():
    ctx = AnalysisContext.resolve(plan_payload(scope_mode='inherit', metric=None, period={'kind': 'year', 'year': 2026}),
                                  {**MEMORY, 'last_metric': 'total_insercion'}, today=TODAY)
    assert ctx.metric == 'total_insercion'


def test_new_explicit_entity_does_not_keep_old_filters():
    ctx = AnalysisContext.resolve(plan_payload(filters={'marca': 'NUEVA'}, period={'kind': 'year', 'year': 2026}),
                                  {**MEMORY, 'last_filters': {'marca': 'ANTIGUA', 'medio': 'TV'}}, today=TODAY)
    assert ctx.filters == {'marca': 'NUEVA'}


def test_follow_up_can_replace_entity_and_keep_period():
    ctx = AnalysisContext.resolve(plan_payload(scope_mode='inherit', filters={'marca': 'NUEVA'}, period={'kind': 'inherit'}), MEMORY, today=TODAY)
    assert ctx.filters == {'marca': 'NUEVA'} and ctx.requested_period == MEMORY['last_period']


def test_entity_comparison_removes_single_entity_filter():
    ctx = AnalysisContext.resolve(plan_payload(scope_mode='inherit', remove_filters=['marca']), MEMORY, today=TODAY)
    assert 'marca' not in ctx.filters


@pytest.mark.parametrize('question', ['Hola', '¿Qué es share?', '¿Qué día es hoy?', '¿Qué es una marca?', '¿Cómo se interpreta un pico?'])
def test_conceptual_intent_does_not_require_tools_even_with_memory(question):
    p = plan_payload(intent='out_of_domain', steps=[], answer='Respuesta conceptual.')
    plan = AnalyticalPlanner(TOOLS).plan(question, MEMORY, payload=p)
    assert plan.budget == 0 and not plan.steps


@pytest.mark.parametrize('change', [{'metric': 'inventada'}, {'dimensions': ['inventada']}, {'filters': {'inventado': 'X'}},
                                   {'operation': 'new_analysis', 'scope_mode': 'adivinar'}, {'intent': 'inventar'}, {'extra': True}])
def test_invalid_interpretation_is_rejected(change):
    with pytest.raises(InvalidToolPlanError):
        AnalyticalPlanner(TOOLS).plan('Pregunta.', payload=plan_payload(**change))


def test_lookup_cannot_plan_unnecessary_exploration():
    p = plan_payload()
    p['steps'].append({'tool': 'serie_temporal_bicomp', 'arguments': {'granularidad': 'month'}, 'purpose': 'Exploración innecesaria.'})
    with pytest.raises(InvalidToolPlanError):
        AnalyticalPlanner(TOOLS).plan('Total.', payload=p)


def test_open_analysis_needs_multiple_perspectives():
    with pytest.raises(InvalidToolPlanError):
        AnalyticalPlanner(TOOLS).plan('Analiza.', payload=plan_payload(intent='open_analysis'))


def test_scope_prevents_accidental_widening_and_metric_change():
    context = AnalysisContext.resolve(plan_payload(scope_mode='inherit', period={'kind': 'inherit'}), MEMORY, today=TODAY)
    with pytest.raises(ValueError): context.bind({'filtros': {'marca': 'OTRA'}}, {'filtros': {}})
    with pytest.raises(ValueError): context.bind({'metrica': 'inv_bruta'}, {'metrica': {}})
    with pytest.raises(ValueError): context.bind({'fecha_inicio': '2020-01-01', 'fecha_fin': '2025-12-31'}, {'fecha_inicio': {}, 'fecha_fin': {}})


@pytest.mark.parametrize('dimension', list(load_semantic_layer()['dimensions']))
def test_ranking_rejects_omitted_explicit_group_from_semantic_model(dimension):
    p = plan_payload(intent='ranking', dimensions=[], steps=[
        {'tool': 'ranking_por_dimension', 'arguments': {'dimension': 'marca'},
         'purpose': 'Obtener un ranking global incorrecto.'}])
    with pytest.raises(InvalidToolPlanError, match='agrupación explícitas'):
        AnalyticalPlanner(TOOLS).plan('Ordena los resultados por ' + dimension.replace('_', ' '), payload=p)


def test_group_validation_handles_accents_plurals_and_longest_semantic_label():
    from src.agent.planner import explicit_group_dimensions
    semantic = load_semantic_layer()
    assert explicit_group_dimensions('Categorías por regiones y resultados por cada ciudades', semantic) == {'region', 'ciudad'}
    assert explicit_group_dimensions('Ranking por medio agrupado', semantic) == {'medio_agrupado'}
    assert explicit_group_dimensions('Ranking por plataforma', semantic) == {'medio'}
    assert explicit_group_dimensions('Ranking con la marca REGIONES', semantic) == set()


def test_comparison_followup_cannot_invent_a_different_literal_focus_year():
    p = plan_payload(intent='period_comparison', operation='compare_periods', scope_mode='inherit',
        period={'kind': 'year', 'year': 2023}, comparison_period={'kind': 'year', 'year': 2024},
        steps=[{'tool': 'comparar_periodos_bicomp', 'purpose': 'Comparar la inversión de ambos periodos.', 'arguments': {}}])
    memory = {'analysis_context': {'requested_period': {'start': '2024-01-01', 'end': '2024-12-31'}}}
    with pytest.raises(InvalidToolPlanError, match='periodo foco'):
        AnalyticalPlanner(TOOLS).plan('¿Aumentó?', memory, payload=p)
    assert AnalyticalPlanner(TOOLS).plan('Compara 2023 respecto a 2024.', memory, payload=p)


def test_empty_optional_period_is_absence_not_a_malformed_month():
    p = plan_payload(comparison_period={})
    assert AnalyticalPlanner(TOOLS).plan('Total.', payload=p).scope['comparison_period'] is None


def test_bare_entity_reference_cannot_authorize_a_new_entity_comparison():
    p = plan_payload(intent='comparison', operation='compare_entities', scope_mode='inherit',
        steps=[{'tool': 'comparar_entidades_bicomp', 'purpose': 'Comparar dos entidades del contexto.',
                'arguments': {'dimension': 'marca', 'valor_a': 'ENTIDAD NUEVA', 'valor_b': 'ENTIDAD PREVIA'}}])
    memory = {'analysis_context': {'intent': 'diagnostic', 'filters': {'marca': 'ENTIDAD PREVIA'}}}
    with pytest.raises(InvalidToolPlanError, match='solo nombra una entidad'):
        AnalyticalPlanner(TOOLS).plan('¿Y ENTIDAD NUEVA?', memory, payload=p)
    assert AnalyticalPlanner(TOOLS).plan('Compara ENTIDAD NUEVA y ENTIDAD PREVIA.', memory, payload=p)
    assert AnalyticalPlanner(TOOLS).plan('Compara ambos.', memory, payload=p)
