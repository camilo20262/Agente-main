"""Offline release checks against saved real SQL and conversation evidence.

No provider or BigQuery calls. Historical runs and reference SQL stay immutable.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from math import isclose
from pathlib import Path
import subprocess
import sys

ROOT = Path('evaluations/conversation_state')


def numeric_checks(original, additional, paraphrases):
    reference = json.loads((ROOT / 'numeric_reference.json').read_text())['checks']
    cases = [
        ('growth_july', original / 'original-01.json', 'ranking_cambio_bicomp'),
        ('peak_bmw', original / 'original-06.json', 'extremos_temporales_bicomp'),
        ('joint_tv', original / 'original-12.json', 'consultar_participacion_bicomp'),
        ('joint_october', additional / 'additional-08.json', 'consultar_participacion_bicomp'),
        ('bmw_october', additional / 'additional-05.json', 'consultar_inversion_publicitaria'),
        ('empty_week_toyota', paraphrases / 'group-3/paraphrase-3-02.json', 'consultar_inversion_publicitaria'),
    ]
    checks = []
    for name, path, tool in cases:
        record = json.loads(path.read_text())
        evidence = next((e['result'] for e in record['result']['evidence'] if e['tool'] == tool), {})
        expected = reference[name]['rows'][0]
        if name == 'growth_july':
            row = (evidence.get('rows') or [{}])[0]
            actual = {k: row.get(k) for k in ('current_value', 'previous_value', 'difference')}
            actual['entity'] = row.get('dimension')
        elif name == 'peak_bmw':
            row = evidence.get('selected_extreme', {})
            actual = {'month': row.get('period'), 'value': row.get('value')}
        elif name.startswith('joint_'):
            actual = {'combined': evidence.get('value'), 'universe': evidence.get('total'), 'share_pct': evidence.get('share_pct')}
        elif name == 'empty_week_toyota':
            actual = {'source_rows': evidence.get('row_count'), 'value': evidence.get('value')}
        else:
            actual = {'value': evidence.get('value')}
        same = lambda a, b: isclose(a, b, rel_tol=1e-9, abs_tol=1e-6) if isinstance(a, (float, int)) and isinstance(b, (float, int)) else a == b
        passed = all(same(actual.get(k), v) for k, v in expected.items())
        if name == 'empty_week_toyota':
            passed = passed and evidence.get('error_type') == 'no_data' and evidence.get('period') == {'start': '2024-03-25', 'end': '2024-03-31'}
        checks.append({'name': name, 'passed': passed, 'conversation_artifact': str(path),
            'reference_job_id': reference[name]['evidence']['job_id'], 'expected': expected, 'actual': actual,
            'scope': record['result']['plan'].get('resolved_context')})
    return checks


def run(original, additional, paraphrases):
    sources = sorted(Path('src').rglob('*.py'))
    code = [*sources, *sorted(Path('evaluations').glob('*.py')), Path('agent.py'), Path('app.py'), Path('cli.py')]
    for path in code:
        ast.parse(path.read_text(), filename=str(path))
    checks = []
    for args in [[sys.executable, '-m', 'pytest', '-q'], [sys.executable, '-m', 'pip', 'check'],
                 ['git', 'diff', '--check'], ['git', 'diff', '--cached', '--check']]:
        process = subprocess.run(args, capture_output=True, text=True)
        checks.append({'command': args, 'exit_code': process.returncode, 'output': process.stdout + process.stderr})
    paths = sorted(set(code + list(Path('src').rglob('*.yaml')) + [Path('requirements.txt')]))
    manifest = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
        'ast_modules': len(code), 'source_fingerprint': hashlib.sha256(''.join(p.read_text() for p in sources).encode()).hexdigest(),
        'file_sha256': manifest, 'numeric_checks': numeric_checks(ROOT / original, ROOT / additional, ROOT / paraphrases),
        'scope': 'Offline tests plus independent SQL/evidence comparisons; this is not a universal semantic approval.'}
    (ROOT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'checks': [c['exit_code'] for c in checks], 'numeric_passed': sum(c['passed'] for c in report['numeric_checks']),
                      'ast_modules': len(code)}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--original', default='default_original')
    parser.add_argument('--additional', default='default_additional')
    parser.add_argument('--paraphrases', default='default_paraphrases')
    args = parser.parse_args()
    run(args.original, args.additional, args.paraphrases)
