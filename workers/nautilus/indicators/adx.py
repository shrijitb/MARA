"""
workers/nautilus/indicators/adx.py

Pure Python ADX (Average Directional Index) — Wilder's smoothing. No TA-Lib.

classify_trend(adx_value) returns:
  "trending"  — ADX > 25  → route to SwingMACDStrategy
  "ranging"   — ADX < 20  → route to RangeMeanRevertStrategy
  "ambiguous" — 20 ≤ ADX ≤ 25  → return [] (no signal, per CLAUDE.md invariant)

Design: ambiguous zone is intentional — ADX 20–25 is a regime transition where
both strategies underperform.  Use ACTIVE_STRATEGY env var to force a mode.
"""

from __future__ import annotations

import math
from typing import List, Tuple


def calculate_adx(
    highs:  List[float],
    lows:   List[float],
    closes: List[float],
    period: int = 14,
) -> Tuple[List[float], List[float], List[float]]:
    """
    Calculate ADX, +DI, and -DI using Wilder's smoothing.

    Returns (adx, plus_di, minus_di) — all same length as input.
    Leading values (before period * 2 + 1 bars) are float('nan').

    Parameters
    ----------
    highs, lows, closes : aligned price lists of equal length
    period              : ADX smoothing period (default 14)
    """
    n   = len(closes)
    nan = float("nan")

    if n < period * 2 + 1:
        empty = [nan] * n
        return empty[:], empty[:], empty[:]

    # ── True Range + Directional Movement ────────────────────────────────────
    tr_list:  List[float] = [nan]
    pdm_list: List[float] = [nan]
    mdm_list: List[float] = [nan]

    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr   = max(h - l, abs(h - pc), abs(l - pc))
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm  = up   if (up > down   and up   > 0) else 0.0
        mdm  = down if (down > up   and down > 0) else 0.0
        tr_list.append(tr)
        pdm_list.append(pdm)
        mdm_list.append(mdm)

    # ── Wilder's smoothed sum ─────────────────────────────────────────────────
    def _wilder(values: List[float]) -> List[float]:
        out   = [nan] * n
        start = next((i for i, v in enumerate(values) if not math.isnan(v)), None)
        if start is None or start + period > n:
            return out
        out[start + period - 1] = sum(values[start:start + period])
        for i in range(start + period, n):
            out[i] = out[i - 1] - out[i - 1] / period + values[i]
        return out

    atr  = _wilder(tr_list)
    apdm = _wilder(pdm_list)
    amdm = _wilder(mdm_list)

    # ── +DI / -DI / DX ───────────────────────────────────────────────────────
    plus_di:  List[float] = [nan] * n
    minus_di: List[float] = [nan] * n
    dx_list:  List[float] = [nan] * n

    for i in range(n):
        if math.isnan(atr[i]) or atr[i] < 1e-12:
            continue
        pdi = 100.0 * apdm[i] / atr[i]
        mdi = 100.0 * amdm[i] / atr[i]
        plus_di[i]  = pdi
        minus_di[i] = mdi
        denom = pdi + mdi
        if denom > 1e-12:
            dx_list[i] = 100.0 * abs(pdi - mdi) / denom

    adx = _wilder(dx_list)
    return adx, plus_di, minus_di


def classify_trend(adx_value: float) -> str:
    """
    Classify market regime from a single ADX value.

    Returns
    -------
    "trending"  — ADX > 25
    "ranging"   — ADX < 20
    "ambiguous" — 20 ≤ ADX ≤ 25  (strategy router returns [], no entry)
    """
    if math.isnan(adx_value):
        return "ambiguous"
    if adx_value > 25.0:
        return "trending"
    if adx_value < 20.0:
        return "ranging"
    return "ambiguous"
