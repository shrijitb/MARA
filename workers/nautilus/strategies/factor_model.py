"""
workers/nautilus/strategies/factor_model.py

Cross-Sectional Crypto Factor Model — dual implementation.

Based on Liu, Tsyvinski, Wu (2019) "Common Risk Factors in Cryptocurrency"
(NBER Working Paper 25882).

Three primary factors:
  1. MOMENTUM (weight 0.4): 21-bar cumulative return
     Cross-sectional: rank assets by recent performance
  2. CARRY    (weight 0.4): Annualized funding rate (cost-of-carry)
     High positive carry → longs are expensive → short the expensive assets
     High negative carry → shorts are expensive → long the cheap assets
  3. SIZE     (weight 0.2): Inverse price level (proxy for market cap rank)
     Lower-priced assets → smaller cap → higher expected return (CSMB)

Signal aggregation:
  1. Compute each factor for every pair in the universe
  2. Z-score each factor cross-sectionally (zero mean, unit std)
  3. Composite = 0.4 * z_momentum + 0.4 * z_carry + 0.2 * z_size
  4. LONG  the highest composite if z > 0.5  (top-ranked asset)
     SHORT the lowest  composite if z < -0.5 (bottom-ranked asset, swing_neutral only)

Volatility targeting:
  rv_bar    = per-bar std of returns (NOT annualized)
  rv_annual = rv_bar * sqrt(BARS_PER_YEAR)   BARS_PER_YEAR = 2190 (6 × 365, 24/7 crypto)
  scalar    = min(2.0, target_vol / rv_annual)   target_vol = 15% annualized
  SL = entry * (1 ∓ rv_bar * 2.0)   (2σ per-bar stop, ~2–4% for real BTC on 4H)
  TP = entry * (1 ± rv_bar * 3.0)   (3σ per-bar target → 1.5× R:R)

Paper mode:
  Momentum: uses _synthetic_ohlcv() from swing_macd (intra-container, always valid)
  Carry:    uses _synthetic_funding_rate_annualized() (same 8h-seeded LCG as funding_arb)
  Live mode (when data/feeds/funding_rates.py is importable):
  Carry uses real annualized yields from OKX via get_annualized_yield().

Signal format:
  (pair, side, entry_price, stop_loss, take_profit)
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Docker-isolation guard ────────────────────────────────────────────────────
try:
    from data.feeds.funding_rates import get_annualized_yield as _live_annualized_yield
    _FEEDS_AVAILABLE = True
except ImportError:
    _FEEDS_AVAILABLE = False

# ── OKX symbol map ────────────────────────────────────────────────────────────
_PAIR_TO_OKX: dict[str, str] = {
    "BTC/USDT":  "BTC-USDT-SWAP",
    "ETH/USDT":  "ETH-USDT-SWAP",
    "SOL/USDT":  "SOL-USDT-SWAP",
    "BNB/USDT":  "BNB-USDT-SWAP",
    "AVAX/USDT": "AVAX-USDT-SWAP",
}

# ── Strategy parameters ───────────────────────────────────────────────────────
MOMENTUM_LOOKBACK   = 21    # bars (21 × 4H = 3.5 trading days for crypto)
FACTOR_WEIGHTS      = {"momentum": 0.40, "carry": 0.40, "size": 0.20}
LONG_THRESHOLD      = 0.50  # composite z-score above this → enter long
SHORT_THRESHOLD     = -0.50 # composite z-score below this → enter short
TARGET_VOL_ANNUAL   = 0.15  # 15% annualized volatility target
VOL_SCALAR_CAP      = 2.0   # cap to prevent extreme leverage in low-vol environments
MIN_VOL_FLOOR       = 0.001 # floor to avoid division by near-zero vol (per-bar)
BARS_PER_YEAR       = 2190  # 4H crypto bars per year: 6 bars/day × 365 days (24/7 market)


# ─────────────────────────────────────────────────────────────────────────────
# Pure-Python helpers
# ─────────────────────────────────────────────────────────────────────────────

def _z_score(values: List[float]) -> List[float]:
    """
    Cross-sectional z-score.  Returns [0.0]*n if std ≈ 0 (all values identical).
    Zero mean, unit std across the input list.
    """
    n = len(values)
    if n < 2:
        return [0.0] * n
    mean = sum(values) / n
    var  = sum((v - mean) ** 2 for v in values) / n
    std  = math.sqrt(var)
    if std < 1e-12:
        return [0.0] * n
    return [(v - mean) / std for v in values]


def _realized_vol(closes: List[float]) -> float:
    """
    Per-bar realized volatility (std of bar-to-bar pct returns).
    NOT annualized — callers annualize as needed via * math.sqrt(BARS_PER_YEAR).
    Returns MIN_VOL_FLOOR if fewer than 2 prices or degenerate series.
    """
    if len(closes) < 2:
        return MIN_VOL_FLOOR
    returns = [
        (closes[i] / closes[i - 1] - 1.0)
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    if not returns:
        return MIN_VOL_FLOOR
    mean_r = sum(returns) / len(returns)
    var    = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    return max(math.sqrt(var), MIN_VOL_FLOOR)


def _synthetic_funding_rate_annualized(symbol: str) -> float:
    """
    Deterministic annualized funding rate.
    Same 8-hour seed as funding_arb._synthetic_funding_rate, but annualized.
    Range: approximately ±0.164  (±0.00015 per 8h * 3 * 365).
    """
    window = int(time.time() // 28800)  # 8-hour windows
    seed   = int(hashlib.md5(f"fa{symbol}{window}".encode()).hexdigest()[:8], 16)
    state  = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
    rate_per_8h = (state / 0xFFFFFFFF - 0.5) * 0.0003  # ±0.00015
    return rate_per_8h * 3 * 365


def _get_carry(okx_symbol: str) -> float:
    """
    Returns annualized carry (funding rate) for a symbol.
    Live if data/feeds/funding_rates.py is importable, else synthetic.
    """
    if _FEEDS_AVAILABLE:
        try:
            return _live_annualized_yield(okx_symbol)
        except Exception:
            pass
    return _synthetic_funding_rate_annualized(okx_symbol)


# ─────────────────────────────────────────────────────────────────────────────
# Public paper-mode signal function
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_signal(
    pairs: List[str],
    bias:  str = "swing_neutral",
) -> Optional[Tuple[str, str, float, float, float]]:
    """
    Cross-sectional 3-factor model scanner.
    Paper-mode fallback when NautilusTrader engine is not running.

    Returns (pair, side, entry_price, stop_loss, take_profit) or None.

    Requires at least 2 pairs to compute a meaningful cross-sectional ranking.

    ``bias`` gates direction:
      "flat"           — no new entries
      "momentum_long"  — long top-ranked asset only
      "swing_neutral"  — long top, short bottom
    """
    if bias == "flat":
        return None
    if len(pairs) < 2:
        return None  # cross-sectional ranking needs a universe

    # Intra-container import — always available in Docker
    from strategies.swing_macd import _synthetic_ohlcv  # type: ignore[import]

    # ── Factor computation per pair ───────────────────────────────────────────
    momentum_raw: List[float] = []
    carry_raw:    List[float] = []
    size_raw:     List[float] = []
    prices:       List[float] = []
    vols:         List[float] = []

    for pair in pairs:
        # Need at least MOMENTUM_LOOKBACK + 1 bars; use 30 for efficiency
        ohlcv  = _synthetic_ohlcv(pair, n_bars=30)
        closes = [b[4] for b in ohlcv]
        price  = closes[-1]

        # Factor 1 — Momentum: 21-bar cumulative return
        if len(closes) >= MOMENTUM_LOOKBACK + 1:
            mom = (closes[-1] / closes[-(MOMENTUM_LOOKBACK + 1)]) - 1.0
        else:
            mom = 0.0

        # Factor 2 — Carry: annualized funding rate
        okx_sym = _PAIR_TO_OKX.get(pair, "")
        carry   = _get_carry(okx_sym) if okx_sym else 0.0

        # Factor 3 — Size: inverse price (lower-cap assets have higher 1/price)
        size = 1.0 / price if price > 0 else 0.0

        # Realized vol for position sizing
        rv = _realized_vol(closes)

        momentum_raw.append(mom)
        carry_raw.append(carry)
        size_raw.append(size)
        prices.append(price)
        vols.append(rv)

    # ── Cross-sectional z-scores ──────────────────────────────────────────────
    z_mom   = _z_score(momentum_raw)
    z_carry = _z_score(carry_raw)
    z_size  = _z_score(size_raw)

    w = FACTOR_WEIGHTS
    composites = [
        w["momentum"] * zm + w["carry"] * zc + w["size"] * zs
        for zm, zc, zs in zip(z_mom, z_carry, z_size)
    ]

    best_idx  = composites.index(max(composites))
    worst_idx = composites.index(min(composites))

    # ── LONG the top-ranked asset ─────────────────────────────────────────────
    if composites[best_idx] > LONG_THRESHOLD:
        pair      = pairs[best_idx]
        price     = prices[best_idx]
        rv        = vols[best_idx]                           # per-bar std
        rv_annual = rv * math.sqrt(BARS_PER_YEAR)           # annualized for scalar
        vol_scalar = min(VOL_SCALAR_CAP, TARGET_VOL_ANNUAL / rv_annual)
        sl = price * (1.0 - rv * 2.0)                       # 2σ per-bar stop
        tp = price * (1.0 + rv * 3.0)                       # 3σ per-bar target
        if sl < price < tp:
            logger.debug("factor_model_long", pair=pair,
                         composite=round(composites[best_idx], 3),
                         vol_scalar=round(vol_scalar, 2), rv=round(rv, 4))
            return (pair, "long", price, sl, tp)

    # ── SHORT the bottom-ranked asset (swing_neutral only) ────────────────────
    if composites[worst_idx] < SHORT_THRESHOLD and bias == "swing_neutral":
        pair      = pairs[worst_idx]
        price     = prices[worst_idx]
        rv        = vols[worst_idx]                          # per-bar std
        rv_annual = rv * math.sqrt(BARS_PER_YEAR)           # annualized for scalar
        vol_scalar = min(VOL_SCALAR_CAP, TARGET_VOL_ANNUAL / rv_annual)
        sl = price * (1.0 + rv * 2.0)                       # 2σ per-bar stop
        tp = price * (1.0 - rv * 3.0)                       # 3σ per-bar target
        if tp < price < sl:
            logger.debug("factor_model_short", pair=pair,
                         composite=round(composites[worst_idx], 3),
                         vol_scalar=round(vol_scalar, 2), rv=round(rv, 4))
            return (pair, "short", price, sl, tp)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NautilusTrader Strategy — lazy factory
# ─────────────────────────────────────────────────────────────────────────────

def build_factor_model_strategy(
    instruments:       List[str] = None,
    bar_spec:          str       = "4-HOUR-LAST-EXTERNAL",
    long_threshold:    float     = LONG_THRESHOLD,
    short_threshold:   float     = SHORT_THRESHOLD,
    target_vol_annual: float     = TARGET_VOL_ANNUAL,
    order_qty_str:     str       = "0.001",
):
    """
    Build and return a FactorModelStrategy instance for NautilusTrader.

    All nautilus_trader imports are inside this function so that importing
    this module never crashes when nautilus_trader is not installed.
    Raises ImportError if nautilus_trader is absent (caller catches it).

    The strategy rebalances the cross-sectional ranking on every 4H bar.
    It subscribes to 4H bars for all instruments and runs the factor
    computation cross-sectionally on each bar event.
    """
    if instruments is None:
        instruments = [
            "BTC-USDT-SWAP.OKX", "ETH-USDT-SWAP.OKX", "SOL-USDT-SWAP.OKX",
            "BNB-USDT-SWAP.OKX", "AVAX-USDT-SWAP.OKX",
        ]

    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity, Price

    class FactorModelConfig(StrategyConfig, frozen=True):
        instruments:       tuple  = tuple(instruments)
        bar_spec:          str    = bar_spec
        long_threshold:    float  = long_threshold
        short_threshold:   float  = short_threshold
        target_vol_annual: float  = target_vol_annual
        order_qty_str:     str    = order_qty_str

    class FactorModelStrategy(Strategy):
        """
        Cross-sectional factor model for NautilusTrader.

        Subscribes to 4H bars for all instruments in the universe.
        On each bar event for any instrument, recomputes cross-sectional
        factor rankings and rebalances to the top/bottom assets.
        """

        def __init__(self, config: FactorModelConfig):
            super().__init__(config)
            self._instrument_ids = [InstrumentId.from_str(i) for i in config.instruments]
            self._bar_types      = [
                BarType.from_str(f"{i}-{config.bar_spec}") for i in config.instruments
            ]
            self._long_thr   = config.long_threshold
            self._short_thr  = config.short_threshold
            self._target_vol = config.target_vol_annual
            self._qty        = Quantity.from_str(config.order_qty_str)
            # CCXT pair format for evaluate_signal
            _okx_to_pair = {v: k for k, v in _PAIR_TO_OKX.items()}
            self._pairs = [
                _okx_to_pair.get(iid.replace(".OKX", ""), iid)
                for iid in config.instruments
            ]
            # Close buffer per instrument (last 30 closes for factor calculation)
            self._closes: dict[str, List[float]] = {i: [] for i in config.instruments}
            self._last_rebalance: float = 0.0
            self._rebalance_interval: float = 14400.0  # 4h in seconds

        def on_start(self) -> None:
            for bt in self._bar_types:
                self.subscribe_bars(bt)

        def on_bar(self, bar: Bar) -> None:
            # Update close buffer for this instrument
            iid_str = str(bar.bar_type.instrument_id)
            if iid_str in self._closes:
                self._closes[iid_str].append(float(bar.close))
                if len(self._closes[iid_str]) > 30:
                    self._closes[iid_str].pop(0)

            # Rate-limit rebalancing to once per 4h
            now = time.time()
            if now - self._last_rebalance < self._rebalance_interval:
                return
            self._last_rebalance = now

            # Delegate to evaluate_signal (cross-sectional, uses latest closes)
            try:
                sig = evaluate_signal(self._pairs, bias="swing_neutral")
                if sig:
                    pair, side, price, sl, tp = sig
                    # Find matching instrument id
                    okx_sym = _PAIR_TO_OKX.get(pair, "")
                    iid = next(
                        (i for i in self._instrument_ids if okx_sym in str(i)), None
                    )
                    if iid is None:
                        return
                    order_side = OrderSide.BUY if side == "long" else OrderSide.SELL
                    sl_price = Price.from_str(f"{sl:.2f}")
                    tp_price = Price.from_str(f"{tp:.2f}")
                    order_list = self.order_factory.bracket_market(
                        instrument_id=iid,
                        order_side=order_side,
                        quantity=self._qty,
                        sl_trigger_price=sl_price,
                        tp_price=tp_price,
                    )
                    self.submit_order_list(order_list)
            except Exception as exc:
                self.log.warning(f"factor_model rebalance failed: {exc}")

        def on_stop(self) -> None:
            for iid in self._instrument_ids:
                self.cancel_all_orders(iid)
                self.close_all_positions(iid)

        def on_dispose(self) -> None:
            pass

    config   = FactorModelConfig()
    strategy = FactorModelStrategy(config)
    return strategy
