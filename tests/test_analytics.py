from decimal import Decimal
import pytest
from src.analytics.calculations import percentage, describe_series, composition_summary, compare


def test_share_uses_full_universe_not_top_n():
    rows = [{'value': 40, 'share_pct': 40}, {'value': 30, 'share_pct': 30}, {'value': 10, 'share_pct': 10}]
    assert composition_summary(rows, total=100)['shown_share_pct'] == 80
    assert composition_summary(rows, total=100)['top3_share_pct'] == 80


def test_decimal_comparison_and_zero_denominator():
    assert compare(Decimal('120'), Decimal('100'))['difference_pct'] == 20
    assert percentage(10, 0) is None and percentage(None, 10) is None


def test_peak_rank_and_share_are_calculated():
    rows = [{'period': f'2025-{m:02}-01', 'value': value} for m, value in enumerate([1, 2, 7], 1)]
    stats = describe_series(rows)
    assert stats['total'] == 10 and stats['peak']['period'] == '2025-03-01'
    assert rows[-1]['rank'] == 1 and rows[-1]['share_of_total_pct'] == 70
    assert stats['first_to_last']['difference'] == 6


def test_anomaly_detection_requires_enough_points_and_preserves_nulls():
    rows = [{'period': str(i), 'value': v} for i, v in enumerate([9, 10, 11, 10, 9, 11, 100, None])]
    stats = describe_series(rows)
    assert stats['observations'] == 7 and stats['anomalies'][0]['value'] == 100
    assert rows[-1]['value'] is None
    assert describe_series(rows[:3])['anomalies'] == []


def test_series_returns_observed_changes_and_dense_ties():
    from src.analytics.calculations import describe_series
    rows = [{'period': '2024-01-01', 'value': 10}, {'period': '2024-02-01', 'value': 20}, {'period': '2024-03-01', 'value': 20}]
    stats = describe_series(rows)
    assert rows[0]['rank'] == 2 and rows[1]['rank'] == rows[2]['rank'] == 1
    assert rows[1]['change_from_previous_observation']['difference'] == 10
    assert rows[1]['change_from_previous_observation']['difference_pct'] == 100
    assert not stats['anomaly_testable']
