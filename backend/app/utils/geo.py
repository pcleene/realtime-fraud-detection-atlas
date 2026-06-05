from math import radians, sin, cos, sqrt, atan2

# Earth radius in kilometers
EARTH_RADIUS_KM = 6371.0088


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Pure Python Haversine formula.
    Earth radius: 6371.0088 km
    Returns distance in kilometers.

    Args:
        lon1: Longitude of first point (degrees)
        lat1: Latitude of first point (degrees)
        lon2: Longitude of second point (degrees)
        lat2: Latitude of second point (degrees)

    Returns:
        Distance in kilometers
    """
    # Convert to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return EARTH_RADIUS_KM * c


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Pure Python Haversine formula.
    Returns distance in meters.
    """
    return haversine_km(lon1, lat1, lon2, lat2) * 1000
