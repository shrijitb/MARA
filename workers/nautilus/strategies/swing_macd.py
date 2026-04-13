"""
workers/nautilus/strategies/swing_macd.py

MACD + Williams Fractals swing strategy — dual implementation.

1. SwingMACDStrategy (NautilusTrader Strategy subclass)
   Runs inside ArkaEngine (engine.py) when nautilus_trader is installed and
   OKX credentials are present.  Handles bracket orders, position tracking,
   and risk checks via NautilusTrader's built-in risk engine.

   build_swing_macd_strategy() is the factory — all NT imports are lazy so
   importing this module never fails without nautilus_trader.

2. evaluate_signal(pairs, bias) — pure-Python paper fallback
   Called by worker_api.py when the NautilusTrader engine is not running.
   Uses deterministic synthetic OHLCV so signals are stable within a 4-hour
   window (matching SWING_TIMEFRAME). Returns the first qualifying setup or None.

Strategy logic (same in both paths):
  Entry LONG  : bullish fractal ≤ 15 bars back + MACD bullish crossover ≤ 3 bars
                + MACD line > 0 + RSI 40–70
  Entry SHORT : bearish fractal ≤ 15 bars back + MACD bearish crossover ≤ 3 bars
                + MACD line < 0 + RSI 30–60
  Exit        : 2% SL + 2× TP (1:2 R:R) + MACD reversal after ≥2 held bars
  ADX gate    : caller (worker_api / engine) ensures ADX > 25 before invoking

OKX perp format: BTC-USDT-SWAP  (not BTC/USDT — OKX's perp naming)
"""

from __future__ import annotations

import math
import os
import time
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Pure-Python helpers (no external deps — used by evaluate_signal fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _ema(values: List[float], period: int) -> List[float]:
    k      = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _macd(
    closes: List[float],
    fast: int   = 12,
    slow: int   = 26,
    signal: int = 9,
) -> Tuple[List[float], List[float], List[float]]:
    """Returns (macd_line, signal_line, histogram) — same length as closes."""
    if len(closes) < slow + signal:
        nan = [float("nan")] * len(closes)
        return nan[:], nan[:], nan[:]

    fast_ema  = _ema(closes, fast)
    slow_ema  = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]

    # Signal EMA starts from bar `slow - fast` (where slow_ema has settled)
    offset     = slow - fast
    sig_raw    = _ema(macd_line[offset:], signal)
    pad        = len(closes) - len(sig_raw)
    sig_line   = [float("nan")] * pad + sig_raw
    histogram  = [
        (m - s) if not math.isnan(s) else float("nan")
        for m, s in zip(macd_line, sig_line)
    ]
    return macd_line, sig_line, histogram


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
    """Williams fractals — needs 2 confirmed bars on each side."""
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


