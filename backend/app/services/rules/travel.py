from datetime import datetime
from typing import Optional, Tuple

from app.config import get_settings
from app.models.customer import GeoPoint
from app.models.transaction import RuleAnalysis
from app.utils.geo import haversine_km


def check_impossible_travel(
    latest_location: Optional[GeoPoint],
    current_lon: Optional[float],
    current_lat: Optional[float],
    delta_seconds: Optional[float],
) -> RuleAnalysis:
    """
    Impossible travel check - detects physically impossible location changes.

    Args:
        latest_location: Customer's last transaction location
        current_lon: Current transaction longitude
        current_lat: Current transaction latitude
        delta_seconds: Seconds since last transaction

    Returns:
        RuleAnalysis with impossible travel check results
    """
    settings = get_settings()
    threshold_kmh = settings.impossible_travel_kmh

    # No location data available
    if (
        latest_location is None
        or current_lon is None
        or current_lat is None
        or delta_seconds is None
        or delta_seconds <= 0
    ):
        return RuleAnalysis(
            rule="impossible_travel",
            score=0,
            triggered=False,
            details={
                "distance_km": None,
                "time_hours": None,
                "speed_kmh": None,
                "threshold_kmh": threshold_kmh,
            },
        )

    # Calculate distance
    prev_lon = latest_location.coordinates[0]
    prev_lat = latest_location.coordinates[1]
    distance_km = haversine_km(prev_lon, prev_lat, current_lon, current_lat)

    # Calculate implied speed
    delta_hours = delta_seconds / 3600
    speed_kmh = distance_km / delta_hours if delta_hours > 0 else 0

    if speed_kmh > threshold_kmh:
        return RuleAnalysis(
            rule="impossible_travel",
            score=settings.weight_impossible_travel,
            triggered=True,
            details={
                "distance_km": round(distance_km, 2),
                "time_hours": round(delta_hours, 4),
                "speed_kmh": round(speed_kmh, 2),
                "threshold_kmh": threshold_kmh,
            },
        )

    return RuleAnalysis(
        rule="impossible_travel",
        score=0,
        triggered=False,
        details={
            "distance_km": round(distance_km, 2),
            "time_hours": round(delta_hours, 4),
            "speed_kmh": round(speed_kmh, 2),
            "threshold_kmh": threshold_kmh,
        },
    )
