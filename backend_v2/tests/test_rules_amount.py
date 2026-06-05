"""Tests for V2 amount rules (var_12, 14, 15, 16, 17, 18, 19, 20, 21, 28, 29)."""

import pytest
from datetime import datetime, timedelta

from app.services.rules.amount import (
    check_var_12, check_var_14, check_var_15, check_var_16, check_var_17,
    check_var_18, check_var_19, check_var_20, check_var_21,
    check_var_28, check_var_29,
)


class TestVar12:
    def test_triggered_near_limit(self):
        limits = {5: 10_000_000}
        result = check_var_12(at3=9_000_000, service=5, service_limits=limits, ratio_threshold=0.80, weight=5)
        assert result.triggered is True

    def test_not_triggered_below_ratio(self):
        limits = {5: 10_000_000}
        result = check_var_12(at3=5_000_000, service=5, service_limits=limits, ratio_threshold=0.80, weight=5)
        assert result.triggered is False

    def test_no_limit_configured(self):
        result = check_var_12(at3=5_000_000, service=99, service_limits={}, ratio_threshold=0.80, weight=5)
        assert result.triggered is False


class TestVar14:
    def test_triggered_above_upper(self):
        bounds = {5: (100_000, 2_000_000)}
        result = check_var_14(at3=3_000_000, service=5, avg_bounds=bounds, weight=5)
        assert result.triggered is True

    def test_triggered_below_lower(self):
        bounds = {5: (100_000, 2_000_000)}
        result = check_var_14(at3=50_000, service=5, avg_bounds=bounds, weight=5)
        assert result.triggered is True

    def test_not_triggered_within_bounds(self):
        bounds = {5: (100_000, 2_000_000)}
        result = check_var_14(at3=500_000, service=5, avg_bounds=bounds, weight=5)
        assert result.triggered is False


class TestVar15:
    def test_triggered_high_ratio(self):
        result = check_var_15(at3=800_000, bl=1_000_000, threshold=0.50, weight=8)
        assert result.triggered is True

    def test_not_triggered_low_ratio(self):
        result = check_var_15(at3=200_000, bl=1_000_000, threshold=0.50, weight=8)
        assert result.triggered is False

    def test_no_balance(self):
        result = check_var_15(at3=200_000, bl=None, threshold=0.50, weight=8)
        assert result.triggered is False


class TestVar16:
    def test_triggered_repetitive(self):
        result = check_var_16(at3=500_000, at3_recent=[500_000, 500_000, 500_000], weight=5)
        assert result.triggered is True

    def test_not_triggered_varied(self):
        result = check_var_16(at3=500_000, at3_recent=[100_000, 200_000, 300_000], weight=5)
        assert result.triggered is False

    def test_empty_recent(self):
        result = check_var_16(at3=500_000, at3_recent=[], weight=5)
        assert result.triggered is False


class TestVar17:
    def test_triggered_spike(self):
        result = check_var_17(at3=5_000_000, at3_prev=500_000, spike_ratio=5.0, weight=5)
        assert result.triggered is True

    def test_not_triggered_normal(self):
        result = check_var_17(at3=600_000, at3_prev=500_000, spike_ratio=5.0, weight=5)
        assert result.triggered is False

    def test_no_previous(self):
        result = check_var_17(at3=5_000_000, at3_prev=None, spike_ratio=5.0, weight=5)
        assert result.triggered is False


class TestVar18:
    def test_triggered_cumulative_high(self):
        result = check_var_18(at3=500_000, at3_sum=4_000_000, bl=5_000_000, balance_ratio=0.50, weight=8)
        assert result.triggered is True

    def test_not_triggered(self):
        result = check_var_18(at3=100_000, at3_sum=500_000, bl=5_000_000, balance_ratio=0.50, weight=8)
        assert result.triggered is False


class TestVar19:
    def test_triggered_post_prov(self):
        now = datetime.utcnow()
        prov = now - timedelta(hours=12)
        result = check_var_19(at3=500_000, at3_sum=4_000_000, bl=5_000_000,
                              pt_latest=prov, z1=now, prov_hours=48, balance_ratio=0.50, weight=8)
        assert result.triggered is True

    def test_not_triggered_no_prov(self):
        result = check_var_19(at3=500_000, at3_sum=4_000_000, bl=5_000_000,
                              pt_latest=None, z1=datetime.utcnow(), prov_hours=48, balance_ratio=0.50, weight=8)
        assert result.triggered is False


class TestVar20:
    def test_triggered_exact_repeat(self):
        result = check_var_20(at3=500_000, at3_recent=[500_000, 500_000, 500_000, 200_000], repeat_count=3, weight=5)
        assert result.triggered is True
        assert result.details["repeat_count"] == 4  # 3 historical + 1 current

    def test_triggered_includes_current(self):
        # 2 historical + 1 current = 3 total, should trigger at repeat_count=3
        result = check_var_20(at3=500_000, at3_recent=[500_000, 500_000], repeat_count=3, weight=5)
        assert result.triggered is True
        assert result.details["repeat_count"] == 3

    def test_not_triggered(self):
        # 1 historical + 1 current = 2 total, not enough for repeat_count=3
        result = check_var_20(at3=500_000, at3_recent=[500_000, 200_000, 300_000], repeat_count=3, weight=5)
        assert result.triggered is False
        assert result.details["repeat_count"] == 2


class TestVar21:
    def test_triggered_drop(self):
        result = check_var_21(at3=40_000, at3_prev=500_000, drop_ratio=0.10, weight=3)
        assert result.triggered is True

    def test_not_triggered_normal(self):
        result = check_var_21(at3=400_000, at3_prev=500_000, drop_ratio=0.10, weight=3)
        assert result.triggered is False


class TestVar28:
    def test_triggered_high_volatility(self):
        result = check_var_28(at6=1_500_000, av1=1_000_000, weight=5)
        assert result.triggered is True

    def test_not_triggered(self):
        result = check_var_28(at6=500_000, av1=1_000_000, weight=5)
        assert result.triggered is False

    def test_no_threshold(self):
        result = check_var_28(at6=500_000, av1=None, weight=5)
        assert result.triggered is False


class TestVar29:
    def test_triggered(self):
        result = check_var_29(at3_sum=60_000_000, av2=50_000_000, weight=5)
        assert result.triggered is True

    def test_not_triggered(self):
        result = check_var_29(at3_sum=30_000_000, av2=50_000_000, weight=5)
        assert result.triggered is False
