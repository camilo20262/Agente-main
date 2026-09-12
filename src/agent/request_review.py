"""One semantic review of the requested operation, before any analytical query.

The reviewer sees a compact request/scope proposal, not the tool catalogue or SQL.
It can correct the interpretation, never calculate facts or execute tools.
"""
from copy import deepcopy
from jsonschema import validate, ValidationError
from src.semantic import load_semantic_layer

REVIEW_PROMPT = '''Revisa la interpretación de la SOLICITUD ACTUAL frente al foco conversacional.
No elijas herramientas, no calcules cifras ni fechas. Solo decide qué pidió el usuario.
Devuelve JSON {"valid":true,"reason":"...","corrections":{}} si la propuesta respeta la solicitud,
o {"valid":false,"reason":"...","corrections":{CAMPOS_CORREGIDOS}}.
Correcciones permitidas: intent, operation, scope_mode, filters, remove_filters, period,
comparison_period, dimensions, analysis. No incluyas steps.
Principios:
- Crecimiento requiere ranking_change (absolute o percent), aceleración ranking_acceleration.
- Agregar solo un filtro es filter_scope y conserva intención, ejes, criterio, calendario y profundidad.
- Pedir un desglose es breakdown con dimensions; promueve su filtro a eje y conserva otros.
- Una nueva pregunta independiente puede reemplazar filtros sin cambiar el calendario heredado.
- Diagnosticar una variación ya conversada conserva period=inherit y comparison_period=inherit;
  intent=diagnostic_search si no eligió dimensión, diagnostic si la eligió.
- Tras un máximo/mínimo calculado, el periodo anterior significa lookup, shift_period,
  period={"kind":"previous_period","anchor":"peak"}. No repitas el máximo ni cambies todo el año.
- Tras un ranking comparativo, el anterior desplaza el foco una vez: shift_period,
  period={"kind":"previous_period","anchor":"focus"}, comparison_period={"kind":"previous_period"}.
- Una fecha explícita nueva usa change_period, no change_entity; no inventa comparación nueva.
- Cambiar entidad conserva el análisis. Volver a una entidad anterior usa restore_scope y recupera
  su alcance más reciente, NO el primer análisis de esa entidad. No añade un desglose salvo petición
  explícita combinada, en cuyo caso analysis.restore_with_breakdown=true.
- Conjuntos explícitos o ambas/juntas usan joint_share, joint_entities y analysis.entity_set
  con dimension/value, o entity_reference=recent, entity_count=2/3. No omitas valores escritos por el usuario.
- Un ranking explícito de anunciantes nunca se convierte en marca.
- Respeta filter_groups de semantic_policy: una agrupación genérica abarca TODOS sus valores;
  no puede reducirse a una sola categoría. La política procede del modelo semántico, no de tu intuición.
- Un referente ausente requiere aclaración, no adivinar.
No corrijas una propuesta válida por preferencias de estilo. No copies un periodo viejo
porque apareció en el historial: usa el último foco solicitado, incluso si tuvo un error.
'''


def review_request(gateway, question, proposal, memory, schema, *, model=None):
    keys = {'intent', 'operation', 'scope_mode', 'filters', 'remove_filters', 'period',
            'comparison_period', 'dimensions', 'analysis'}
    scope_keys = {'metric', 'filters', 'requested_period', 'comparison_period', 'dimensions', 'intent', 'analysis'}
    compact = lambda scope: {k: v for k, v in scope.items() if k in scope_keys}
    payload = {'last_requested_scope': compact(memory.get('analysis_context', {})),
        'last_peak': memory.get('last_peak', {}), 'recent_entities': memory.get('recent_entities', []),
        'recent_scopes': [compact(s) for s in memory.get('recent_scopes', [])[-6:]],
        'semantic_policy': load_semantic_layer()['business_rules'],
        'correction_schema': {k: schema['properties'][k] for k in keys},
        'proposal': {k: v for k, v in proposal.items() if k in keys},
        'current_request': question}
    review = gateway.complete(REVIEW_PROMPT, payload, model=model, stage='request_review', json_mode=True, temperature=0)
    try:
        validate(review, {'type': 'object', 'required': ['valid', 'reason', 'corrections'], 'additionalProperties': False,
            'properties': {'valid': {'type': 'boolean'}, 'reason': {'type': 'string'},
                'corrections': {'type': 'object', 'additionalProperties': False,
                    'properties': {k: schema['properties'][k] for k in keys}}}})
    except ValidationError as exc:
        raise ValueError(f'Revisión inválida en {".".join(map(str, exc.path))}: {exc.message}') from exc
    corrections = deepcopy(review['corrections'])
    if not review['valid'] and not corrections:
        raise ValueError('La revisión semántica rechazó el plan sin una corrección concreta: ' + review['reason'])
    if review['valid'] and corrections:
        raise ValueError('La revisión se contradice: declara válido pero cambia el alcance.')
    return review
