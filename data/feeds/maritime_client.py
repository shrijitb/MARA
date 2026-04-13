"""
data/feeds/maritime_client.py

AIS maritime vessel traffic client — chokepoint anomaly detection.

Uses aisstream.io websocket API (free tier, API key required).
Subscribes to bounding boxes around 6 strategic chokepoints and detects
vessel density anomalies that signal supply chain disruptions.

Environment variables:
    AIS_API_KEY   — aisstream.io API key (free at aisstream.io)

Chokepoints monitored:
    Strait of Hormuz     — Persian Gulf oil transit
    Strait of Malacca    — SE Asia container throughput
    Suez Canal           — Red Sea / Mediterranean
    Panama Canal         — Pacific / Atlantic
    Bosphorus            — Black Sea (Ukraine grain, Russian oil)
    Taiwan Strait        — Pacific semiconductor supply chains

Public API:
    fetch_vessel_activity(timeout_sec)   → list[dict]  (vessel position msgs)
    detect_traffic_anomalies(vessels)    → list[dict]  (anomaly events)
    score_maritime(vessels)              → float (0-100)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

AIS_API_KEY = os.environ.get("AIS_API_KEY", "")

# ── Chokepoint bounding boxes [lat_min, lon_min, lat_max, lon_max] ────────────
CHOKEPOINTS: dict[str, dict] = {
    "strait_of_hormuz": {
        "bbox":         [[22.0, 56.0], [26.5, 60.0]],
        "domains":      ["commodities", "crypto_perps"],
        "baseline_vessels": 25,    # normal 24h vessel count
        "description":  "Persian Gulf oil transit — Iran/Oman",
    },
    "strait_of_malacca": {
        "bbox":         [[1.0, 99.5], [6.5, 104.5]],
        "domains":      ["commodities", "us_equities"],
        "baseline_vessels": 60,
        "description":  "SE Asia container shipping artery",
    },
    "suez_canal": {
        "bbox":         [[29.0, 32.0], [31.5, 33.0]],
        "domains":      ["commodities"],
        "baseline_vessels": 15,
        "description":  "Red Sea / Mediterranean connector",
    },
    "panama_canal": {
        "bbox":         [[8.5, -80.0], [9.5, -79.0]],
        "domains":      ["commodities", "us_equities"],
        "baseline_vessels": 12,
        "description":  "Pacific / Atlantic connector",
    },
    "bosphorus": {
        "bbox":         [[40.9, 28.6], [41.3, 29.3]],
        "domains":      ["commodities"],
        "baseline_vessels": 10,
        "description":  "Black Sea — Ukraine grain, Russian oil",
    },
    "taiwan_strait": {
        "bbox":         [[22.0, 119.0], [26.5, 122.0]],
        "domains":      ["us_equities", "crypto_perps"],
        "baseline_vessels": 30,
        "description":  "Pacific semiconductor + container throughput",
    },
}

# Anomaly thresholds
_REDUCTION_ALERT = 0.40    # vessel count drops to ≤40% of baseline
_SPIKE_ALERT     = 2.50    # vessel count spikes to ≥250% of baseline


async def fetch_vessel_activity(timeout_sec: float = 12.0) -> list[dict]:
    """
    Connect to aisstream.io websocket and collect vessel position messages
    from all monitored chokepoints.

    Returns list of raw AIS message dicts. Returns [] if:
      - AIS_API_KEY not set
      - websockets not installed
      - connection fails
    """
    if not AIS_API_KEY:
        logger.debug("AIS_API_KEY not set — maritime signals disabled")
        return []

    try:
        import websockets
    except ImportError:
        logger.warning("websockets not installed — maritime signals disabled. "
                       "Install with: pip install websockets")
        return []

    bboxes = [cp["bbox"] for cp in CHOKEPOINTS.values()]
    subscribe_msg = {
        "APIKey":       AIS_API_KEY,
        "BoundingBoxes": bboxes,
        "FilterMessageTypes": ["PositionReport"],
    }

    messages: list[dict] = []
    try:
        async with websockets.connect(
            "wss://stream.aisstream.io/v0/stream",
            open_timeout=10,
            close_timeout=5,
        ) as ws:
            await ws.send(json.dumps(subscribe_msg))
            deadline = asyncio.get_event_loop().time() + timeout_sec
            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msg = json.loads(raw)
                    messages.append(msg)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

    except Exception as exc:
        logger.warning(f"AIS stream connect failed: {exc}")
        return []

    logger.info(f"AIS: collected {len(messages)} position reports")
    return messages


def _assign_chokepoint(lat: float, lon: float) -> Optional[str]:
    """Return which chokepoint a lat/lon falls within, or None."""
    for name, cp in CHOKEPOINTS.items():
        bbox = cp["bbox"]
        lat_min, lon_min = bbox[0]
        lat_max, lon_max = bbox[1]
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return None


def detect_traffic_anomalies(vessels: list[dict]) -> list[dict]:
    """
    Detect density anomalies per chokepoint from collected vessel messages.

    Returns list of anomaly event dicts, each with:
      chokepoint, vessel_count, baseline, ratio, anomaly_type,
      domains, severity_int (1-9), description
    """
    # Count vessels per chokepoint
    counts: dict[str, int] = {k: 0 for k in CHOKEPOINTS}

    for msg in vessels:
        pos = msg.get("Message", {}).get("PositionReport", {})
        lat = pos.get("Latitude")
        lon = pos.get("Longitude")
        if lat is None or lon is None:
            continue
        try:
            cp = _assign_chokepoint(float(lat), float(lon))
        except (ValueError, TypeError):
            continue
        if cp:
            counts[cp] += 1

    anomalies: list[dict] = []
    for name, count in counts.items():
        cp        = CHOKEPOINTS[name]
        baseline  = cp["baseline_vessels"]
        if baseline == 0:
            continue
        ratio = count / baseline

        if ratio <= _REDUCTION_ALERT:
            # Traffic stoppage — supply chain disruption signal
            severity = 7 if ratio <= 0.1 else (6 if ratio <= 0.25 else 5)
            anomalies.append({
                "chokepoint":    name,
                "vessel_count":  count,
                "baseline":      baseline,
                "ratio":         round(ratio, 3),
                "anomaly_type":  "traffic_stoppage",
                "domains":       cp["domains"],
                "severity_int":  severity,
                "description":   f"{name} vessel count {count} vs baseline {baseline} "
                                 f"(ratio={ratio:.2f}) — possible blockage or conflict",
            })
        elif ratio >= _SPIKE_ALERT:
            # Traffic spike — possible pre-conflict convoy or sanctions evasion
            severity = 4
            anomalies.append({
                "chokepoint":    name,
                "vessel_count":  count,
                "baseline":      baseline,
                "ratio":         round(ratio, 3),
                "anomaly_type":  "traffic_spike",
                "domains":       cp["domains"],
                "severity_int":  severity,
                "description":   f"{name} vessel count {count} vs baseline {baseline} "
                                 f"(ratio={ratio:.2f}) — unusual traffic concentration",
            })

    if anomalies:
        logger.info(f"AIS: {len(anomalies)} chokepoint anomalies detected")
    return anomalies


def score_maritime(vessels: list[dict]) -> float:
    """
    Convert vessel activity to 0-100 supply chain disruption score.

    Higher scores = more severe chokepoint disruptions.
    """
    anomalies = detect_traffic_anomalies(vessels)
    if not anomalies:
        return 0.0

    score = 0.0
    for a in anomalies:
        sev = a.get("severity_int", 1)
        if a["anomaly_type"] == "traffic_stoppage":
            score += sev * 5.0     # stoppages are high-severity signals
        else:
            score += sev * 2.0     # spikes are lower priority

    return round(min(100.0, score), 1)
