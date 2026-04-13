"""
MARA Regime Classifier — hypervisor/regime/classifier.py

4-state Gaussian HMM-based regime classifier.  Replaces the legacy priority-
ordered threshold rule engine with a probabilistic framework.

States (4):
  RISK_ON    — low vol, positive momentum, tight spreads
  RISK_OFF   — elevated vol, negative returns, widening spreads
  CRISIS     — VIX spike, credit blowout, flight to safety
  TRANSITION — ambiguous / mixed signals, regime uncertainty

REST contract (unchanged external shape):
  GET /regime → {
      "regime":                 str,    # argmax label — backward compatible
      "confidence":             float,  # P(argmax state)
      "probabilities":          dict,   # {label: prob} for all 4 states
      "circuit_breaker_active": bool,
  }

Workers that only read the "regime" string continue to work unchanged.
The allocator reads "probabilities" for blended capital allocation.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

# Allow running standalone: python hypervisor/regime/classifier.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hypervisor.regime.feature_pipeline import FeaturePipeline
from hypervisor.regime.hmm_model import RegimeHMM, STATE_LABELS
from hypervisor.regime.circuit_breakers import apply_circuit_breakers

logger = logging.getLogger(__name__)

# Minimum context window fed to HMM for stable forward filtering.
_MIN_CONTEXT = 20


# ── Regime enum (4-state) ─────────────────────────────────────────────────────

class Regime(str, Enum):
    RISK_ON    = "RISK_ON"
    RISK_OFF   = "RISK_OFF"
    CRISIS     = "CRISIS"
    TRANSITION = "TRANSITION"


# ── RegimeResult ──────────────────────────────────────────────────────────────

@dataclass
class RegimeResult:
    regime:                 Regime
    confidence:             float          # P(argmax state) ∈ [0, 1]
    probabilities:          dict           # {label: float} for all 4 states
    circuit_breaker_active: bool  = False
    triggered_by:           list  = field(default_factory=list)
    timestamp:              float = field(default_factory=time.time)
    overridden:             bool  = False

    def to_dict(self) -> dict:
        return {
            "regime":                 self.regime.value,
            "confidence":             self.confidence,
            "probabilities":          self.probabilities,
            "circuit_breaker_active": self.circuit_breaker_active,
            "triggered_by":           self.triggered_by,
            "timestamp":              self.timestamp,
            "overridden":             self.overridden,
        }


# ── RegimeClassifier ──────────────────────────────────────────────────────────

class RegimeClassifier:
    """
    4-state HMM-based regime classifier.

    Lifecycle:
      __init__  — tries to load persisted model + feature stats from disk.
      classify_sync() — bootstraps + trains on first call if no model found.
      retrain() — monthly retrain triggered by APScheduler in hypervisor/main.py.
    """

    def __init__(self):
        self._hmm      = RegimeHMM(n_states=4)
        self._pipeline = FeaturePipeline(lookback_days=252)
        self._override: Optional[Regime] = None
        self.current:   Optional[RegimeResult] = None
        self._history:  list = []
        # z-scored context window fed to HMM for inference (grows up to 252 rows)
        self._ctx: list = []

        model_ok = self._hmm.load()
        stats_ok = self._pipeline.load_stats()
        if model_ok and stats_ok:
            logger.info("RegimeClassifier: loaded persisted HMM + feature stats")
        else:
            logger.info(
                "RegimeClassifier: no persisted model — will bootstrap on first classify()"
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def override(self, regime_name: str) -> None:
        """Manual override — persists until clear_override() is called."""
        self._override = Regime(regime_name)

    def clear_override(self) -> None:
        self._override = None

    def classify_sync(self) -> RegimeResult:
        """
        Synchronous classification entry point.
        Called by the hypervisor via asyncio.to_thread(classifier.classify_sync).

        On first call (no persisted model): bootstraps 3 years of market data,
        trains the HMM, then classifies. Subsequent calls load from disk and
        classify in <1 s (one yfinance page + FRED query).
        """
        if self._override is not None:
            return self._make_override_result()

        if not self._hmm.is_fitted:
            self._bootstrap_and_train()

        return self._classify_internal()

    async def classify(self) -> RegimeResult:
        """Async wrapper — runs classify_sync() in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.classify_sync)

    def retrain(self) -> None:
        """
        Full monthly retrain.  Fetches 3 years of fresh data, retrains HMM.
        Logs BIC for n=2..6 states so we can monitor whether 4 remains optimal.
        Called by APScheduler cron on day=1, hour=3 of each month.
        """
        logger.info("RegimeClassifier.retrain: starting monthly retrain...")
        try:
            raw_features = self._pipeline.bootstrap(years=3)
            z_features   = self._pipeline.normalize(raw_features)
            bic_results  = self._hmm.select_n_states(z_features)
            best_n = min(bic_results, key=lambda n: bic_results[n]["bic"])
            logger.info(f"RegimeClassifier.retrain: BIC-optimal n_states={best_n} "
                        f"(using n=4 regardless)")
            self._hmm.train(z_features)
            self._ctx = []   # reset context window after retrain
            logger.info("RegimeClassifier.retrain: complete")
        except Exception as e:
            logger.error(f"RegimeClassifier.retrain failed: {e}", exc_info=True)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _bootstrap_and_train(self) -> None:
        logger.info("RegimeClassifier: bootstrapping model (first run)...")
        raw_features = self._pipeline.bootstrap(years=3)
        z_features   = self._pipeline.normalize(raw_features)
        self._hmm.train(z_features)

    def _classify_internal(self) -> RegimeResult:
        # Step 1: extract z-scored feature vector for current conditions
        try:
            z_vec = self._pipeline.extract_current()  # (1, 6)
            raw   = self._pipeline.get_raw_features()
        except Exception as e:
            logger.error(f"Feature extraction failed: {e}")
            return self._held_result()

        # Step 2: grow context window (for stable HMM filtering).
        # Cap at 252 bars (1 year of trading days) as a rolling window.
        # Previously trimmed to 100 on overflow, causing a 153-bar discontinuity
        # in the forward-filter every ~252 cycles and degrading HMM accuracy.
        self._ctx.append(z_vec[0])
        if len(self._ctx) > 252:
            self._ctx = self._ctx[-252:]
        context = np.array(self._ctx)   # (T, 6)

        # Step 3: HMM posterior probabilities
        try:
            probs = self._hmm.predict_proba(context)   # (4,)
        except Exception as e:
            logger.error(f"HMM inference failed: {e}")
            return self._held_result()

        # Step 4: war premium score for circuit breakers
        war_score = 0.0
        try:
            from data.feeds.conflict_index import get_war_premium_score
            war_score = float(get_war_premium_score())
        except Exception:
            pass

        # Step 5: circuit breakers
        probs_cb, cb_active = apply_circuit_breakers(probs, raw, war_score)

        # Step 6: decode
        state_idx   = int(np.argmax(probs_cb))
        label       = STATE_LABELS[state_idx]
        confidence  = float(probs_cb[state_idx])
        probability_dict = {STATE_LABELS[i]: float(probs_cb[i]) for i in range(4)}

        triggered = ["hmm_inference"]
        if cb_active:
            triggered.append("circuit_breaker")

        result = RegimeResult(
            regime                 = Regime(label),
            confidence             = confidence,
            probabilities          = probability_dict,
            circuit_breaker_active = cb_active,
            triggered_by           = triggered,
        )
        self.current = result
        self._history.append(result)
        if len(self._history) > 100:
            self._history.pop(0)
        return result

    def _held_result(self) -> RegimeResult:
        """Return last known result, or uniform TRANSITION as safe default."""
        if self.current is not None:
            return RegimeResult(
                regime                 = self.current.regime,
                confidence             = round(self.current.confidence * 0.8, 4),
                probabilities          = self.current.probabilities,
                circuit_breaker_active = self.current.circuit_breaker_active,
                triggered_by           = ["held_on_error"],
            )
        return RegimeResult(
            regime        = Regime.TRANSITION,
            confidence    = 0.25,
            probabilities = {lbl: 0.25 for lbl in STATE_LABELS.values()},
            triggered_by  = ["fallback_uniform"],
        )

    def _make_override_result(self) -> RegimeResult:
        assert self._override is not None
        label = self._override.value
        probs = {lbl: (1.0 if lbl == label else 0.0) for lbl in STATE_LABELS.values()}
        return RegimeResult(
            regime        = self._override,
            confidence    = 1.0,
            probabilities = probs,
            triggered_by  = ["manual_override"],
            overridden    = True,
        )


# ── Standalone verification ───────────────────────────────────────────────────
# Usage: python hypervisor/regime/classifier.py

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("\n" + "=" * 60)
    print("MARA REGIME CLASSIFIER — LIVE TEST (HMM)")
    print("=" * 60)

    clf    = RegimeClassifier()
    print("\nFetching features and classifying (may bootstrap on first run)...")
    result = clf.classify_sync()

    print(f"\n  Regime:       {result.regime.value}")
    print(f"  Confidence:   {result.confidence:.1%}")
    print(f"  CB active:    {result.circuit_breaker_active}")
    print(f"  Triggered by: {result.triggered_by}")
    print(f"\n  Probabilities:")
    for lbl, p in result.probabilities.items():
        bar = "█" * int(p * 30)
        print(f"    {lbl:<12} {p:5.1%}  {bar}")
    print("=" * 60 + "\n")
