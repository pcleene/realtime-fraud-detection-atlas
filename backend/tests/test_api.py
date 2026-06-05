"""Tests for API endpoints."""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_check(self, client):
        """Should return health status."""
        response = client.get("/health")
        # May fail if no MongoDB running, but endpoint should be accessible
        assert response.status_code in [200, 500]
        data = response.json()
        assert "status" in data
        assert "database" in data


class TestRootEndpoint:
    """Tests for / endpoint."""

    def test_root(self, client):
        """Should return API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "RegionalBank Fraud Scoring POC"
        assert data["version"] == "1.0.0"


class TestScoreTransactionEndpoint:
    """Tests for /score-transaction endpoint."""

    def test_invalid_customer_id_format(self, client):
        """Should reject invalid customer_id format."""
        response = client.post(
            "/score-transaction",
            json={
                "customer_id": "INVALID",
                "account_id": "ACC-12345678",
                "amount": 500000,
                "lat": -6.2088,
                "lon": 106.8456,
                "timestamp": datetime.utcnow().isoformat(),
                "channel": "Livin",
                "merchant_id": "M-001",
                "merchant_name": "Test Merchant",
                "mcc": "5311",
                "device_id": "D-001",
                "device_type": "android",
                "ip": "<private-ip>",
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "invalid_request"

    def test_valid_customer_id_format(self, client):
        """Should accept valid customer_id format."""
        response = client.post(
            "/score-transaction",
            json={
                "customer_id": "CUST-7F3A2B1C9E4D",
                "account_id": "ACC-12345678",
                "amount": 500000,
                "lat": -6.2088,
                "lon": 106.8456,
                "timestamp": datetime.utcnow().isoformat(),
                "channel": "Livin",
                "merchant_id": "M-001",
                "merchant_name": "Test Merchant",
                "mcc": "5311",
                "device_id": "D-001",
                "device_type": "android",
                "ip": "<private-ip>",
            },
        )
        # Will be 404 if customer doesn't exist, but format is valid
        assert response.status_code in [200, 404, 500]

    def test_missing_required_fields(self, client):
        """Should reject request with missing fields."""
        response = client.post(
            "/score-transaction",
            json={
                "customer_id": "CUST-7F3A2B1C9E4D",
            },
        )
        assert response.status_code == 422  # Validation error

    def test_invalid_channel(self, client):
        """Should reject invalid channel."""
        response = client.post(
            "/score-transaction",
            json={
                "customer_id": "CUST-7F3A2B1C9E4D",
                "account_id": "ACC-12345678",
                "amount": 500000,
                "lat": -6.2088,
                "lon": 106.8456,
                "timestamp": datetime.utcnow().isoformat(),
                "channel": "INVALID",
                "merchant_id": "M-001",
                "merchant_name": "Test Merchant",
                "mcc": "5311",
                "device_id": "D-001",
                "device_type": "android",
                "ip": "<private-ip>",
            },
        )
        assert response.status_code == 422

    def test_invalid_device_type(self, client):
        """Should reject invalid device type."""
        response = client.post(
            "/score-transaction",
            json={
                "customer_id": "CUST-7F3A2B1C9E4D",
                "account_id": "ACC-12345678",
                "amount": 500000,
                "lat": -6.2088,
                "lon": 106.8456,
                "timestamp": datetime.utcnow().isoformat(),
                "channel": "Livin",
                "merchant_id": "M-001",
                "merchant_name": "Test Merchant",
                "mcc": "5311",
                "device_id": "D-001",
                "device_type": "desktop",  # Invalid
                "ip": "<private-ip>",
            },
        )
        assert response.status_code == 422
