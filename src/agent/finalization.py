"""Tool-free answer generation, one complete repair, then a deterministic fallback."""
from __future__ import annotations
from src.agent.prompts import FINAL_RESPONSE_PROMPT
from src.agent.response_validator import compact_evidence, validate_answer
from src.agent.facts import fact_catalog, render_narrative


def display(value):
    if isinstance(value, (int, float)):
        return f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return 'Sin información' if value is None else str(value)


def safe_answer(evidence, *, reason=None):
    explanations = {'no_data': 'no encontré datos numéricos para el alcance solicitado',
                    'arguments': 'no pude resolver los argumentos de una consulta',
                    'schema': 'una consulta no superó la validación del esquema',
                    'infrastructure': 'la fuente de datos no estuvo disponible',
                    'duplicate': 'se omitió una consulta repetida',
                    'intent_budget': 'se alcanzó el presupuesto de investigación'}
    lines = [f'Análisis parcial: {explanations.get(reason, reason)}.'] if reason else []
    for item in evidence:
        result = item.get('result', {})
        options = result.get('clarification_options')
        if options:
            missing = ', '.join(map(str, options['missing_values']))
            available = ', '.join(map(str, options['available_values']))
            return (f'No encontré {missing} como valor exacto de {options["dimension"]} en el alcance solicitado. '
                    f'Los valores disponibles son: {available}. ¿Cuál quieres comparar?')
        if result.get('success') is not True or item.get('historical'):
            continue
        scope = ', '.join(str(v) for v in result.get('filters', {}).values()) or result.get('brand') or 'el alcance consultado'
        label = result.get('metric_label') or result.get('metric', 'Resultado')
        period = result.get('effective_period') or result.get('observed_period') or result.get('period') or {}
        period_text = f" Entre {period['start']} y {period['end']}." if period.get('start') and period.get('end') else ''
        if result.get('capability') in {'rank_change', 'rank_acceleration', 'temporal_extrema', 'dimension_search'} or (result.get('values') and result.get('share_pct') is not None):
            lines.extend(f['text'] for f in fact_catalog([item]))
        elif result.get('value') is not None:
            lines.append(f"{scope}: {label} de {display(result['value'])}.{period_text}")
            if result.get('share_pct') is not None:
                lines.append(f"Participación calculada: {display(result['share_pct'])} %.")
        elif result.get('value_a') is not None and result.get('value_b') is not None:
            a = result.get('brand_a') or result.get('value_a_label') or str(result.get('period_a', 'Periodo actual'))
            b = result.get('brand_b') or result.get('value_b_label') or str(result.get('period_b', 'Periodo anterior'))
            lines.append(f"{a}: {display(result['value_a'])}; {b}: {display(result['value_b'])} ({label}).")
            if result.get('difference') is not None:
                lines.append(f"Diferencia calculada: {display(result['difference'])}.")
            if result.get('difference_pct') is not None:
                lines.append(f"Variación calculada: {display(result['difference_pct'])} %.")
        elif result.get('rows'):
            lines.append(f'{label} para {scope}.{period_text}')
            for row in result['rows'][:5]:
                category = display(row.get('dimension', row.get('period', 'Dato')))
                if result.get('segment_dimension'):
                    category = f"{result['segment_dimension']}={display(row.get('segment'))}, {category}"
                lines.append(f"- {category}: {display(row.get('value'))}.")
        elif result.get('values'):
            lines.append('Valores disponibles (muestra): ' + ', '.join(map(str, result['values'][:10])) + '.')
        elif result.get('start') and result.get('end'):
            lines.append(f"Cobertura disponible: {result['start']} a {result['end']}.")
        if result.get('is_partial'):
            lines.append('Corresponde al acumulado disponible, con cobertura parcial del periodo solicitado.')
        for warning in result.get('warnings', [])[:2]:
            lines.append(str(warning).rstrip('.') + '.')
    if not lines or (reason and len(lines) == 1):
        lines.append('No obtuve evidencia utilizable para responder esta pregunta. No puedo afirmar valores ni variaciones.')
    return '\n\n'.join(dict.fromkeys(lines))


class AnswerFinalizer:
    def __init__(self, gateway, settings, metrics):
        self.gateway, self.settings, self.metrics = gateway, settings, metrics

    def finalize(self, question, context, evidence, *, model=None, partial_reason=None, temperature=0.1):
        if context.intent in {'lookup', 'joint_share', 'temporal_extrema', 'ranking_change', 'ranking_acceleration'} and any(i['result'].get('success') is True for i in evidence):
            return safe_answer(evidence, reason=partial_reason), bool(partial_reason), []
        issues = []
        previous_answer = None
        facts = fact_catalog(evidence)
        for attempt in range(1 + self.settings.response_validation_retries):
            payload = {'question': question, 'scope': context.as_dict(), 'facts': facts,
                       'limitations': partial_reason, 'repair_issues': issues,
                       'previous_answer': previous_answer,
                       'instruction': 'Reescribir respuesta COMPLETA. Elimina las afirmaciones rechazadas; no intentes recalcularlas. Sin herramientas ni cálculos nuevos.'}
            if 'estacionalidad_sin_ciclos_comparables' in issues:
                payload['repair_instruction'] = ('Elimina las afirmaciones de estacionalidad de TODOS los campos, '
                    'también títulos. Un pico en una única serie anual solo acredita concentración temporal. '
                    'Describe el máximo observado y su participación calculada; no afirmes un patrón repetido.')
            try:
                raw, finish = self.gateway.complete(FINAL_RESPONSE_PROMPT, payload, model=model, temperature=temperature, structured_output=True, stage='repair' if attempt else 'final')
            except Exception as exc:
                issues = [f'fallo_generacion:{type(exc).__name__}']
                break
            try:
                answer = render_narrative(raw, facts, evidence)
            except (ValueError, TypeError, KeyError) as exc:
                issues = [str(exc)]
                previous_answer = raw
                self.metrics.events.append({'stage': 'validation', 'attempt': attempt, 'issues': issues, 'candidate': raw})
                continue
            validation = validate_answer(answer, evidence, finish_reason=finish, intent=context.intent)
            self.metrics.events.append({'stage': 'validation', 'attempt': attempt, 'issues': list(validation.issues), 'candidate': answer})
            if validation.valid:
                if partial_reason:
                    answer = 'Análisis parcial: no se completó toda la investigación planificada.\n\n' + answer
                return answer, bool(partial_reason), []
            issues = list(validation.issues)
            previous_answer = answer
        self.metrics.errors.extend('response_validation:' + issue for issue in issues)
        return safe_answer(evidence, reason=partial_reason or 'no pude producir una interpretación que superara la validación'), True, issues
