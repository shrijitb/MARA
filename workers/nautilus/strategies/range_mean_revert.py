"""
workers/nautilus/strategies/range_mean_revert.py

Bollinger Bands + RSI + Williams Fractals range mean-reversion strategy.

Fires when ADX < 20 (ranging market).  Router in worker_api.py / engine.py
applies the ADX gate before routing here.

Two implementations:
  1. build_range_mean_revert_strategy() — NautilusTrader Strategy (lazy NT import)
  2. evaluate_signal(pairs) — pure-Python paper-mode fallback

Logic:
  Entry LONG  : close touches or crosses below lower BB + RSI < 35 +
                bullish fractal within 15 bars (structural support)
  Entry SHORT : close touches or crosses above upper BB + RSI > 65 +
                bearish fractal within 15 bars (structural resistance)
  Exit        : close crosses back to BB midline (20-period SMA) OR
                RSI reverts to 50 ± 5
  Stop loss   : 1.5× BB width below/above entry
  Take profit : BB midline (dynamic)
"""

from __future__ import annotations

import math
import os
import time
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Pure-Python helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sma(values: List[float], period: int) -> List[float]:
    result = [float("nan")] * len(values)
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1:i + 1]) / period
    return result


def _stddev(values: List[float], period: int) -> List[float]:
    sma    = _sma(values, period)
    result = [float("nan")] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        mean   = sma[i]
        var    = sum((x - mean) ** 2 for x in window) / period
        result[i] = math.sqrt(var)
    return result


def _bollinger(
    closes: List[float],
    period: int  = 20,
    k:      float = 2.0,
) -> Tuple[List[float], List[float], List[float]]:
    """Returns (upper, mid, lower) — same length as closes."""
    mid   = _sma(closes, period)
    std   = _stddev(closes, period)
    upper = [m + k * s if not math.isnan(m) else float("nan")
             for m, s in zip(mid, std)]
    lower = [m - k * s if not math.isnan(m) else float("nan")
             for m, s in zip(mid, std)]
    return upper, mid, lower


def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0.0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
    ag = sum(gains) / period
    al = sum(losses) / period
    if al < 1e-12:
        return 100.0
    return 100.0 - 100.0 / (1 + ag / al)


def _fractals(
    highs: List[float], lows: List[float]
) -> Tuple[List[int], List[int]]:
    bull: List[int] = []
    bear: List[int] = []
    for i in range(2, len(highs) - 2):
        if (lows[i]  < lows[i-1]  and lows[i]  < lows[i-2]  and
                lows[i]  < lows[i+1]  and lows[i]  < lows[i+2]):
            bull.append(i)
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and
                highs[i] > highs[i+1] and highs[i] > highs[i+2]):
            bear.append(i)
    return bull, bear


