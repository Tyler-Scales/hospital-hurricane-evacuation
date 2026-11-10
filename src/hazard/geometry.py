#!/usr/bin/env python3
"""
Geometry primitives for hospital-storm exposure.

Design note: no polygons, no geopandas. Every exposure question the study asks
reduces to distance-and-bearing arithmetic against quadrant wind radii, which
is both more precise than rasterizing a swath polygon and dependency-free.

  "Was this hospital inside 34-kt winds?"
      -> for each track observation, compute distance and bearing from the
         storm center to the hospital, pick the quadrant the hospital sits in,
         and compare distance to that quadrant's reported radius. Union over
         all track observations.

  "How close did the T-48h forecast put the storm to this hospital?"
      -> minimum distance from the hospital to the forecast positions issued
         at that advisory cycle.

All distances are nautical miles, matching ATCF and HURDAT2 native units.
"""

import numpy as np

EARTH_RADIUS_NM = 3440.065


def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles. Broadcasts over arrays."""
    lat1, lon1, lat2, lon2 = map(np.asarray, (lat1, lon1, lat2, lon2))
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    lat1, lon1, lat2, lon2 = map(np.asarray, (lat1, lon1, lat2, lon2))
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return np.degrees(np.arctan2(y, x)) % 360.0


def quadrant_index(bearing):
    """
    Map a bearing to an ATCF quadrant index.

    ATCF radii are reported NE, SE, SW, NW in that order, where each quadrant
    spans 90 degrees starting at due north:
        NE = [0, 90)   SE = [90, 180)   SW = [180, 270)   NW = [270, 360)
    """
    return (np.asarray(bearing) // 90).astype(int) % 4


def in_wind_field(hosp_lat, hosp_lon, track_lat, track_lon, radii):
    """
    Boolean array over track observations: was the hospital inside the wind
    field at that observation?

    radii: (n_obs, 4) array of quadrant radii in nm, ordered NE/SE/SW/NW.
           NaN means not reported; those observations return False.

    A reported radius of exactly 0 is a real zero-extent quadrant, not missing,
    and correctly yields False.
    """
    track_lat = np.asarray(track_lat, dtype=float)
    track_lon = np.asarray(track_lon, dtype=float)
    radii = np.asarray(radii, dtype=float)

    dist = haversine_nm(track_lat, track_lon, hosp_lat, hosp_lon)
    brg = bearing_deg(track_lat, track_lon, hosp_lat, hosp_lon)
    q = quadrant_index(brg)

    quad_radius = radii[np.arange(len(track_lat)), q]
    with np.errstate(invalid="ignore"):
        return np.where(np.isnan(quad_radius), False, dist <= quad_radius)


def min_distance_to_track(hosp_lat, hosp_lon, track_lat, track_lon):
    """Closest approach of a track (as sampled points) to a hospital, in nm."""
    d = haversine_nm(np.asarray(track_lat, dtype=float),
                     np.asarray(track_lon, dtype=float), hosp_lat, hosp_lon)
    return float(np.min(d)) if d.size else float("nan")


def interpolate_track(lats, lons, times_hours, step_hours=1.0):
    """
    Linearly densify a track in time.

    HURDAT2 is 6-hourly. A fast-moving storm covers 60+ nm between fixes, so
    nearest-approach and swath-membership tests computed on raw 6-hourly points
    systematically understate exposure. Densifying to hourly removes most of
    that error at negligible cost.

    Linear interpolation in lat/lon is adequate at these spacings; great-circle
    curvature over 6 hours of storm motion is far below the precision of the
    wind radii themselves.
    """
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    t = np.asarray(times_hours, dtype=float)
    if t.size < 2:
        return lats, lons, t
    fine = np.arange(t[0], t[-1] + step_hours / 2, step_hours)
    return np.interp(fine, t, lats), np.interp(fine, t, lons), fine


def forecast_error_nm(fcst_lat, fcst_lon, actual_lat, actual_lon):
    """
    Great-circle error between a forecast position and the verifying best-track
    position. Used to build the empirical, era-specific track-error
    distribution that replaces the published NHC cone (see note below).
    """
    return haversine_nm(fcst_lat, fcst_lon, actual_lat, actual_lon)
