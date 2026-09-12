import json
import pytest
from src.agent.facts import fact_catalog, render_narrative
from src.agent.response_validator import validate_answer


def test_narrative_selects_deterministic_facts_and_rejects_unknown_ids():
    evidence = [{'id': 'e1', 'tool': 'ranking', 'result': {'success': True, 'metric': 'inv_neta',
        'filters': {'marca': 'A'}, 'dimension': 'medio', 'rows': [{'dimension': 'DIGITAL', 'value': 60, 'share_pct': 30}]}}]
    facts = fact_catalog(evidence)
    raw = json.dumps({'summary': 'El principal medio es digital.', 'findings': [{'title': 'Mix', 'fact_ids': ['F1'], 'interpretation': 'Representa una parte de la inversión.'}], 'hypotheses': []})
    rendered = render_narrative(raw, facts, evidence)
    assert '60,00' in rendered and '30,00 %' in rendered
    assert validate_answer(rendered, evidence).valid
    with pytest.raises(ValueError, match='desconocida'):
        render_narrative(raw.replace('F1', 'F999'), facts, evidence)


def test_factual_labels_and_partial_cutoff_are_preserved():
    data = [{'id': 'e1', 'result': {'success': True, 'metric': 'inv_neta', 'dimension': 'formato',
        'rows': [{'dimension': None, 'value': 100, 'share_pct': 100}], 'is_partial': True,
        'effective_period': {'start': '2026-01-01', 'end': '2026-07-31'}}}]
    facts = fact_catalog(data)
    output = render_narrative(json.dumps({'summary': 'Predomina la falta de información.', 'findings': [
        {'title': 'Calidad de datos', 'fact_ids': ['F1'], 'interpretation': ''}], 'hypotheses': []}), facts, data)
    assert 'Sin información' in output and '2026-07-31' in output
    assert validate_answer(output, data).valid


def test_prose_cannot_add_a_percentage_not_in_selected_evidence():
    data = [{'result': {'success': True, 'metric': 'inv_neta', 'value': 100}}]
    output = render_narrative(json.dumps({'summary': 'La inversión creció 999%.', 'findings': [
        {'title': 'Inversión', 'fact_ids': ['F1']}]}), fact_catalog(data), data)
    assert "999" not in output
    assert validate_answer(output, data).valid


def test_joint_share_fact_preserves_requested_percentage_and_full_denominator():
    data = [{'result': {'success': True, 'metric': 'inv_neta', 'dimension': 'medio',
        'values': ['A', 'B'], 'value': 30, 'total': 200, 'share_pct': 15}}]
    facts = fact_catalog(data)
    assert len(facts) == 1
    assert all(value in facts[0]['text'] for value in ['A, B', '30,00', '200,00', '15,00 %'])
    output = render_narrative(json.dumps({'findings': [{'title': 'Participación conjunta', 'fact_ids': ['F1']}]}), facts, data)
    assert validate_answer(output, data).valid


@pytest.mark.parametrize('claim', ['más de una sexta parte', 'casi dos tercios', 'el doble', 'una séptima parte', 'casi tres veces', 'diez por ciento'])
def test_quantitative_words_cannot_bypass_the_no_arithmetic_contract(claim):
    data = [{'result': {'success': True, 'metric': 'inv_neta', 'value': 100}}]
    output = render_narrative(json.dumps({'findings': [{'title': 'Inversión', 'fact_ids': ['F1'],
        'interpretation': 'Esto representa ' + claim + ' del total.'}]}), fact_catalog(data), data)
    assert claim not in output and '100,00' in output


def test_missing_categories_are_replaced_by_mandatory_quality_fact():
    data = [{'result': {'success': True, 'metric': 'inv_neta', 'dimension': 'formato',
        'rows': [{'dimension': None, 'value': 90, 'share_pct': 90}, {'dimension': 'VIDEO', 'value': 10, 'share_pct': 10}],
        'data_quality': {'unknown_share_pct': 90, 'known_share_pct': 10}}}]
    facts = fact_catalog(data)
    assert len(facts) == 2 and 'VIDEO' in facts[0]['text']
    output = render_narrative(json.dumps({'findings': [{'title': 'Formato identificado', 'fact_ids': ['F1']}]}), facts, data)
    assert '90,00 %' in output and 'no son categorías de negocio' in output
    assert 'formato=Sin información' not in output
    assert validate_answer(output, data).valid


def test_driver_facts_identify_both_entities_without_needing_another_fact():
    data = [{'result': {'success': True, 'metric': 'inv_neta', 'value_a_label': 'ENTIDAD X', 'value_b_label': 'ENTIDAD Y',
        'drivers': [{'dimension': 'medio', 'value': 'RADIO', 'current_value': 30, 'previous_value': 20,
                     'contribution': 10, 'contribution_pct': 100}]}}]
    text = fact_catalog(data)[0]['text']
    assert '30,00 en ENTIDAD X' in text and '20,00 en ENTIDAD Y' in text
