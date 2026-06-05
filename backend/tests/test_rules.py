"""Tests for fraud scoring rules."""

import pytest
from datetime import datetime, timedelta

from app.models.customer import GeoPoint
from app.services.rules.velocity import check_velocity
from app.services.rules.travel import check_impossible_travel
from app.services.rules.password import check_password_frequency
from app.utils.geo import haversine_km


class TestVelocityRule:
    """Tests for velocity check rule."""

    def test_no_previous_transaction(self):
        """Should not trigger when no previous transaction."""
        result = check_velocity(None, datetime.utcnow())
        assert not result.triggered
        assert result.score == 0
        assert result.rule == "velocity"

    def test_normal_gap(self):
        """Should not trigger with normal transaction gap."""
        now = datetime.utcnow()
        previous = now - timedelta(hours=1)
        result = check_velocity(previous, now)
        assert not result.triggered
        assert result.score == 0
        assert result.details["delta_seconds"] == 3600.0

    def test_rapid_transaction(self):
        """Should trigger with rapid sequential transactions."""
        now = datetime.utcnow()
        previous = now - timedelta(seconds=5)
        result = check_velocity(previous, now)
        assert result.triggered
        assert result.score == 20  # Default weight
        assert result.details["delta_seconds"] < 10

    def test_boundary_condition(self):
        """Should not trigger at exactly threshold."""
        now = datetime.utcnow()
        previous = now - timedelta(seconds=10)
        result = check_velocity(previous, now)
        assert not result.triggered


class TestImpossibleTravelRule:
    """Tests for impossible travel detection."""

    def test_no_location_data(self):
        """Should not trigger when no location data."""
        result = check_impossible_travel(None, None, None, None)
        assert not result.triggered
        assert result.score == 0

    def test_no_previous_location(self):
        """Should not trigger when no previous location."""
        result = check_impossible_travel(None, 106.8456, -6.2088, 3600)
        assert not result.triggered

    def test_normal_travel(self):
        """Should not trigger with normal travel speed."""
        # Jakarta to Bandung (~150km) in 3 hours = 50 km/h
        prev_location = GeoPoint.from_coords(106.8456, -6.2088)  # Jakarta
        result = check_impossible_travel(
            prev_location,
            107.6191,  # Bandung lon
            -6.9175,  # Bandung lat
            10800,  # 3 hours in seconds
        )
        assert not result.triggered
        assert result.details["speed_kmh"] < 800

    def test_impossible_travel(self):
        """Should trigger with impossible travel speed."""
        # Jakarta to Surabaya (~800km) in 30 minutes = 1600 km/h
        prev_location = GeoPoint.from_coords(106.8456, -6.2088)  # Jakarta
        result = check_impossible_travel(
            prev_location,
            112.7521,  # Surabaya lon
            -7.2575,  # Surabaya lat
            1800,  # 30 minutes in seconds
        )
        assert result.triggered
        assert result.score == 30  # Default weight
        assert result.details["speed_kmh"] > 800

    def test_same_location(self):
        """Should not trigger when staying at same location."""
        prev_location = GeoPoint.from_coords(106.8456, -6.2088)
        result = check_impossible_travel(
            prev_location,
            106.8456,
            -6.2088,
            60,  # 1 minute
        )
        assert not result.triggered
        assert result.details["speed_kmh"] < 1


class TestPasswordFrequencyRule:
    """Tests for password frequency check."""

    def test_no_password_data(self):
        """Should not trigger when no password data."""
        result = check_password_frequency(None)
        assert not result.triggered
        assert result.score == 0

    def test_normal_password_frequency(self):
        """Should not trigger with normal password change frequency."""
        result = check_password_frequency(90.0)  # 90 days average
        assert not result.triggered
        assert result.score == 0

    def test_frequent_password_changes(self):
        """Should trigger with frequent password changes."""
        result = check_password_frequency(5.0)  # 5 days average
        assert result.triggered
        assert result.score == 15  # Default weight

    def test_boundary_condition(self):
        """Should not trigger at exactly threshold."""
        result = check_password_frequency(7.0)  # Exactly 7 days
        assert not result.triggered


class TestHaversine:
    """Tests for haversine distance calculation."""

    def test_same_point(self):
        """Distance between same point should be 0."""
        distance = haversine_km(106.8456, -6.2088, 106.8456, -6.2088)
        assert distance < 0.001

    def test_known_distance(self):
        """Test with known distance (Jakarta to Bandung ~150km)."""
        distance = haversine_km(
            106.8456, -6.2088,  # Jakarta
            107.6191, -6.9175,  # Bandung
        )
        assert 140 < distance < 160  # Approximately 150km

    def test_long_distance(self):
        """Test with long distance (Jakarta to Surabaya ~780km)."""
        distance = haversine_km(
            106.8456, -6.2088,  # Jakarta
            112.7521, -7.2575,  # Surabaya
        )
        assert 750 < distance < 820  # Approximately 780km

    def test_antipodal_points(self):
        """Test with very distant points."""
        distance = haversine_km(0, 0, 180, 0)
        # Half the earth's circumference
        assert 19000 < distance < 21000
