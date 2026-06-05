"""Fraud scoring package — re-exports the main service class."""

from app.services.fraud.service import FraudScoringServiceV2

__all__ = ["FraudScoringServiceV2"]
