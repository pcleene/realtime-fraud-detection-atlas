"""Tests for fraud scoring service."""

import pytest
from app.services.fraud import calculate_final_score, calculate_risk_level
from app.models.transaction import RuleAnalysis


class TestScoreAggregation:
    """Tests for score aggregation."""

    def test_no_rules_triggered(self):
        """Should return 0 score when no rules triggered."""
        analysis = [
            RuleAnalysis(rule="velocity", score=0, triggered=False, details={}),
            RuleAnalysis(rule="impossible_travel", score=0, triggered=False, details={}),
            RuleAnalysis(rule="blacklist_proximity", score=0, triggered=False, details={}),
            RuleAnalysis(rule="password_frequency", score=0, triggered=False, details={}),
            RuleAnalysis(rule="holiday", score=0, triggered=False, details={}),
        ]
        final_score, risk_level = calculate_final_score(analysis)
        assert final_score == 0
        assert risk_level == "low"

    def test_single_rule_triggered(self):
        """Should sum single rule score."""
        analysis = [
            RuleAnalysis(rule="velocity", score=20, triggered=True, details={}),
            RuleAnalysis(rule="impossible_travel", score=0, triggered=False, details={}),
        ]
        final_score, risk_level = calculate_final_score(analysis)
        assert final_score == 20
        assert risk_level == "low"

    def test_multiple_rules_triggered(self):
        """Should sum multiple rule scores."""
        analysis = [
            RuleAnalysis(rule="velocity", score=20, triggered=True, details={}),
            RuleAnalysis(rule="impossible_travel", score=30, triggered=True, details={}),
            RuleAnalysis(rule="blacklist_proximity", score=35, triggered=True, details={}),
        ]
        final_score, risk_level = calculate_final_score(analysis)
        assert final_score == 85
        assert risk_level == "high"

    def test_score_capped_at_100(self):
        """Should cap score at 100."""
        analysis = [
            RuleAnalysis(rule="velocity", score=30, triggered=True, details={}),
            RuleAnalysis(rule="impossible_travel", score=30, triggered=True, details={}),
            RuleAnalysis(rule="blacklist_proximity", score=35, triggered=True, details={}),
            RuleAnalysis(rule="password_frequency", score=15, triggered=True, details={}),
            RuleAnalysis(rule="holiday", score=10, triggered=True, details={}),
        ]
        final_score, risk_level = calculate_final_score(analysis)
        assert final_score == 100
        assert risk_level == "high"


class TestRiskLevelClassification:
    """Tests for risk level classification."""

    def test_low_risk_threshold(self):
        """Should classify as low risk below medium threshold."""
        assert calculate_risk_level(0) == "low"
        assert calculate_risk_level(20) == "low"
        assert calculate_risk_level(39) == "low"

    def test_medium_risk_threshold(self):
        """Should classify as medium risk at/above medium threshold."""
        assert calculate_risk_level(40) == "medium"
        assert calculate_risk_level(50) == "medium"
        assert calculate_risk_level(69) == "medium"

    def test_high_risk_threshold(self):
        """Should classify as high risk at/above high threshold."""
        assert calculate_risk_level(70) == "high"
        assert calculate_risk_level(85) == "high"
        assert calculate_risk_level(100) == "high"
