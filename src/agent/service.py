"""Bounded investigation orchestrator shared by Streamlit, CLI and benchmarks."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
import time
from typing import Any
from zoneinfo import ZoneInfo
from src.agent.analysis_context import AnalysisContext, UnresolvedComparisonError
from src.agent.cache import QueryResultCache
from src.agent.execution import ToolExecutor
from src.agent.finalization import AnswerFinalizer, safe_answer
from src.agent.llm import LLMGateway
from src.agent.memory import AnalyticalMemory
from src.agent.observability import ConversationMetrics
from src.agent.planner import AnalyticalPlan, AnalyticalPlanner, InvalidToolPlanError, PlanStep, PLAN_SCHEMA, INTENT_BUDGETS
from src.agent.prompts import SYSTEM_PROMPT, PLANNING_PROMPT, RESEARCH_PROMPT
from src.agent.response_validator import compact_evidence, validate_answer
from src.agent.sufficiency import evidence_sufficient
from src.agent.requirements import requirements_for
from src.agent.request_review import review_request
from src.agent.transitions import SCOPE_ARGS
from src.semantic import load_semantic_layer
from src.visualization import build_chart_spec


def _extract_user_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(b['text'] for b in content if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
    return ''


def _summarize_partial_evidence(evidence, *, reason='alcancé el límite de pasos'):
    return safe_answer(evidence, reason=reason)


class AgentMaxStepsError(RuntimeError):
    """Compatibility import; normal execution returns a controlled partial result."""


class RepeatedToolCallError(RuntimeError):
    """Compatibility import; duplicate calls now end without repeating a query."""


@dataclass
class AgentResult:
    answer: str
    evidence: list[dict[str, Any]]
    steps: int
    plan: dict[str, Any]
    chart_specs: list[dict[str, Any]]
    metrics: dict[str, Any]
    is_partial: bool = False


class AgentService:
    def __init__(self, *, client, settings, registry, system_prompt=SYSTEM_PROMPT,
                 memory=None, cache=None, metrics=None, planner=None, today=None):
        self.client, self.settings, self.registry = client, settings, registry
        self.system_prompt = system_prompt
        self.memory = memory or AnalyticalMemory()
        self.cache = cache or QueryResultCache(settings.query_cache_ttl_seconds)
        self.metrics = metrics or ConversationMetrics()
        self.gateway = LLMGateway(client, settings, self.metrics)
        self.planner = planner or AnalyticalPlanner({s['function']['name'] for s in registry.schemas})
        self.today = today or (lambda: datetime.now(ZoneInfo('America/Bogota')).date())
        self._historical_evidence, self._historical_charts = [], []

    def _history(self, messages):
        """Bound model input; preserve newest turn, no repeated base64 attachments."""
        history, remaining = [], self.settings.history_max_chars
        for message in reversed(messages):
            if message.get('role') not in {'user', 'assistant'}:
                continue
            content = _extract_user_text(message.get('content'))
            if not content or remaining <= 0 or len(history) >= self.settings.history_max_messages:
                continue
            history.append({'role': message['role'], 'content': content[-remaining:]})
            remaining -= len(history[-1]['content'])
        return list(reversed(history))

    def _plan(self, question, messages, model, attachments=None):
        memory = self.memory.context()
        latest = next((m.get('content') for m in reversed(messages) if m.get('role') == 'user'), '')
        images = [b for b in latest if isinstance(b, dict) and b.get('type') == 'image_url'] if isinstance(latest, list) else []
        if images and (model or self.settings.openrouter_model) not in self.settings.vision_models:
            return AnalyticalPlan('clarification', ['none'], [], answer='El modelo seleccionado no tiene visión habilitada. Retira las imágenes para consultar BICOMP o selecciona un modelo con visión configurada.', budget=0)
        if self.planner.interpreter is not None:
            return self.planner.plan(question, memory)
        payload = {'question': question, 'history': self._history(messages), 'memory': memory,
                   'today': self.today().isoformat(), 'semantic': load_semantic_layer(), 'documents_as_data': attachments or [],
                   'tools': self.registry.planning_catalog, 'PLAN_SCHEMA': PLAN_SCHEMA, 'budgets': INTENT_BUDGETS}
        # Keep the active instruction after bulky schemas/history to prevent stale-turn copying.
        payload['current_request'] = payload.pop('question')
        payload['interpretation_instruction'] = 'Interpreta SOLO current_request. La memoria da referentes; no repitas la pregunta previa. Elige primero intención y operación, luego capacidades.'
        semantic_corrections = {}
        review_used = False
        for attempt in range(2):
            try:
                interpreted = self.gateway.complete(PLANNING_PROMPT, payload, model=model, stage='planning', json_mode=True, images=images, temperature=0)
                if self.settings.plan_semantic_review and not review_used and not images and INTENT_BUDGETS.get(interpreted.get('intent'), 0) > 0:
                    review_used = True
                    try:
                        review = review_request(self.gateway, question, interpreted, memory, PLAN_SCHEMA, model=model)
                    except Exception:
                        # A failed review cannot erase an already interpretable request.
                        # Retain its validated scope for a later follow-up, without executing it.
                        self.memory.last_request['interpretation'] = deepcopy(interpreted)
                        try:
                            candidate = self.planner.plan(question, memory, payload=interpreted)
                            context = self._context(candidate)
                            self._last_interpreted_plan, self._last_interpreted_context = candidate, context
                        except (ValueError, InvalidToolPlanError):
                            pass
                        raise
                    self.metrics.events.append({'stage': 'semantic_review', 'proposal': deepcopy(interpreted), **review})
                    semantic_corrections = review['corrections']
                    payload['authoritative_semantic_corrections'] = semantic_corrections
                if semantic_corrections:
                    interpreted.update(deepcopy(semantic_corrections))
                    for step in interpreted.get('steps', []):
                        step['arguments'] = {k: v for k, v in step.get('arguments', {}).items() if k not in SCOPE_ARGS}
                    if semantic_corrections.get('intent') == 'lookup' and not any(s.get('tool') == 'calcular_ratio_bicomp' for s in interpreted.get('steps', [])):
                        interpreted['steps'] = [{'tool': 'consultar_inversion_publicitaria', 'arguments': {}, 'purpose': 'Obtener el total requerido por el contrato revisado.'}]
                    elif semantic_corrections.get('intent') in {'ranking', 'composition'} and len(interpreted.get('dimensions', [])) == 1:
                        interpreted['steps'] = [{'tool': 'ranking_por_dimension', 'arguments': {'dimension': interpreted['dimensions'][0], 'limite': interpreted.get('analysis', {}).get('limit', 10)}, 'purpose': 'Obtener la distribución requerida por el contrato revisado.'}]
                self.memory.last_request['interpretation'] = deepcopy(interpreted)
                plan = self.planner.plan(question, memory, payload=interpreted)
                try:
                    candidate_context = self._context(plan)
                except UnresolvedComparisonError as exc:
                    self._last_interpreted_plan, self._last_interpreted_context = plan, exc.requested_context
                    raise
                self._last_interpreted_plan, self._last_interpreted_context = plan, candidate_context
                self._validate_filter_catalogs(plan, payload)
                schemas = {s['function']['name']: s['function']['parameters']['properties'] for s in self.registry.schemas}
                period_steps = [s for s in plan.steps if any(k in schemas[s.tool] for k in ('periodo_a', 'periodo_actual'))]
                if period_steps:
                    context = self._context(plan)
                    for step in period_steps:
                        context.bind(step.arguments, {'periodo_a': {}, 'periodo_b': {}} if 'periodo_a' in schemas[step.tool]
                                     else {'periodo_actual': {}, 'periodo_anterior': {}})
                if plan.scope.get('operation') == 'inspect_peak':
                    context = self._context(plan)
                    for step in plan.steps:
                        context.bind(step.arguments, schemas[step.tool])
                return plan
            except (ValueError, InvalidToolPlanError) as exc:
                self.metrics.events.append({'stage': 'plan_validation', 'attempt': attempt,
                    'issue': str(exc)[:800], 'rejected_plan': locals().get('interpreted')})
                if attempt:
                    raise
                payload['validation_error'] = str(exc)
                payload['rejected_plan'] = locals().get('interpreted')
        raise InvalidToolPlanError('No se obtuvo un plan válido.')

    def _validate_filter_catalogs(self, plan, payload):
        """Validate configured small vocabularies against live cached catalogues.

        No fuzzy matching or value rewriting. An invalid dimension/value pair is
        returned to the interpreter with the exact alternatives in its one repair.
        """
        repo = self.registry.repository
        dimensions = load_semantic_layer()['business_rules'].get('validate_value_dimensions', [])
        used = set(plan.scope.get('filters', {})) & set(dimensions)
        if not used or not hasattr(repo, 'catalogo'):
            return
        catalogs = {}
        for dimension in dimensions:
            before_queries = getattr(repo, 'query_count', 0)
            before_bytes = getattr(repo, 'bytes_processed', 0)
            result = repo.catalogo(dimension=dimension, limit=1000)
            self.metrics.bigquery_queries += getattr(repo, 'query_count', 0) - before_queries
            self.metrics.bigquery_bytes_processed += getattr(repo, 'bytes_processed', 0) - before_bytes
            if result.get('success'):
                catalogs[dimension] = result.get('values', [])
                self.metrics.events.append({'stage': 'catalog_validation', 'dimension': dimension,
                    'values': catalogs[dimension], 'evidence': result.get('evidence')})
        payload['confirmed_filter_catalogs'] = catalogs
        for dimension in used:
            if dimension not in catalogs or len(catalogs[dimension]) >= 1000:
                continue  # A truncated catalogue cannot prove absence.
            values = plan.scope['filters'][dimension]
            values = values if isinstance(values, list) else [values]
            missing = {str(v).strip().upper() for v in values} - {str(v).strip().upper() for v in catalogs[dimension]}
            if missing:
                raise ValueError(f'Valores inexistentes para {dimension}: {sorted(missing)}. Corrige la pareja dimensión/valor usando confirmed_filter_catalogs; no inventes etiquetas.')

    def _context(self, plan):
        repo = self.registry.repository
        cached = repo._coverage_cache.get('coverage', {}) if hasattr(repo, '_coverage_cache') else None
        available = {k: cached[k] for k in ('start', 'end') if cached.get(k)} if cached else None
        kind = (plan.scope.get('period') or {}).get('kind')
        if not available and kind in {'ytd', 'recent_months', 'current_month', 'previous_month', 'previous_year'}:
            before = getattr(repo, 'query_count', 0)
            before_bytes = getattr(repo, 'bytes_processed', 0)
            result = repo.obtener_rango_fechas()
            self.metrics.bigquery_queries += getattr(repo, 'query_count', 0) - before
            self.metrics.bigquery_bytes_processed += getattr(repo, 'bytes_processed', 0) - before_bytes
            if not result.get('success'):
                raise ValueError('No hay cobertura para resolver el periodo relativo.')
            available = {k: result[k] for k in ('start', 'end')}
            self.metrics.events.append({'stage': 'coverage_resolution', 'available_period': available})
        return AnalysisContext.resolve(plan.scope, self.memory.context(), today=self.today(), available=available)

    def _next_step(self, question, context, evidence, remaining, model, *, error=None):
        payload = {'question': question, 'scope': context.as_dict(), 'evidence': compact_evidence(evidence),
                   'remaining_tool_budget': remaining, 'tools': self.registry.planning_catalog, 'correctable_error': error}
        decision = self.gateway.complete(RESEARCH_PROMPT, payload, model=model, stage='correction' if error else 'deepening', json_mode=True, temperature=0)
        self.metrics.events.append({'stage': 'research_decision', 'stop': decision.get('stop'), 'reason': decision.get('reason')})
        if decision.get('stop') is True or decision.get('steps') == []:
            return None, decision.get('reason', 'Evidencia suficiente.')
        steps = decision.get('steps')
        if not isinstance(steps, list) or len(steps) != 1 or not decision.get('reason'):
            raise InvalidToolPlanError('Una profundización requiere exactamente una consulta y una justificación.')
        step = PlanStep(**steps[0])
        if len(step.purpose) < 8:
            raise InvalidToolPlanError('La consulta no explica qué evidencia agrega.')
        if error and evidence:
            original = evidence[-1].get('arguments', {})
            for key in ('dimension_entidad', 'valor_a', 'valor_b', 'marca_a', 'marca_b'):
                if original.get(key) is not None and step.arguments.get(key) != original[key]:
                    raise InvalidToolPlanError(
                        f'Una corrección de argumentos no puede cambiar {key}; conserva la comparación solicitada.'
                    )
        self.planner.validate(AnalyticalPlan(context.intent, ['bicomp'], [step]))
        return step, decision['reason']

    def run(self, messages, *, model=None, temperature=0.1, attachments=None) -> AgentResult:
        started = time.perf_counter()
        before = self.metrics.as_dict()
        # Keep traces bounded per turn; aggregate counters remain conversation-wide.
        self.metrics.events = []
        self.metrics.errors = []
        question = next((_extract_user_text(m.get('content')) for m in reversed(messages) if m.get('role') == 'user'), '')
        self._last_interpreted_plan = self._last_interpreted_context = None
        memory_before = self.memory.context()
        self.memory.last_request = {'question': question, 'status': 'unresolved'}
        evidence, charts = [], []
        plan = AnalyticalPlan('clarification', ['none'], [], answer='No recibí una pregunta.', budget=0)
        context = AnalysisContext()
        stop_reason, partial, answer = '', False, ''
        try:
            plan = self._plan(question, messages, model, attachments)
            self.metrics.events.append({'stage': 'plan', 'intent': plan.intent, 'scope': plan.scope})
            if not plan.steps:
                answer = plan.answer or 'Falta información para definir el alcance de la consulta.'
                validation = validate_answer(answer, [], intent=plan.intent)
                if not validation.valid:
                    answer = 'No pude producir una respuesta completa. Reformula la pregunta con el alcance que quieres analizar.'
                    partial = True
                stop_reason = plan.intent
            else:
                context = self._context(plan)
                inherited = memory_before.get('analysis_context', {})
                mutations = {k: {'before': inherited.get(k), 'after': v} for k, v in context.as_dict().items()
                             if k in {'filters', 'requested_period', 'comparison_period', 'dimensions', 'intent'} and inherited.get(k) != v}
                self.memory.remember_request(context.as_dict(), plan.as_dict()['steps'],
                    request={'question': question, 'scope': plan.scope, 'status': 'planned'})
                self.metrics.events.append({'stage': 'request_contract', 'requested_intent': plan.intent,
                    'requested_scope': plan.scope, 'inherited_scope': inherited, 'scope_mutations': mutations,
                    'resolved_scope': context.as_dict(), 'requirements': requirements_for(plan.intent, plan.scope),
                    'selected_capabilities': [requirements_for(plan.intent, plan.scope)['capability']],
                    'tools': [s.tool for s in plan.steps]})
                executor = ToolExecutor(self.registry, self.cache, self.metrics)
                pending = list(plan.steps)
                optional_steps = set()
                max_tools = min(plan.budget, self.settings.max_agent_steps)
                correction_used = False
                while pending and len(evidence) < self.settings.max_agent_steps:
                    step = pending.pop(0)
                    record = executor.execute(step, context, len(evidence) + 1)
                    evidence.append(record)
                    result = record['result']
                    if result.get('success') is not True:
                        kind = result.get('error_type', 'no_data')
                        correction_stop = False
                        if kind in {'arguments', 'schema'} and not correction_used and len(evidence) < self.settings.max_agent_steps:
                            correction_used = True
                            try:
                                corrected, correction_reason = self._next_step(question, context, evidence, 1, model, error=result)
                                correction_stop = corrected is None and evidence_sufficient(plan.intent, evidence, plan.scope)
                                if correction_stop:
                                    self.metrics.events.append({'stage': 'unneeded_step_omitted', 'tool': step.tool,
                                        'reason': correction_reason, 'original_error': kind})
                            except Exception as exc:
                                self.metrics.events.append({'stage': 'correction_error', 'detail': str(exc)[:300]})
                                corrected = None
                            if corrected:
                                if id(step) in optional_steps:
                                    optional_steps.add(id(corrected))
                                pending.insert(0, corrected)
                                max_tools += 1  # One repair attempt; never repeats the underlying query.
                                continue
                        stop_reason = kind
                        partial = not (correction_stop or ((kind == 'duplicate' or id(step) in optional_steps) and evidence_sufficient(plan.intent, evidence, plan.scope)))
                        if correction_stop:
                            stop_reason = 'evidence_sufficient_after_correction_review'
                        break
                    if result.get('available_period'):
                        context.available_period = result['available_period']
                    if result.get('observed_period'):
                        context.observed_period = result['observed_period']
                    # Preserve usable context even if optional research/model transport fails.
                    self.memory.remember_analysis(context.as_dict(), evidence)
                    self.memory.last_strategy = deepcopy(plan.as_dict()['steps'])
                    if len(evidence) >= max_tools:
                        partial = bool(pending)
                        stop_reason = 'intent_budget' if partial else 'planned_evidence_complete'
                        break
                    if not pending and plan.intent in {'open_analysis', 'diagnostic', 'anomaly'}:
                        if plan.intent == 'diagnostic' and evidence_sufficient(plan.intent, evidence, plan.scope):
                            stop_reason = 'diagnostic_evidence_complete'
                            break
                        try:
                            next_step, stop_reason = self._next_step(question, context, evidence, max_tools-len(evidence), model)
                        except Exception as exc:
                            self.metrics.events.append({'stage': 'optional_research_error', 'detail': str(exc)[:300]})
                            next_step, stop_reason = None, 'planned_evidence_complete'
                        if next_step:
                            optional_steps.add(id(next_step))
                            pending.append(next_step)
                    if not pending:
                        stop_reason = stop_reason or 'planned_evidence_complete'
                        break
                if pending and not stop_reason:
                    stop_reason, partial = 'safety_limit', True
                sufficient = evidence_sufficient(plan.intent, evidence, plan.scope)
                self.metrics.events.append({'stage': 'sufficiency', 'requirements': requirements_for(plan.intent, plan.scope),
                    'sufficient': sufficient, 'successful_evidence_ids': [e.get('id') for e in evidence if e['result'].get('success') is True]})
                if not partial and not sufficient:
                    stop_reason, partial = 'insufficient_evidence', True
                for item in evidence:
                    try:
                        chart = build_chart_spec(item['tool'], item['result'])
                        if chart:
                            charts.append(chart)
                    except (KeyError, ValueError, TypeError) as exc:
                        self.metrics.errors.append(f'chart:{type(exc).__name__}')
                if any(i['result'].get('success') is True for i in evidence):
                    answer, final_partial, _ = AnswerFinalizer(self.gateway, self.settings, self.metrics).finalize(
                        question, context, evidence, model=model, temperature=temperature, partial_reason=stop_reason if partial else None)
                    partial = partial or final_partial
                    self.memory.remember_analysis(context.as_dict(), evidence)
                    self._historical_evidence = deepcopy(evidence)
                    self._historical_charts = deepcopy(charts)
                else:
                    answer, partial = safe_answer(evidence, reason=stop_reason or 'sin datos utilizables'), True
        except Exception as exc:
            if not evidence and self._last_interpreted_plan is not None and self._last_interpreted_context is not None:
                plan, context = self._last_interpreted_plan, self._last_interpreted_context
                self.memory.remember_request(context.as_dict(), plan.as_dict()['steps'],
                    request={'question': question, 'scope': plan.scope, 'status': 'validation_failed'})
            self.metrics.errors.append(f'run:{type(exc).__name__}')
            self.metrics.events.append({'stage': 'error', 'type': type(exc).__name__, 'detail': str(exc)[:600]})
            stop_reason, partial = 'controlled_error', True
            answer = safe_answer(evidence, reason='no pude completar la investigación')
        self.metrics.total_latency_ms += round((time.perf_counter()-started)*1000, 2)
        if plan.steps and not partial:
            self.memory.last_successful_scope = deepcopy(context.as_dict())
        self.memory.last_request['status'] = stop_reason
        self.metrics.events.append({'stage': 'memory_transition', 'before': memory_before, 'after': self.memory.context()})
        self.metrics.events.append({'stage': 'stop', 'reason': stop_reason, 'partial': partial})
        metrics = self.metrics.as_dict()
        metrics['turn'] = {k: metrics[k]-before[k] for k in ('total_llm_calls', 'total_tool_calls', 'bigquery_queries', 'bigquery_bytes_processed', 'input_tokens', 'output_tokens', 'cache_hits', 'total_latency_ms')}
        metrics['stop_reason'] = stop_reason
        return AgentResult(answer, evidence, len(evidence), {**plan.as_dict(), 'resolved_context': context.as_dict()}, charts, metrics, partial)
