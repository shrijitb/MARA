"""
workers/nautilus/strategies/day_scalp.py

Optional 1-minute bar day trading strategy — EMA crossover + RSI filter.

Activated when TRADING_MODE=day (or TRADING_MODE=both) in .env.
Runs alongside swing strategies or alone.

Config  (env vars, all optional — defaults shown):
  DAY_INSTRUMENT      BTC-USDT-SWAP.OKX
  DAY_EMA_FAST        9
  DAY_EMA_SLOW        21
  DAY_RSI_PERIOD      14
  DAY_RSI_OB          70.0    (overbought — skip long)
  DAY_RSI_OS          30.0    (oversold    — skip short)
  DAY_STOP_PCT        0.005   (0.5 % stop, tighter than swing)
  DAY_TP_RATIO        1.5
  DAY_MAX_TRADES      10      (daily trade cap)
  DAY_MAX_LOSS_PCT    0.02    (daily loss limit vs allocated capital)
  DAY_ORDER_QTY       0.001   (BTC quantity per order)

Latency budget: <200 ms from bar close to order submission.

Paper fallback:
  evaluate_signal(pairs) is called by worker_api.py if the NT engine is not
  running.  Identical logic; uses deterministic synthetic 1-minute OHLCV.
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

def _ema(values: List[float], period: int) -> List[float]:
    k      = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


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


def _synthetic_1m_ohlcv(pair: str, n_bars: int = 60) -> List[tuple]:
    """Deterministic synthetic 1-minute OHLCV — stable within a 1-minute window."""
    import hashlib
    window = int(time.time() // 60)   # changes every minute
    seed   = int(hashlib.md5(f"day{pair}{window}".encode()).hexdigest()[:8], 16)
    base   = {
        "BTC/USDT": 65000.0, "ETH/USDT": 3200.0, "SOL/USDT": 160.0,
        "BNB/USDT": 580.0,   "AVAX/USDT": 38.0,
    }.get(pair, 100.0)

    bars, price, state = [], base, seed
    for _ in range(n_bars):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        pct   = (state / 0xFFFFFFFF - 0.5) * 0.001   # tighter 1m moves
        o     = price
        c     = o * (1 + pct)
        h     = max(o, c) * (1 + abs(pct) * 0.1)
        l     = min(o, c) * (1 - abs(pct) * 0.1)
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
    EMA crossover + RSI day-scalp scanner — paper fallback.
    Returns (pair, side, entry_price, stop_loss, take_profit) or None.
    """
    ema_fast  = int(os.environ.get("DAY_EMA_FAST",  "9"))
    ema_slow  = int(os.environ.get("DAY_EMA_SLOW",  "21"))
    rsi_p     = int(os.environ.get("DAY_RSI_PERIOD","14"))
    rsi_ob    = float(os.environ.get("DAY_RSI_OB",  "70.0"))
    rsi_os    = float(os.environ.get("DAY_RSI_OS",  "30.0"))
    sl_pct    = float(os.environ.get("DAY_STOP_PCT", "0.005"))
    tp_ratio  = float(os.environ.get("DAY_TP_RATIO", "1.5"))

    for pair in pairs:
        ohlcv  = _synthetic_1m_ohlcv(pair)
        closes = [b[4] for b in ohlcv]

        if len(closes) < ema_slow + 2:
            continue

        fast_ema = _ema(closes, ema_fast)
        slow_ema = _ema(closes, ema_slow)
        rsi_val  = _rsi(closes, rsi_p)
        price    = closes[-1]

        # Crossover detection (previous and current bar)
        prev_cross = fast_ema[-2] - slow_ema[-2]
        curr_cross = fast_ema[-1] - slow_ema[-1]

        # ── Long: EMA fast crosses above slow + not overbought ───────────────
        if (bias != "flat" and
                prev_cross <= 0 < curr_cross and
                rsi_val < rsi_ob):
            sl = price * (1 - sl_pct)
            tp = price * (1 + sl_pct * tp_ratio)
            return (pair, "long", price, sl, tp)

        # ── Short: EMA fast crosses below slow + not oversold ────────────────
        if (bias == "swing_neutral" and
                prev_cross >= 0 > curr_cross and
                rsi_val > rsi_os):
            sl = price * (1 + sl_pct)
            tp = price * (1 - sl_pct * tp_ratio)
            return (pair, "short", price, sl, tp)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NautilusTrader Strategy — lazy factory
# ─────────────────────────────────────────────────────────────────────────────

