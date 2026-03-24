"""
MARA Regime Classifier — hypervisor/regime/classifier.py

Consumes get_macro_snapshot() and classifies the current market regime.
All thresholds are loaded from config/regimes.yaml — no hardcoded values.
The Hypervisor calls classify() every heartbeat and broadcasts the result.

Regime priority order (first match wins, top = highest priority):
  WAR_PREMIUM > CRISIS_ACUTE > BEAR_RECESSION > BULL_FROTHY >
  REGIME_CHANGE > SHADOW_DRIFT > BULL_CALM (default)
"""

from __future__ import annotations

import asyncio
import time
import yaml
import sys
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# Allow running standalone: python hypervisor/regime/classifier.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data.feeds.market_data import get_macro_snapshot


# ---------------------------------------------------------------------------
# Regime enum
# ---------------------------------------------------------------------------

class Regime(str, Enum):
    WAR_PREMIUM    = "WAR_PREMIUM"
    CRISIS_ACUTE   = "CRISIS_ACUTE"
    BEAR_RECESSION = "BEAR_RECESSION"
    BULL_FROTHY    = "BULL_FROTHY"
    REGIME_CHANGE  = "REGIME_CHANGE"
    SHADOW_DRIFT   = "SHADOW_DRIFT"
    BULL_CALM      = "BULL_CALM"   # default — no other conditions met


# ---------------------------------------------------------------------------
# Snapshot dataclass — typed wrapper around get_macro_snapshot() dict
# ---------------------------------------------------------------------------

@dataclass
class MacroSnapshot:
    bdi_slope_12w:        float = 0.0
    vix:                  float = 20.0
    yield_curve:          float = 0.5
    dxy:                  float = 100.0
    gold_oil_ratio:       float = 20.0
    defense_momentum_20d: float = 0.0
    btc_funding_rate:     float = 0.0
    war_premium_score:    float = 0.0
    timestamp:            float = field(default_factory=time.time)
    errors:               list  = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "MacroSnapshot":
        return cls(
            bdi_slope_12w        = d.get("bdi_slope_12w")        or 0.0,
            vix                  = d.get("vix")                  or 20.0,
            yield_curve          = d.get("yield_curve")          or 0.5,
            dxy                  = d.get("dxy")                  or 100.0,
            gold_oil_ratio       = d.get("gold_oil_ratio")       or 20.0,
            defense_momentum_20d = d.get("defense_momentum_20d") or 0.0,
            btc_funding_rate     = d.get("btc_funding_rate")     or 0.0,
            war_premium_score    = d.get("war_premium_score")    or 0.0,
            errors               = d.get("errors")               or [],
        )

    def data_quality(self) -> float:
        """
        Returns fraction of fields that have real data (0.0 - 1.0).
        Used to decide whether to trust the classification or hold last regime.
        Below 0.5 = too many data errors, hold previous regime.
        """
        fields = [
            self.bdi_slope_12w, self.vix, self.yield_curve, self.dxy,
            self.gold_oil_ratio, self.defense_momentum_20d,
            self.btc_funding_rate,
        ]
        populated = sum(1 for f in fields if f != 0.0)
        return populated / len(fields)


# ---------------------------------------------------------------------------
# Regime classification result
# ---------------------------------------------------------------------------

