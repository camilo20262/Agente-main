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


def test_driver_response_closes_top_four_and_omits_free_directional_interpretation():
    drivers = [
        {'dimension': 'medio', 'value': 'TV NAL', 'current_value': 0, 'previous_value': 51068.40,
         'contribution': -51068.40, 'contribution_pct': 44.39},
        {'dimension': 'medio', 'value': 'TELEVISION NACIONAL', 'current_value': 0, 'previous_value': 51068.30,
         'contribution': -51068.30, 'contribution_pct': 44.39},
        {'dimension': 'medio', 'value': 'RADIO', 'current_value': 0, 'previous_value': 50877.40,
         'contribution': -50877.40, 'contribution_pct': 44.23},
        {'dimension': 'medio', 'value': 'TV SUSCRIPCION', 'current_value': 42042, 'previous_value': 0,
         'contribution': 42042, 'contribution_pct': -36.55},
        {'dimension': 'medio', 'value': 'OTRO A', 'current_value': 0, 'previous_value': 3000,
         'contribution': -3000, 'contribution_pct': 2.61},
        {'dimension': 'medio', 'value': 'OTRO B', 'current_value': 0, 'previous_value': 1061.69,
         'contribution': -1061.69, 'contribution_pct': 0.92},
    ]
    data = [{'id': 'e1', 'result': {'success': True, 'metric': 'inv_neta',
        'value_a_label': 'BMW', 'value_b_label': 'Volvo', 'value_a': 88994.42, 'value_b': 204028.21,
        'difference': -115033.79, 'difference_pct': -56.38, 'drivers': drivers, 'drivers_total': 6,
        'driver_closure': {'shown_count': 4, 'shown_contribution': -110972.10, 'omitted_count': 2,
                           'residual_contribution': -4061.69, 'residual_contribution_pct': 3.53}}}]
    facts = fact_catalog(data)
    tv_subscription = next(f for f in facts if 'TV SUSCRIPCION' in f['text'])
    output = render_narrative(json.dumps({'findings': [{'title': 'TV SUSCRIPCION',
        'fact_ids': [tv_subscription['id']],
        'interpretation': 'Esto aumenta la desventaja de BMW.'}]}), facts, data)
    assert 'Esto aumenta la desventaja' not in output
    assert 'Las 4 contribuciones principales suman -110.972,10' in output
    assert '2 categorías no mostradas es -4.061,69' in output
    assert '3,53 % de la diferencia neta' in output
    for label in ('TV NAL', 'TELEVISION NACIONAL', 'RADIO', 'TV SUSCRIPCION'):
        assert label in output
    assert validate_answer(output, data).valid
