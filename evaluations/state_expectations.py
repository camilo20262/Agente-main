"""External oracle for the specified conversations (not imported by runtime)."""
YEAR = {'start': '2025-01-01', 'end': '2025-12-31'}
NEXT_YEAR = {'start': '2026-01-01', 'end': '2026-12-31'}
JUL = {'start': '2026-07-01', 'end': '2026-07-31'}
JUN = {'start': '2026-06-01', 'end': '2026-06-30'}
MAY = {'start': '2026-05-01', 'end': '2026-05-31'}
OCT = {'start': '2025-10-01', 'end': '2025-10-31'}
SEP = {'start': '2025-09-01', 'end': '2025-09-30'}
TV = {'medio_agrupado': ['TV ABIERTA', 'TV CABLE']}
BMW = {'marca': 'BMW'}
VOLVO = {'marca': 'VOLVO'}
DIGITAL = {'medio': 'DIGITAL'}


def expect(intent, filters, period, dimensions=None, comparison=None, **kw):
    return {'intent': intent, 'filters': filters, 'requested_period': period,
            'dimensions': dimensions or [], 'comparison_period': comparison or {}, 'metric': 'inv_neta', **kw}


ORIGINAL = [
    expect('ranking_change', {}, JUL, ['marca'], JUN, capability='rank_change'),
    expect('ranking_change', {}, JUN, ['marca'], MAY, capability='rank_change'),
    expect('diagnostic_search', {}, JUN, [], MAY, capability='dimension_search'),
    expect('lookup', BMW, YEAR),
    expect('lookup', {**BMW, **DIGITAL}, YEAR),
    expect('temporal_extrema', BMW, YEAR, capability='peak'),
    expect('composition', BMW, YEAR, ['medio'], removed_filters=['medio', 'medio_agrupado']),
    expect('ranking', BMW, YEAR, ['vehiculo'], dimension='vehiculo', min_rows=5),
    expect('ranking', DIGITAL, YEAR, ['marca'], dimension='marca'),
    expect('ranking', TV, YEAR, ['anunciante'], dimension='anunciante', min_rows=10),
    expect('ranking', TV, NEXT_YEAR, ['anunciante'], dimension='anunciante', min_rows=10),
    expect('joint_share', TV, NEXT_YEAR, ['marca'], capability='joint_share', entities=['BMW', 'VOLVO']),
]
ADDITIONAL = [
    expect('open_analysis', BMW, YEAR, any_dimensions=True),
    expect('open_analysis', {**BMW, **DIGITAL}, YEAR, any_dimensions=True, preserve_fields=['dimensions', 'analysis']),
    expect(['composition', 'open_analysis'], BMW, YEAR, ['medio'], removed_filters=['medio', 'medio_agrupado']),
    expect('temporal_extrema', BMW, YEAR, capability='peak'),
    expect('lookup', BMW, OCT),
    expect('diagnostic_search', BMW, OCT, [], SEP, capability='dimension_search'),
    expect('diagnostic_search', VOLVO, OCT, [], SEP, capability='dimension_search'),
    expect('joint_share', {}, OCT, ['marca'], capability='joint_share', entities=['BMW', 'VOLVO']),
    expect('ranking', TV, OCT, ['anunciante'], dimension='anunciante'),
    expect('ranking', TV, NEXT_YEAR, ['anunciante'], dimension='anunciante'),
    expect('diagnostic_search', BMW, OCT, [], SEP, capability='dimension_search'),
    expect('diagnostic', BMW, OCT, ['vehiculo'], SEP, capability='comparison', dimension='vehiculo'),
]
