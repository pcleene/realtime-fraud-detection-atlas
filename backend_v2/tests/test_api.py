"""API endpoint tests for V2."""

import pytest
from datetime import datetime


class TestScoreTransactionValidation:
    """Test input validation for /score-transaction (no DB required)."""

    def test_invalid_customer_id_format(self):
        """Customer ID must match CUST-{hex12} pattern."""
        from app.routes.score import CUSTOMER_ID_PATTERN
        assert CUSTOMER_ID_PATTERN.match("CUST-AABBCCDDEE11") is not None
        assert CUSTOMER_ID_PATTERN.match("CUST-aabbccddeeff") is not None
        assert CUSTOMER_ID_PATTERN.match("INVALID-ID") is None
        assert CUSTOMER_ID_PATTERN.match("CUST-SHORT") is None
        assert CUSTOMER_ID_PATTERN.match("CUST-TOOLONGSTRING123") is None

    def test_customer_id_exact_length(self):
        from app.routes.score import CUSTOMER_ID_PATTERN
        # Exactly 12 hex chars
        assert CUSTOMER_ID_PATTERN.match("CUST-123456789ABC") is not None
        # 11 hex chars
        assert CUSTOMER_ID_PATTERN.match("CUST-123456789AB") is None
        # 13 hex chars
        assert CUSTOMER_ID_PATTERN.match("CUST-123456789ABCD") is None


class TestRequestModel:
    def test_score_request_defaults(self):
        from app.models.requests import ScoreTransactionRequest
        req = ScoreTransactionRequest(
            customer_id="CUST-AABBCCDDEEFF",
            b2="1234567890",
            at3=500_000,
            service=5,
            service_name="Y",
            z1=datetime.utcnow(),
        )
        assert req.tp == 0
        assert req.at7 == 0
        assert req.is_financial == 1
        assert req.lat is None
        assert req.lon is None

    def test_score_request_all_fields(self):
        from app.models.requests import ScoreTransactionRequest
        req = ScoreTransactionRequest(
            customer_id="CUST-AABBCCDDEEFF",
            b1="9876543210",
            b2="1234567890",
            c2="BENEFICIARY",
            d2="BCA",
            n2="Merchant Name",
            at3=500_000,
            tp=300,
            at7=1000,
            service=5,
            service_name="Y",
            z1=datetime.utcnow(),
            h1="samsung SM-A546B",
            is_financial=1,
            channel="Livin",
            lat=-6.2,
            lon=106.8,
        )
        assert req.at3 == 500_000
        assert req.channel == "Livin"


class TestHealthEndpoint:
    def test_health_response_model(self):
        from app.models.requests import HealthResponse, ShardingStatus
        resp = HealthResponse(
            status="healthy",
            database="connected",
            sharding=ShardingStatus(enabled=False, shards=0),
            collections={},
            indexes="verified",
        )
        assert resp.status == "healthy"


class TestMockEndpoint:
    def test_mock_constants(self):
        from app.routes.mock import SERVICE_CODES, DESTINATION_BANKS
        assert len(SERVICE_CODES) > 0
        assert "RegionalBank" in DESTINATION_BANKS
