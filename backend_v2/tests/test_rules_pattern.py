"""Tests for V2 pattern rules (var_30, 31)."""

import pytest

from app.services.rules.pattern import check_var_30, check_var_31


class TestVar30:
    def test_triggered_repetitive(self):
        result = check_var_30(tp=300, tp_recent=[300, 300, 300], weight=3)
        assert result.triggered is True

    def test_not_triggered_varied(self):
        result = check_var_30(tp=300, tp_recent=[0, 55555, 300], weight=3)
        assert result.triggered is False

    def test_empty_recent(self):
        result = check_var_30(tp=300, tp_recent=[], weight=3)
        assert result.triggered is False


class TestVar31:
    def test_triggered_low_ratio(self):
        # Very small amount for a purpose code
        result = check_var_31(tp=300, at3=50, ratio_threshold=0.01, weight=3)
        assert result.triggered is True

    def test_not_triggered_normal_ratio(self):
        result = check_var_31(tp=300, at3=500_000, ratio_threshold=0.01, weight=3)
        assert result.triggered is False

    def test_zero_purpose(self):
        result = check_var_31(tp=0, at3=500_000, ratio_threshold=0.01, weight=3)
        assert result.triggered is False