@dataclass
class RegimeResult:
    regime:        Regime
    snapshot:      MacroSnapshot
    confidence:    float          # 0.0 - 1.0, based on how many signals agree
    triggered_by:  list[str]      # which conditions fired
    timestamp:     float = field(default_factory=time.time)
    overridden:    bool  = False

    def to_dict(self) -> dict:
        return {
            "regime":       self.regime.value,
            "confidence":   self.confidence,
            "triggered_by": self.triggered_by,
            "timestamp":    self.timestamp,
            "overridden":   self.overridden,
            "snapshot": {
                "bdi_slope_12w":        self.snapshot.bdi_slope_12w,
                "vix":                  self.snapshot.vix,
                "yield_curve":          self.snapshot.yield_curve,
                "dxy":                  self.snapshot.dxy,
                "gold_oil_ratio":       self.snapshot.gold_oil_ratio,
                "defense_momentum_20d": self.snapshot.defense_momentum_20d,
                "btc_funding_rate":     self.snapshot.btc_funding_rate,
                "war_premium_score":    self.snapshot.war_premium_score,
                "data_quality":         self.snapshot.data_quality(),
            },
        }


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class RegimeClassifier:
    def __init__(self, config_path: str = "config/regimes.yaml"):
        self.thresholds  = self._load_thresholds(config_path)
        self.current:    Optional[RegimeResult] = None
        self._override:  Optional[Regime]       = None
        self._history:   list[RegimeResult]     = []

    # --- Public API --------------------------------------------------------

    def override(self, regime_name: str):
        """Manual override — persists until clear_override() is called."""
        self._override = Regime(regime_name)

    def clear_override(self):
        self._override = None

    async def classify(self) -> RegimeResult:
        """
        Fetches macro snapshot and runs rule engine.
        Async because get_macro_snapshot() hits external APIs.
        Holds previous regime if data quality is too low.
        """
        loop     = asyncio.get_event_loop()
        raw      = await loop.run_in_executor(None, get_macro_snapshot)
        snapshot = MacroSnapshot.from_dict(raw)

        # Manual override takes full priority
        if self._override is not None:
            result = RegimeResult(
                regime       = self._override,
                snapshot     = snapshot,
                confidence   = 1.0,
                triggered_by = ["manual_override"],
                overridden   = True,
            )
            self.current = result
            self._history.append(result)
            return result

        # Hold last regime if data is too degraded
        if snapshot.data_quality() < 0.5 and self.current is not None:
            held = RegimeResult(
                regime       = self.current.regime,
                snapshot     = snapshot,
                confidence   = self.current.confidence * 0.8,   # decay confidence
                triggered_by = ["held_low_data_quality"],
            )
            self.current = held
            return held

        result = self._rule_engine(snapshot)
        self.current = result
        self._history.append(result)
        if len(self._history) > 100:
            self._history.pop(0)
        return result

    def classify_sync(self) -> RegimeResult:
        """Synchronous version for backtest loops and standalone testing."""
        raw      = get_macro_snapshot()
        snapshot = MacroSnapshot.from_dict(raw)
        if self._override:
            return RegimeResult(
                regime=self._override, snapshot=snapshot,
                confidence=1.0, triggered_by=["manual_override"], overridden=True
            )
        return self._rule_engine(snapshot)

    # --- Rule Engine -------------------------------------------------------

    def _rule_engine(self, s: MacroSnapshot) -> RegimeResult:
        """
        Priority-ordered rules. First match wins.
        Each rule returns (matched: bool, triggers: list[str], confidence: float).
        """
        t = self.thresholds   # shorthand

        # --- WAR_PREMIUM ---
        war_signals = []
        if s.defense_momentum_20d > t["war_defense_momentum"]:
            war_signals.append(f"defense_momentum={s.defense_momentum_20d:.4f}")
        if s.war_premium_score > t["war_premium_threshold"]:
            war_signals.append(f"war_premium_score={s.war_premium_score:.1f}")
        if s.gold_oil_ratio > t["war_gold_oil_ratio"]:
            war_signals.append(f"gold_oil_ratio={s.gold_oil_ratio:.1f}")
        if s.bdi_slope_12w > t["war_bdi_slope"]:
            war_signals.append(f"bdi_slope={s.bdi_slope_12w:.5f}")
        # Requires at least 2 of 4 signals (avoids false positives)
        if len(war_signals) >= 2:
            return RegimeResult(
                regime=Regime.WAR_PREMIUM, snapshot=s,
                confidence=min(0.5 + len(war_signals) * 0.15, 0.95),
                triggered_by=war_signals,
            )

        # --- CRISIS_ACUTE ---
        crisis_signals = []
        if s.vix > t["crisis_vix"]:
            crisis_signals.append(f"vix={s.vix:.1f}")
        if s.yield_curve < t["crisis_yield_curve"]:
            crisis_signals.append(f"yield_curve={s.yield_curve:.4f}")
        if s.bdi_slope_12w < t["crisis_bdi_slope"]:
            crisis_signals.append(f"bdi_slope={s.bdi_slope_12w:.5f}")
        if s.gold_oil_ratio > t["crisis_gold_oil_ratio"]:
            crisis_signals.append(f"gold_oil_ratio={s.gold_oil_ratio:.1f}")
        if len(crisis_signals) >= 2:
            return RegimeResult(
                regime=Regime.CRISIS_ACUTE, snapshot=s,
                confidence=min(0.5 + len(crisis_signals) * 0.15, 0.95),
                triggered_by=crisis_signals,
            )

        # --- BEAR_RECESSION ---
        bear_signals = []
        if s.yield_curve < t["bear_yield_curve"]:
            bear_signals.append(f"yield_curve={s.yield_curve:.4f}")
        if s.bdi_slope_12w < t["bear_bdi_slope"]:
            bear_signals.append(f"bdi_slope={s.bdi_slope_12w:.5f}")
        if s.btc_funding_rate < t["bear_funding_rate"]:
            bear_signals.append(f"btc_funding={s.btc_funding_rate:.6f}")
        if s.vix > t["bear_vix"]:
            bear_signals.append(f"vix={s.vix:.1f}")
        if len(bear_signals) >= 2:
            return RegimeResult(
                regime=Regime.BEAR_RECESSION, snapshot=s,
                confidence=min(0.4 + len(bear_signals) * 0.15, 0.90),
                triggered_by=bear_signals,
            )

        # --- BULL_FROTHY ---
        frothy_signals = []
        if s.vix < t["frothy_vix"]:
            frothy_signals.append(f"vix={s.vix:.1f}")
        if s.btc_funding_rate > t["frothy_funding_rate"]:
            frothy_signals.append(f"btc_funding={s.btc_funding_rate:.6f}")
        if s.dxy < t["frothy_dxy"]:
            frothy_signals.append(f"dxy={s.dxy:.1f}")
        if s.bdi_slope_12w > t["frothy_bdi_slope"]:
            frothy_signals.append(f"bdi_slope={s.bdi_slope_12w:.5f}")
        if len(frothy_signals) >= 2:
            return RegimeResult(
                regime=Regime.BULL_FROTHY, snapshot=s,
                confidence=min(0.4 + len(frothy_signals) * 0.12, 0.85),
                triggered_by=frothy_signals,
            )

        # --- REGIME_CHANGE --- (BDI diverging sharply + elevated fear)
        if abs(s.bdi_slope_12w) > t["change_bdi_slope_abs"] and s.vix > t["change_vix"]:
            return RegimeResult(
                regime=Regime.REGIME_CHANGE, snapshot=s,
                confidence=0.60,
                triggered_by=[
                    f"bdi_slope_abs={abs(s.bdi_slope_12w):.5f}",
                    f"vix={s.vix:.1f}",
                ],
            )

        # --- SHADOW_DRIFT --- (BDI moving abnormally but VIX calm = hidden pressure)
        if abs(s.bdi_slope_12w) > t["shadow_bdi_slope_abs"] and s.vix < t["shadow_vix"]:
            return RegimeResult(
                regime=Regime.SHADOW_DRIFT, snapshot=s,
                confidence=0.55,
                triggered_by=[
                    f"bdi_slope_abs={abs(s.bdi_slope_12w):.5f}",
                    f"vix={s.vix:.1f}",
                ],
            )

        # --- BULL_CALM --- default
        return RegimeResult(
            regime=Regime.BULL_CALM, snapshot=s,
            confidence=0.70,
            triggered_by=["no_stress_signals"],
        )

    # --- Config loader -----------------------------------------------------

    @staticmethod
    def _load_thresholds(config_path: str) -> dict:
        """
        Loads thresholds from config/regimes.yaml.
        Falls back to safe defaults if file missing — system still runs.
        """
        defaults = {
            # WAR_PREMIUM
            "war_defense_momentum":  0.08,
            "war_premium_threshold": 25.0,   # 28+ = current Middle East stress, ~1 = peacetime
            "war_gold_oil_ratio":    45.0,   # recalibrated from 25 — gold baseline higher
            "war_bdi_slope":         0.05,
            # CRISIS_ACUTE
            "crisis_vix":           40.0,
            "crisis_yield_curve":  -0.50,
            "crisis_bdi_slope":    -0.10,
            "crisis_gold_oil_ratio":25.0,
            # BEAR_RECESSION
            "bear_yield_curve":     0.0,
            "bear_bdi_slope":       0.0,
            "bear_funding_rate":   -0.0001,
            "bear_vix":            25.0,
            # BULL_FROTHY
            "frothy_vix":          15.0,
            "frothy_funding_rate":  0.0003,
            "frothy_dxy":         100.0,
            "frothy_bdi_slope":     0.03,
            # REGIME_CHANGE
            "change_bdi_slope_abs": 0.15,
            "change_vix":          25.0,
            # SHADOW_DRIFT
            "shadow_bdi_slope_abs": 0.08,
            "shadow_vix":          20.0,
        }
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            thresholds = cfg.get("thresholds", {})
            defaults.update(thresholds)   # override defaults with yaml values
        except FileNotFoundError:
            pass   # use defaults silently
        return defaults


