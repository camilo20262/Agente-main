"""Independent conversation assertions, supplied by an oracle rather than the plan.

A planner cannot grade itself by declaring the easier intent. Expectations belong
in test cases; returned evidence and resolved state are checked independently.
"""
from math import isclose


def assess_record(record, expected):
    verdict = assess_state(record['result'], expected)
    before = record.get('memory_before', {}).get('analysis_context', {})
    after = record['result'].get('plan', {}).get('resolved_context', {})
    for field in expected.get('preserve_fields', []):
        if field not in before or before[field] != after.get(field):
            verdict['issues'].append('changed_inherited:' + field)
    verdict['issues'] = sorted(set(verdict['issues']))
    verdict['passed'] = not verdict['issues']
    return verdict


def assess_state(result, expected):
    def canonical(value):
        if isinstance(value, str): return value.strip().upper()
        if isinstance(value, list): return sorted((canonical(v) for v in value), key=str)
        if isinstance(value, dict):
            copy = {k: canonical(v) for k, v in value.items()}
            # The two source columns both have exact DIGITAL; this equivalence is limited
            # to evaluating that confirmed value, never used for runtime query rewriting.
            if copy.get('medio_agrupado') == 'DIGITAL':
                copy['medio'] = copy.pop('medio_agrupado')
            return copy
        return value
    plan = result.get('plan', {})
    scope = plan.get('resolved_context', {})
    evidence = [e['result'] for e in result.get('evidence', []) if e.get('result', {}).get('success') is True]
    errors = []
    if expected.get('intent') and plan.get('intent') not in ([expected['intent']] if isinstance(expected['intent'], str) else expected['intent']):
        errors.append('intent')
    for key in ('filters', 'dimensions', 'requested_period', 'comparison_period', 'metric'):
        if key == 'dimensions' and expected.get('any_dimensions'): continue
        if key == 'dimensions' and expected.get('capability') == 'peak' and scope.get(key) in ([], ['fecha']): continue
        if key == 'dimensions' and scope.get(key) == ['medio_agrupado'] and expected.get(key) == ['medio']: continue
        if key in expected and canonical(scope.get(key)) != canonical(expected[key]):
            errors.append('scope:' + key)
    for key, value in expected.get('contains_filters', {}).items():
        if canonical(scope.get('filters', {}).get(key)) != canonical(value):
            errors.append('filter:' + key)
    for key, value in expected.get('contains_analysis', {}).items():
        evidence_key = {'change_basis': 'criterion'}.get(key, key)
        actual = scope.get('analysis', {}).get(key)
        if actual is None:
            actual = next((r[evidence_key] for r in evidence if evidence_key in r), None)
        if actual != value:
            errors.append('analysis:' + key)
        if capability_value := next((r.get(evidence_key) for r in evidence if r.get('capability') in {'rank_change', 'rank_acceleration'}), None):
            if capability_value != value:
                errors.append('evidence_analysis:' + key)
    for dimension in expected.get('removed_filters', []):
        if dimension in scope.get('filters', {}) or any(dimension in r.get('filters', {}) for r in evidence):
            errors.append('filtered_breakdown:' + dimension)
    capability = expected.get('capability')
    if capability in {'rank_change', 'rank_acceleration'}:
        valid = [r for r in evidence if r.get('capability') == capability and r.get('comparison_equivalent')
                 and r.get('period_a') and r.get('period_b') and r['period_a'] != r['period_b'] and r.get('rows')]
        if not valid:
            errors.append('growth_requires_comparative_ranking')
        for r in valid:
            for row in r['rows']:
                if not isclose(row.get('difference', float('inf')), row['current_value']-row['previous_value'], abs_tol=.01):
                    errors.append('growth_math')
    elif capability == 'peak':
        if not any(r.get('granularity') and r.get('rows') and (r.get('extrema') or r.get('peak')) for r in evidence):
            errors.append('peak_requires_series')
    elif capability == 'joint_share':
        valid = [r for r in evidence if len(r.get('values', [])) >= 2 and r.get('total') and r.get('share_pct') is not None and not r.get('missing_values')]
        if not valid:
            errors.append('joint_requires_computed_universe')
        for r in valid:
            if not isclose(r['value']/r['total']*100, r['share_pct'], abs_tol=.001):
                errors.append('joint_math')
            if expected.get('entities') and canonical(r['values']) != canonical(expected['entities']):
                errors.append('joint_entities')
    elif capability == 'comparison':
        if not any(r.get('period_a') and r.get('period_b') and r['period_a'] != r['period_b'] and r.get('comparison_equivalent') for r in evidence):
            errors.append('comparison_requires_reference')
    elif capability == 'dimension_search':
        if not any(r.get('drivers') and len([c for c in r.get('candidate_evaluations', []) if c.get('eligible')]) >= 2 for r in evidence):
            errors.append('diagnostic_requires_candidates')
    if expected.get('dimension') and not any(r.get('dimension') == expected['dimension'] for r in evidence):
        errors.append('evidence_dimension')
    if expected.get('min_rows') and not any(len(r.get('rows', [])) >= expected['min_rows'] for r in evidence):
        errors.append('ranking_too_short')
    if expected.get('success', True) and (result.get('is_partial') or not evidence):
        errors.append('partial_or_no_evidence')
    return {'passed': not errors, 'issues': sorted(set(errors))}
