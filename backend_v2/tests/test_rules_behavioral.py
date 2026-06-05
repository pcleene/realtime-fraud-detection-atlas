"""Tests for V2 behavioral rules (var_9, 11, 22)."""

import pytest
from datetime import datetime, timedelta

from app.models.customer import LoanIncoming
from app.services.rules.behavioral import check_var_9, check_var_11, check_var_22


class TestVar9:
    def test_triggered_loan_outflow(self):
        now = datetime.utcnow()
        loans = [
            LoanIncoming(at3=10_000_000, z1=now - timedelta(hours=6), q2="Kredivo"),
        ]
        result = check_var_9(
            at3=8_000_000, z1=now, pot_i_recent=loans,
            loan_window_hours=24, outflow_ratio=0.70, weight=10,
        )
        assert result.triggered is True

    def test_not_triggered_small_outflow(self):
        now = datetime.utcnow()
        loans = [
            LoanIncoming(at3=10_000_000, z1=now - timedelta(hours=6), q2="Kredivo"),
        ]
        result = check_var_9(
            at3=1_000_000, z1=now, pot_i_recent=loans,
            loan_window_hours=24, outflow_ratio=0.70, weight=10,
        )
        assert result.triggered is False

    def test_no_loans(self):
        result = check_var_9(
            at3=1_000_000, z1=datetime.utcnow(), pot_i_recent=[],
            loan_window_hours=24, outflow_ratio=0.70, weight=10,
        )
        assert result.triggered is False


class TestVar11:
    def test_triggered_first_time(self):
        result = check_var_11(service=99, service_ever=[5, 12, 16], weight=3)
        assert result.triggered is True
        assert result.score == 3

    def test_not_triggered_known_service(self):
        result = check_var_11(service=12, service_ever=[5, 12, 16], weight=3)
        assert result.triggered is False


class TestVar22:
    def test_triggered_unknown_beneficiary(self):
        result = check_var_22(
            b2="UNKNOWN-ACCT", b24_list=["KNOWN-1", "KNOWN-2"],
            b24_count=2, embed_limit=500, weight=5,
        )
        assert result.triggered is True

    def test_not_triggered_known(self):
        result = check_var_22(
            b2="KNOWN-1", b24_list=["KNOWN-1", "KNOWN-2"],
            b24_count=2, embed_limit=500, weight=5,
        )
        assert result.triggered is False

    def test_overflow_check_needed(self):
        result = check_var_22(
            b2="UNKNOWN-ACCT", b24_list=["K1", "K2"],
            b24_count=600, embed_limit=500, weight=5,
        )
        assert result.needs_overflow_check is True