# ---------------------------------------------------------------------------
# VERIFICATION — run standalone to test classification on live data
# Usage: python hypervisor/regime/classifier.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("\n" + "="*60)
    print("MARA REGIME CLASSIFIER — LIVE TEST")
    print("="*60)

    clf = RegimeClassifier()
    print("\nFetching macro snapshot and classifying...")
    result = clf.classify_sync()

    print(f"\n  Regime:      {result.regime.value}")
    print(f"  Confidence:  {result.confidence:.0%}")
    print(f"  Triggered by:")
    for t in result.triggered_by:
        print(f"    • {t}")

    print(f"\n  Snapshot:")
    snap = result.to_dict()["snapshot"]
    for k, v in snap.items():
        print(f"    {k:<28} {v}")

    print("\n" + "-"*60)
    print("Historical regime test (2020 COVID crash simulation):")
    print("Injecting CRISIS_ACUTE snapshot...")

    crisis_snap = MacroSnapshot(
        vix=65.0, yield_curve=-0.8, bdi_slope_12w=-0.15,
        gold_oil_ratio=30.0, defense_momentum_20d=0.02,
        btc_funding_rate=-0.0003, war_premium_score=5.0, dxy=103.0
    )
    crisis_result = clf._rule_engine(crisis_snap)
    status = "✅" if crisis_result.regime == Regime.CRISIS_ACUTE else "❌"
    print(f"  {status} Expected CRISIS_ACUTE, got: {crisis_result.regime.value}")

    print("\nInjecting WAR_PREMIUM snapshot...")
    war_snap = MacroSnapshot(
        vix=28.0, yield_curve=0.2, bdi_slope_12w=0.06,
        gold_oil_ratio=50.0, defense_momentum_20d=0.12,
        btc_funding_rate=0.0001, war_premium_score=55.0, dxy=101.0
    )
    war_result = clf._rule_engine(war_snap)
    status = "✅" if war_result.regime == Regime.WAR_PREMIUM else "❌"
    print(f"  {status} Expected WAR_PREMIUM, got: {war_result.regime.value}")

    print("\nInjecting BULL_CALM snapshot...")
    calm_snap = MacroSnapshot(
        vix=13.0, yield_curve=0.8, bdi_slope_12w=0.01,
        gold_oil_ratio=18.0, defense_momentum_20d=0.01,
        btc_funding_rate=0.0001, war_premium_score=3.0, dxy=101.0
    )
    calm_result = clf._rule_engine(calm_snap)
    status = "✅" if calm_result.regime == Regime.BULL_CALM else "❌"
    print(f"  {status} Expected BULL_CALM, got: {calm_result.regime.value}")

    print("="*60 + "\n")
