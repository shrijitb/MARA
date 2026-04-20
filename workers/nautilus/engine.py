"""
workers/nautilus/engine.py

ArcaEngine — NautilusTrader TradingNode lifecycle manager.

Modes (controlled by TRADING_MODE env var):
  swing  (default) — 4H bars, SwingMACDStrategy + RangeMeanRevertStrategy
                     routed by ADX.  Latency budget: seconds.
  day              — 1m bars, DayScalpStrategy.  Latency budget: <200ms.
  both             — registers all three strategies simultaneously.

The TradingNode runs as a background asyncio task inside FastAPI's event loop.
worker_api.py reads shared state from ArcaEngine.state for /status and /metrics.

Paper vs live:
  paper (default)  — OKX demo API (is_demo=True).  No real money.
  live             — OKX live API (is_demo=False).  Phase 3 only.
  If OKX credentials are absent the engine silently skips startup and
  worker_api.py falls back to the internal paper simulator.

Design: all nautilus_trader imports are inside methods.  Importing this
module never fails without nautilus_trader installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class EngineState:
    """Shared state that worker_api.py reads for REST responses."""

    def __init__(self):
        self.started:         bool  = False
        self.error:           Optional[str] = None
        self.pnl_usd:         float = 0.0
        self.open_positions:  int   = 0
        self.trade_count:     int   = 0
        self.win_count:       int   = 0
        self.returns_log:     List[float] = []
        # Populated by strategy callbacks
        self.active_mode:     str   = "swing"


class ArcaEngine:
    """
    NautilusTrader TradingNode lifecycle wrapper.

    Usage (from worker_api.py lifespan):
        engine = ArcaEngine(mode="swing")
        task   = asyncio.create_task(engine.run())
        # ... FastAPI serves requests, reads engine.state ...
        engine.stop()
        await asyncio.wait_for(task, timeout=5.0)
    """

    def __init__(self, mode: str = "swing"):
        self.mode:  str          = mode
        self.state: EngineState  = EngineState()
        self._node               = None
        self._stop_event         = asyncio.Event()

    # ── Build NautilusTrader TradingNodeConfig ────────────────────────────────

    def _build_config(
        self,
        api_key:    str,
        api_secret: str,
        passphrase: str,
        paper:      bool = True,
    ) -> Any:
        from nautilus_trader.config import (
            TradingNodeConfig,
            LiveDataEngineConfig,
            LiveExecEngineConfig,
        )
        from nautilus_trader.adapters.okx.config import (
            OKXDataClientConfig,
            OKXExecClientConfig,
        )

        return TradingNodeConfig(
            trader_id="ARCA-001",
            data_engine=LiveDataEngineConfig(qsize=10_000),
            exec_engine=LiveExecEngineConfig(qsize=10_000),
            data_clients={
                "OKX": OKXDataClientConfig(
                    api_key=api_key,
                    api_secret=api_secret,
                    passphrase=passphrase,
                    is_demo=paper,
                ),
            },
            exec_clients={
                "OKX": OKXExecClientConfig(
                    api_key=api_key,
                    api_secret=api_secret,
                    passphrase=passphrase,
                    is_demo=paper,
                ),
            },
        )

    # ── Strategy factory ──────────────────────────────────────────────────────

    def _build_strategies(self, allocated_usd: float) -> List[Any]:
        strategies = []
        instruments = os.environ.get(
            "OKX_INSTRUMENTS", "BTC-USDT-SWAP.OKX"
        ).split(",")
        primary_instrument = instruments[0].strip()

        if self.mode in ("swing", "both"):
            from strategies.swing_macd import build_swing_macd_strategy
            from strategies.range_mean_revert import build_range_mean_revert_strategy
            strategies.append(build_swing_macd_strategy(
                instrument_id=primary_instrument,
                stop_loss_pct=float(os.environ.get("SWING_STOP_LOSS_PCT",     "0.02")),
                take_profit_ratio=float(os.environ.get("SWING_TAKE_PROFIT_RATIO", "2.0")),
            ))
            strategies.append(build_range_mean_revert_strategy(
                instrument_id=primary_instrument,
            ))

        if self.mode in ("day", "both"):
            from strategies.day_scalp import build_day_scalp_strategy
            strategies.append(build_day_scalp_strategy(
                instrument_id=primary_instrument,
                allocated_usd=allocated_usd,
            ))

        return strategies

    # ── Main entry point — called as asyncio.create_task(engine.run()) ────────

    async def run(self, allocated_usd: float = 0.0) -> None:
        """
        Start TradingNode and block until stop() is called.
        Silently returns (sets state.error) if credentials or
        nautilus_trader are unavailable — caller falls back to paper sim.
        """
        api_key    = os.environ.get("OKX_API_KEY",        "")
        api_secret = os.environ.get("OKX_API_SECRET",     "")
        passphrase = os.environ.get("OKX_API_PASSPHRASE", "")
        paper      = os.environ.get("PAPER_TRADING",      "true").lower() == "true"

        if not (api_key and api_secret and passphrase):
            self.state.error = "OKX credentials not set — engine skipped, paper simulator active"
            logger.info("arca_engine_skipped", reason="no_okx_credentials")
            return

        try:
            from nautilus_trader.live.node import TradingNode
            from nautilus_trader.adapters.okx.factories import (
                OKXLiveDataClientFactory,
                OKXLiveExecClientFactory,
            )
        except ImportError as exc:
            self.state.error = f"nautilus_trader not installed: {exc}"
            logger.warning("arca_engine_import_failed", error=str(exc))
            return

        try:
            config     = self._build_config(api_key, api_secret, passphrase, paper)
            self._node = TradingNode(config=config)

            self._node.add_data_client_factory("OKX", OKXLiveDataClientFactory)
            self._node.add_exec_client_factory("OKX", OKXLiveExecClientFactory)

            strategies = self._build_strategies(allocated_usd)
            for strategy in strategies:
                self._node.trader.add_strategy(strategy)

            self._node.build()
            self.state.started    = True
            self.state.active_mode = self.mode
            logger.info("arca_engine_started", mode=self.mode, paper=paper,
                        n_strategies=len(strategies))

            # run_async() is a coroutine that blocks until node.stop() is called
            await self._node.run_async()

        except Exception as exc:
            self.state.error = f"engine runtime error: {exc}"
            logger.error("arca_engine_error", error=str(exc))
        finally:
            self.state.started = False

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        if self._node is not None:
            try:
                self._node.stop()
            except Exception as exc:
                logger.warning("arca_engine_stop_error", error=str(exc))

    # ── State accessors for worker_api.py ────────────────────────────────────

    def is_ready(self) -> bool:
        return self.state.started

    def get_pnl(self) -> float:
        """Read realised PnL from NautilusTrader's portfolio if available."""
        if self._node is None or not self.state.started:
            return self.state.pnl_usd
        try:
            account = self._node.portfolio.account("OKX")
            if account is not None:
                return float(account.balance_total().as_double())
        except Exception:
            pass
        return self.state.pnl_usd

    def get_open_positions(self) -> int:
        if self._node is None or not self.state.started:
            return self.state.open_positions
        try:
            return len(self._node.cache.positions_open())
        except Exception:
            return self.state.open_positions
