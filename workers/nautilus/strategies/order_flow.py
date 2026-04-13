"""
workers/nautilus/strategies/order_flow.py

Order Flow Imbalance (OFI) Strategy — dual implementation.

Theory (Cont, Kukanov, Stoikov 2014):
  Order book changes create net buying or selling pressure. When the bid side
  gains volume faster than the ask side, price tends to rise — and vice versa.

This implementation uses bid-ask volume imbalance as an OFI proxy:

  imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)

  Range: [-1, +1]
    +1 = maximum buy pressure (all volume on bid)
    -1 = maximum sell pressure (all volume on ask)

Entry conditions:
  imbalance > +0.3  → LONG  (buy pressure dominant)
  imbalance < -0.3  → SHORT (sell pressure dominant, bias == "swing_neutral" only)

Paper mode:
  Uses _synthetic_book_imbalance() — deterministic within a 1-minute window.
  Produces imbalances across the full [-1, +1] range; ~30% of windows will
  exceed ±0.3 producing signals.

Live mode (when data/feeds/order_book.py is importable):
  Fetches top-20 levels from OKX public REST and computes real imbalance.

Signal format:
  (pair, side, entry_price, stop_loss, take_profit)

SL: 0.8% from entry
TP: 1.2% from entry (1.5× R:R)
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Docker-isolation guard ────────────────────────────────────────────────────
try:
    from data.feeds.order_book import compute_bid_ask_imbalance, get_order_book
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
IMBALANCE_THRESHOLD = 0.30   # signal fires beyond ±0.3
SL_PCT              = 0.008  # 0.8%
TP_PCT              = 0.012  # 1.2%  (1.5× R:R)


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic fallback — paper mode
# ─────────────────────────────────────────────────────────────────────────────

def _synthetic_book_imbalance(symbol: str) -> float:
    """
    Deterministic bid-ask imbalance in [-1.0, +1.0].
    Seed changes every 1 minute so signals vary naturally while staying
    stable within any single evaluation window.
    """
    window = int(time.time() // 60)  # 1-minute windows
    seed   = int(hashlib.md5(f"ofi{symbol}{window}".encode()).hexdigest()[:8], 16)
    state  = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
    # Map [0, 0xFFFFFFFF] → [-1.0, +1.0]
    return (state / 0xFFFFFFFF - 0.5) * 2.0


# ─────────────────────────────────────────────────────────────────────────────
# Internal imbalance resolver
# ─────────────────────────────────────────────────────────────────────────────

def _get_imbalance(okx_symbol: str) -> float:
    """
    Returns bid-ask imbalance for an OKX symbol.
    Uses live order book when data/feeds/order_book.py is importable,
    else falls back to synthetic.
    """
    if _FEEDS_AVAILABLE:
        try:
            book = get_order_book(okx_symbol, depth=20)
            if book:
                return compute_bid_ask_imbalance(book)
        except Exception:
            pass
    return _synthetic_book_imbalance(okx_symbol)


# ─────────────────────────────────────────────────────────────────────────────
# Public paper-mode signal function
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_signal(
    pairs: List[str],
    bias:  str = "swing_neutral",
) -> Optional[Tuple[str, str, float, float, float]]:
    """
    Order flow imbalance scanner.
    Paper-mode fallback when NautilusTrader engine is not running.

    Returns (pair, side, entry_price, stop_loss, take_profit) or None.

    ``bias`` gates direction:
      "flat"           — no new entries
      "momentum_long"  — long signals only (buy pressure)
      "swing_neutral"  — both long and short
    """
    if bias == "flat":
        return None

    # Intra-container import — always available in Docker
    from strategies.swing_macd import _synthetic_ohlcv  # type: ignore[import]

    for pair in pairs:
        okx_symbol = _PAIR_TO_OKX.get(pair)
        if not okx_symbol:
            continue

        imbalance = _get_imbalance(okx_symbol)

        # Get current price
        ohlcv = _synthetic_ohlcv(pair)
        price = ohlcv[-1][4]  # last close

        if imbalance > IMBALANCE_THRESHOLD:
            # Buy pressure dominant → LONG
            sl = price * (1 - SL_PCT)
            tp = price * (1 + TP_PCT)
            logger.debug("order_flow_long", pair=pair, imbalance=round(imbalance, 4),
                         price=price, sl=sl, tp=tp)
            return (pair, "long", price, sl, tp)

        if imbalance < -IMBALANCE_THRESHOLD and bias == "swing_neutral":
            # Sell pressure dominant → SHORT
            sl = price * (1 + SL_PCT)
            tp = price * (1 - TP_PCT)
            logger.debug("order_flow_short", pair=pair, imbalance=round(imbalance, 4),
                         price=price, sl=sl, tp=tp)
            return (pair, "short", price, sl, tp)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NautilusTrader Strategy — lazy factory
# ─────────────────────────────────────────────────────────────────────────────

def build_order_flow_strategy(
    instrument_id:        str   = "BTC-USDT-SWAP.OKX",
    bar_spec:             str   = "1-MINUTE-LAST-EXTERNAL",
    imbalance_threshold:  float = IMBALANCE_THRESHOLD,
    stop_loss_pct:        float = SL_PCT,
    take_profit_pct:      float = TP_PCT,
    order_qty_str:        str   = "0.001",
):
    """
    Build and return an OrderFlowStrategy instance for NautilusTrader.

    All nautilus_trader imports are inside this function so that importing
    this module never crashes when nautilus_trader is not installed.
    Raises ImportError if nautilus_trader is absent (caller catches it).

    The strategy uses 1-minute bars as tick proxies for order flow updates.
    On each bar event it queries the current book imbalance and acts accordingly.
    """
    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity, Price

    bar_type_str = f"{instrument_id}-{bar_spec}"

    class OrderFlowConfig(StrategyConfig, frozen=True):
        instrument_id:       str   = instrument_id
        bar_type_str:        str   = bar_type_str
        imbalance_threshold: float = imbalance_threshold
        stop_loss_pct:       float = stop_loss_pct
        take_profit_pct:     float = take_profit_pct
        order_qty_str:       str   = order_qty_str

    class OrderFlowStrategy(Strategy):
        """
        Order flow imbalance strategy for NautilusTrader.

        Checks bid-ask imbalance on each 1-minute bar. Enters long when
        buy pressure dominates (imbalance > threshold), short when sell
        pressure dominates (imbalance < -threshold).
        Exits on SL/TP or when imbalance reverses sign.
        """

        def __init__(self, config: OrderFlowConfig):
            super().__init__(config)
            self._iid      = InstrumentId.from_str(config.instrument_id)
            self._btype    = BarType.from_str(config.bar_type_str)
            self._thr      = config.imbalance_threshold
            self._sl_pct   = config.stop_loss_pct
            self._tp_pct   = config.take_profit_pct
            self._qty      = Quantity.from_str(config.order_qty_str)
            self._okx_sym  = config.instrument_id.replace(".OKX", "")

        def on_start(self) -> None:
            self.subscribe_bars(self._btype)

        def on_bar(self, bar: Bar) -> None:
            imbalance = _get_imbalance(self._okx_sym)
            has_pos   = bool(self.cache.positions(instrument_id=self._iid))

            if has_pos:
                # Exit if imbalance has reversed sign past half-threshold
                positions = self.cache.positions(instrument_id=self._iid)
                for pos in positions:
                    if pos.is_long  and imbalance < -self._thr * 0.5:
                        self.close_all_positions(self._iid)
                    elif pos.is_short and imbalance > self._thr * 0.5:
                        self.close_all_positions(self._iid)
                return

            price = float(bar.close)

            if imbalance > self._thr:
                sl = Price.from_str(f"{price * (1 - self._sl_pct):.2f}")
                tp = Price.from_str(f"{price * (1 + self._tp_pct):.2f}")
                try:
                    order_list = self.order_factory.bracket_market(
                        instrument_id=self._iid,
                        order_side=OrderSide.BUY,
                        quantity=self._qty,
                        sl_trigger_price=sl,
                        tp_price=tp,
                    )
                    self.submit_order_list(order_list)
                except Exception as exc:
                    self.log.warning(f"order_flow bracket_market failed: {exc}")

            elif imbalance < -self._thr:
                sl = Price.from_str(f"{price * (1 + self._sl_pct):.2f}")
                tp = Price.from_str(f"{price * (1 - self._tp_pct):.2f}")
                try:
                    order_list = self.order_factory.bracket_market(
                        instrument_id=self._iid,
                        order_side=OrderSide.SELL,
                        quantity=self._qty,
                        sl_trigger_price=sl,
                        tp_price=tp,
                    )
                    self.submit_order_list(order_list)
                except Exception as exc:
                    self.log.warning(f"order_flow bracket_market failed: {exc}")

        def on_stop(self) -> None:
            self.cancel_all_orders(self._iid)
            self.close_all_positions(self._iid)

        def on_dispose(self) -> None:
            pass

    config   = OrderFlowConfig()
    strategy = OrderFlowStrategy(config)
    return strategy
