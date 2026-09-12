import json
from src.tools.registry import ToolRegistry
from types import SimpleNamespace
from evaluations.evaluator import evaluate_planner

TOOLS = {s['function']['name'] for s in ToolRegistry(SimpleNamespace(source='mock')).schemas}


def prediction(memory):
    data = bool(memory.get('last_domain'))
    return {'intent': 'lookup' if data else 'out_of_domain', 'operation': 'new_analysis', 'scope_mode': 'inherit',
            'filters': {}, 'period': {'kind': 'inherit'}, 'dimensions': [], 'analysis_questions': [],
            'steps': [{'tool': 'consultar_inversion_publicitaria', 'purpose': 'Consultar el alcance previo.', 'arguments': {}}] if data else [],
            'answer': '' if data else 'Falta contexto.'}


def test_bicomp_planner_evaluation_is_deterministic(tmp_path):
    cases = [{'question': '¿Y después?', 'expected_domain': 'none', 'expected_tool': None},
             {'question': '¿Y antes?', 'expected_domain': 'bicomp', 'expected_tool': 'consultar_inversion_publicitaria'}]
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(cases))
    result = evaluate_planner(TOOLS, path, interpreter=lambda q, m: prediction(m))
    assert result['cases'] == 2 and result['domain_accuracy'] == 0.5
    assert len(result['failures']) == 1 and result['failures'][0]['question'] == '¿Y antes?'


def test_evaluation_uses_case_memory_and_resets_independent_cases(tmp_path):
    cases = [{'question': 'y para otro año', 'requires_memory': True,
              'memory': {'last_domain': 'bicomp', 'last_entities': {'brands': ['ENTIDAD_A']}},
              'expected_domain': 'bicomp', 'expected_tool': 'consultar_inversion_publicitaria', 'expected_intent': 'lookup'},
             {'question': 'y para otro año', 'expected_domain': 'none', 'expected_tool': None, 'expected_intent': 'out_of_domain'}]
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(cases))
    observed = []
    def interpret(question, memory):
        observed.append(memory.copy())
        return prediction(memory)
    result = evaluate_planner(TOOLS, path, interpreter=interpret)
    assert result['failures'] == []
    assert observed[0]['last_domain'] == 'bicomp' and observed[1] == {}
    cases[0]['expected_intent'] = 'out_of_domain'
    path.write_text(json.dumps(cases))
    assert len(evaluate_planner(TOOLS, path, interpreter=interpret)['failures']) == 1
