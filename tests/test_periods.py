from datetime import date
import pytest
from src.agent.periods import resolve_period, equivalent_periods, coverage, window

AVAILABLE = {'start': '2019-01-01', 'end': '2026-07-31'}


def test_year_requested_is_distinct_from_partial_coverage():
    requested = resolve_period({'kind': 'year', 'year': 2026}, today=date(2026, 9, 10))
    result = coverage(requested, AVAILABLE, {'start': '2026-01-01', 'end': '2026-07-01'})
    assert result['is_partial'] and result['effective_period']['end'] == '2026-07-31'
    assert result['requested_period']['end'] == '2026-12-31'


def test_ytd_versus_ytd_uses_last_available_day():
    a, b = equivalent_periods(window('2026-01-01', '2026-12-31'), window('2025-01-01', '2025-12-31'), AVAILABLE)
    assert a == window('2026-01-01', '2026-07-31')
    assert b == window('2025-01-01', '2025-07-31')


def test_ytd_alignment_works_in_reverse_order():
    a, b = equivalent_periods(window('2025-01-01', '2025-12-31'), window('2026-01-01', '2026-12-31'), AVAILABLE)
    assert a['end'] == '2025-07-31' and b['end'] == '2026-07-31'


def test_leap_day_comparison():
    a, b = equivalent_periods(window('2024-01-01', '2024-12-31'), window('2023-01-01', '2023-12-31'), {'start': '2020-01-01', 'end': '2024-02-29'})
    assert a['end'] == '2024-02-29' and b['end'] == '2023-02-28'


def test_calendar_months_can_have_different_lengths():
    a, b = equivalent_periods(window('2025-02-01', '2025-02-28'), window('2025-01-01', '2025-01-31'), AVAILABLE)
    assert a['end'] == '2025-02-28' and b['end'] == '2025-01-31'


@pytest.mark.parametrize('kind,expected', [('ytd', ('2026-01-01', '2026-07-31')), ('recent_months', ('2026-02-01', '2026-07-31')),
                                         ('current_month', ('2026-07-01', '2026-07-31')), ('previous_month', ('2026-06-01', '2026-06-30'))])
def test_relative_periods_use_available_cutoff(kind, expected):
    assert resolve_period({'kind': kind}, today=date(2026, 9, 10), available=AVAILABLE) == window(*expected)


def test_invalid_and_uncovered_periods_are_rejected():
    with pytest.raises(ValueError): window('2026-03-01', '2026-02-01')
    with pytest.raises(ValueError): equivalent_periods(window('2030-01-01', '2030-12-31'), window('2029-01-01', '2029-12-31'), AVAILABLE)
    with pytest.raises(ValueError): equivalent_periods(window('2025-01-01', '2025-12-31'), window('2024-01-01', '2024-01-31'), AVAILABLE)


def test_peak_requires_computed_evidence():
    with pytest.raises(ValueError): resolve_period({'kind': 'peak'}, today=date(2026, 9, 10))
    assert resolve_period({'kind': 'peak'}, today=date(2026, 9, 10), peak={'period': '2025-11-01', 'granularity': 'month'}) == window('2025-11-01', '2025-11-30')
