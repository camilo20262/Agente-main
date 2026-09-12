"""LLM interpretation with deterministic validation; no entity-specific routing."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any, Callable
from jsonschema import validate, ValidationError
from src.semantic import load_semantic_layer
from copy import deepcopy
import re
import unicodedata
from src.agent.transitions import compile_transition
from src.agent.requirements import compile_requirements, requirements_for


class InvalidToolPlanError(ValueError):
    """An interpreted plan violates the analytical contract."""


INTENT_BUDGETS = {'lookup': 1, 'ranking': 2, 'trend': 2, 'composition': 2,
                  'comparison': 3, 'period_comparison': 3, 'diagnostic': 5,
                  'open_analysis': 5, 'anomaly': 4, 'catalog': 2, 'coverage': 1,
                  'out_of_domain': 0, 'attachment_analysis': 0, 'clarification': 0, 'ranking_change': 1, 'ranking_acceleration': 1,
                  'temporal_extrema': 1, 'diagnostic_search': 1, 'joint_share': 1}


@dataclass(frozen=True)
class PlanStep:
    tool: str
    purpose: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalyticalPlan:
    intent: str
    domains: list[str]
    steps: list[PlanStep]
    scope: dict[str, Any] = field(default_factory=dict)
    analysis_questions: list[str] = field(default_factory=list)
    answer: str = ''
    budget: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


PLAN_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['intent', 'operation', 'scope_mode', 'filters', 'period', 'dimensions', 'analysis_questions', 'steps'],
    'properties': {
        'intent': {'enum': list(INTENT_BUDGETS)}, 'scope_mode': {'enum': ['inherit', 'replace']},
        'operation': {'enum': ['new_analysis', 'change_period', 'change_entity', 'breakdown',
                               'compare_entities', 'compare_periods', 'explain_difference', 'inspect_peak', 'continue_analysis',
                               'discover_extreme', 'shift_period', 'joint_entities', 'filter_scope', 'restore_scope']},
        'analysis': {'type': 'object', 'additionalProperties': False, 'properties': {
            'restore_with_breakdown': {'type': 'boolean'},
            'change_basis': {'enum': ['absolute', 'percent']}, 'direction': {'enum': ['asc', 'desc']},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
            'granularity': {'enum': ['day', 'week', 'month']}, 'extreme': {'enum': ['max', 'min']},
            'candidate_dimensions': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 2, 'maxItems': 3},
            'entity_reference': {'enum': ['explicit', 'recent']}, 'entity_count': {'type': 'integer', 'minimum': 2, 'maximum': 3},
            'retain_filters': {'type': 'array', 'items': {'type': 'string'}},
            'entity_set': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                'required': ['dimension', 'value'], 'properties': {'dimension': {'type': 'string'}, 'value': {'type': 'string'}}}}}},
        'metric': {'type': ['string', 'null']}, 'filters': {'type': 'object'},
        'remove_filters': {'type': 'array', 'items': {'type': 'string'}},
        'period': {'type': ['object', 'null']}, 'comparison_period': {'type': ['object', 'null']},
        'dimensions': {'type': 'array', 'items': {'type': 'string'}},
        'analysis_questions': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 5},
        'answer': {'type': ['string', 'null']},
        'steps': {'type': 'array', 'maxItems': 5, 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['tool', 'purpose', 'arguments'], 'properties': {
                'tool': {'type': 'string'}, 'purpose': {'type': 'string', 'minLength': 8},
                'arguments': {'type': 'object'}}}},
    },
}

PERIOD_SCHEMA = {'type': ['object', 'null'], 'properties': {
    'kind': {'enum': ['year', 'month', 'range', 'ytd', 'recent_months', 'current_month',
                      'previous_month', 'previous_year', 'previous_period', 'peak', 'inherit', 'all']},
    'anchor': {'enum': ['focus', 'reference', 'peak', 'available']},
    'year': {'type': 'integer', 'minimum': 1, 'maximum': 9999},
    'month': {'type': 'integer', 'minimum': 1, 'maximum': 12},
    'count': {'type': 'integer', 'minimum': 1, 'maximum': 120},
    'granularity': {'enum': ['day', 'week', 'month']},
    'start': {'type': 'string', 'format': 'date'}, 'end': {'type': 'string', 'format': 'date'}},
    'required': ['kind'], 'additionalProperties': False,
    'allOf': [{'if': {'required': ['kind'], 'properties': {'kind': {'const': kind}}}, 'then': {'required': fields}}
              for kind, fields in [('month', ['month']), ('range', ['start', 'end'])]]}
PLAN_SCHEMA['properties']['period'] = PERIOD_SCHEMA
PLAN_SCHEMA['properties']['comparison_period'] = PERIOD_SCHEMA


def explicit_group_dimensions(question: str, semantic: dict) -> set[str]:
    """Recognize explicit semantic grouping labels for validation, never tool routing."""
    def fold(value):
        return ''.join(c for c in unicodedata.normalize('NFD', value.casefold())
                       if unicodedata.category(c) != 'Mn')

    labels = {}
    for dimension in semantic['dimensions']:
        for term in [dimension.replace('_', ' '), *semantic.get('synonyms', {}).get(dimension, [])]:
            label = fold(term)
            for variant in (label, label + 's', label + 'es'):
                labels[variant] = dimension
    alternatives = '|'.join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    return {labels[match.group(1)] for match in re.finditer(
        r'\bpor\s+(?:cada\s+)?(' + alternatives + r')\b', fold(question))}


def is_elliptical_entity_reference(question: str, steps: list[dict]) -> bool:
    """Check a bare conjunction + LLM-identified entity; do not discover entities or route tools."""
    normalized = re.sub(r'[¿?¡!.,;:]', '', question).strip().casefold()
    for step in steps:
        args = step.get('arguments', {})
        for key in ('valor_a', 'valor_b', 'marca_a', 'marca_b'):
            label = args.get(key)
            if isinstance(label, str):
                label = re.sub(r'[¿?¡!.,;:]', '', label).strip().casefold()
                if label and normalized in {f'{conjunction} {label}' for conjunction in ('y', 'e', 'and')}:
                    return True
    return False


class AnalyticalPlanner:
    def __init__(self, allowed_tools: set[str], interpreter: Callable[..., dict[str, Any]] | None = None):
        self.allowed_tools = allowed_tools
        self.interpreter = interpreter

    def plan(self, question: str, memory=None, *, payload=None) -> AnalyticalPlan:
        if payload is None:
            if self.interpreter is None:
                raise InvalidToolPlanError('El planner requiere una interpretación estructurada; no adivina entidades mediante palabras clave.')
            payload = self.interpreter(question, memory or {})
        try:
            payload = deepcopy(payload)
            payload.setdefault('analysis_questions', [])  # Optional prose is not an evidence contract.
            previous_scope = (memory or {}).get('analysis_context', {})
            if payload.get('operation') == 'filter_scope' and previous_scope:
                changed_filters = any(previous_scope.get('filters', {}).get(k) != v for k, v in payload.get('filters', {}).items()) or payload.get('remove_filters')
                changed_measure = any(previous_scope.get('analysis', {}).get(k) != v for k, v in payload.get('analysis', {}).items() if k in {'change_basis', 'direction', 'granularity', 'extreme'})
                if changed_measure and not changed_filters:
                    raise ValueError('filter_scope modifica filtros, no el criterio de medida. Declara new_analysis con scope_mode=inherit para cambiar el criterio conservando el alcance.')
            payload = compile_requirements(compile_transition(payload, memory or {}), memory or {})
            # Lift explicit step scope before validating; execution then has one authority.
            for current, previous in [('periodo_a', 'periodo_b'), ('periodo_actual', 'periodo_anterior')]:
                for step in payload.get('steps', []):
                    args = step.get('arguments', {})
                    if args.get(current) and not payload.get('period'):
                        payload['period'] = args[current]
                    if args.get(previous) and not payload.get('comparison_period'):
                        payload['comparison_period'] = args[previous]
            for field_name in ('period', 'comparison_period'):
                period = payload.get(field_name)
                if period == {}:
                    payload[field_name] = None
                elif period == {'inherit': True}:
                    payload[field_name] = {'kind': 'inherit'}
                elif period and 'kind' not in period and set(period) == {'start', 'end'}:
                    payload[field_name] = {'kind': 'range', **period}
            validate(payload, PLAN_SCHEMA)
            semantic = load_semantic_layer()
            rules = semantic['business_rules']
            previous_filters = (memory or {}).get('analysis_context', {}).get('filters', (memory or {}).get('last_filters', {}))
            # Validate the semantic default, without recognizing any particular entity.
            for dimension in rules.get('entity_dimensions', []):
                if dimension not in payload['filters'] or dimension == rules.get('default_entity_dimension'):
                    continue
                terms = [dimension.replace('_', ' '), *semantic.get('synonyms', {}).get(dimension, [])]
                terms.extend(term for term, target in rules.get('ambiguous_entity_terms', {}).items() if target == dimension)
                explicit = any(re.search(r'\b' + re.escape(term) + r'(?:s|es)?\b', question, re.I) for term in terms)
                inherited = payload['scope_mode'] == 'inherit' and dimension in previous_filters
                if not explicit and not inherited:
                    raise ValueError(f'El usuario no especificó {dimension}. Un nombre comercial sin tipo usa {rules.get("default_entity_dimension")}; corrige filtros del alcance y de todas las herramientas.')
            if payload.get('metric') and payload['metric'] not in semantic['metrics']:
                raise ValueError('Métrica fuera del modelo semántico.')
            if set(payload['dimensions']) - set(semantic['dimensions']):
                raise ValueError('Dimensión fuera del modelo semántico.')
            if payload['intent'] == 'open_analysis' and payload['operation'] == 'new_analysis' and not payload['dimensions']:
                payload['dimensions'] = list(dict.fromkeys(s.get('arguments', {}).get('dimension') for s in payload['steps'] if s.get('arguments', {}).get('dimension')))
            if payload['steps'] or payload['intent'] in {'diagnostic_search', 'temporal_extrema'}:
                explicit_axes = explicit_group_dimensions(question, semantic)
                missing = explicit_axes - set(payload['dimensions'])
                if missing:
                    raise ValueError('El plan omite dimensiones de agrupación explícitas: '
                                     + ', '.join(sorted(missing))
                                     + '. Conserva todos los ejes solicitados en dimensions y en las herramientas; '
                                       'un ranking global no responde un ranking dentro de grupos.')
                active_filters = {**(previous_filters if payload['scope_mode'] == 'inherit' else {}), **payload['filters']}
                retained_axes = explicit_axes & (set(active_filters) - set(payload.get('remove_filters', []))) - set(payload.get('analysis', {}).get('retain_filters', []))
                if retained_axes:
                    raise ValueError('El desglose explícito sigue restringido por su propio eje: '
                        + ', '.join(sorted(retained_axes)) + '. Usa breakdown para promover el filtro; '
                        'si la solicitud también restaura una entidad, declara analysis.restore_with_breakdown=true. '
                        'Solo conserva esa restricción con analysis.retain_filters si el usuario la pidió explícitamente.')
            if (set(payload['filters']) | set(payload.get('remove_filters', []))) - set(semantic['dimensions']):
                raise ValueError('Filtro fuera del modelo semántico.')
            steps = [PlanStep(**item) for item in payload['steps']]
            intent = payload['intent']
            previous = (memory or {}).get('analysis_context', {})
            operation = payload['operation']
            if previous and operation == 'compare_entities' and is_elliptical_entity_reference(question, payload['steps']):
                raise ValueError('El seguimiento solo nombra una entidad nueva; no solicita comparar dos entidades. '
                    'Usa operation=change_entity, coloca la entidad mencionada en filters y conserva '
                    'la intención, dimensiones y referencia temporal anteriores. No ejecutes una comparación nueva.')
            if operation == 'compare_periods' and payload['scope_mode'] == 'inherit' and previous.get('requested_period'):
                period = payload.get('period') or {}
                prior_start = previous['requested_period'].get('start', '')
                literal_year = str(period.get('year', '')) if period.get('kind') == 'year' else str(period.get('start', ''))[:4] if period.get('kind') == 'range' else ''
                if literal_year and prior_start[:4] != literal_year and literal_year not in question:
                    raise ValueError('La comparación de seguimiento cambia el periodo foco sin una fecha explícita del usuario. '
                        'Conserva period=inherit y usa comparison_period para la referencia; no inviertas A/B. '
                        'Si el usuario pidió una fecha relativa, exprésala simbólicamente, no inventes un año literal.')
            expected_intent = None
            if previous and operation in {'change_period', 'change_entity', 'continue_analysis'}:
                expected_intent = previous.get('intent')
            elif previous and operation == 'breakdown' and payload['scope_mode'] == 'inherit' and previous.get('comparison_period'):
                expected_intent = 'diagnostic'
            if expected_intent and intent != expected_intent:
                raise ValueError(f'La operación {operation} conserva el objetivo analítico: intent debe ser {expected_intent}. Ajusta también los pasos, sin reducir la profundidad del seguimiento.')
            if operation == 'discover_extreme' and previous.get('intent') == 'temporal_extrema' and (memory or {}).get('last_peak') and (payload.get('period') or {}).get('kind') == 'inherit' and all(payload.get('analysis', {}).get(k, default) == previous.get('analysis', {}).get(k, default) for k, default in [('granularity', 'month'), ('extreme', 'max')]):
                raise ValueError('El extremo de ese alcance ya está calculado. Si pide el periodo anterior al extremo, usa intent=lookup, operation=shift_period, period={kind:previous_period,anchor:peak}. Si pide repetir la misma consulta, declara continue_analysis. No redescubras el mismo extremo para un seguimiento temporal.')
            if operation == 'inspect_peak' and (payload.get('period') or {}).get('kind') != 'peak':
                raise ValueError('Inspeccionar un pico calculado requiere period={"kind":"peak"}; no volver a investigar todo el año.')
            if INTENT_BUDGETS[intent] == 0 and steps:
                raise ValueError('Una respuesta conceptual o aclaratoria no ejecuta herramientas.')
            if INTENT_BUDGETS[intent] and not steps:
                raise ValueError('Una pregunta de datos requiere una consulta planificada.')
            if len(steps) > INTENT_BUDGETS[intent]:
                raise ValueError('El plan excede el presupuesto de su intención.')
            if intent == 'open_analysis' and len(steps) < 2:
                raise ValueError('Un análisis abierto requiere al menos dos perspectivas útiles.')
            scope = {k: v for k, v in payload.items() if k not in {'steps', 'answer', 'analysis_questions'}}
            plan = AnalyticalPlan(intent, ['none'] if INTENT_BUDGETS[intent] == 0 else ['bicomp'], steps,
                                  scope, payload['analysis_questions'], payload.get('answer', ''), INTENT_BUDGETS[intent])
            self.validate(plan)
            return plan
        except (ValidationError, TypeError, KeyError, ValueError) as exc:
            raise InvalidToolPlanError((f"{'.'.join(map(str, exc.path))}: {exc.message}" if isinstance(exc, ValidationError) else str(exc))[:800]) from exc

    def validate(self, plan: AnalyticalPlan) -> None:
        invalid = [step.tool for step in plan.steps if step.tool not in self.allowed_tools]
        if invalid:
            raise InvalidToolPlanError('El plan contiene tools no registradas: ' + ', '.join(invalid))
