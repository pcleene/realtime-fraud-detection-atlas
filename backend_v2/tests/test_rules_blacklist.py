"""Tests for V2 blacklist rules (var_1, 2, 3, 4, 5, 6, 7, 23, 25)."""

import pytest
from datetime import datetime, timedelta

from app.cache import BlacklistCache
from app.services.rules.blacklist import (
    check_var_1, check_var_2, check_var_3, check_var_4,
    check_var_5, check_var_6, check_var_7, check_var_23, check_var_25,
)


@pytest.fixture
def cache():
    c = BlacklistCache()
    c.dest_accounts = {"BLACKLISTED-ACCT-001", "BLACKLISTED-ACCT-002"}
    c.fraud_cascade = {
        "CASCADE-ACCT-001": {
            "b23": "CASCADE-ACCT-001",
            "customer_id": "CUST-AAAA00000001",
            "z1": datetime.utcnow() - timedelta(hours=12),
        },
    }
    c.suspicious_merchants = {"suspicious-shop-001", "fraud-mart-002"}
    c.gambling_accounts = {"GAMBLING-ACCT-001"}
    c.watchlist_accounts = {"WATCHLIST-ACCT-001"}
    return c


class TestVar1:
    def test_triggered(self, cache):
        result = check_var_1("BLACKLISTED-ACCT-001", cache, weight=15)
        assert result.triggered is True
        assert result.score == 15

    def test_not_triggered(self, cache):
        result = check_var_1("CLEAN-ACCT-001", cache, weight=15)
        assert result.triggered is False
        assert result.score == 0


class TestVar2:
    def test_triggered_within_window(self, cache):
        result = check_var_2(
            "CUST-AAAA00000001", "CASCADE-ACCT-001",
            datetime.utcnow(), cache, cascade_hours=24, weight=15,
        )
        assert result.triggered is True

    def test_not_triggered_different_customer(self, cache):
        result = check_var_2(
            "CUST-DIFFERENT", "CASCADE-ACCT-001",
            datetime.utcnow(), cache, cascade_hours=24, weight=15,
        )
        assert result.triggered is False

    def test_not_triggered_not_in_cascade(self, cache):
        result = check_var_2(
            "CUST-AAAA00000001", "CLEAN-ACCT",
            datetime.utcnow(), cache, cascade_hours=24, weight=15,
        )
        assert result.triggered is False


class TestVar3:
    def test_triggered(self):
        result = check_var_3(True, weight=10)
        assert result.triggered is True

    def test_not_triggered(self):
        result = check_var_3(False, weight=10)
        assert result.triggered is False


class TestVar4:
    def test_triggered(self):
        result = check_var_4(True, weight=5)
        assert result.triggered is True

    def test_not_triggered(self):
        result = check_var_4(False, weight=5)
        assert result.triggered is False


class TestVar5:
    def test_triggered(self, cache):
        result = check_var_5("SUSPICIOUS-SHOP-001", cache, weight=10)
        assert result.triggered is True

    def test_not_triggered(self, cache):
        result = check_var_5("Clean Merchant", cache, weight=10)
        assert result.triggered is False

    def test_none_merchant(self, cache):
        result = check_var_5(None, cache, weight=10)
        assert result.triggered is False


class TestVar6:
    def test_triggered(self, cache):
        result = check_var_6("GAMBLING-ACCT-001", cache, weight=10)
        assert result.triggered is True

    def test_not_triggered(self, cache):
        result = check_var_6("CLEAN-ACCT", cache, weight=10)
        assert result.triggered is False


class TestVar7:
    def test_triggered(self):
        result = check_var_7(True, weight=10)
        assert result.triggered is True

    def test_not_triggered(self):
        result = check_var_7(False, weight=10)
        assert result.triggered is False


class TestVar23:
    def test_triggered(self, cache):
        result = check_var_23("WATCHLIST-ACCT-001", cache, weight=10)
        assert result.triggered is True

    def test_not_triggered(self, cache):
        result = check_var_23("CLEAN-ACCT", cache, weight=10)
        assert result.triggered is False


class TestVar25:
    def test_triggered(self):
        result = check_var_25(True, weight=5)
        assert result.triggered is True

    def test_not_triggered(self):
        result = check_var_25(False, weight=5)
        assert result.triggered is False
