---
name: haversine-geo-calculations
description: Calculate distances between geographic coordinates using the Haversine formula. Use this skill when implementing location-based features like fraud detection (impossible travel), geofencing, proximity searches, delivery distance calculations, or any feature that needs to determine distance between two lat/lon points without database queries.
---

# Haversine Distance Calculations

The Haversine formula calculates the great-circle distance between two points on a sphere given their latitude and longitude coordinates.

## Why Use Haversine In-App?

- **Speed**: ~0.01ms per calculation (pure CPU)
- **No I/O**: No database round-trips
- **Scalability**: Works in any worker without shared state
- **Caching**: Calculate distances on cached data instead of querying

**Performance comparison**:
| Method | Latency | Notes |
|--------|---------|-------|
| In-app Haversine | 0.01ms | Pure CPU |
| MongoDB $nearSphere | 1-200ms | Network I/O |
| PostGIS ST_Distance | 1-50ms | Network I/O |

## Pure Python Implementation

```python
from math import radians, sin, cos, sqrt, atan2

# Earth radius in kilometers (WGS84 mean radius)
EARTH_RADIUS_KM = 6371.0088


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Calculate great-circle distance between two points using Haversine formula.

    Args:
        lon1: Longitude of first point (degrees)
        lat1: Latitude of first point (degrees)
        lon2: Longitude of second point (degrees)
        lat2: Latitude of second point (degrees)

    Returns:
        Distance in kilometers
    """
    # Convert degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return EARTH_RADIUS_KM * c


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Calculate distance in meters.

    Args:
        lon1, lat1: First point coordinates (degrees)
        lon2, lat2: Second point coordinates (degrees)

    Returns:
        Distance in meters
    """
    return haversine_km(lon1, lat1, lon2, lat2) * 1000
```

## Use Case: Impossible Travel Detection

Detect if a user traveled impossibly fast between transactions:

```python
from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class GeoPoint:
    """Geographic point with coordinates."""
    type: str = "Point"
    coordinates: list = None  # [longitude, latitude]

    @classmethod
    def from_coords(cls, lon: float, lat: float):
        return cls(type="Point", coordinates=[lon, lat])


def check_impossible_travel(
    previous_location: Optional[GeoPoint],
    current_lon: Optional[float],
    current_lat: Optional[float],
    delta_seconds: Optional[float],
    max_speed_kmh: float = 800.0,  # Commercial jet speed
) -> dict:
    """
    Check if travel between two points is physically impossible.

    Args:
        previous_location: Last known location
        current_lon, current_lat: Current transaction location
        delta_seconds: Time since last transaction
        max_speed_kmh: Maximum plausible travel speed

    Returns:
        Dict with travel analysis results
    """
    # Missing data - can't evaluate
    if (
        previous_location is None
        or current_lon is None
        or current_lat is None
        or delta_seconds is None
        or delta_seconds <= 0
    ):
        return {
            "triggered": False,
            "reason": "insufficient_data",
            "distance_km": None,
            "speed_kmh": None,
        }

    # Calculate distance
    prev_lon = previous_location.coordinates[0]
    prev_lat = previous_location.coordinates[1]
    distance_km = haversine_km(prev_lon, prev_lat, current_lon, current_lat)

    # Calculate implied speed
    delta_hours = delta_seconds / 3600
    speed_kmh = distance_km / delta_hours if delta_hours > 0 else 0

    # Check if speed exceeds maximum
    if speed_kmh > max_speed_kmh:
        return {
            "triggered": True,
            "reason": "impossible_speed",
            "distance_km": round(distance_km, 2),
            "time_hours": round(delta_hours, 4),
            "speed_kmh": round(speed_kmh, 2),
            "max_speed_kmh": max_speed_kmh,
        }

    return {
        "triggered": False,
        "reason": "plausible_travel",
        "distance_km": round(distance_km, 2),
        "time_hours": round(delta_hours, 4),
        "speed_kmh": round(speed_kmh, 2),
        "max_speed_kmh": max_speed_kmh,
    }
```

## Use Case: Proximity Check Against Cached Locations

Check if a point is near any location in a cached list:

