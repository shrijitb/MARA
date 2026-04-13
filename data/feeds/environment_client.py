"""
data/feeds/environment_client.py

Environmental disruption signals — NASA FIRMS + USGS Seismic.

NASA FIRMS (Fire Information for Resource Management System):
    Detects thermal anomalies (fires/explosions) near energy infrastructure.
    Endpoint: https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_SNPP_NRT/world/1
    Free API key at: https://firms.modaps.eosdis.nasa.gov/api/area/

USGS Earthquake Hazards Program:
    M4.5+ earthquakes near critical infrastructure / energy chokepoints.
    Endpoint: https://earthquake.usgs.gov/fdsnws/event/1/query
    No authentication required.

Environment variables:
    NASA_FIRMS_API_KEY   — free key from NASA FIRMS

Public API:
    fetch_thermal_anomalies(days_back)   → list[dict]  (FIRMS fire events)
    fetch_earthquakes(days_back, min_mag) → list[dict] (USGS quake events)
    score_environment(firms, quakes)      → float (0-100)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

NASA_FIRMS_API_KEY = os.environ.get("NASA_FIRMS_API_KEY", "")
USGS_BASE_URL      = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# ── Infrastructure hotspots [lat, lon, radius_deg, name, domain] ─────────────
# Areas where thermal anomalies or quakes indicate supply chain risk.
CRITICAL_INFRASTRUCTURE: list[dict] = [
    # Middle East oil infrastructure
    {"lat": 27.5, "lon": 49.5,  "r": 3.0, "name": "Saudi Aramco Abqaiq",  "domain": "commodities"},
    {"lat": 26.0, "lon": 50.5,  "r": 2.0, "name": "Saudi Gulf terminals", "domain": "commodities"},
    {"lat": 29.5, "lon": 48.0,  "r": 3.0, "name": "Kuwait oil fields",    "domain": "commodities"},
    {"lat": 30.5, "lon": 48.0,  "r": 3.0, "name": "Basra export terminal","domain": "commodities"},
    # Pipelines and LNG
    {"lat": 38.0, "lon": 27.0,  "r": 2.0, "name": "Turkey LNG terminal", "domain": "commodities"},
    {"lat": 41.0, "lon": 29.0,  "r": 2.0, "name": "Bosphorus corridor",  "domain": "commodities"},
    # Ukraine grain belt
    {"lat": 49.5, "lon": 32.0,  "r": 5.0, "name": "Ukraine grain belt",  "domain": "commodities"},
    # Taiwan semiconductor fabs
    {"lat": 24.7, "lon": 121.0, "r": 1.5, "name": "TSMC Hsinchu",        "domain": "us_equities"},
    {"lat": 22.6, "lon": 120.3, "r": 1.5, "name": "TSMC Tainan",         "domain": "us_equities"},
    # Pacific Ring of Fire — earthquake risk for supply chains
    {"lat": 35.7, "lon": 139.7, "r": 2.0, "name": "Tokyo port",          "domain": "us_equities"},
]

_MIN_QUAKE_MAGNITUDE = 4.5


def fetch_thermal_anomalies(days_back: int = 1) -> list[dict]:
    """
    Fetch VIIRS fire/thermal anomalies from NASA FIRMS.

    Returns list of FIRMS record dicts with:
      latitude, longitude, brightness, frp, acq_date, acq_time, confidence

    Returns [] if API key not set or request fails.
    """
    if not NASA_FIRMS_API_KEY:
        logger.debug("NASA_FIRMS_API_KEY not set — thermal anomaly signals disabled")
        return []

    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv"
        f"/{NASA_FIRMS_API_KEY}/VIIRS_SNPP_NRT/world/{days_back}"
    )

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Arka-OSINT/2.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")

        reader  = csv.DictReader(io.StringIO(raw))
        records = [row for row in reader]
        logger.info(f"NASA FIRMS: fetched {len(records)} thermal anomaly records")
        return records

    except urllib.error.HTTPError as exc:
        logger.warning(f"NASA FIRMS HTTP {exc.code}: {exc.reason}")
        return []
    except Exception as exc:
        logger.warning(f"NASA FIRMS fetch failed: {exc}")
        return []


def fetch_earthquakes(days_back: int = 7, min_magnitude: float = _MIN_QUAKE_MAGNITUDE) -> list[dict]:
    """
    Fetch M4.5+ earthquakes from USGS Earthquake Hazards Program.

    No API key required. Returns list of GeoJSON feature dicts.
    Each feature has geometry.coordinates [lon, lat, depth_km] and
    properties.mag, properties.place, properties.time (epoch ms).
    """
    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days_back)

    params = urllib.parse.urlencode({
        "format":       "geojson",
        "starttime":    start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime":      end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": str(min_magnitude),
        "orderby":      "magnitude",
        "limit":        200,
    })
    url = f"{USGS_BASE_URL}?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Arka-OSINT/2.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())

        features = data.get("features", [])
        logger.info(f"USGS: fetched {len(features)} M{min_magnitude}+ earthquakes")
        return features

    except Exception as exc:
        logger.warning(f"USGS fetch failed: {exc}")
        return []


def _near_infrastructure(lat: float, lon: float) -> list[dict]:
    """Return all infrastructure sites within their alert radius of (lat, lon)."""
    nearby = []
    for site in CRITICAL_INFRASTRUCTURE:
        d_lat = abs(lat - site["lat"])
        d_lon = abs(lon - site["lon"])
        if d_lat <= site["r"] and d_lon <= site["r"]:
            nearby.append(site)
    return nearby


def classify_firms_events(firms_records: list[dict]) -> list[dict]:
    """
    Filter thermal anomalies near critical infrastructure.
    Returns list of event dicts with severity_int (1-9) and domain.
    """
    events = []
    for rec in firms_records:
        try:
            lat = float(rec.get("latitude", 0))
            lon = float(rec.get("longitude", 0))
            frp = float(rec.get("frp", 0))        # fire radiative power MW
            conf = rec.get("confidence", "")
        except (ValueError, TypeError):
            continue

        sites = _near_infrastructure(lat, lon)
        if not sites:
            continue

        # Severity from FRP (MW)
        if frp > 1000:
            severity = 8
        elif frp > 500:
            severity = 7
        elif frp > 200:
            severity = 6
        elif frp > 50:
            severity = 5
        else:
            severity = 4

        for site in sites:
            events.append({
                "source":       "nasa_firms",
                "event_type":   "infrastructure_fire",
                "severity_int": severity,
                "lat":          lat,
                "lon":          lon,
                "frp_mw":       frp,
                "confidence":   conf,
                "site":         site["name"],
                "domain":       site["domain"],
                "description":  f"Thermal anomaly near {site['name']} "
                                f"(FRP={frp:.0f} MW, conf={conf})",
            })

    return events


def classify_earthquake_events(quake_features: list[dict]) -> list[dict]:
    """
    Filter earthquakes near critical infrastructure.
    Returns list of event dicts with severity_int and domain.
    """
    events = []
    for feat in quake_features:
        props  = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue

        lon, lat = float(coords[0]), float(coords[1])
        mag      = float(props.get("mag", 0))
        place    = props.get("place", "")

        sites = _near_infrastructure(lat, lon)
        if not sites and mag < 6.0:
            continue   # Only track < M6.0 if it hits infrastructure

        # Severity from magnitude
        if mag >= 7.5:
            severity = 8
        elif mag >= 7.0:
            severity = 7
        elif mag >= 6.5:
            severity = 6
        elif mag >= 6.0:
            severity = 5
        else:
            severity = 3

        domain = "commodities"
        for site in sites:
            domain = site.get("domain", "commodities")
            break

        events.append({
            "source":       "usgs_seismic",
            "event_type":   "earthquake",
            "severity_int": severity,
            "lat":          lat,
            "lon":          lon,
            "magnitude":    mag,
            "place":        place,
            "sites_nearby": [s["name"] for s in sites],
            "domain":       domain,
            "description":  f"M{mag:.1f} earthquake near {place or 'unknown location'}",
        })

    return events


def score_environment(firms_records: list[dict], quake_features: list[dict]) -> float:
    """
    Convert environmental events to 0-100 supply disruption score.

    Only infrastructure-adjacent events contribute.
    """
    fires  = classify_firms_events(firms_records)
    quakes = classify_earthquake_events(quake_features)
    all_ev = fires + quakes

    if not all_ev:
        return 0.0

    score = 0.0
    for ev in all_ev:
        score += ev.get("severity_int", 1) * 4.0

    return round(min(100.0, score), 1)