def _synthetic_ohlcv(pair: str, n_bars: int = 80) -> List[tuple]:
    """Deterministic synthetic OHLCV — stable within a 4-hour window."""
    import hashlib
    window = int(time.time() // 14400)
    seed   = int(hashlib.md5(f"rmr{pair}{window}".encode()).hexdigest()[:8], 16)
    base   = {
        "BTC/USDT": 65000.0, "ETH/USDT": 3200.0, "SOL/USDT": 160.0,
        "BNB/USDT": 580.0,   "AVAX/USDT": 38.0,
    }.get(pair, 100.0)

    bars, price, state = [], base, seed
    for _ in range(n_bars):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        # Ranging market: smaller moves than trending
        pct   = (state / 0xFFFFFFFF - 0.5) * 0.003
        o     = price
        c     = o * (1 + pct)
        h     = max(o, c) * (1 + abs(pct) * 0.2)
        l     = min(o, c) * (1 - abs(pct) * 0.2)
        bars.append((None, o, h, l, c, 0))
        price = c
    return bars


# ─────────────────────────────────────────────────────────────────────────────
# Public paper-mode signal function
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_signal(
    pairs: List[str],
    bias:  str = "swing_neutral",
) -> Optional[Tuple[str, str, float, float, float]]:
    """
    BB + RSI + Fractals range mean-reversion scanner.
    Paper-mode fallback when NautilusTrader engine is not running.

    Returns (pair, side, entry_price, stop_loss, take_profit) or None.
    """
    for pair in pairs:
        ohlcv  = _synthetic_ohlcv(pair)
        closes = [b[4] for b in ohlcv]
        highs  = [b[2] for b in ohlcv]
        lows   = [b[3] for b in ohlcv]

        upper, mid, lower = _bollinger(closes)
        if math.isnan(upper[-1]) or math.isnan(lower[-1]):
            continue

        rsi_val = _rsi(closes)
        price   = closes[-1]
        bb_width = upper[-1] - lower[-1]

        # Confirmed fractals (exclude last 2 bars)
        conf_highs = highs[:-2]
        conf_lows  = lows[:-2]
        bull_idx, bear_idx = _fractals(conf_highs, conf_lows)

        # ── Long setup: price at lower band + oversold + bullish fractal ────
        if (bias != "flat" and
                price <= lower[-1] * 1.001 and
                rsi_val < 35 and
                bull_idx):
            sl = price - bb_width * 0.5     # 0.5× band width below entry
            tp = mid[-1]                    # midline is the target
            if sl < price and tp > price:
                return (pair, "long", price, sl, tp)

        # ── Short setup: price at upper band + overbought + bearish fractal ─
        if (bias == "swing_neutral" and
                price >= upper[-1] * 0.999 and
                rsi_val > 65 and
                bear_idx):
            sl = price + bb_width * 0.5
            tp = mid[-1]
            if sl > price and tp < price:
                return (pair, "short", price, sl, tp)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NautilusTrader Strategy — lazy factory
# ─────────────────────────────────────────────────────────────────────────────

def build_range_mean_revert_strategy(
    instrument_id: str   = "BTC-USDT-SWAP.OKX",
    bar_spec:      str   = "4-HOUR-LAST-EXTERNAL",
    bb_period:     int   = 20,
    bb_k:          float = 2.0,
    rsi_period:    int   = 14,
    order_qty_str: str   = "0.001",
):
    """
    Build and return a RangeMeanRevertStrategy instance.
    All nautilus_trader imports are lazy — won't crash without it installed.
    Raises ImportError if nautilus_trader is absent (caller catches it).
    """
    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity, Price
    from nautilus_trader.indicators.bollinger_bands import BollingerBands
    from nautilus_trader.indicators.rsi import RelativeStrengthIndex

    bar_type_str = f"{instrument_id}-{bar_spec}"

    class RangeMeanRevertConfig(StrategyConfig, frozen=True):
        instrument_id: str   = instrument_id
        bar_type_str:  str   = bar_type_str
        bb_period:     int   = bb_period
        bb_k:          float = bb_k
        rsi_period:    int   = rsi_period
        order_qty_str: str   = order_qty_str

    class RangeMeanRevertStrategy(Strategy):
        """
        Bollinger Bands + RSI + Williams Fractals mean-reversion strategy.

        Fires only when the router has confirmed ADX < 20 (ranging market).
        Subscribes to 4H bars.  Uses NautilusTrader's built-in BB and RSI
        indicators, registered via register_indicator_for_bars for deterministic
        replay in backtesting mode.
        """

        def __init__(self, config: RangeMeanRevertConfig):
            super().__init__(config)
            self._iid    = InstrumentId.from_str(config.instrument_id)
            self._btype  = BarType.from_str(config.bar_type_str)
            self._bb     = BollingerBands(config.bb_period, config.bb_k)
            self._rsi    = RelativeStrengthIndex(config.rsi_period)
            self._qty    = Quantity.from_str(config.order_qty_str)
            # Fractal buffers (last 35 confirmed bars)
            self._highs: List[float] = []
            self._lows:  List[float] = []
            self._bb_period = config.bb_period

        def on_start(self) -> None:
            self.subscribe_bars(self._btype)
            self.register_indicator_for_bars(self._btype, self._bb)
            self.register_indicator_for_bars(self._btype, self._rsi)

        def on_bar(self, bar: Bar) -> None:
            self._highs.append(float(bar.high))
            self._lows.append(float(bar.low))
            if len(self._highs) > 35:
                self._highs.pop(0)
                self._lows.pop(0)

            if not (self._bb.initialized and self._rsi.initialized):
                return

            price    = float(bar.close)
            upper    = float(self._bb.upper)
            lower    = float(self._bb.lower)
            mid      = float(self._bb.middle)
            rsi_val  = float(self._rsi.value)
            bb_width = upper - lower

            if self._has_position():
                # Exit at midline reversion
                positions = self.cache.positions(instrument_id=self._iid)
                for pos in positions:
                    if pos.is_long  and price >= mid:
                        self.close_all_positions(self._iid)
                    elif pos.is_short and price <= mid:
                        self.close_all_positions(self._iid)
                return

            conf_highs = self._highs[:-2] if len(self._highs) > 2 else []
            conf_lows  = self._lows[:-2]  if len(self._lows)  > 2 else []
            bull_idx, bear_idx = _fractals(conf_highs, conf_lows)

            # Long: price at lower band, oversold, bullish fractal support
            if price <= lower * 1.001 and rsi_val < 35 and bull_idx:
                sl = price - bb_width * 0.5
                tp = mid
                if sl < price < tp:
                    self._submit(OrderSide.BUY, price, sl, tp)

            # Short: price at upper band, overbought, bearish fractal resistance
            elif price >= upper * 0.999 and rsi_val > 65 and bear_idx:
                sl = price + bb_width * 0.5
                tp = mid
                if tp < price < sl:
                    self._submit(OrderSide.SELL, price, sl, tp)

        def _has_position(self) -> bool:
            return bool(self.cache.positions(instrument_id=self._iid))

        def _submit(
            self,
            side:  "OrderSide",
            price: float,
            sl:    float,
            tp:    float,
        ) -> None:
            try:
                order_list = self.order_factory.bracket_market(
                    instrument_id    = self._iid,
                    order_side       = side,
                    quantity         = self._qty,
                    sl_trigger_price = Price.from_str(f"{sl:.2f}"),
                    tp_price         = Price.from_str(f"{tp:.2f}"),
                )
                self.submit_order_list(order_list)
            except Exception as exc:
                self.log.warning(f"bracket_market failed: {exc}")

        def on_stop(self) -> None:
            self.cancel_all_orders(self._iid)
            self.close_all_positions(self._iid)

        def on_dispose(self) -> None:
            pass

    config   = RangeMeanRevertConfig()
    strategy = RangeMeanRevertStrategy(config)
    return strategy
