from agent import TOOLS
from evaluations.evaluator import evaluate_planner


def test_bicomp_planner_evaluation_is_deterministic():
    result = evaluate_planner({tool["function"]["name"] for tool in TOOLS})
    assert result["cases"] == 31
    assert result["domain_accuracy"] == 1.0
    assert result["tool_selection_accuracy"] == 1.0
    assert result["failures"] == []


def test_evaluation_uses_case_memory_and_resets_independent_cases(tmp_path):
    import json

    cases = [
        {"question": "y para 2026", "requires_memory": True,
         "memory": {"last_domain": "bicomp", "last_entities": {"brands": ["VOLVO"]}},
         "expected_domain": "bicomp", "expected_tool": "consultar_inversion_publicitaria", "expected_intent": "metric_query"},
        {"question": "y para 2026", "expected_domain": "none", "expected_tool": None, "expected_intent": "out_of_domain"},
    ]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    result = evaluate_planner({tool["function"]["name"] for tool in TOOLS}, path)
    assert result["failures"] == []

    cases[0]["expected_intent"] = "out_of_domain"
    path.write_text(json.dumps(cases), encoding="utf-8")
    result = evaluate_planner({tool["function"]["name"] for tool in TOOLS}, path)
    assert len(result["failures"]) == 1
    assert result["failures"][0]["predicted_intent"] == "metric_query"