```python
from typing import List, Dict, Any, Optional


def check_proximity_in_cache(
    lon: float,
    lat: float,
    locations: List[Dict[str, Any]],
    radius_meters: float,
) -> Optional[Dict[str, Any]]:
    """
    Check if a point is within radius of any cached location.

    Much faster than database query for small location lists (<1000).

    Args:
        lon, lat: Point to check
        locations: List of location dicts with 'coordinates' field
        radius_meters: Maximum distance to consider "nearby"

    Returns:
        First matching location within radius, or None
    """
    for location in locations:
        # Handle GeoJSON format
        coords = location.get("location", {}).get("coordinates", [])
        if len(coords) < 2:
            continue

        loc_lon, loc_lat = coords[0], coords[1]
        distance_m = haversine_m(lon, lat, loc_lon, loc_lat)

        if distance_m <= radius_meters:
            return {
                **location,
                "distance_m": round(distance_m, 2),
            }

    return None


# Example usage with cached blacklist locations
BLACKLIST_CACHE = [
    {"name": "Suspicious ATM 1", "location": {"coordinates": [106.8456, -6.2088]}},
    {"name": "Known fraud hotspot", "location": {"coordinates": [106.8271, -6.1754]}},
]

result = check_proximity_in_cache(
    lon=106.8450,
    lat=-6.2090,
    locations=BLACKLIST_CACHE,
    radius_meters=100,
)
# Returns: {"name": "Suspicious ATM 1", ..., "distance_m": 65.32}
```

## Use Case: Find Nearest Location

```python
def find_nearest(
    lon: float,
    lat: float,
    locations: List[Dict[str, Any]],
    max_results: int = 1,
) -> List[Dict[str, Any]]:
    """
    Find nearest locations sorted by distance.

    Args:
        lon, lat: Reference point
        locations: List of candidate locations
        max_results: Maximum results to return

    Returns:
        List of locations with distance, sorted by nearest first
    """
    results = []

    for location in locations:
        coords = location.get("location", {}).get("coordinates", [])
        if len(coords) < 2:
            continue

        distance_m = haversine_m(lon, lat, coords[0], coords[1])
        results.append({
            **location,
            "distance_m": round(distance_m, 2),
        })

    # Sort by distance
    results.sort(key=lambda x: x["distance_m"])

    return results[:max_results]
```

## Use Case: Geofence Check

```python
def is_within_geofence(
    lon: float,
    lat: float,
    center_lon: float,
    center_lat: float,
    radius_meters: float,
) -> bool:
    """
    Check if a point is within a circular geofence.

    Args:
        lon, lat: Point to check
        center_lon, center_lat: Geofence center
        radius_meters: Geofence radius

    Returns:
        True if point is within geofence
    """
    distance = haversine_m(lon, lat, center_lon, center_lat)
    return distance <= radius_meters


# Example: Check if transaction is within expected service area
is_valid = is_within_geofence(
    lon=106.8456,
    lat=-6.2088,
    center_lon=106.8271,  # Jakarta center
    center_lat=-6.1754,
    radius_meters=50000,  # 50km radius
)
```

## Distance Reference Table

| Distance (km) | Example |
|---------------|---------|
| 0.1 | City block |
| 1 | Neighborhood |
| 10 | City district |
| 100 | Between cities |
| 1,000 | Between countries |
| 10,000 | Between continents |

## Speed Reference Table

| Speed (km/h) | Transport |
|--------------|-----------|
| 5 | Walking |
| 30 | Urban driving |
| 120 | Highway driving |
| 300 | High-speed train |
| 800 | Commercial aircraft |
| 1,000 | Private jet (aggressive threshold) |

## Common Mistakes

1. **Swapping lat/lon order**:
   ```python
   # Wrong - GeoJSON uses [lon, lat]
   haversine_km(lat1, lon1, lat2, lon2)

   # Correct
   haversine_km(lon1, lat1, lon2, lat2)
   ```

2. **Forgetting to convert from degrees**:
   ```python
   # The formula internally converts to radians
   # Always pass degrees, not radians
   ```

3. **Using Euclidean distance for geographic coordinates**:
   ```python
   # Wrong - doesn't account for Earth's curvature
   distance = sqrt((lon2-lon1)**2 + (lat2-lat1)**2)

   # Correct - uses Haversine
   distance = haversine_km(lon1, lat1, lon2, lat2)
   ```

4. **Querying database for small proximity checks**:
   ```python
   # Slow - network I/O for each check
   await db.locations.find_one({"location": {"$nearSphere": ...}})

   # Fast - in-memory calculation
   check_proximity_in_cache(lon, lat, cached_locations, radius_m)
   ```

## When to Use Database vs In-App

| Scenario | Use | Reason |
|----------|-----|--------|
| Check against <1000 cached points | In-app Haversine | No I/O, ~0.3ms for 30 checks |
| Search millions of locations | Database $nearSphere | Indexed query, O(log n) |
| Real-time speed check | In-app Haversine | Sub-millisecond response |
| Find nearest from large dataset | Database with index | Efficient spatial index |
