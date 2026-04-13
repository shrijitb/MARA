"""
data/feeds/order_book.py

OKX L2 Order Book feed.

Provides bid/ask depth snapshots and bid-ask imbalance calculations.
Used by the order_flow strategy and available to any component that imports
from the project root (hypervisor, tests). NOT available inside the nautilus
Docker container — strategies guard this import with try/except ImportError.

Functions:
  get_order_book(symbol, depth)        — top N bid/ask levels from OKX REST
  compute_bid_ask_imbalance(book)      — (bid_vol - ask_vol) / (bid_vol + ask_vol)
  get_live_imbalance(symbol, depth)    — convenience: fetch + compute in one call

OKX endpoint (public, no auth):
  GET /api/v5/market/books?instId={symbol}&sz={depth}
  Response: data[0].bids = [[price, size, liquidated_orders, orders], ...]
            data[0].asks = [[price, size, liquidated_orders, orders], ...]

Symbol format: OKX perp notation — "BTC-USDT-SWAP" (no .OKX suffix).
"""

from __future__ import annotations

import time
import requests

# ---------------------------------------------------------------------------
# Cache — short TTL: order book data stales within seconds
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 10  # 10 seconds — books are very short-lived

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
# Book fetch
# ---------------------------------------------------------------------------

def get_order_book(
    symbol: str = "BTC-USDT-SWAP",
    depth:  int = 20,
) -> dict:
    """
    Fetch top ``depth`` bid and ask levels from OKX.

    Returns:
      {
        "bids": [[price_str, size_str, ...], ...],  # highest bid first
        "asks": [[price_str, size_str, ...], ...],  # lowest ask first
      }

    Returns {} on any failure.
    """
    def _fetch():
        url = f"{_OKX_BASE}/api/v5/market/books?instId={symbol}&sz={depth}"
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                return {}
            return {
                "bids": data[0].get("bids", []),
                "asks": data[0].get("asks", []),
            }
        except Exception:
            return {}

    return _cached(f"orderbook_{symbol}_{depth}", CACHE_TTL, _fetch)


# ---------------------------------------------------------------------------
# Imbalance — pure function (no network calls)
# ---------------------------------------------------------------------------

def compute_bid_ask_imbalance(book: dict) -> float:
    """
    Bid-ask volume imbalance across all levels in ``book``.

    imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)

    Range: [-1.0, 1.0]
      +1.0 = all volume on bid side (maximum buy pressure)
      -1.0 = all volume on ask side (maximum sell pressure)
       0.0 = balanced or empty book

    Each level is [price, size, ...] — only size (index 1) is used.
    """
    if not book:
        return 0.0

    bid_vol = sum(float(level[1]) for level in book.get("bids", []) if len(level) >= 2)
    ask_vol = sum(float(level[1]) for level in book.get("asks", []) if len(level) >= 2)
    total   = bid_vol + ask_vol

    if total < 1e-12:
        return 0.0

    return (bid_vol - ask_vol) / total


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def get_live_imbalance(
    symbol: str = "BTC-USDT-SWAP",
    depth:  int = 20,
) -> float:
    """
    Fetch the order book and return the bid-ask imbalance in one call.
    Returns 0.0 on failure.
    """
    try:
        book = get_order_book(symbol, depth)
        return compute_bid_ask_imbalance(book)
    except Exception:
        return 0.0
