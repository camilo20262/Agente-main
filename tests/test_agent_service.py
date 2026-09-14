"""End-to-end simulated conversations against the public service and real registry.

Replaces assumptions about forced NVIDIA tools with explicit plan/stop contracts.
Original protections (deduplication, partial evidence, multimodal text, retries) remain.
"""
import json
from datetime import date
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from src.agent.service import AgentService, _extract_user_text
from src.agent.planner import AnalyticalPlanner
from src.config import Settings
from src.tools.registry import ToolRegistry


class FakeRepository:
    source = 'mock'
    def __init__(self): self.calls = []
    def consultar_inversion(self, **kwargs):
        self.calls.append(kwargs)
        return {'success': True, 'domain': 'bicomp', 'source': 'mock', 'metric': kwargs.get('metric', 'inv_neta'),
                'value': 100, 'filters': kwargs.get('filters') or {},
                'period': {'start': kwargs.get('start_date'), 'end': kwargs.get('end_date')}}
    def serie_temporal_bicomp(self, **kwargs):
        return {**self.consultar_inversion(**kwargs), 'granularity': 'month',
                'rows': [{'period': '2025-01-01', 'value': 40}, {'period': '2025-11-01', 'value': 60}],
                'peak': {'period': '2025-11-01', 'value': 60, 'share_of_total_pct': 60}}
    def ranking(self, **kwargs):
        return {**self.consultar_inversion(**kwargs), 'dimension': kwargs['dimension'],
                'rows': [{'dimension': 'DIGITAL', 'value': 100, 'share_pct': 100}]}
    def analizar_medios(self, **kwargs): return self.ranking(dimension='medio', **kwargs)
    def comparar_marcas(self, **kwargs):
        return {**self.consultar_inversion(**kwargs), 'brand_a': kwargs['brand_a'], 'brand_b': kwargs['brand_b'],
                'value_a': 100, 'value_b': 80, 'difference': 20, 'difference_pct': 25}


def payload(intent='lookup', *, filters=None, period=None, steps=None, mode='replace'):
    return {'intent': intent, 'operation': 'new_analysis', 'scope_mode': mode, 'metric': 'inv_neta',
            'filters': filters if filters is not None else {'marca': 'BMW'},
            'period': period if period is not None else {'kind': 'year', 'year': 2025},
            'dimensions': [], 'analysis_questions': ['Resolver la pregunta.'],
            'steps': steps if steps is not None else [step('consultar_inversion_publicitaria')]}


def step(tool, arguments=None):
    return {'tool': tool, 'purpose': 'Obtener evidencia necesaria para la pregunta.', 'arguments': arguments or {}}


class ScriptedCompletions:
    def __init__(self, responses): self.responses, self.calls = iter(responses), []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception): raise response
        if isinstance(response, tuple): content, finish = response
        else: content, finish = response, 'stop'
        if isinstance(content, dict): content = json.dumps(content)
        return NS(choices=[NS(message=NS(content=content, tool_calls=[]), finish_reason=finish)], usage=NS(prompt_tokens=10, completion_tokens=10))


def service(responses, repo=None, **settings):
    settings.setdefault('plan_semantic_review', False)  # These fixtures already supply the interpreted contract.
    completions = ScriptedCompletions(responses)
    repo = repo or FakeRepository()
    client = NS(base_url='https://integrate.api.nvidia.com/v1', chat=NS(completions=completions))
    return AgentService(client=client, settings=Settings(**settings), registry=ToolRegistry(repo), today=lambda: date(2026, 9, 10)), completions, repo


