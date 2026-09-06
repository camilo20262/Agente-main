from src.semantic import load_semantic_layer


def test_bicomp_sum_is_a_code_loaded_business_rule():
    semantic = load_semantic_layer()
    assert semantic["metrics"]["inv_neta"]["default_aggregation"] == "sum"
    assert semantic["business_rules"]["bicomp"]["default_aggregation"] == "sum"
    assert load_semantic_layer() is semantic
