"""Opt-in real, sequential conversations with requested/evidence state snapshots."""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


ORIGINAL = [
    '¿Quién está creciendo más?', '¿Y el anterior?',
    '¿Qué dimensión explica mejor la variación sin que yo te diga cuál revisar?',
    '¿Cuánto invirtió BMW en 2025?', '¿Cuánto invirtió BMW en digital durante 2025?',
    '¿Cuál fue el mes de mayor inversión de BMW en 2025?',
    '¿Cómo se distribuyó BMW por medios en 2025?',
    '¿Cuáles fueron los 5 vehículos con mayor inversión de BMW en 2025?',
    '¿Qué marcas lideraron la inversión en digital en 2025?',
    'Top 10 anunciantes en televisión durante 2025.', '¿y en 2026?',
    '¿Qué porcentaje conjunto representan BMW y Volvo?',
]
ADDITIONAL = [
    'Analiza BMW en 2025.', 'Solo digital.', 'Ahora por medios.',
    '¿Cuál fue el mes más fuerte?', '¿Y el anterior?', '¿Qué explica el cambio?',
    'Ahora Volvo.', '¿Y ambas juntas?', 'Top anunciantes en televisión.',
    '¿Y en 2026?', 'Vuelve a BMW.', '¿Cómo se distribuye por vehículos?',
]


def run_conversation(questions, output, prefix='original'):
    from agent import build_agent_service
    service = build_agent_service()
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    raw_plans = []
    complete = service.gateway.complete
    def capture(*args, **kwargs):
        result = complete(*args, **kwargs)
        if kwargs.get('stage') == 'planning': raw_plans.append(deepcopy(result))
        return result
    service.gateway.complete = capture
    metadata = {'started_at': datetime.now(timezone.utc).isoformat(),
        'plan_semantic_review': service.settings.plan_semantic_review,
        'source_fingerprint': hashlib.sha256(''.join(p.read_text() for p in sorted(Path('src').rglob('*.py'))).encode()).hexdigest(),
        'mode': 'One real service instance and ordered history for the complete conversation', 'records': []}
    messages = []
    for index, question in enumerate(questions, 1):
        before = deepcopy(service.memory.context()); raw_plans.clear()
        messages.append({'role': 'user', 'content': question})
        started = time.perf_counter(); result = service.run(messages)
        record = {'id': f'{prefix}-{index:02}', 'question': question, 'elapsed_s': round(time.perf_counter()-started, 2),
            'memory_before': before, 'memory_after': deepcopy(service.memory.context()),
            'raw_planner_outputs': deepcopy(raw_plans), 'compiled_transition': result.plan,
            'inherited_scope': before.get('last_requested_scope') or before.get('analysis_context', {}),
            'result': asdict(result)}
        if prefix in {'original', 'additional'}:
            from evaluations.state_expectations import ORIGINAL as ORIGINAL_EXPECTED, ADDITIONAL as ADDITIONAL_EXPECTED
            from evaluations.state_evaluator import assess_record
            expected = (ORIGINAL_EXPECTED if prefix == 'original' else ADDITIONAL_EXPECTED)[index-1]
            record['expected'] = expected
            record['assessment'] = assess_record(record, expected)
        metadata['records'].append(record)
        (output/(record['id']+'.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str)+'\n')
        messages.append({'role': 'assistant', 'content': result.answer})
        print(json.dumps({'id': record['id'], 'intent': result.plan.get('intent'),
            'operation': result.plan.get('scope', {}).get('operation'), 'steps': result.steps,
            'partial': result.is_partial, 'stop_reason': result.metrics.get('stop_reason')}, ensure_ascii=False), flush=True)
    (output/'summary.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str)+'\n')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--conversation', choices=['original', 'additional'], default='original')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not args.live: parser.error('Real execution requires --live.')
    run_conversation(ORIGINAL if args.conversation == 'original' else ADDITIONAL, args.output, args.conversation)
