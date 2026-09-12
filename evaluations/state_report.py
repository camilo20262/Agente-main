"""Reassess all state-audit rounds without rewriting raw execution artifacts."""
import json
from pathlib import Path
from evaluations.state_evaluator import assess_record
from evaluations.state_expectations import ORIGINAL, ADDITIONAL
from evaluations.state_paraphrases import GROUPS

ROOT = Path('evaluations/conversation_state')


def reports():
    rounds = []
    for p in sorted(ROOT.glob('*/summary.json')):
        data = json.loads(p.read_text())
        records = data.get('records', [])
        if not records: continue
        expected = ORIGINAL if records[0]['id'].startswith('original-') else ADDITIONAL if records[0]['id'].startswith('additional-') else None
        assessed = []
        for index, record in enumerate(records):
            contract = expected[index] if expected else record.get('expected')
            if record['id'].startswith('paraphrase-'):
                _, group, turn = record['id'].split('-')
                contract = GROUPS[int(group)-1][int(turn)-1][1]
            if contract is None: continue
            verdict = assess_record(record, contract)
            assessed.append({'id': record['id'], 'question': record['question'], **verdict,
                'intent': record['result']['plan'].get('intent'), 'scope': record['result']['plan'].get('resolved_context'),
                'stop_reason': record['result']['metrics'].get('stop_reason'),
                'tools': record['result']['steps'], 'queries': record['result']['metrics'].get('turn', {}).get('bigquery_queries', 0),
                'answer': record['result']['answer']})
        started = data.get('started_at')
        if not started:
            times = [json.loads(g.read_text()).get('started_at', '') for g in p.parent.glob('group-*/summary.json')]
            started = min(times) if times else ''
        report = {'started_at': started, 'round': p.parent.name, 'cases': len(assessed), 'passed': sum(a['passed'] for a in assessed),
                  'semantic_review_observed': any(e.get('stage') == 'semantic_review' for r in records for e in r['result']['metrics'].get('events', [])),
                  'records': assessed, 'source_fingerprint': data.get('source_fingerprint')}
        (p.parent/'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        rounds.append(report)
    rounds.sort(key=lambda r: (r['started_at'], r['round']))
    (ROOT/'review_history.json').write_text(json.dumps(rounds, ensure_ascii=False, indent=2)+'\n')
    return rounds


if __name__ == '__main__':
    for r in reports(): print(r['round'], f"{r['passed']}/{r['cases']}")
