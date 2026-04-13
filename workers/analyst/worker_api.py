"""
workers/analyst/worker_api.py

Analyst Worker — AI Advisory Pipeline with OSINT Domain Routing.
FastAPI service running on port 8003.

What this does:
    Runs a single-prompt LLM advisory pipeline via Ollama.
    Accepts macro snapshots, regime signals, and OSINT domain decisions
    from the Hypervisor. Returns advisory signals with domain-level
    context: which market domains are safe, which are at risk.
    NEVER executes orders. advisory_only = True always.

LLM backend:
    Uses Ollama directly via ollama_patch.py.
    Model configured via OLLAMA_MODEL env var (default: qwen3:4b).

Domain routing integration:
    POST /signal now accepts optional "domain_decisions" field:
      [{"domain": str, "action": str, "weight_modifier": float, "rationale": str}]
    These are included in the LLM prompt to generate domain-aware thesis.

REST contract (Arka standard):
    GET  /health    liveness + agent status
    GET  /status    current regime, last signal, uptime
    GET  /metrics   Prometheus text format
    POST /signal    run advisory pipeline, return recommendations
    POST /execute   always returns advisory_only — never executes
    POST /pause     halt analysis cycles
    POST /resume    re-enable analysis
    POST /regime    update regime framing for agent prompts
    POST /allocate  receive capital allocation from hypervisor
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI
from fastapi.responses import Response

from ollama_patch import call_ollama, OLLAMA_MODEL, OLLAMA_HOST

logger = structlog.get_logger(__name__)

WORKER_NAME = "analyst"

# ── Regime-specific system prompts (4-state HMM) ─────────────────────────────

REGIME_PROMPTS: Dict[str, str] = {
    "RISK_ON": (
        "You are a risk-first portfolio advisor. Current regime: RISK_ON. "
        "Markets are bullish and volatility is low. "
        "Focus on: (1) momentum strategies in trending assets, "
        "(2) balanced portfolio optimization, "
        "(3) capturing systematic alpha. Appropriate risk sizing."
    ),
    "RISK_OFF": (
        "You are a risk-first portfolio advisor. Current regime: RISK_OFF. "
        "Elevated volatility, deteriorating macro conditions. "
        "Focus on: (1) reducing directional exposure, "
        "(2) defensive rotation into safe assets, "
        "(3) tighter stop-losses and smaller position sizes."
    ),
    "CRISIS": (
        "You are a risk-first portfolio advisor. Current regime: CRISIS. "
        "Market panic. VIX is spiking. Capital preservation is the only goal. "
        "Focus on: (1) what positions should be closed or hedged immediately, "
        "(2) minimum safe cash buffer, (3) delta-neutral strategies only. "
        "Do NOT recommend new long positions."
    ),
    "TRANSITION": (
        "You are a risk-first portfolio advisor. Current regime: TRANSITION. "
        "Markets in transition. Direction unclear. Mixed signals. "
        "Focus on: (1) delta-neutral strategies, (2) reducing directional exposure, "
        "(3) monitoring signals for the next regime. Caution above all."
    ),
}


def _format_domain_context(domain_decisions: List[dict]) -> str:
    """Format domain routing decisions into a concise LLM prompt section."""
    if not domain_decisions:
        return ""

    lines = ["OSINT Domain Intelligence:"]
    for d in domain_decisions:
        action   = d.get("action", "hold")
        domain   = d.get("domain", "?")
        mod      = d.get("weight_modifier", 1.0)
        rationale = d.get("rationale", "")
        lines.append(f"  {domain}: {action.upper()} (x{mod:.1f}) — {rationale[:100]}")

    return "\n".join(lines)


class AdvisorState:
    """Holds all mutable state for the advisory pipeline."""

    def __init__(self):
        self.current_regime:      str             = "TRANSITION"
        self.paused:              bool            = False
        self.last_signal:         Optional[dict]  = None
        self.last_signal_time:    float           = 0.0
        self.signals_generated:   int             = 0
        self.allocated_usd:       float           = 0.0
        self.start_time:          float           = time.time()
        self.last_domain_decisions: List[dict]    = []

    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    def is_healthy(self) -> bool:
        return OLLAMA_HOST is not None

    async def run_pipeline(
        self,
        ticker:           str,
        context:          str,
        regime:           str,
        domain_decisions: List[dict] | None = None,
    ) -> Dict[str, Any]:
        """
        Run the advisory pipeline via direct Ollama call.
        Returns a structured advisory dict with domain context.
        """
        system_prompt    = REGIME_PROMPTS.get(regime, REGIME_PROMPTS["TRANSITION"])
        domain_context   = _format_domain_context(domain_decisions or [])
        start            = time.time()

        result = await asyncio.get_running_loop().run_in_executor(
            None, self._run_ollama, ticker, context, system_prompt, domain_context
        )

        latency_ms = int((time.time() - start) * 1000)
        result["latency_ms"]       = latency_ms
        result["regime"]           = regime
        result["ticker"]           = ticker
        result["advisory_only"]    = True
        result["model"]            = OLLAMA_MODEL
        result["domain_decisions"] = domain_decisions or []

        self.last_signal      = result
        self.last_signal_time = time.time()
        self.signals_generated += 1

        return result

    def _run_ollama(
        self,
        ticker:         str,
        context:        str,
        system_prompt:  str,
        domain_context: str,
    ) -> Dict[str, Any]:
        """Single-prompt Ollama call: regime + OSINT domain context → advisory."""
        domain_section = f"\n{domain_context}\n" if domain_context else ""
        prompt = (
            f"{system_prompt}\n\n"
            f"Asset: {ticker}\n"
            f"Market context: {context}\n"
            f"{domain_section}\n"
            "Respond with exactly 4 lines:\n"
            "ACTION: (long | short | neutral | hedge)\n"
            "CONFIDENCE: (0.0 to 1.0)\n"
            "SIZE_PCT: (0.0 to 1.0, fraction of allocated capital)\n"
            "RATIONALE: (one sentence incorporating domain intelligence if relevant)\n"
        )
        raw    = call_ollama(prompt)
        parsed = self._parse_structured_response(raw)
        return {
            "source": "ollama_direct",
            "raw":    raw[:500],
            **parsed,
        }

    @staticmethod
    def _parse_structured_response(text: str) -> Dict[str, Any]:
        """Parse the 4-line structured response."""
        result = {
            "action":             "neutral",
            "confidence":         0.5,
            "suggested_size_pct": 0.05,
            "rationale":          "No rationale extracted.",
        }
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("ACTION:"):
                val = line.split(":", 1)[-1].strip().lower()
                if val in ("long", "short", "hedge", "neutral"):
                    result["action"] = val
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    result["confidence"] = min(1.0, float(line.split(":", 1)[-1].strip()))
                except ValueError:
                    pass
            elif line.upper().startswith("SIZE_PCT:"):
                try:
                    result["suggested_size_pct"] = min(1.0, float(line.split(":", 1)[-1].strip()))
                except ValueError:
                    pass
            elif line.upper().startswith("RATIONALE:"):
                result["rationale"] = line.split(":", 1)[-1].strip()[:300]
        return result


# ── Application State ─────────────────────────────────────────────────────────

state = AdvisorState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("analyst_worker_starting", ollama=OLLAMA_HOST, model=OLLAMA_MODEL)
    yield
    logger.info("analyst_worker_shutdown")


app = FastAPI(lifespan=lifespan)


# ── REST Contract ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status":  "ok" if state.is_healthy() else "degraded",
        "worker":  WORKER_NAME,
        "paused":  state.paused,
        "regime":  state.current_regime,
        "model":   OLLAMA_MODEL,
        "backend": OLLAMA_HOST,
    }


@app.get("/status")
def status():
    return {
        "worker":             WORKER_NAME,
        "regime":             state.current_regime,
        "paused":             state.paused,
        "signals_generated":  state.signals_generated,
        "last_signal_age_s":  round(time.time() - state.last_signal_time, 1)
                              if state.last_signal_time else None,
        "last_signal":        state.last_signal,
        "uptime_s":           round(state.uptime_seconds(), 1),
        "advisory_only":      True,
        "pnl":                0.0,
        "sharpe":             0.0,
        "allocated_usd":      state.allocated_usd,
        "open_positions":     0,
    }


@app.post("/signal")
async def signal(body: dict):
    if state.paused:
        return []

    regime           = body.get("regime", state.current_regime)
    snapshot         = body.get("snapshot", {})
    tickers          = body.get("tickers", ["PORTFOLIO"])
    domain_decisions = body.get("domain_decisions", state.last_domain_decisions)

    # Store latest domain decisions for future calls
    if body.get("domain_decisions"):
        state.last_domain_decisions = domain_decisions

    context = (
        f"VIX={snapshot.get('vix', '?')} | "
        f"Gold/Oil={snapshot.get('gold_oil_ratio', '?')} | "
        f"BDI slope={snapshot.get('bdi_slope_12w', '?')} | "
        f"Yield curve={snapshot.get('yield_curve', '?')} | "
        f"Defense momentum={snapshot.get('defense_momentum_20d', '?')} | "
        f"BTC funding={snapshot.get('btc_funding_rate', '?')}"
    )

    signals = []
    for ticker in tickers[:3]:
        advisory = await state.run_pipeline(
            ticker, context, regime, domain_decisions
        )
        signals.append({
            "worker":             WORKER_NAME,
            "symbol":             ticker,
            "direction":          advisory.get("action", "neutral"),
            "confidence":         advisory.get("confidence", 0.5),
            "suggested_size_pct": advisory.get("suggested_size_pct", 0.05),
            "regime_tags":        [regime],
            "ttl_seconds":        300,
            "advisory_only":      True,
            "rationale":          advisory.get("rationale", ""),
            "latency_ms":         advisory.get("latency_ms", 0),
            "source":             advisory.get("source", "ollama_direct"),
            "domain_decisions":   domain_decisions,
        })

    logger.info("signals_generated", count=len(signals), regime=regime,
                domain_decisions_count=len(domain_decisions))
    return signals


@app.post("/execute")
def execute(body: dict):
    return {
        "status":        "advisory_only",
        "worker":        WORKER_NAME,
        "message":       "Analyst is advisory-only. Use Nautilus for execution.",
        "last_advisory": state.last_signal,
    }


@app.post("/regime")
async def update_regime(body: dict):
    new_regime = body.get("regime")
    if not new_regime or new_regime == state.current_regime:
        return {"status": "no_change"}

    old_regime = state.current_regime
    state.current_regime = new_regime
    logger.info("regime_updated", old=old_regime, new=new_regime)
    return {"status": "updated", "regime": new_regime}


@app.post("/allocate")
async def allocate(body: dict):
    amount = float(body.get("amount_usd") or 0.0)
    state.allocated_usd = amount
    return {"status": "ok", "worker": WORKER_NAME, "allocated_usd": amount}


@app.post("/pause")
def pause():
    state.paused = True
    logger.info("analyst_paused")
    return {"status": "paused"}


@app.post("/resume")
def resume():
    state.paused = False
    logger.info("analyst_resumed")
    return {"status": "resumed"}


@app.get("/metrics")
def metrics():
    active = 0 if state.paused else 1
    content = (
        f'arka_worker_active{{worker="analyst"}} {active}\n'
        f'arka_analyst_signals_total {state.signals_generated}\n'
        f'arka_analyst_uptime_seconds {state.uptime_seconds():.1f}\n'
    )
    return Response(content=content, media_type="text/plain")
