from agent import TOOLS
from evaluations.evaluator import evaluate_planner


def test_bicomp_planner_evaluation_is_deterministic():
    result = evaluate_planner({tool["function"]["name"] for tool in TOOLS})
    assert result["cases"] == 24
    assert result["domain_accuracy"] == 1.0
    assert result["tool_selection_accuracy"] == 1.0