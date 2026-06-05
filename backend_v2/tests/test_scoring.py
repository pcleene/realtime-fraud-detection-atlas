"""Integration tests for V2 scoring -- all 31 rules together."""

import pytest
from datetime import datetime

from app.models.transaction import RuleResult
from app.utils.scoring import calculate_final_score


class TestFinalScoreCalculation:
    def test_no_rules_triggered(self):
        results = [
            RuleResult(rule=f"var_{i}", triggered=False, weight=10, score=0)
            for i in range(1, 5)
        ]
        score, level = calculate_final_score(results)
        assert score == 0
        assert level == "low"

    def test_single_rule_triggered(self):
        results = [
            RuleResult(rule="var_1", triggered=True, weight=15, score=15),
            RuleResult(rule="var_2", triggered=False, weight=15, score=0),
        ]
        score, level = calculate_final_score(results)
        assert score == 15
        assert level == "low"

    def test_medium_risk(self):
        results = [
            RuleResult(rule="var_1", triggered=True, weight=15, score=15),
            RuleResult(rule="var_2", triggered=True, weight=15, score=15),
            RuleResult(rule="var_8", triggered=True, weight=10, score=10),
            RuleResult(rule="var_15", triggered=True, weight=8, score=8),
        ]
        score, level = calculate_final_score(results)
        assert score == 48
        assert level == "medium"

    def test_high_risk(self):
        results = [
            RuleResult(rule="var_1", triggered=True, weight=15, score=15),
            RuleResult(rule="var_2", triggered=True, weight=15, score=15),
            RuleResult(rule="var_6", triggered=True, weight=10, score=10),
            RuleResult(rule="var_8", triggered=True, weight=8, score=8),
            RuleResult(rule="var_15", triggered=True, weight=8, score=8),
            RuleResult(rule="var_18", triggered=True, weight=8, score=8),
            RuleResult(rule="var_23", triggered=True, weight=10, score=10),
        ]
        score, level = calculate_final_score(results)
        assert score == 74
        assert level == "high"

    def test_score_capped_at_100(self):
        # Create results that sum to >100
        results = [
            RuleResult(rule=f"var_{i}", triggered=True, weight=20, score=20)
            for i in range(1, 10)
        ]
        score, level = calculate_final_score(results)
        assert score == 100
        assert level == "high"
