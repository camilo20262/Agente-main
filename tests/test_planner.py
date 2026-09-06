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