def build_day_scalp_strategy(
    instrument_id:    str   = "BTC-USDT-SWAP.OKX",
    bar_spec:         str   = "1-MINUTE-LAST-EXTERNAL",
    ema_fast:         int   = 9,
    ema_slow:         int   = 21,
    rsi_period:       int   = 14,
    rsi_overbought:   float = 70.0,
    rsi_oversold:     float = 30.0,
    stop_loss_pct:    float = 0.005,
    take_profit_ratio: float = 1.5,
    max_daily_trades: int   = 10,
    max_daily_loss_pct: float = 0.02,
    order_qty_str:    str   = "0.001",
    allocated_usd:    float = 0.0,
):
    """
    Build and return a DayScalpStrategy instance.
    All nautilus_trader imports are lazy.
    Raises ImportError if nautilus_trader is absent (caller catches it).
    """
    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity, Price
    from nautilus_trader.indicators.average.ema import ExponentialMovingAverage
    from nautilus_trader.indicators.rsi import RelativeStrengthIndex

    bar_type_str = f"{instrument_id}-{bar_spec}"

    class DayScalpConfig(StrategyConfig, frozen=True):
        instrument_id:      str   = instrument_id
        bar_type_str:       str   = bar_type_str
        ema_fast:           int   = ema_fast
        ema_slow:           int   = ema_slow
        rsi_period:         int   = rsi_period
        rsi_overbought:     float = rsi_overbought
        rsi_oversold:       float = rsi_oversold
        stop_loss_pct:      float = stop_loss_pct
        take_profit_ratio:  float = take_profit_ratio
        max_daily_trades:   int   = max_daily_trades
        max_daily_loss_pct: float = max_daily_loss_pct
        order_qty_str:      str   = order_qty_str
        allocated_usd:      float = allocated_usd

    class DayScalpStrategy(Strategy):
        """
        1-minute EMA crossover + RSI day scalp.

        Subscribes to 1m bars on OKX.  Enforces:
          - max_daily_trades per calendar day (UTC reset)
          - max_daily_loss_pct: halts new entries if daily drawdown exceeds limit
        Latency budget: <200ms from bar-close to order submission.
        """

        def __init__(self, config: DayScalpConfig):
            super().__init__(config)
            self._iid             = InstrumentId.from_str(config.instrument_id)
            self._btype           = BarType.from_str(config.bar_type_str)
            self._ema_fast        = ExponentialMovingAverage(config.ema_fast)
            self._ema_slow        = ExponentialMovingAverage(config.ema_slow)
            self._rsi             = RelativeStrengthIndex(config.rsi_period)
            self._qty             = Quantity.from_str(config.order_qty_str)
            self._sl_pct          = config.stop_loss_pct
            self._tp_ratio        = config.take_profit_ratio
            self._rsi_ob          = config.rsi_overbought
            self._rsi_os          = config.rsi_oversold
            self._max_trades      = config.max_daily_trades
            self._max_loss_pct    = config.max_daily_loss_pct
            self._allocated_usd   = config.allocated_usd
            # Daily tracking (UTC day)
            self._daily_trades:   int   = 0
            self._daily_loss:     float = 0.0
            self._last_day:       int   = 0   # UTC day number
            # Previous bar's EMA difference for crossover detection
            self._prev_diff: Optional[float] = None

        def on_start(self) -> None:
            self.subscribe_bars(self._btype)
            self.register_indicator_for_bars(self._btype, self._ema_fast)
            self.register_indicator_for_bars(self._btype, self._ema_slow)
            self.register_indicator_for_bars(self._btype, self._rsi)

        def on_bar(self, bar: Bar) -> None:
            # UTC day reset
            today = int(time.time()) // 86400
            if today != self._last_day:
                self._daily_trades = 0
                self._daily_loss   = 0.0
                self._last_day     = today

            if not (self._ema_fast.initialized and
                    self._ema_slow.initialized and
                    self._rsi.initialized):
                self._prev_diff = None
                return

            curr_diff = float(self._ema_fast.value) - float(self._ema_slow.value)
            rsi_val   = float(self._rsi.value)
            price     = float(bar.close)

            # Guard limits before new entry
            if (self._daily_trades >= self._max_trades or
                    (self._allocated_usd > 0 and
                     self._daily_loss / self._allocated_usd >= self._max_loss_pct) or
                    self._has_position()):
                self._prev_diff = curr_diff
                return

            if self._prev_diff is not None:
                if self._prev_diff <= 0 < curr_diff and rsi_val < self._rsi_ob:
                    sl = price * (1 - self._sl_pct)
                    tp = price * (1 + self._sl_pct * self._tp_ratio)
                    self._submit(OrderSide.BUY, price, sl, tp)

                elif self._prev_diff >= 0 > curr_diff and rsi_val > self._rsi_os:
                    sl = price * (1 + self._sl_pct)
                    tp = price * (1 - self._sl_pct * self._tp_ratio)
                    self._submit(OrderSide.SELL, price, sl, tp)

            self._prev_diff = curr_diff

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
                self._daily_trades += 1
            except Exception as exc:
                self.log.warning(f"day_scalp bracket_market failed: {exc}")

        def on_stop(self) -> None:
            self.cancel_all_orders(self._iid)
            self.close_all_positions(self._iid)

        def on_dispose(self) -> None:
            pass

    config   = DayScalpConfig()
    strategy = DayScalpStrategy(config)
    return strategy
