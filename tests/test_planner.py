import pytest

from src.agent.planner import AnalyticalPlan, AnalyticalPlanner, InvalidToolPlanError, PlanStep


TOOLS = {"consultar_inversion_publicitaria", "comparar_marcas", "comparar_periodos_bicomp", "explicar_variacion_bicomp", "serie_temporal_bicomp"}


def test_plans_variation_with_registered_tool():
    plan = AnalyticalPlanner(TOOLS).plan("¿Por qué cayó la inversión de Volvo en febrero?")
    assert plan.domains == ["bicomp"]
    assert plan.steps[0].tool == "explicar_variacion_bicomp"


def test_follow_up_reuses_memory_domain_and_entities():
    memory = {"last_domain": "bicomp", "last_entities": {"brands": ["VOLVO", "RENAULT"]}}
    plan = AnalyticalPlanner(TOOLS).plan("Ahora solo digital.", memory)
    assert plan.domains == ["bicomp"]
    assert plan.steps[0].tool == "comparar_marcas"


def test_invalid_tool_plan_is_rejected():
    planner = AnalyticalPlanner(TOOLS)
    with pytest.raises(InvalidToolPlanError):
        planner.validate(AnalyticalPlan("bad", ["bicomp"], [PlanStep("inventada", "no válida")]))


BICOMP_MEMORY = {
    "last_domain": "bicomp", "last_metric": "inv_neta",
    "last_entities": {"brands": ["VOLVO"]}, "last_filters": {"marca": "VOLVO"},
    "last_period": {"start": "2025-01-01", "end": "2025-12-31"},
}


@pytest.mark.parametrize("question", ["y para 2026", "¿Y en marzo?", "el mes pasado", "este trimestre", "la semana anterior"])
def test_temporal_follow_up_reuses_bicomp_context_without_modifying_it(question):
    from copy import deepcopy

    memory = deepcopy(BICOMP_MEMORY)
    plan = AnalyticalPlanner(TOOLS).plan(question, memory)
    assert plan.domains == ["bicomp"]
    assert plan.intent == "metric_query"
    assert plan.steps[0].tool == "consultar_inversion_publicitaria"
    assert memory == BICOMP_MEMORY


@pytest.mark.parametrize("question", ["y para 2026", "¿Y en marzo?", "por formato", "este trimestre"])
@pytest.mark.parametrize("memory", [None, {"last_domain": "attachments"}])
def test_temporal_or_dimension_reference_does_not_create_bicomp_context(question, memory):
    plan = AnalyticalPlanner(TOOLS).plan(question, memory)
    assert plan.intent == "out_of_domain"
    assert plan.steps == []


def test_temporal_follow_up_keeps_insertion_metric_routing():
    memory = {**BICOMP_MEMORY, "last_metric": "total_insercion"}
    plan = AnalyticalPlanner(TOOLS | {"consultar_inserciones_bicomp"}).plan("y para 2026", memory)
    assert plan.steps[0].tool == "consultar_inserciones_bicomp"


def test_temporal_follow_up_preserves_brand_comparison():
    memory = {**BICOMP_MEMORY, "last_entities": {"brands": ["VOLVO", "RENAULT"]}}
    plan = AnalyticalPlanner(TOOLS).plan("¿y en marzo?", memory)
    assert plan.steps[0].tool == "comparar_marcas"


@pytest.mark.parametrize("question", [
    "Inversión por formato", "Inversión por dispositivo", "Inserciones por región",
    "Inserción por formato", "Inserciones por ciudades", "Inserciones por sector",
    "Inserciones por holding", "Inserciones por agencia", "Inserciones por país",
    "Inserciones por anunciante", "Inserciones por marca",
])
def test_explicit_dimension_breakdown_uses_generic_ranking(question):
    plan = AnalyticalPlanner(TOOLS | {"ranking_por_dimension"}).plan(question)
    assert plan.domains == ["bicomp"]
    assert plan.intent == "dimension_breakdown"
    assert plan.steps[0].tool == "ranking_por_dimension"


@pytest.mark.parametrize("question", ["¿y por formato?", "por región", "por dispositivo"])
def test_dimension_only_follow_up_inherits_bicomp(question):
    plan = AnalyticalPlanner(TOOLS | {"ranking_por_dimension"}).plan(question, BICOMP_MEMORY)
    assert plan.domains == ["bicomp"]
    assert plan.steps[0].tool == "ranking_por_dimension"


@pytest.mark.parametrize("question,tool", [
    ("Inserciones por medio", "analizar_medios"),
    ("Inserciones por vehículo", "analizar_vehiculos"),
    ("¿Cuántas inserciones tuvo Volvo?", "consultar_inserciones_bicomp"),
])
def test_existing_specialized_routes_are_preserved(question, tool):
    plan = AnalyticalPlanner(TOOLS | {tool}).plan(question)
    assert plan.steps[0].tool == tool


def test_current_date_question_remains_out_of_domain_with_memory():
    plan = AnalyticalPlanner(TOOLS).plan("¿Qué día es hoy?", BICOMP_MEMORY)
    assert plan.intent == "out_of_domain"


def test_explicit_single_brand_question_with_year_does_not_inherit_comparison():
    memory = {**BICOMP_MEMORY, "last_entities": {"brands": ["VOLVO", "RENAULT"]}}
    plan = AnalyticalPlanner(TOOLS).plan("¿Cuánto invirtió Volvo en 2026?", memory)
    assert plan.steps[0].tool == "consultar_inversion_publicitaria"


@pytest.mark.parametrize("question,tool,intent", [
    ("Ranking por marca.", "ranking_por_dimension", "dimension_breakdown"),
    ("Ranking por medio.", "analizar_medios", "media_analysis"),
    ("Ranking por vehículo.", "analizar_vehiculos", "vehicle_analysis"),
])
def test_ranking_dimension_routing_is_intentional(question, tool, intent):
    # Intentional change: "Ranking por marca." now uses the generic ranking,
    # instead of ranking_marcas. Medio/vehiculo keep their specialized routes.
    # PlanStep selects a tool only; dimension arguments are tested at the repository.
    allowed = TOOLS | {"ranking_marcas", "ranking_por_dimension", "analizar_medios", "analizar_vehiculos"}
    plan = AnalyticalPlanner(allowed).plan(question)
    assert plan.domains == ["bicomp"]
    assert plan.intent == intent
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == tool