def test_agent_iterates_and_keeps_tools_available():
    plan = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), step('analizar_medios')])
    s, client, repo = service([plan, {'stop': True, 'reason': 'Dos perspectivas suficientes.', 'steps': []}, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza esta marca.'}])
    assert result.steps == 2 and not result.is_partial
    assert len(repo.calls) == 2
    assert result.metrics['stop_reason'] == 'Dos perspectivas suficientes.'
    assert 'sql' not in json.loads(client.calls[-1]['messages'][-1]['content'])['facts'][0]


@pytest.mark.parametrize('brand', ['BMW', 'Volvo', 'MARCA IMPREVISTA'])
def test_simple_lookup_stops_after_one_tool_without_final_llm(brand):
    s, client, repo = service([payload(filters={'marca': brand})])
    result = s.run([{'role': 'user', 'content': f'¿Cuánto invirtió {brand} en 2025?'}])
    assert not result.is_partial and result.steps == 1
    assert len(repo.calls) == len(client.calls) == 1
    assert repo.calls[0]['filters'] == {'marca': brand.upper()}
    assert repo.calls[0]['start_date'] == '2025-01-01'
    assert '100,00' in result.answer and brand.upper() in result.answer


def test_repeated_identical_tool_call_is_stopped():
    plan = payload('open_analysis', steps=[step('consultar_inversion_publicitaria'), step('consultar_inversion_publicitaria')])
    s, client, repo = service([plan, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza.'}])
    assert len(repo.calls) == 1
    assert result.is_partial and result.metrics['stop_reason'] == 'duplicate'
    assert len(client.calls) == 2  # No eight-step loop.


def test_agent_executes_multiple_distinct_steps():
    plan = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), step('analizar_medios')])
    decision = {'stop': False, 'reason': 'Caracterizar el pico observado.', 'steps': [step('ranking_por_dimension', {'dimension': 'formato'})]}
    s, _, repo = service([plan, decision, {'stop': True, 'reason': 'Pico caracterizado.', 'steps': []}, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza.'}])
    assert result.steps == 3 and len(repo.calls) == 3 and not result.is_partial


@pytest.mark.parametrize('bad_args', [{'fecha_inicio': '2025-99-99'}, {'marca': 'BMW'}])
def test_nvidia_allows_recovery_until_successful_evidence(bad_args):
    plan = payload(steps=[step('consultar_inversion_publicitaria', bad_args)])
    decision = {'stop': False, 'reason': 'Corregir argumentos inválidos.', 'steps': [step('consultar_inversion_publicitaria')]}
    s, client, repo = service([plan, decision])
    result = s.run([{'role': 'user', 'content': 'Inversión.'}])
    assert result.steps == 2 and len(repo.calls) == 1 and not result.is_partial
    assert len(client.calls) == 2


@pytest.mark.parametrize('content,expected', [
    ('inversión', 'inversión'),
    ([{'type': 'text', 'text': 'inversión'}, {'type': 'image_url', 'image_url': {'url': 'https://example.invalid/a'}}], 'inversión'),
    ([{'type': 'text', 'text': 'por'}, {'type': 'text', 'text': 'región'}], 'por región'),
    ([{'type': 'image_url'}], ''), ([None, 'ignored', {'type': 'text', 'text': 123}], ''),
    ([], ''), (None, ''), ({'text': 'inversión'}, ''), ('', '')])
def test_planner_uses_latest_user_text_and_preserves_content(content, expected):
    from copy import deepcopy
    original = deepcopy(content)
    assert _extract_user_text(content) == expected
    assert content == original


@pytest.mark.parametrize('successful_step', [1, 2])
def test_max_steps_returns_partial_evidence_without_unbounded_llm_calls(successful_step):
    plan = payload('open_analysis', steps=[step('consultar_inversion_publicitaria'), step('analizar_medios'), step('serie_temporal_bicomp', {'granularidad': 'month'})])
    s, client, repo = service([plan, 'La inversión fue 100.'], max_agent_steps=successful_step)
    result = s.run([{'role': 'user', 'content': 'Analiza.'}])
    assert result.steps == successful_step and result.is_partial and len(repo.calls) == successful_step
    assert len(client.calls) == 2
    assert result.metrics['stop_reason'] == 'intent_budget'


def test_max_steps_preserves_ranking_chart_and_limits_summary_rows():
    plan = payload('open_analysis', steps=[step('ranking_por_dimension', {'dimension': 'region'}), step('analizar_medios')])
    s, _, _ = service([plan, ('Una frase incompleta', 'length'), ('Otra frase incompleta', 'length')], max_agent_steps=1)
    result = s.run([{'role': 'user', 'content': 'Analiza por región.'}])
    assert result.is_partial and result.chart_specs
    assert result.answer.endswith('.') and 'Una frase incompleta' not in result.answer


@pytest.mark.parametrize('same_batch', [True, False])
def test_unknown_tools_never_execute_or_replace_current_evidence(same_batch):
    if same_batch:
        plan = payload(steps=[step('herramienta_inventada')])
        s, _, repo = service([plan, plan])
    else:
        plan = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), step('analizar_medios')])
        s, _, repo = service([plan, {'stop': False, 'reason': 'Detalle adicional.', 'steps': [step('herramienta_inventada')]}, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Inversión.'}])
    if same_batch:
        assert result.is_partial and not repo.calls and not result.evidence
    else:
        assert not result.is_partial and len(repo.calls) == 2 and len(result.evidence) == 2


def test_second_question_unknown_tool_does_not_claim_historical_data_is_current():
    s, _, _ = service([payload(), payload(steps=[step('inventada')]), payload(steps=[step('inventada')])])
    s.run([{'role': 'user', 'content': 'Inversión anterior.'}])
    result = s.run([{'role': 'user', 'content': 'Otra entidad.'}])
    assert result.is_partial and '100' not in result.answer


@pytest.mark.parametrize('error_type', ['no_data', 'infrastructure'])
def test_failed_tools_stop_without_repeating(error_type):
    repo = FakeRepository()
    repo.consultar_inversion = Mock(return_value={'success': False, 'error_type': error_type, 'error': 'Fallo controlado.'})
    s, client, _ = service([payload()], repo)
    result = s.run([{'role': 'user', 'content': 'Inversión.'}])
    assert result.is_partial and result.steps == 1
    assert len(client.calls) == repo.consultar_inversion.call_count == 1


def test_repeated_real_tool_preserves_evidence_without_historical_substitution():
    plan = payload('open_analysis', steps=[step('consultar_inversion_publicitaria'), step('consultar_inversion_publicitaria')])
    s, _, repo = service([plan, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza.'}])
    assert result.is_partial and len(repo.calls) == 1 and '100' in result.answer


def test_follow_up_inherits_entity_and_changes_only_year():
    follow = payload(filters={}, period={'kind': 'year', 'year': 2026}, mode='inherit')
    s, _, repo = service([payload(), follow])
    s.run([{'role': 'user', 'content': '¿Cuánto invirtió BMW en 2025?'}])
    result = s.run([{'role': 'user', 'content': '¿y en 2026?'}])
    assert repo.calls[-1]['filters'] == {'marca': 'BMW'}
    assert repo.calls[-1]['start_date'] == '2026-01-01'
    assert result.plan['resolved_context']['metric'] == 'inv_neta'


def test_invalid_final_answer_is_repaired_without_queries():
    plan = payload('composition', steps=[step('analizar_medios')])
    s, client, repo = service([plan, 'Digital representa 65%.', 'Digital representa 100%.'])
    result = s.run([{'role': 'user', 'content': 'Mix de medios.'}])
    assert not result.is_partial and result.answer == 'Digital representa 100%.'
    assert len(repo.calls) == 1 and len(client.calls) == 3
    assert json.loads(client.calls[-1]['messages'][-1]['content'])['repair_issues']


def test_repair_failure_never_exposes_truncated_text():
    plan = payload('composition', steps=[step('analizar_medios')])
    s, _, repo = service([plan, ('Digital tiene', 'length'), ('Y además', 'length')])
    result = s.run([{'role': 'user', 'content': 'Mix.'}])
    assert result.is_partial and 'Y además' not in result.answer and result.answer.endswith('.')
    assert len(repo.calls) == 1


def test_client_exception_returns_controlled_state():
    s, _, repo = service([RuntimeError('Proveedor caído')])
    result = s.run([{'role': 'user', 'content': 'Inversión.'}])
    assert result.is_partial and not repo.calls
    assert result.metrics['total_latency_ms'] > 0 and result.metrics['errors']


def test_history_has_size_bound_and_no_base64_repetition():
    s, _, _ = service([])
    messages = [{'role': 'user', 'content': 'A'*3000} for _ in range(100)]
    history = s._history(messages)
    assert len(history) <= 12 and sum(len(m['content']) for m in history) <= 16000


def test_optional_decision_failure_preserves_peak_memory_and_finalization():
    plan = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), step('analizar_medios')])
    s, _, repo = service([plan, RuntimeError('Provider unavailable'), 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza la marca.'}])
    assert not result.is_partial and len(repo.calls) == 2
    assert s.memory.last_peak['period'] == '2025-11-01'
    assert any(e['stage'] == 'optional_research_error' for e in result.metrics['events'])


def test_empty_next_steps_does_not_destroy_completed_investigation():
    plan = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), step('analizar_medios')])
    s, _, repo = service([plan, {'stop': False, 'reason': 'Ya hay evidencia suficiente.', 'steps': []}, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza.'}])
    assert not result.is_partial and len(repo.calls) == 2


def test_unconfigured_vision_does_not_claim_to_read_image():
    s, client, repo = service([])
    result = s.run([{'role': 'user', 'content': [{'type': 'text', 'text': 'Analiza esta imagen.'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]}])
    assert result.plan['intent'] == 'clarification' and not client.calls and not repo.calls
    assert 'visión' in result.answer


def test_configured_vision_receives_actual_image_as_user_data():
    p = payload('attachment_analysis', steps=[], filters={}); p['answer'] = 'La imagen muestra una línea.'
    s, client, repo = service([p], vision_models=(Settings().openrouter_model,))
    block = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}
    result = s.run([{'role': 'user', 'content': [{'type': 'text', 'text': 'Analiza la imagen.'}, block]}])
    assert not result.is_partial and not repo.calls
    assert client.calls[0]['messages'][-1]['content'][-1] == block
    assert 'image_url' not in str(client.calls[0]['messages'][0])


def test_optional_research_failure_does_not_invalidate_sufficient_main_evidence():
    plan = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), step('analizar_medios')])
    next_step = {'stop': False, 'reason': 'Desglosar un detalle del patrón.', 'steps': [step('ranking_por_dimension', {'dimension': 'inexistente'})]}
    s, _, repo = service([plan, next_step, {'stop': True, 'reason': 'Las dos perspectivas resuelven la pregunta.', 'steps': []}, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza.'}])
    assert not result.is_partial and len(repo.calls) == 2 and result.steps == 3
    assert result.metrics['errors']  # Failure remains auditable.


def test_malformed_optional_correction_still_finalizes_main_evidence():
    plan = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}), step('analizar_medios')])
    next_step = {'stop': False, 'reason': 'Investigar una observación concreta.', 'steps': [step('ranking_por_dimension', {'dimension': 'inexistente'})]}
    s, _, repo = service([plan, next_step, {'stop': False, 'reason': 'Respuesta mal formada.'}, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza.'}])
    assert not result.is_partial and len(repo.calls) == 2
    assert any(e['stage'] == 'correction_error' for e in result.metrics['events'])


def test_correctable_unneeded_step_can_be_omitted_after_explicit_sufficiency_review():
    plan = payload('open_analysis', steps=[step('serie_temporal_bicomp', {'granularidad': 'month'}),
        step('analizar_medios'), step('serie_temporal_bicomp', {'dimension': 'formato'})])
    s, client, repo = service([plan, {'stop': True, 'reason': 'Tiempo y distribución ya responden el análisis.', 'steps': []},
                              'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza la inversión.'}])
    assert not result.is_partial and len(repo.calls) == 2
    assert result.metrics['stop_reason'] == 'evidence_sufficient_after_correction_review'
    assert any(e['stage'] == 'unneeded_step_omitted' for e in result.metrics['events'])
    assert result.evidence[-1]['result']['success'] is False


def test_argument_correction_cannot_replace_compared_entities():
    s, _, _ = service([{'stop': False, 'reason': 'Intentar una corrección de argumentos.', 'steps': [
        step('comparar_marcas', {'marca_a': 'TOYOTA', 'marca_b': 'VOLVO'})]}])
    context = s._context(s.planner.plan('Compara BMW y Volvo', payload=payload(
        'comparison', filters={}, steps=[step('comparar_marcas', {'marca_a': 'BMW', 'marca_b': 'VOLVO'})])))
    evidence = [{'arguments': {'marca_a': 'BMW', 'marca_b': 'VOLVO'},
                 'result': {'success': False, 'error_type': 'arguments'}}]
    with pytest.raises(Exception, match='no puede cambiar marca_a'):
        s._next_step('Compara BMW y Volvo', context, evidence, 1, None, error=evidence[-1]['result'])


def test_open_analysis_cannot_finish_complete_with_only_total_and_one_distribution():
    plan = payload('open_analysis', steps=[step('consultar_inversion_publicitaria'), step('analizar_medios')])
    s, _, repo = service([plan, {'stop': True, 'reason': 'El modelo cree que basta.', 'steps': []}, 'La inversión fue 100.'])
    result = s.run([{'role': 'user', 'content': 'Analiza esta entidad.'}])
    assert result.is_partial and len(repo.calls) == 2
    assert result.metrics['stop_reason'] == 'insufficient_evidence'
    assert result.answer.startswith('### Resultado sujeto a validación')
