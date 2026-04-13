"""
workers/arbitrader/sidecar/main.py

NautilusTrader-based statistical arbitrage worker — FastAPI sidecar on port 8004.

Replaces the former Java Arbitrader + Python sidecar architecture.
The JVM is no longer involved.  All arb detection and paper order management
runs in pure Python / NautilusTrader.

Strategy:
  Subscribes to trade ticks for two correlated OKX instruments (e.g.
  BTC-USDT-SWAP and ETH-USDT-SWAP).  Tracks the rolling spread between
  their mid-prices.  When the spread deviates > ARB_Z_THRESHOLD standard
  deviations from its 60-tick rolling mean, a market-neutral pair trade
  is submitted: long the cheap leg, short the expensive one.
  Exit: spread reverts to within ARB_REVERT_Z of the mean.

Paper mode (default):
  ArbitrageEngine skips NT startup if credentials are absent; the internal
  paper arb simulator fires synthetic spread signals for testing.

REST contract (full Arka standard):
    GET  /health
    GET  /status     pnl, sharpe, allocated_usd, open_positions
    GET  /metrics    Prometheus text (plain/text, not JSON)
    POST /regime
    POST /allocate
    POST /signal
    POST /execute
    POST /pause
    POST /resume

Env vars:
    OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE
    PAPER_TRADING=true
    ARB_LEG_A=BTC-USDT-SWAP.OKX
    ARB_LEG_B=ETH-USDT-SWAP.OKX
    ARB_Z_THRESHOLD=2.0      (z-score entry threshold)
    ARB_REVERT_Z=0.5         (z-score exit threshold)
    ARB_WINDOW=60            (rolling window in ticks)
    ARB_ORDER_QTY_A=0.001
    ARB_ORDER_QTY_B=0.01
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI
from fastapi.responses import Response

logger = structlog.get_logger(__name__)

WORKER_NAME = "arbitrader"

# ── Regime bias ───────────────────────────────────────────────────────────────
REGIME_BIAS: Dict[str, str] = {
    "RISK_ON":    "active",    # Normal arb exposure
    "RISK_OFF":   "reduced",   # Smaller size
    "CRISIS":     "flat",      # No new entries
    "TRANSITION": "reduced",
}


# ─────────────────────────────────────────────────────────────────────────────
# Paper arb simulator
# ─────────────────────────────────────────────────────────────────────────────

def _synthetic_spread(window: int = 60) -> float:
    """Deterministic spread value for paper mode (changes each minute)."""
    import hashlib
    tick = int(time.time() // 60)
    seed = int(hashlib.md5(f"arb{tick}".encode()).hexdigest()[:8], 16)
    # Spread oscillates around 0, occasionally exceeds ±2σ
    val  = (seed / 0xFFFFFFFF - 0.5) * 4.0   # range ~[-2, +2]
    return val


# ─────────────────────────────────────────────────────────────────────────────
# Worker state
# ─────────────────────────────────────────────────────────────────────────────

class ArbState:
    def __init__(self):
        self.allocated_usd:   float = 0.0
        self.paper_trading:   bool  = True
        self.current_regime:  str   = "TRANSITION"
        self.bias:            str   = "reduced"
        self.paused:          bool  = False
        self.open_positions:  int   = 0
        self.realised_pnl:    float = 0.0
        self.unrealised_pnl:  float = 0.0
        self.trade_count:     int   = 0
        self.win_count:       int   = 0
        self.returns_log:     List[float] = []
        self.engine_ready:    bool  = False
        self.engine_error:    Optional[str] = None
        self.start_time:      float = time.time()
        # Active paper position: {"side": "long_a_short_b"|"short_a_long_b",
        #                         "entry_spread": float, "size_usd": float}
        self._paper_position: Optional[Dict] = None

    def sharpe(self) -> float:
        if len(self.returns_log) < 5:
            return 0.0
        import statistics
        mean = sum(self.returns_log) / len(self.returns_log)
        try:
            std = statistics.stdev(self.returns_log)
        except Exception:
            return 0.0
        if std < 1e-12:
            return 0.0
        return (mean / std) * math.sqrt(252)

    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count > 0 else 0.0

    def uptime(self) -> float:
        return time.time() - self.start_time

    # ── Paper arb cycle ───────────────────────────────────────────────────────

    async def run_paper_cycle(self) -> Optional[Dict[str, Any]]:
        if self.paused or self.bias == "flat" or self.allocated_usd < 10.0:
            return None

        z_entry  = float(os.environ.get("ARB_Z_THRESHOLD", "2.0"))
        z_revert = float(os.environ.get("ARB_REVERT_Z",    "0.5"))
        spread   = _synthetic_spread()

        # Exit existing position if spread has reverted
        if self._paper_position is not None:
            pos = self._paper_position
            if abs(spread) < z_revert:
                entry = pos["entry_spread"]
                pnl   = pos["size_usd"] * abs(entry - spread) / max(abs(entry), 0.01)
                if pos["side"] == "short_a_long_b" and entry < 0:
                    pnl = -pnl
                self.realised_pnl     += pnl
                ret = pnl / pos["size_usd"]
                self.returns_log.append(ret)
                self.trade_count      += 1
                if pnl > 0:
                    self.win_count    += 1
                self._paper_position   = None
                self.open_positions    = 0
                logger.info("arb_position_closed", spread=round(spread, 4),
                            pnl=round(pnl, 4))
                return {"action": "closed", "spread": spread, "pnl": round(pnl, 4)}
            return None  # still in position, no new signal

        # Enter if spread is extreme
        if abs(spread) >= z_entry:
            size_usd = self.allocated_usd * 0.5
            side     = "long_a_short_b" if spread < 0 else "short_a_long_b"
            self._paper_position = {
                "side": side, "entry_spread": spread, "size_usd": size_usd,
                "opened_at": time.time(),
            }
            self.open_positions = 1
            logger.info("arb_position_opened", side=side,
                        spread=round(spread, 4), size_usd=size_usd)
            return {"action": "opened", "side": side, "spread": round(spread, 4),
                    "size_usd": size_usd}

        return None


state = ArbState()
_engine_task: Optional[asyncio.Task] = None


# ─────────────────────────────────────────────────────────────────────────────
# ArbitrageEngine — NautilusTrader TradingNode lifecycle
# ─────────────────────────────────────────────────────────────────────────────

async def _run_nt_engine() -> None:
    """
    Start a NautilusTrader TradingNode for live pair arb on OKX.
    Silently returns if credentials are missing or NT is not installed.
    """
    api_key    = os.environ.get("OKX_API_KEY",        "")
    api_secret = os.environ.get("OKX_API_SECRET",     "")
    passphrase = os.environ.get("OKX_API_PASSPHRASE", "")
    paper      = os.environ.get("PAPER_TRADING",      "true").lower() == "true"

    if not (api_key and api_secret and passphrase):
        state.engine_error = "OKX credentials not set — paper arb simulator active"
        logger.info("arbitrader_engine_skipped", reason="no_okx_credentials")
        return

    try:
        from nautilus_trader.config import (
            TradingNodeConfig,
            LiveDataEngineConfig,
            LiveExecEngineConfig,
            StrategyConfig,
        )
        from nautilus_trader.live.node import TradingNode
        from nautilus_trader.adapters.okx.config import (
            OKXDataClientConfig,
            OKXExecClientConfig,
        )
        from nautilus_trader.adapters.okx.factories import (
            OKXLiveDataClientFactory,
            OKXLiveExecClientFactory,
        )
        from nautilus_trader.trading.strategy import Strategy
        from nautilus_trader.model.data import QuoteTick
        from nautilus_trader.model.identifiers import InstrumentId
        from nautilus_trader.model.enums import OrderSide
        from nautilus_trader.model.objects import Quantity, Price
    except ImportError as exc:
        state.engine_error = f"nautilus_trader not installed: {exc}"
        logger.warning("arbitrader_import_failed", error=str(exc))
        return

    leg_a = os.environ.get("ARB_LEG_A", "BTC-USDT-SWAP.OKX")
    leg_b = os.environ.get("ARB_LEG_B", "ETH-USDT-SWAP.OKX")
    z_thr = float(os.environ.get("ARB_Z_THRESHOLD", "2.0"))
    z_rev = float(os.environ.get("ARB_REVERT_Z",    "0.5"))
    win   = int(os.environ.get("ARB_WINDOW",         "60"))
    qty_a = os.environ.get("ARB_ORDER_QTY_A", "0.001")
    qty_b = os.environ.get("ARB_ORDER_QTY_B", "0.01")

    # ── Define the pair-arb strategy ─────────────────────────────────────────
    class PairArbConfig(StrategyConfig, frozen=True):
        leg_a:          str   = leg_a
        leg_b:          str   = leg_b
        z_threshold:    float = z_thr
        z_revert:       float = z_rev
        window:         int   = win
        order_qty_a:    str   = qty_a
        order_qty_b:    str   = qty_b

    class PairArbStrategy(Strategy):
        """
        Market-neutral pair arb on two OKX perp instruments.
        Subscribes to quote ticks for both legs.  Maintains a rolling
        spread buffer, z-scores it, and fires bracket trades on extremes.
        """

        def __init__(self, config: PairArbConfig):
            super().__init__(config)
            self._iid_a    = InstrumentId.from_str(config.leg_a)
            self._iid_b    = InstrumentId.from_str(config.leg_b)
            self._z        = config.z_threshold
            self._z_rev    = config.z_revert
            self._window   = config.window
            self._qty_a    = Quantity.from_str(config.order_qty_a)
            self._qty_b    = Quantity.from_str(config.order_qty_b)
            self._spreads: List[float] = []
            self._mid_a:   Optional[float] = None
            self._mid_b:   Optional[float] = None
            self._in_pos:  bool = False

        def on_start(self) -> None:
            self.subscribe_quote_ticks(self._iid_a)
            self.subscribe_quote_ticks(self._iid_b)

        def on_quote_tick(self, tick: QuoteTick) -> None:
            mid = (float(tick.bid_price) + float(tick.ask_price)) / 2.0
            if tick.instrument_id == self._iid_a:
                self._mid_a = mid
            elif tick.instrument_id == self._iid_b:
                self._mid_b = mid

            if self._mid_a is None or self._mid_b is None:
                return

            # Spread = log(A) - log(B)  (log ratio is stationary for correlated assets)
            spread = math.log(self._mid_a) - math.log(self._mid_b)
            self._spreads.append(spread)
            if len(self._spreads) > self._window:
                self._spreads.pop(0)

            if len(self._spreads) < self._window:
                return

            mean  = sum(self._spreads) / len(self._spreads)
            var   = sum((s - mean) ** 2 for s in self._spreads) / len(self._spreads)
            # Skip when spread is effectively flat: using a 1e-6 sigma floor here
            # would turn any tiny deviation into a multi-million z-score and fire a
            # false arb entry.  Insufficient variance means no tradeable dislocation.
            if var < 1e-12:
                return
            sigma = math.sqrt(var)
            z     = (spread - mean) / sigma

            if self._in_pos:
                if abs(z) < self._z_rev:
                    self.close_all_positions(self._iid_a)
                    self.close_all_positions(self._iid_b)
                    self._in_pos = False
            else:
                if z > self._z:    # A expensive vs B → short A, long B
                    self._enter(OrderSide.SELL, OrderSide.BUY)
                elif z < -self._z: # A cheap vs B → long A, short B
                    self._enter(OrderSide.BUY, OrderSide.SELL)

        def _enter(self, side_a: "OrderSide", side_b: "OrderSide") -> None:
            try:
                self.submit_order(self.order_factory.market(
                    instrument_id=self._iid_a,
                    order_side=side_a,
                    quantity=self._qty_a,
                ))
                self.submit_order(self.order_factory.market(
                    instrument_id=self._iid_b,
                    order_side=side_b,
                    quantity=self._qty_b,
                ))
                self._in_pos = True
            except Exception as exc:
                self.log.warning(f"pair arb entry failed: {exc}")

        def on_stop(self) -> None:
            self.cancel_all_orders(self._iid_a)
            self.cancel_all_orders(self._iid_b)
            self.close_all_positions(self._iid_a)
            self.close_all_positions(self._iid_b)

        def on_dispose(self) -> None:
            pass

    # ── Boot TradingNode ──────────────────────────────────────────────────────
    try:
        config = TradingNodeConfig(
            trader_id="ARKA-ARB-001",
            data_engine=LiveDataEngineConfig(qsize=10_000),
            exec_engine=LiveExecEngineConfig(qsize=10_000),
            data_clients={
                "OKX": OKXDataClientConfig(
                    api_key=api_key, api_secret=api_secret,
                    passphrase=passphrase, is_demo=paper,
                ),
            },
            exec_clients={
                "OKX": OKXExecClientConfig(
                    api_key=api_key, api_secret=api_secret,
                    passphrase=passphrase, is_demo=paper,
                ),
            },
        )
        node = TradingNode(config=config)
        node.add_data_client_factory("OKX", OKXLiveDataClientFactory)
        node.add_exec_client_factory("OKX", OKXLiveExecClientFactory)
        node.trader.add_strategy(PairArbStrategy(PairArbConfig()))
        node.build()
        state.engine_ready = True
        logger.info("arbitrader_engine_started", leg_a=leg_a, leg_b=leg_b, paper=paper)
        await node.run_async()
    except Exception as exc:
        state.engine_error = f"engine runtime error: {exc}"
        logger.error("arbitrader_engine_error", error=str(exc))
    finally:
        state.engine_ready = False


# ─────────────────────────────────────────────────────────────────────────────
# App lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine_task
    logger.info("arbitrader_worker_starting")

    _engine_task = asyncio.create_task(_run_nt_engine(), name="arb-engine")
    await asyncio.sleep(0.1)   # let engine detect missing credentials

    logger.info("arbitrader_worker_ready",
                engine_ready=state.engine_ready, engine_error=state.engine_error)
    yield

    if _engine_task and not _engine_task.done():
        _engine_task.cancel()
        try:
            await asyncio.wait_for(_engine_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass

    logger.info("arbitrader_worker_shutdown",
                trades=state.trade_count, pnl=round(state.realised_pnl, 4))


app = FastAPI(lifespan=lifespan)


# ─────────────────────────────────────────────────────────────────────────────
# REST Contract
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status":         "ok",
        "worker":         WORKER_NAME,
        "paused":         state.paused,
        "regime":         state.current_regime,
        "engine_ready":   state.engine_ready,
        "engine_error":   state.engine_error,
        "open_positions": state.open_positions,
    }


@app.get("/status")
def status():
    return {
        "worker":         WORKER_NAME,
        "regime":         state.current_regime,
        "paused":         state.paused,
        "allocated_usd":  round(state.allocated_usd, 2),
        "pnl":            round(state.realised_pnl + state.unrealised_pnl, 4),
        "realised_pnl":   round(state.realised_pnl, 4),
        "unrealised_pnl": round(state.unrealised_pnl, 4),
        "sharpe":         round(state.sharpe(), 3),
        "win_rate":       round(state.win_rate(), 3),
        "trade_count":    state.trade_count,
        "open_positions": state.open_positions,
        "engine_ready":   state.engine_ready,
        "uptime_s":       round(state.uptime(), 1),
    }


@app.post("/allocate")
async def allocate(body: dict):
    amount = float(body.get("amount_usd", 0.0))
    paper  = bool(body.get("paper_trading", True))
    state.allocated_usd = amount
    state.paper_trading = paper
    logger.info("arb_capital_allocated", amount_usd=amount, paper=paper)
    if amount >= 10.0 and not state.paused:
        result = await state.run_paper_cycle()
        if result:
            return {"status": "allocated_and_entered", "amount_usd": amount, "trade": result}
    return {"status": "allocated", "amount_usd": amount}


@app.post("/regime")
async def update_regime(body: dict):
    new_regime = body.get("regime", state.current_regime)
    state.current_regime = new_regime
    state.bias = REGIME_BIAS.get(new_regime, "reduced")
    if new_regime == "CRISIS":
        state.paused = True
    logger.info("arb_regime_updated", regime=new_regime, bias=state.bias)
    return {"status": "updated", "regime": new_regime, "bias": state.bias}


@app.post("/signal")
async def signal(body: dict):
    if state.paused or state.bias == "flat":
        return []
    leg_a = os.environ.get("ARB_LEG_A", "BTC-USDT-SWAP.OKX")
    leg_b = os.environ.get("ARB_LEG_B", "ETH-USDT-SWAP.OKX")
    spread = _synthetic_spread()
    z_thr  = float(os.environ.get("ARB_Z_THRESHOLD", "2.0"))
    if abs(spread) < z_thr:
        return []
    side = "long_a_short_b" if spread < 0 else "short_a_long_b"
    return [{
        "worker":             WORKER_NAME,
        "symbol":             f"{leg_a}|{leg_b}",
        "direction":          side,
        "confidence":         min(0.95, abs(spread) / (z_thr * 2)),
        "suggested_size_pct": 0.5,
        "regime_tags":        [state.current_regime],
        "ttl_seconds":        60,
        "rationale":          f"pair arb z={spread:.2f} threshold={z_thr}",
    }]


@app.post("/execute")
async def execute(body: dict):
    if state.paused:
        return {"status": "paused", "executed": False}
    result = await state.run_paper_cycle()
    return {"status": "executed" if result else "no_signal", "result": result}


@app.post("/pause")
def pause():
    state.paused = True
    logger.info("arbitrader_paused")
    return {"status": "paused"}


@app.post("/resume")
def resume():
    state.paused = False
    logger.info("arbitrader_resumed")
    return {"status": "resumed"}


@app.get("/metrics")
def metrics():
    active  = 0 if state.paused else 1
    content = (
        f'arka_worker_active{{worker="{WORKER_NAME}"}} {active}\n'
        f'mara_arbitrader_pnl_usd {state.realised_pnl:.4f}\n'
        f'mara_arbitrader_open_positions {state.open_positions}\n'
        f'mara_arbitrader_trade_count {state.trade_count}\n'
        f'mara_arbitrader_sharpe {state.sharpe():.4f}\n'
        f'mara_arbitrader_engine_ready {1 if state.engine_ready else 0}\n'
    )
    return Response(content=content, media_type="text/plain")
