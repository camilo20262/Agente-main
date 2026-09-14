from datetime import date
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from google.api_core.exceptions import BadRequest, ServiceUnavailable
from src.config import Settings
from src.data.bigquery_repository import BigQueryRepository
from src.tools.registry import ToolRegistry
from src.data.sql_guard import validate_read_only_sql, UnsafeQueryError


def repository(monkeypatch, rows):
    repo = BigQueryRepository(Settings(), client=object())
    schema = {'fecha': 'DATE', 'inv_neta': 'FLOAT', 'marca': 'STRING', 'medio': 'STRING', 'ciudad': 'STRING'}
    monkeypatch.setattr(repo, 'get_bicomp_schema', lambda: schema)
    execute = Mock(return_value={'rows': rows, 'evidence': {'bytes_processed': 0, 'duration_ms': 0}})
    monkeypatch.setattr(repo, '_execute_bicomp', execute)
    return repo, execute


def test_null_metric_is_not_success(monkeypatch):
    repo, _ = repository(monkeypatch, [{'value': None, 'source_rows': 4}])
    result = repo.consultar_inversion()
    assert result['success'] is False and result['error_type'] == 'no_data'


def test_lookup_obtains_coverage_in_same_query(monkeypatch):
    repo, execute = repository(monkeypatch, [{'value': 1490000, 'source_rows': 10,
        '_available_start': date(2019, 1, 1), '_available_end': date(2026, 7, 31),
        '_observed_start': date(2026, 1, 1), '_observed_end': date(2026, 7, 1)}])
    result = repo.consultar_inversion(start_date='2026-01-01', end_date='2026-12-31')
    assert execute.call_count == 1 and result['is_partial']
    assert result['effective_period']['end'] == '2026-07-31'
    assert result['requested_period']['end'] == '2026-12-31'


def test_safe_normalization_applies_to_all_text_dimensions(monkeypatch):
    repo, _ = repository(monkeypatch, [])
    expression = repo._dimension_group_expression('ciudad')
    sql, params = repo._bicomp_filters({'ciudad': [' Bogotá ', 'bogotá']}, None, None)
    assert 'UPPER(TRIM(' in expression and 'UPPER(TRIM(' in sql
    assert params[0][2] == ['BOGOTÁ', 'BOGOTÁ']


def test_catalog_cache_is_explicit_and_ttl_respected(monkeypatch):
    repo, execute = repository(monkeypatch, [{'value': 'A'}])
    first = repo.obtener_marcas()
    second = repo.obtener_marcas()
    assert second['cache_hit'] is True and execute.call_count == 1
    repo._catalog_cache.clear()
    repo.obtener_marcas()
    assert execute.call_count == 2


@pytest.mark.parametrize('error,kind', [(BadRequest('Bad SQL'), 'schema'), (ServiceUnavailable('Down'), 'infrastructure')])
def test_google_errors_are_classified(error, kind):
    repo = NS(source='bigquery', consultar_inversion=Mock(side_effect=error))
    result = ToolRegistry(repo).execute('consultar_inversion_publicitaria', {})
    assert not result['success'] and result['error_type'] == kind


@pytest.mark.parametrize('sql', ['SELECT * FROM foreign.dataset.table',
    'SELECT * FROM `p.d.t`, `foreign.dataset.table`',
    'WITH x AS (SELECT * FROM foreign.dataset.table) SELECT * FROM x'])
def test_sql_allowlist_covers_unquoted_comma_and_cte_sources(sql):
    with pytest.raises(UnsafeQueryError): validate_read_only_sql(sql, {'p.d.t'})


def test_sql_comments_inside_literals_are_preserved():
    sql = "SELECT '--literal' AS label FROM `p.d.t`"
    assert '--literal' in validate_read_only_sql(sql, {'p.d.t'})


def test_alias_conflict_cannot_drop_filters():
    repo = NS(source='mock', consultar_inversion=Mock())
    result = ToolRegistry(repo).execute('consultar_inversion_publicitaria', {'filtros': {'marca': 'A'}, 'filters': {'marca': 'B'}})
    assert result['success'] is False and result['error_type'] == 'arguments'
    repo.consultar_inversion.assert_not_called()


def test_entity_difference_has_complete_partition_and_same_period(monkeypatch):
    repo = BigQueryRepository(Settings(), client=object())
    monkeypatch.setattr(repo, '_bicomp_field', lambda field, **kw: field)
    current = {'rows': [{'dimension': 'A', 'value': 80}, {'dimension': 'B', 'value': 20}], 'evidence': {}}
    previous = {'rows': [{'dimension': 'A', 'value': 20}, {'dimension': 'C', 'value': 30}], 'evidence': {}}
    full = Mock(side_effect=[current, previous]); monkeypatch.setattr(repo, '_full_dimension', full)
    result = repo.explicar_diferencia_entidades(entity_dimension='marca', value_a='X', value_b='Y', dimension='medio',
        start_date='2024-01-01', end_date='2024-12-31')
    assert result['difference'] == 50 and result['difference_pct'] == 100
    assert sum(r['contribution'] for r in result['drivers']) == 50
    assert sum(r['contribution_pct'] for r in result['drivers']) == pytest.approx(100)
    assert result['driver_closure'] == {
        'shown_count': 3, 'shown_contribution': 50, 'omitted_count': 0,
        'residual_contribution': 0, 'residual_contribution_pct': 0,
    }
    assert full.call_args_list[0].args[-1] == full.call_args_list[1].args[-1]
    assert result['comparison_type'] == 'entities'


