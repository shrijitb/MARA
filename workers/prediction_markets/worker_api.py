"""
workers/prediction_markets/worker_api.py

Prediction Markets Worker — Kalshi + Polymarket market-making stub.
FastAPI service running on port 8002.

What this does (Phase 3):
    Market-makes on binary prediction markets (Kalshi, Polymarket).
    Targets wide-spread far-book contracts where edge is highest.
    Inventory management: flat-book target after each cycle.

    In paper mode (current): tracks virtual positions and simulated PnL.
    In live mode (Phase 3): requires KALSHI_EMAIL/KALSHI_PASSWORD or
    POLY_PRIVATE_KEY to place real orders.

REST contract (Arka standard):
    GET  /health    liveness + paused state
    GET  /status    pnl, sharpe, allocated_usd, open_positions
    GET  /metrics   Prometheus text format
    POST /regime    adapt market focus to current regime
    POST /allocate  receive capital allocation from hypervisor
    POST /signal    return current open positions / advisory signals
    POST /execute   execute (paper only until Phase 3)
    POST /pause     halt new market-making
    POST /resume    resume market-making
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import Response

logger = structlog.get_logger(__name__)

WORKER_NAME = "prediction_markets"
PORT        = int(os.environ.get("PORT", 8002))

# Kalshi credentials (Phase 3)
KALSHI_EMAIL    = os.environ.get("KALSHI_EMAIL", "")
KALSHI_PASSWORD = os.environ.get("KALSHI_PASSWORD", "")

# Polymarket credentials (Phase 3)
POLY_PRIVATE_KEY = os.environ.get("POLY_PRIVATE_KEY", "")

LIVE_MODE = bool(KALSHI_EMAIL or POLY_PRIVATE_KEY)


# ── State ─────────────────────────────────────────────────────────────────────

class PredictionMarketsState:
    def __init__(self):
        self.current_regime:   str   = "TRANSITION"
        self.paused:           bool  = False
        self.allocated_usd:    float = 0.0
        self.paper_trading:    bool  = True
        self.open_positions:   int   = 0
        self.pnl:              float = 0.0
        self.sharpe:           float = 0.0
        self.trades_executed:  int   = 0
        self.start_time:       float = time.time()

    def uptime_seconds(self) -> float:
        return time.time() - self.start_time


state = PredictionMarketsState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    mode = "LIVE" if LIVE_MODE else "PAPER/STUB"
    logger.info("prediction_markets_starting", mode=mode, port=PORT)
    if not LIVE_MODE:
        logger.warning(
            "prediction_markets_stub_mode",
            reason="No KALSHI_EMAIL or POLY_PRIVATE_KEY — running as paper stub",
        )
    yield
    logger.info("prediction_markets_shutdown")


app = FastAPI(lifespan=lifespan)


# ── REST Contract ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status":      "ok",
        "worker":      WORKER_NAME,
        "paused":      state.paused,
        "regime":      state.current_regime,
        "live_mode":   LIVE_MODE,
        "paper_trading": state.paper_trading,
    }


@app.get("/status")
def status():
    return {
        "worker":          WORKER_NAME,
        "regime":          state.current_regime,
        "paused":          state.paused,
        "pnl":             round(state.pnl, 4),
        "sharpe":          round(state.sharpe, 4),
        "allocated_usd":   round(state.allocated_usd, 2),
        "open_positions":  state.open_positions,
        "trades_executed": state.trades_executed,
        "uptime_s":        round(state.uptime_seconds(), 1),
        "paper_trading":   state.paper_trading,
        "live_mode":       LIVE_MODE,
    }


@app.post("/regime")
async def update_regime(body: dict):
    new_regime = body.get("regime")
    if not new_regime:
        return {"status": "no_change"}
    old_regime = state.current_regime
    state.current_regime = new_regime
    state.paper_trading  = body.get("paper_trading", True)
    logger.info("regime_updated", old=old_regime, new=new_regime)
    return {"status": "updated", "regime": new_regime}


@app.post("/allocate")
async def allocate(body: dict):
    amount = float(body.get("amount_usd", 0.0))
    state.allocated_usd  = amount
    state.paper_trading  = body.get("paper_trading", True)
    logger.info("allocated", amount=amount, paper=state.paper_trading)
    return {"status": "ok", "worker": WORKER_NAME, "allocated_usd": amount}


@app.post("/signal")
async def signal(body: dict):
    if state.paused:
        return []
    # Phase 3: query Kalshi/Polymarket for current open positions / best opportunities
    return []


@app.post("/execute")
async def execute(body: dict):
    if state.paused:
        return {"status": "paused"}
    if not LIVE_MODE:
        return {
            "status":  "paper",
            "worker":  WORKER_NAME,
            "message": "Phase 3: requires KALSHI_EMAIL or POLY_PRIVATE_KEY",
        }
    # Phase 3: execute Kalshi/Polymarket orders
    return {"status": "ok", "worker": WORKER_NAME}


@app.post("/pause")
def pause():
    state.paused = True
    logger.info("prediction_markets_paused")
    return {"status": "paused"}


@app.post("/resume")
def resume():
    state.paused = False
    logger.info("prediction_markets_resumed")
    return {"status": "resumed"}


@app.get("/metrics")
def metrics():
    active  = 0 if state.paused else 1
    content = (
        f'arka_worker_active{{worker="prediction_markets"}} {active}\n'
        f'arka_prediction_markets_pnl {state.pnl:.4f}\n'
        f'arka_prediction_markets_open_positions {state.open_positions}\n'
        f'arka_prediction_markets_uptime_seconds {state.uptime_seconds():.1f}\n'
    )
    return Response(content=content, media_type="text/plain")