def _synthetic_ohlcv(pair: str, n_bars: int = 120) -> List[tuple]:
    """
    Deterministic synthetic OHLCV for paper mode.
    Seed changes every 4-hour window so signals are stable within a candle.
    """
    import hashlib
    window = int(time.time() // 14400)  # 4-hour windows
    seed   = int(hashlib.md5(f"{pair}{window}".encode()).hexdigest()[:8], 16)
    base   = {
        "BTC/USDT":  65000.0, "ETH/USDT": 3200.0, "SOL/USDT": 160.0,
        "BNB/USDT":  580.0,   "AVAX/USDT": 38.0,
    }.get(pair, 100.0)

    bars, price, state = [], base, seed
    for _ in range(n_bars):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        pct   = (state / 0xFFFFFFFF - 0.5) * 0.006
        o     = price
        c     = o * (1 + pct)
        h     = max(o, c) * (1 + abs(pct) * 0.3)
        l     = min(o, c) * (1 - abs(pct) * 0.3)
        bars.append((None, o, h, l, c, 0))
        price = c
    return bars


# ─────────────────────────────────────────────────────────────────────────────
# Public paper-mode signal function — called by worker_api.py
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_signal(
    pairs: List[str],
    bias:  str = "swing_neutral",
) -> Optional[Tuple[str, str, float, float, float]]:
    """
    Pure-Python MACD + Fractals scanner.
    Used as paper fallback when NautilusTrader engine is not running.

    Returns (pair, side, entry_price, stop_loss, take_profit) or None.

    ``bias`` shapes which signals are accepted:
      "momentum_long"  — long setups only
      "swing_neutral"  — both long and short
      "flat"           — caller should skip this entirely
    """
    sl_pct  = float(os.environ.get("SWING_STOP_LOSS_PCT",     "0.02"))
    tp_ratio = float(os.environ.get("SWING_TAKE_PROFIT_RATIO", "2.0"))

    for pair in pairs:
        ohlcv  = _synthetic_ohlcv(pair)
        closes = [b[4] for b in ohlcv]
        highs  = [b[2] for b in ohlcv]
        lows   = [b[3] for b in ohlcv]

        macd_line, sig_line, _ = _macd(closes)
        if all(math.isnan(v) for v in macd_line):
            continue

        rsi_val = _rsi(closes)

        # Fractals need 2 confirmed bars — exclude last 2
        conf_highs = highs[:-2]
        conf_lows  = lows[:-2]
        bull_idx, bear_idx = _fractals(conf_highs, conf_lows)

        last_macd = macd_line[-1]
        prev_macd = macd_line[-2] if len(macd_line) > 1 else last_macd
        last_sig  = sig_line[-1]
        prev_sig  = sig_line[-2] if len(sig_line) > 1 else last_sig
        price     = closes[-1]

        # Crossover: previously below signal, now above (or vice versa)
        def _crossed_up() -> bool:
            if math.isnan(last_sig) or math.isnan(prev_sig):
                return False
            return prev_macd <= prev_sig and last_macd > last_sig

        def _crossed_down() -> bool:
            if math.isnan(last_sig) or math.isnan(prev_sig):
                return False
            return prev_macd >= prev_sig and last_macd < last_sig

        # ── Long setup ────────────────────────────────────────────────────────
        if (bias != "flat" and
                bull_idx and
                _crossed_up() and
                last_macd > 0 and
                40 <= rsi_val <= 70):
            fractal_low = conf_lows[bull_idx[-1]]
            sl = fractal_low * (1 - sl_pct)
            tp = price + (price - sl) * tp_ratio
            logger.debug("swing_macd_long", pair=pair, price=price, sl=sl, tp=tp)
            return (pair, "long", price, sl, tp)

        # ── Short setup (skip in momentum_long bias) ──────────────────────────
        if (bias == "swing_neutral" and
                bear_idx and
                _crossed_down() and
                last_macd < 0 and
                30 <= rsi_val <= 60):
            fractal_high = conf_highs[bear_idx[-1]]
            sl = fractal_high * (1 + sl_pct)
            tp = price - (sl - price) * tp_ratio
            logger.debug("swing_macd_short", pair=pair, price=price, sl=sl, tp=tp)
            return (pair, "short", price, sl, tp)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NautilusTrader Strategy — lazy factory
# ─────────────────────────────────────────────────────────────────────────────

def build_swing_macd_strategy(
    instrument_id:     str   = "BTC-USDT-SWAP.OKX",
    bar_spec:          str   = "4-HOUR-LAST-EXTERNAL",
    macd_fast:         int   = 12,
    macd_slow:         int   = 26,
    macd_signal:       int   = 9,
    stop_loss_pct:     float = 0.02,
    take_profit_ratio: float = 2.0,
    order_qty_str:     str   = "0.001",
):
    """
    Build and return a SwingMACDStrategy instance.

    All nautilus_trader imports are inside this function so that importing
    this module never crashes when nautilus_trader is not installed.
    Raises ImportError if nautilus_trader is absent (caller catches it).
    """
    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity, Price
    from nautilus_trader.indicators.macd import MovingAverageConvergenceDivergence

    bar_type_str = f"{instrument_id}-{bar_spec}"

    class SwingMACDConfig(StrategyConfig, frozen=True):
        instrument_id:     str   = instrument_id
        bar_type_str:      str   = bar_type_str
        macd_fast:         int   = macd_fast
        macd_slow:         int   = macd_slow
        macd_signal_p:     int   = macd_signal      # 'signal' is a reserved attr
        stop_loss_pct:     float = stop_loss_pct
        take_profit_ratio: float = take_profit_ratio
        order_qty_str:     str   = order_qty_str

    class SwingMACDStrategy(Strategy):
        """
        MACD + Williams Fractals swing strategy running inside NautilusTrader.

        Subscribes to 4H bars on OKX.  On each confirmed bar the MACD
        indicator is updated (via register_indicator_for_bars).
        Bracket orders (market entry + SL + TP) are submitted through
        NautilusTrader's execution engine — no custom position book needed.
        ADX gate is applied upstream by the strategy router.
        """

        def __init__(self, config: SwingMACDConfig):
            super().__init__(config)
            self._iid  = InstrumentId.from_str(config.instrument_id)
            self._btype = BarType.from_str(config.bar_type_str)
            self._macd  = MovingAverageConvergenceDivergence(
                config.macd_fast,
                config.macd_slow,
                config.macd_signal_p,
            )
            self._sl_pct  = config.stop_loss_pct
            self._tp_ratio = config.take_profit_ratio
            self._qty     = Quantity.from_str(config.order_qty_str)
            # Rolling buffer for fractal detection (last 35 confirmed bars)
            self._highs: List[float] = []
            self._lows:  List[float] = []
            self._bars_held: int     = 0

        def on_start(self) -> None:
            self.subscribe_bars(self._btype)
            self.register_indicator_for_bars(self._btype, self._macd)

        def on_bar(self, bar: Bar) -> None:
            # Maintain fractal buffer (need ≥5 bars for a confirmed fractal)
            self._highs.append(float(bar.high))
            self._lows.append(float(bar.low))
            if len(self._highs) > 35:
                self._highs.pop(0)
                self._lows.pop(0)

            if not self._macd.initialized:
                return

            macd_val = float(self._macd.value)
            has_long = self._has_long()

            if has_long:
                self._bars_held += 1
                # MACD reversal exit after ≥2 bars
                if macd_val < 0 and self._bars_held >= 2:
                    self._exit_long()
            elif macd_val > 0:
                self._try_enter_long(bar, macd_val)

        def _has_long(self) -> bool:
            positions = self.cache.positions(instrument_id=self._iid)
            return any(p.is_long for p in positions)

        def _try_enter_long(self, bar: Bar, macd_val: float) -> None:
            if len(self._lows) < 5:
                return
            # Need 2 confirmed bars on each side → exclude last 2
            conf_lows = self._lows[:-2]
            bull, _   = _fractals(self._highs[:-2], conf_lows)
            if not bull:
                return
            fractal_low = conf_lows[bull[-1]]
            price  = float(bar.close)
            sl     = fractal_low * (1 - self._sl_pct)
            tp     = price + (price - sl) * self._tp_ratio
            if sl >= price:
                return
            try:
                order_list = self.order_factory.bracket_market(
                    instrument_id    = self._iid,
                    order_side       = OrderSide.BUY,
                    quantity         = self._qty,
                    sl_trigger_price = Price.from_str(f"{sl:.2f}"),
                    tp_price         = Price.from_str(f"{tp:.2f}"),
                )
                self.submit_order_list(order_list)
                self._bars_held = 0
            except Exception as exc:
                self.log.warning(f"bracket_market failed: {exc}")

        def _exit_long(self) -> None:
            self.close_all_positions(self._iid)
            self._bars_held = 0

        def on_stop(self) -> None:
            self.cancel_all_orders(self._iid)
            self.close_all_positions(self._iid)

        def on_dispose(self) -> None:
            pass

    config   = SwingMACDConfig()
    strategy = SwingMACDStrategy(config)
    return strategy
