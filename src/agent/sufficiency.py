"""Capability-based sufficiency, independent of question wording or entity names."""


def evidence_sufficient(intent, evidence, scope=None):
    results = [e['result'] for e in evidence if e.get('result', {}).get('success') is True]
    if intent in {'ranking_change', 'ranking_acceleration'}:
        capability = 'rank_acceleration' if intent == 'ranking_acceleration' else 'rank_change'
        return any(r.get('capability') == capability and r.get('rows') and r.get('comparison_equivalent')
                   and r.get('period_a') and r.get('period_b') and r['period_a'] != r['period_b']
                   and (intent != 'ranking_acceleration' or r.get('period_c')) for r in results)
    if intent == 'temporal_extrema':
        return any(r.get('capability') == 'temporal_extrema' and r.get('rows') and r.get('extrema')
                   and r.get('granularity') for r in results)
    if intent == 'diagnostic_search':
        return any(r.get('capability') == 'dimension_search' and r.get('drivers') and r.get('comparison_equivalent')
                   and len([c for c in r.get('candidate_evaluations', []) if c.get('eligible')]) >= 2 for r in results)
    if intent == 'joint_share':
        return any(r.get('share_pct') is not None and r.get('total') is not None and r.get('value') is not None
                   and len(r.get('values', [])) >= 2 and not r.get('missing_values') and r.get('dimension') for r in results)
    if intent in {'catalog', 'coverage'}:
        return any(r.get('values') or (r.get('start') and r.get('end')) for r in results)
    if intent in {'lookup', 'ranking', 'composition', 'trend', 'anomaly'}:
        required = {'lookup': lambda r: r.get('value') is not None,
                    'ranking': lambda r: bool(r.get('rows')) and bool(r.get('dimension')),
                    'composition': lambda r: (bool(r.get('rows')) and bool(r.get('dimension'))) or r.get('share_pct') is not None,
                    'trend': lambda r: bool(r.get('rows')) and bool(r.get('granularity')),
                    'anomaly': lambda r: bool(r.get('statistics'))}
        return any(required[intent](r) for r in results)
    if intent in {'comparison', 'period_comparison'}:
        return any(r.get('value_a') is not None and r.get('value_b') is not None for r in results)
    if intent == 'diagnostic':
        return any(r.get('drivers') or ((scope or {}).get('operation') == 'inspect_peak' and r.get('rows') and r.get('dimension')) for r in results)
    if intent == 'open_analysis':
        perspectives = set()
        for r in results:
            if r.get('rows') and r.get('granularity'): perspectives.add('temporal')
            if r.get('rows') and r.get('dimension'): perspectives.add('distribution:' + r['dimension'])
            if r.get('value_a') is not None: perspectives.add('comparison')
        return len(perspectives) >= 2
    return False
