"""Coordinate helpers.

Garmin stores positions in a "semicircle" integer encoding, not decimal degrees.
The standard conversion is:

    degrees = semicircles * (180 / 2**31)

The exact format used by the *golf* export has caused community confusion, so the
POC must convert one shot and verify it lands on the correct hole on a satellite
map before trusting the whole dataset (see SPEC §7).
"""

from __future__ import annotations

import math

_SEMICIRCLE_TO_DEGREES = 180.0 / 2**31

_EARTH_RADIUS_M = 6_371_000.0
METERS_TO_YARDS = 1.09361
METERS_TO_FEET = 3.28084


def semicircles_to_degrees(semicircles: float) -> float:
    """Convert a single Garmin semicircle integer to decimal degrees."""
    return semicircles * _SEMICIRCLE_TO_DEGREES


def latlon_from_semicircles(lat_sc: float, lon_sc: float) -> tuple[float, float]:
    """Convert a (lat, lon) semicircle pair to decimal degrees."""
    return semicircles_to_degrees(lat_sc), semicircles_to_degrees(lon_sc)


def looks_like_semicircles(value: float) -> bool:
    """Heuristic: semicircle-encoded lat/lon are large integers (|v| up to 2**31).

    Decimal-degree coordinates fall in [-180, 180]. If a coordinate's magnitude is
    far outside that range it is almost certainly semicircle-encoded. Use this only
    as a hint while exploring the raw data — confirm against a map.
    """
    return abs(value) > 360


Point = tuple[float, float]  # (lat, lon) in decimal degrees


def haversine_meters(a: Point, b: Point) -> float:
    """Great-circle distance between two decimal-degree points, in meters."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))


def haversine_yards(a: Point, b: Point) -> float:
    return haversine_meters(a, b) * METERS_TO_YARDS


def _local_offsets(origin: Point, pt: Point) -> tuple[float, float]:
    """East/north meters of ``pt`` relative to ``origin`` (small-area flat projection)."""
    k = math.cos(math.radians(origin[0]))
    east = math.radians(pt[1] - origin[1]) * _EARTH_RADIUS_M * k
    north = math.radians(pt[0] - origin[0]) * _EARTH_RADIUS_M
    return east, north


def shot_geometry(start: Point, end: Point, pin: Point, side_threshold_yd: float = 5.0) -> dict:
    """Classify a shot's outcome relative to the pin.

    Decomposes the shot into along-track (toward the pin) and cross-track (lateral)
    components, so we can say short/long and left/right — the "was this a good shot
    for the task" signal the coach asked for.

    Returns: range ('short'|'long'), side ('left'|'right'|'straight'),
    lateralYds, remainingYds (end→pin), and toPinBeforeYds (start→pin).
    """
    tx, ty = _local_offsets(start, pin)   # start -> pin (target line)
    sx, sy = _local_offsets(start, end)   # start -> end (actual)
    target_len = math.hypot(tx, ty)
    remaining = haversine_yards(end, pin)
    before = haversine_yards(start, pin)
    if target_len == 0:
        return {"range": None, "side": None, "lateralYds": None,
                "remainingYds": round(remaining, 1), "toPinBeforeYds": round(before, 1)}
    ux, uy = tx / target_len, ty / target_len
    along = sx * ux + sy * uy                 # progress toward pin (m)
    cross = sx * uy - sy * ux                  # +right / -left of target line (m)
    lateral_yd = abs(cross) * METERS_TO_YARDS
    side = "straight"
    if lateral_yd >= side_threshold_yd:
        side = "right" if cross > 0 else "left"
    return {
        "range": "long" if along > target_len else "short",
        "side": side,
        "lateralYds": round(lateral_yd, 1),
        "remainingYds": round(remaining, 1),
        "toPinBeforeYds": round(before, 1),
    }