def test_entity_difference_reports_observed_side_when_other_entity_has_no_rows(monkeypatch):
    from src.agent.finalization import safe_answer
    from src.agent.response_validator import validate_answer

    repo = BigQueryRepository(Settings(), client=object())
    monkeypatch.setattr(repo, '_bicomp_field', lambda field, **kw: field)
    empty = {'rows': [], 'evidence': {'rows': 0}, 'metric_label': 'Inversión publicitaria neta',
             'requested_period': {'start': '2026-05-01', 'end': '2026-05-31'},
             'effective_period': {'start': '2026-05-01', 'end': '2026-05-31'}}
    observed = {'rows': [
        {'dimension': 'RADIO', 'value': 30, 'source_rows': 1},
        {'dimension': 'TV NAL', 'value': 20, 'source_rows': 1},
    ], 'evidence': {'rows': 2}, 'metric_label': 'Inversión publicitaria neta'}
    monkeypatch.setattr(repo, '_full_dimension', Mock(side_effect=[empty, observed]))

    result = repo.explicar_diferencia_entidades(
        entity_dimension='marca', value_a='BMW', value_b='Volvo', dimension='medio',
        start_date='2026-05-01', end_date='2026-05-31')

    assert result['success'] is False and result['error_type'] == 'no_data'
    assert result['comparison_status'] == 'incomplete_entity_observation'
    assert result['missing_entities'] == ['BMW']
    assert result['entity_observations'] == [
        {'label': 'BMW', 'status': 'no_rows', 'source_rows': 0, 'group_count': 0, 'observed_value': None},
        {'label': 'Volvo', 'status': 'observed', 'source_rows': 2, 'group_count': 2, 'observed_value': 50},
    ]
    assert 'periodos' not in result['error']
    evidence = [{'tool': 'explicar_diferencia_entidades_bicomp', 'result': result}]
    answer = safe_answer(evidence, reason='no_data')
    assert all(text in answer for text in ('BMW', 'Volvo', '50,00', 'mayo de 2026'))
    assert all(section in answer for section in ('### Lectura disponible', '### Implicación para el análisis', '### Recomendación'))
    assert all(term not in answer for term in ('BICOMP', 'BigQuery', '2026-05-01', '2026-05-31'))
    assert 'no equivale necesariamente a una inversión de cero' in answer
    assert validate_answer(answer, evidence, intent='diagnostic').valid


def test_external_query_cannot_bypass_allowlist():
    with pytest.raises(UnsafeQueryError):
        validate_read_only_sql("SELECT * FROM EXTERNAL_QUERY('connection', 'SELECT * FROM secret')", {'p.d.t'})


def test_grouped_ranking_partitions_denominator_before_top_n(monkeypatch):
    rows = [{'segment': 'NORTE', 'dimension': 'A', 'value': 80, 'group_total': 100, 'rank': 1, 'share_pct': 80, 'ranked_rows_total': 1}]
    repo, execute = repository(monkeypatch, rows)
    result = repo.ranking_segmentado(dimension='marca', group_dimension='ciudad', limit=1)
    sql = execute.call_args.args[0].sql
    assert 'SUM(value) OVER (PARTITION BY segment)' in sql
    assert sql.index('SUM(value) OVER (PARTITION BY segment)') < sql.index('WHERE rank <= @limit')
    assert result['dimensions'] == ['ciudad', 'marca'] and result['rows'][0]['share_pct'] == 80


def test_grouped_ranking_rejects_identical_dimensions(monkeypatch):
    repo, execute = repository(monkeypatch, [])
    with pytest.raises(ValueError): repo.ranking_segmentado(dimension='marca', group_dimension='marca')
    execute.assert_not_called()


def test_missing_labels_have_one_definition_for_sql_and_narrative(monkeypatch):
    from src.analytics.calculations import MISSING_LABELS
    repo, execute = repository(monkeypatch, [])
    repo.ranking(dimension='marca')
    sql = execute.call_args.args[0].sql
    assert 'N/D' in MISSING_LABELS
    assert all("'" + label + "'" in sql for label in MISSING_LABELS)


def test_ratio_is_labeled_as_derived_metric_not_numerator_amount(monkeypatch):
    repo, _ = repository(monkeypatch, [{'value': 1.82, 'numerator': 182, 'denominator': 100}])
    monkeypatch.setattr(repo, '_bicomp_field', lambda field, **kw: field)
    result = repo.calcular_ratio(numerator='inv_bruta', denominator='inv_neta')
    assert result['unit'] == 'ratio' and result['metric_label'].startswith('Cociente')
    assert 'bruta' in result['metric_label'] and 'neta' in result['metric_label']
