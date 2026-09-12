"""Opt-in live adversarial benchmark; writes actual plans, SQL, responses and verdicts."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from src.agent.response_validator import validate_answer
from src.semantic import load_semantic_layer


def cases():
    singles = [
        ('lookup', '¿Cuánto invirtió BMW en 2025?'),
        ('lookup', '¿Cuánto invirtió Volvo?'),
        ('lookup', '¿Cuál fue la inversión neta de la marca Volvo en marzo de 2025?'),
        ('ranking', '¿Qué marcas invirtieron más en 2025?'),
        ('ranking', 'Top 10 anunciantes en digital durante 2025.'),
        ('trend', '¿Cómo viene evolucionando Volvo durante los últimos seis meses disponibles?'),
        ('composition', '¿Cuál es el mix de medios de BMW en 2025?'),
        ('composition', '¿Cómo se distribuyó la inversión por formato en 2025?'),
        ('comparison', 'Compara Volvo con BMW en 2025.'),
        ('comparison', 'Compara Digital vs TV para Volvo en 2025.'),
        ('period_comparison', '¿Subió la inversión de Volvo en 2026 frente a 2025? Usa ventanas equivalentes.'),
        ('period_comparison', 'Compara la inversión YTD de BMW frente al mismo periodo del año anterior.'),
        ('diagnostic', '¿Qué medios explican el cambio de la inversión de Volvo en 2026 frente a 2025?'),
        ('open_analysis', 'Analiza el sector automotriz en 2025.'),
        ('open_analysis', 'Encuentra los principales hallazgos de inversión de este año.'),
        ('anomaly', '¿Hay algún pico anormal en la inversión mensual de BMW durante 2025?'),
        ('clarification', '¿Cómo vamos?'),
        ('out_of_domain', 'Hola.'),
        ('out_of_domain', 'Explícame qué significa share.'),
        ('out_of_domain', '¿Cómo interpretarías un pico de inversión?'),
        ('composition', 'Analiza la calidad de la dimensión formato para Volvo en 2025: no interpretes NULL ni N/A como formatos reales.'),
        ('lookup', '¿Cuánto invirtió la marca MARCA_INEXISTENTE_AUDITORIA en 2025?'),
        ('lookup', '¿Cuántas inserciones tuvo BMW en 2025?'),
        ('lookup', 'Calcula el coste por inserción de BMW en 2025 usando inversión neta.'),
    ]
    dimensions = list(load_semantic_layer()['dimensions'])
    generated = [d for d in ('ciudad', 'region', 'sector', 'agencia') if d in dimensions]
    singles += [('ranking', f'Muestra las cinco categorías con mayor inversión neta USD por {d} en 2025.') for d in generated]
    groups = [[{'id': f'independent-{i+1:02}', 'question': q, 'family': intent,
                'expected_dimensions': ['categoria', generated[i-24]] if i >= 24 else [],
                'allow_dimension_clarification': i == 9,
                'expected_no_data': 'INEXISTENTE' in q}] for i, (intent, q) in enumerate(singles)]
    follow = [('open_analysis', 'Analízame Volvo en 2025.'), ('open_analysis', '¿Y en 2026?'),
              ('period_comparison', '¿Ha bajado?'), ('diagnostic', '¿En qué medios?'),
              ('composition', '¿Y BMW?'), ('comparison', 'Compara ambos.'), ('diagnostic', '¿Qué explica la diferencia?')]
    groups.append([{'id': f'conversation-{i+1:02}', 'question': q, 'family': intent} for i, (intent, q) in enumerate(follow)])
    peak = [('open_analysis', 'Analízame BMW en 2025.'), ('diagnostic', '¿Qué pasó en el mes más fuerte?'), ('composition', '¿Y por medios?')]
    groups.append([{'id': f'peak-followup-{i+1:02}', 'question': q, 'family': intent} for i, (intent, q) in enumerate(peak)])
    return groups


def assess(case, result):
    checks = []
    context = result.plan.get('resolved_context', {})
    if not result.answer.strip() or result.steps >= 8: checks.append('empty_or_safety_limit')
    data = [e for e in result.evidence if e['result'].get('success') is True]
    clarified = case.get('allow_dimension_clarification') and any(e['result'].get('clarification_options') for e in result.evidence) and result.answer.endswith('?')
    if case.get('expected_no_data'):
        if data or not result.is_partial: checks.append('invented_missing_entity')
    elif case['family'] not in {'out_of_domain', 'clarification'} and not data and not clarified:
        checks.append('no_evidence')
    if case['family'] in {'out_of_domain', 'clarification'} and result.evidence: checks.append('unnecessary_query')
    if case.get('expected_dimensions'):
        covered = {dimension for e in data for dimension in e['result'].get('dimensions', [e['result'].get('dimension')]) if dimension}
        if not set(case['expected_dimensions']) <= covered: checks.append('missing_requested_group_dimension')
    if case.get('expected_metric') and context.get('metric') != case['expected_metric']:
        checks.append('wrong_metric')
    if case.get('expected_percentage') and '%' not in result.answer:
        checks.append('missing_requested_percentage')
    if case['id'] == 'independent-01':
        if context.get('filters', {}).get('marca', '').upper() != 'BMW': checks.append('wrong_entity_dimension')
        if result.steps != 1: checks.append('lookup_overresearch')
    if case['id'] in {'conversation-02', 'conversation-03', 'conversation-04'}:
        if context.get('filters', {}).get('marca', '').upper() != 'VOLVO': checks.append('lost_followup_entity')
    if case['id'] == 'conversation-02' and context.get('requested_period', {}).get('start') != '2026-01-01': checks.append('wrong_followup_year')
    if case['id'] == 'conversation-02' and result.plan.get('intent') != 'open_analysis': checks.append('lost_analysis_depth')
    if case['id'] in {'conversation-03', 'conversation-04', 'conversation-05'}:
        if context.get('requested_period', {}).get('start', '')[:4] != '2026' or context.get('comparison_period', {}).get('start', '')[:4] != '2025':
            checks.append('reversed_or_lost_followup_periods')
    if case['id'] == 'conversation-04' and not any(e['result'].get('drivers') for e in data): checks.append('mix_instead_of_variation_drivers')
    if case['id'] == 'conversation-05' and context.get('filters', {}).get('marca', '').upper() != 'BMW': checks.append('wrong_followup_entity')
    if case['id'] == 'conversation-06':
        pairs = [{str(e['result'].get('brand_a', e['result'].get('value_a_label', ''))).upper(),
                  str(e['result'].get('brand_b', e['result'].get('value_b_label', ''))).upper()} for e in data]
        if {'VOLVO', 'BMW'} not in pairs: checks.append('wrong_entity_pair')
    if case['id'] == 'conversation-07' and not any(e['result'].get('comparison_type') == 'entities' and e['result'].get('drivers') for e in data): checks.append('missing_entity_difference_drivers')
    if case['id'] == 'peak-followup-02':
        if context.get('requested_period', {}).get('start', '')[:4] != '2025': checks.append('lost_peak_year')
        if case.get('expected_peak') and context.get('requested_period', {}).get('start') != case['expected_peak']: checks.append('wrong_peak_month')
    if data:
        validation = validate_answer(result.answer, result.evidence, intent=result.plan.get('intent'))
        # Safe deterministic fallback is recorded separately, never counted as an analytical success.
        if not validation.valid: checks.extend(validation.issues)
    if result.is_partial and not case.get('expected_no_data') and not clarified: checks.append('partial_or_fallback')
    return {'status': 'FAIL' if checks else 'PASS', 'issues': list(dict.fromkeys(checks)),
            'expected_family': case['family'], 'actual_intent': result.plan.get('intent')}


def run_group(group, output):
    from agent import build_agent_service
    service = build_agent_service()
    messages, records = [], []
    for case in group:
        case = dict(case)
        if case['id'] == 'peak-followup-02': case['expected_peak'] = service.memory.last_peak.get('period')
        messages.append({'role': 'user', 'content': case['question']})
        started = time.perf_counter()
        result = service.run(messages)
        record = {**case, 'elapsed_s': round(time.perf_counter()-started, 2), 'result': asdict(result), **assess(case, result)}
        records.append(record)
        (output / (case['id'] + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str))
        messages.append({'role': 'assistant', 'content': result.answer})
        print(json.dumps({'id': case['id'], 'question': case['question'], 'status': record['status'],
                          'intent': result.plan.get('intent'), 'steps': result.steps,
                          'llm_calls': result.metrics.get('turn', {}).get('total_llm_calls'),
                          'issues': record['issues']}, ensure_ascii=False), flush=True)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Explicitly call the configured LLM and BigQuery.')
    parser.add_argument('--output', default='evaluations/results/live')
    parser.add_argument('--ids', nargs='*')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--cases', help='Optional JSON file with independent/conversational case groups.')
    args = parser.parse_args()
    if not args.live: parser.error('Use --live to authorize the network benchmark.')
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    groups = json.loads(Path(args.cases).read_text()) if args.cases else cases()
    if args.ids: groups = [g for g in groups if any(c['id'] in args.ids for c in g)]
    started = datetime.now(timezone.utc).isoformat()
    fingerprint = hashlib.sha256(''.join(p.read_text() for p in sorted(Path('src').rglob('*.py'))).encode()).hexdigest()
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_group, group, output) for group in groups]
        for future in as_completed(futures): records.extend(future.result())
    report = {'started_at': started, 'source_fingerprint': fingerprint, 'count': len(records),
              'passed': sum(r['status']=='PASS' for r in records), 'failed': sum(r['status']=='FAIL' for r in records),
              'records': sorted(records, key=lambda r:r['id'])}
    (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({k:v for k,v in report.items() if k!='records'}), flush=True)


if __name__ == '__main__': main()
