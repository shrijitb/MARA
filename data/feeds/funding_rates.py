"""
data/feeds/funding_rates.py

OKX Perpetual Funding Rate feed.

Extends market_data.py with historical rates and annualized yield calculations.
Does NOT duplicate get_crypto_funding_rate() — use market_data.py for spot lookups.

Functions:
  get_funding_history(symbol, limit)   — historical funding rates (OKX history endpoint)
  get_next_funding_rate(symbol)        — next settlement rate (from current-rate response)
  get_annualized_yield(symbol, ...)    — mean(history) * 3 * 365 (annualized carry)
  get_all_current_rates(symbols)       — batch annualized yields for all given symbols

OKX endpoints (public, no auth):
  GET /api/v5/public/funding-rate?instId={symbol}
      → data[0].fundingRate (current)  data[0].nextFundingRate (next)
  GET /api/v5/public/funding-rate-history?instId={symbol}&limit={limit}
      → data[] list of {fundingRate, fundingTime} entries

Symbol format: OKX perp notation — "BTC-USDT-SWAP" (no .OKX suffix).
3 settlements per day on OKX (every 8 hours), so annual = rate * 3 * 365.
"""

from __future__ import annotations

import time
import requests
from typing import Optional

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL      = 300      # 5 min — current / next rates
HISTORY_TTL    = 28_800   # 8 h  — history only changes at each settlement

_OKX_BASE = "https://www.okx.com"


def _cached(key: str, ttl: int, fn):
    now = time.time()
    if key in _cache:
        ts, val = _cache[key]
        if now - ts < ttl:
            return val
    val = fn()
    _cache[key] = (now, val)
    return val


# ---------------------------------------------------------------------------
# Default universe
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "BNB-USDT-SWAP",
    "AVAX-USDT-SWAP",
]


# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------

def get_funding_history(
    symbol: str = "BTC-USDT-SWAP",
    limit:  int = 100,
) -> list[dict]:
    """
    Fetch historical funding rates from OKX.

    Returns a list of dicts, newest first:
      [{"fundingRate": float, "fundingTime": str}, ...]

    Returns [] on any network or parse failure.
    """
    def _fetch():
        url = (
            f"{_OKX_BASE}/api/v5/public/funding-rate-history"
            f"?instId={symbol}&limit={limit}"
        )
        try:
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            raw = r.json().get("data", [])
            return [
                {
                    "fundingRate": float(entry["fundingRate"]),
                    "fundingTime": entry.get("fundingTime", ""),
                }
                for entry in raw
            ]
        except Exception:
            return []

    return _cached(f"funding_history_{symbol}_{limit}", HISTORY_TTL, _fetch)


# ---------------------------------------------------------------------------
# Next funding rate (from the current-rate endpoint's nextFundingRate field)
# ---------------------------------------------------------------------------

def get_next_funding_rate(symbol: str = "BTC-USDT-SWAP") -> float:
    """
    Returns the predicted next settlement rate from OKX.
    Falls back to 0.0 on failure.
    """
    def _fetch():
        url = f"{_OKX_BASE}/api/v5/public/funding-rate?instId={symbol}"
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                return 0.0
            return float(data[0].get("nextFundingRate", 0.0))
        except Exception:
            return 0.0

    return _cached(f"funding_next_{symbol}", CACHE_TTL, _fetch)


# ---------------------------------------------------------------------------
# Annualized yield
# ---------------------------------------------------------------------------

def get_annualized_yield(
    symbol:           str = "BTC-USDT-SWAP",
    lookback_periods: int = 21,
) -> float:
    """
    Mean funding rate over the last ``lookback_periods`` settlements,
    annualized:  mean_rate * 3 * 365

    3 settlements per day × 365 days = 1095 periods per year.

    Example: mean_rate = 0.0001 → 0.0001 * 3 * 365 = 10.95% p.a.

    Returns 0.0 if history is empty or fetch fails.
    """
    history = get_funding_history(symbol, limit=lookback_periods)
    if not history:
        return 0.0
    rates = [h["fundingRate"] for h in history]
    mean_rate = sum(rates) / len(rates)
    return mean_rate * 3 * 365


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------

def get_all_current_rates(
    symbols: Optional[list[str]] = None,
) -> dict[str, float]:
    """
    Returns {symbol: annualized_yield} for every requested symbol.
    Failures are silently substituted with 0.0.
    """
    if symbols is None:
        symbols = DEFAULT_SYMBOLS
    result = {}
    for s in symbols:
        try:
            result[s] = get_annualized_yield(s)
        except Exception:
            result[s] = 0.0
    return result
