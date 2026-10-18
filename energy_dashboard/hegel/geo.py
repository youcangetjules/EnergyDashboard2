"""Distances on the Earth for a pod circle. No map library."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000.0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (WGS 84 sphere)."""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lam = radians(lon2 - lon1)
    a = sin(d_phi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(d_lam / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * asin(sqrt(min(1.0, a)))


def in_radius(
    lat: float,
    lon: float,
    centre_lat: float,
    centre_lon: float,
    radius_km: float,
) -> bool:
    return distance_m(lat, lon, centre_lat, centre_lon) <= radius_km * 1000.0


def coord_key(lat: float, lon: float) -> tuple[float, float]:
    """Round to about one metre so identical published pins compare equal."""
    return (round(lat, 5), round(lon, 5))
