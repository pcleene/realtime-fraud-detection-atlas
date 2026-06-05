"""Tests for V2 velocity rules (var_8, 10, 13, 24, 26)."""

import pytest
from datetime import datetime, timedelta

from app.services.rules.velocity import (
    check_var_8, check_var_10, check_var_13, check_var_24, check_var_26,
)


class TestVar8:
    def test_triggered_rapid_transaction(self):
        now = datetime.utcnow()
        prev = now - timedelta(seconds=5)
        result = check_var_8(now, prev, threshold_seconds=10, weight=8)
        assert result.triggered is True
        assert result.score == 8

    def test_not_triggered_normal_gap(self):
        now = datetime.utcnow()
        prev = now - timedelta(seconds=30)
        result = check_var_8(now, prev, threshold_seconds=10, weight=8)
        assert result.triggered is False
        assert result.score == 0

    def test_no_previous_transaction(self):
        result = check_var_8(datetime.utcnow(), None, threshold_seconds=10, weight=8)
        assert result.triggered is False


class TestVar10:
    def test_triggered_same_day(self):
        now = datetime.utcnow()
        prev = now - timedelta(hours=12)
        result = check_var_10(now, prev, threshold_days=1, weight=5)
        assert result.triggered is True

    def test_not_triggered_different_day(self):
        now = datetime.utcnow()
        prev = now - timedelta(days=2)
        result = check_var_10(now, prev, threshold_days=1, weight=5)
        assert result.triggered is False

    def test_no_previous(self):
        result = check_var_10(datetime.utcnow(), None, threshold_days=1, weight=5)
        assert result.triggered is False


class TestVar13:
    def test_triggered_unusual_hour(self):
        # Transaction at 3 AM, typical range 8-20
        z1 = datetime(2024, 1, 15, 3, 0, 0)
        result = check_var_13(z1, z3=8, z4=20, weight=5)
        assert result.triggered is True

    def test_not_triggered_normal_hour(self):
        z1 = datetime(2024, 1, 15, 12, 0, 0)
        result = check_var_13(z1, z3=8, z4=20, weight=5)
        assert result.triggered is False

    def test_no_typical_hours(self):
        result = check_var_13(datetime.utcnow(), z3=None, z4=None, weight=5)
        assert result.triggered is False


class TestVar24:
    def test_triggered_recent_card_change(self):
        now = datetime.utcnow()
        card_change = now - timedelta(hours=12)
        result = check_var_24(now, card_change, window_hours=24, weight=8)
        assert result.triggered is True

    def test_not_triggered_old_card_change(self):
        now = datetime.utcnow()
        card_change = now - timedelta(days=7)
        result = check_var_24(now, card_change, window_hours=24, weight=8)
        assert result.triggered is False

    def test_no_card_change(self):
        result = check_var_24(datetime.utcnow(), None, window_hours=24, weight=8)
        assert result.triggered is False


class TestVar26:
    def test_triggered_recent_provisioning(self):
        now = datetime.utcnow()
        prov = now - timedelta(hours=12)
        result = check_var_26(now, prov, window_hours=24, weight=8)
        assert result.triggered is True

    def test_not_triggered_old_provisioning(self):
        now = datetime.utcnow()
        prov = now - timedelta(days=7)
        result = check_var_26(now, prov, window_hours=24, weight=8)
        assert result.triggered is False

    def test_no_provisioning(self):
        result = check_var_26(datetime.utcnow(), None, window_hours=24, weight=8)
        assert result.triggered is False
