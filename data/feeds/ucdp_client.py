"""
data/feeds/ucdp_client.py

UCDP GED (Uppsala Conflict Data Program — Georeferenced Event Dataset) client.

Endpoint: https://ucdpapi.pcr.uu.se/api/gedevents/{version}

Free — no API key required. Returns armed conflict events with fatality counts,
location coordinates, and conflict names.

Authentication: None required.
Rate limit: Polite use (1 req/s). No documented quota.

Public API:
    fetch_ucdp_events(days_back)  → list[dict]  (raw UCDP event dicts)
    score_ucdp_events(events)     → float (0-100)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

UCDP_API_VERSION = "23.1"
UCDP_BASE_URL    = f"https://ucdpapi.pcr.uu.se/api/gedevents/{UCDP_API_VERSION}"

# Fatality thresholds for scoring
_HIGH_FATALITY  = 50    # single event ≥50 deaths = high severity
_MASS_FATALITY  = 200   # ≥200 = extreme severity


def fetch_ucdp_events(days_back: int = 90) -> list[dict]:
    """
    Fetch georeferenced armed conflict events from UCDP GED.

    Each event dict contains (at minimum):
      id, conflict_name, country, region, where_latlng,
      deaths_a, deaths_b, deaths_civilians, deaths_best,
      date_start, date_end, type_of_violence

    type_of_violence codes:
      1 = state-based conflict
      2 = non-state conflict
      3 = one-sided violence (civilians)

    Returns [] on API failure (caller degrades gracefully).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params = urllib.parse.urlencode({
        "StartDate": cutoff,
        "pagesize":  200,
        "page":      1,
    })
    url = f"{UCDP_BASE_URL}?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent":  "Arka-OSINT/2.0 (research; contact: arka@localhost)",
                "Accept":      "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())

        events = data.get("Result", [])
        logger.info(f"UCDP: fetched {len(events)} events since {cutoff}")
        return events

    except urllib.error.HTTPError as exc:
        logger.warning(f"UCDP HTTP {exc.code}: {exc.reason}")
        return []
    except Exception as exc:
        logger.warning(f"UCDP fetch failed: {exc}")
        return []


def score_ucdp_events(events: list[dict]) -> float:
    """
    Convert UCDP event list to 0-100 conflict score.

    Scoring logic:
      - Base: 1 point per event (up to 30 pts from event count)
      - Fatality bonus: progressive scale
        10-49 deaths: +2 pts per event
        50-199 deaths: +5 pts per event
        200+ deaths: +10 pts per event
      - Caps at 100.

    >>> score_ucdp_events([])
    0.0
    """
    if not events:
        return 0.0

    score = 0.0
    for ev in events:
        try:
            deaths = int(ev.get("deaths_best") or ev.get("deaths_a") or 0)
        except (ValueError, TypeError):
            deaths = 0
        score += 1.0   # base
        if deaths >= _MASS_FATALITY:
            score += 10.0
        elif deaths >= _HIGH_FATALITY:
            score += 5.0
        elif deaths >= 10:
            score += 2.0

    return round(min(100.0, score), 1)


def classify_ucdp_severity(event: dict) -> int:
    """
    Return severity integer 1-9 for a single UCDP event.

    Maps fatality count to EventSeverity scale used by osint_processor.
    """
    try:
        deaths = int(event.get("deaths_best") or event.get("deaths_a") or 0)
    except (ValueError, TypeError):
        deaths = 0
    if deaths == 0:
        return 2   # LOW (violence occurred but no deaths confirmed)
    if deaths < 5:
        return 3   # MODERATE
    if deaths < 20:
        return 4   # NOTABLE
    if deaths < 50:
        return 5   # SIGNIFICANT
    if deaths < 100:
        return 6   # HIGH
    if deaths < 200:
        return 7   # SEVERE
    if deaths < 500:
        return 8   # CRITICAL
    return 9       # EXTREME
