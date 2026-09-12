from decimal import Decimal
import pytest
from src.agent.response_validator import validate_answer, compact_evidence


def evidence(**result):
    return [{'result': {'success': True, 'metric': 'inv_neta', 'value': 1490000, 'period': {'start': '2026-01-01', 'end': '2026-12-31'}, **result}, 'id': 'e1', 'tool': 'consulta'}]


@pytest.mark.parametrize('text', ['Participación: 65%.', 'Representan casi 64,8%.', 'Participación: 57,9 por ciento.'])
def test_percentages_without_any_percentage_evidence_are_rejected(text):
    assert not validate_answer(text, evidence()).valid


def test_combining_percentages_is_not_allowed():
    data = evidence(rows=[{'dimension': 'A', 'share_pct': Decimal('56.8')}, {'dimension': 'B', 'share_pct': 8.0}])
    assert not validate_answer('Juntos representan 64,8%.', data).valid
    assert validate_answer('A representa 56,8% y B representa 8,0%.', data).valid


def test_decimal_percentages_and_rounding_are_supported():
    assert validate_answer('Participación: 57,9%.', evidence(share_pct=Decimal('57.87'))).valid
    assert validate_answer('Inversión: 1,49 millones.', evidence()).valid
    assert not validate_answer('Inversión: 999 millones.', evidence()).valid


@pytest.mark.parametrize('answer,finish', [('', 'stop'), ('Inversión: 1,49 millones.', 'length'), ('Esto continúa con', 'stop'),
                                          ('**Texto.', 'stop'), ('```texto.', 'stop'), ('[Enlace](sin cerrar.', 'stop')])
def test_incomplete_answers_never_pass(answer, finish):
    assert not validate_answer(answer, evidence(), finish_reason=finish).valid


def test_row_count_is_not_insertions():
    assert not validate_answer('Hubo 460 inserciones.', evidence(row_count=460)).valid
    assert validate_answer('Hubo 460 inserciones.', evidence(metric='total_insercion', value=460)).valid


def test_causal_claims_must_be_in_hypotheses_and_checks_resume_after_section():
    assert not validate_answer('El crecimiento responde a Black Friday.', evidence()).valid
    assert validate_answer('### Hipótesis\nPodría responder a Black Friday; revisar las campañas para validarlo.', evidence()).valid
    assert not validate_answer('### Hipótesis\nPodría ser una activación.\n### Hallazgos\nEl crecimiento fue por Black Friday.', evidence()).valid


def test_single_cycle_does_not_prove_seasonality():
    assert not validate_answer('Existe estacionalidad.', evidence()).valid
    assert validate_answer('No se puede demostrar estacionalidad.', evidence()).valid


def test_partial_year_requires_actual_cutoff():
    data = evidence(is_partial=True, effective_period={'start': '2026-01-01', 'end': '2026-07-31'})
    assert not validate_answer('El total anual fue 1,49 millones.', data).valid
    assert validate_answer('El acumulado disponible hasta julio de 2026 fue 1,49 millones.', data).valid


def test_simple_direction_contradiction_is_rejected():
    assert not validate_answer('La inversión aumentó.', evidence(difference=-20, difference_pct=-10)).valid


def test_compaction_removes_sql_and_keeps_context_and_catalog_values():
    data = evidence(filters={'marca': 'A'}, values=['A', 'B'], available_period={'end': '2026-07-31'},
                    evidence={'sql': 'SELECT SECRET', 'bytes_processed': 100}, row_count=999)
    compact = compact_evidence(data)
    assert 'SECRET' not in str(compact) and 'row_count' not in str(compact)
    assert compact[0]['values'] == ['A', 'B'] and compact[0]['available_period']['end'] == '2026-07-31'


def test_compaction_marks_truncation_and_preserves_full_series_peak():
    compact = compact_evidence(evidence(granularity='month', rows=[{'period': str(i), 'value': i} for i in range(40)], peak={'value': 39}))
    assert compact[0]['rows_truncated'] == {'shown': 24, 'total': 40}
    assert compact[0]['peak']['value'] == 39


def test_numeric_source_labels_are_not_fabricated_amounts():
    data = evidence(rows=[{'dimension': '360 FITNESS', 'value': 1234}])
    assert validate_answer('360 FITNESS registra 1.234.', data).valid
    assert not validate_answer('360 FITNESS registra 9.876.', data).valid


def test_observed_date_day_is_supported_without_allowing_arbitrary_days():
    data = evidence(observed_period={'start': '2025-01-01', 'end': '2025-12-27'})
    assert validate_answer('Datos observados hasta el 27 de diciembre de 2025.', data).valid
    assert not validate_answer('Datos observados hasta el 29 de diciembre de 2025.', data).valid


def test_decrease_magnitude_keeps_direction_grounded():
    data = evidence(difference=-20, difference_pct=-15.821)
    assert validate_answer('La inversión bajó 15,82%.', data).valid
    assert not validate_answer('La inversión aumentó 15,82%.', data).valid


def test_partial_year_negation_is_not_an_annual_claim():
    data = evidence(is_partial=True, effective_period={'end': '2026-07-31'})
    assert validate_answer('Datos hasta julio: no es un total anual completo.', data).valid
    assert not validate_answer('El total anual completo es 1,49 millones. Datos hasta julio.', data).valid


def test_small_decimal_is_not_misread_as_thousands():
    assert validate_answer('El valor es 0.302.', evidence(value=0.302)).valid


def test_percentage_over_one_thousand_is_parsed_as_a_whole():
    assert validate_answer('La variación es 1.203,08 %.', evidence(difference_pct=1203.083)).valid
    assert validate_answer('La variación es 1,203.08 %.', evidence(difference_pct=1203.083)).valid


def test_decrease_amount_can_be_expressed_as_a_magnitude():
    data = evidence(drivers=[{'value': 'OOH', 'contribution': -193114.899}])
    assert validate_answer('OOH restó 193.114,90.', data).valid
    assert not validate_answer('OOH aportó 193.114,90.', data).valid
def test_conceptual_explanations_can_discuss_possible_causes_without_claiming_observations():
    from src.agent.response_validator import validate_answer
    text = 'Un pico puede reflejar lanzamientos o campañas estacionales; se necesita contexto para interpretarlo.'
    assert validate_answer(text, [], intent='out_of_domain').valid
    assert not validate_answer(text, [], intent='diagnostic').valid
    assert not validate_answer('', [], intent='out_of_domain').valid
