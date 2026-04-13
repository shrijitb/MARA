"""
data/feeds/domain_router.py

Domain Router: OSINT-driven market domain entry/exit decisions.

A "domain" is a market segment that Arka can trade:
  - crypto_perps:   OKX perpetual swaps (BTC, ETH, SOL, etc.)
  - prediction:     Kalshi + Polymarket prediction markets
  - us_equities:    Via watchlist instruments (advisory only until IBKR)
  - commodities:    Gold, oil exposure via ETF proxies
  - fixed_income:   Bond exposure via ETF proxies (defensive)

The router makes three types of decisions:
  1. ENTER:   Start allocating to a domain (opportunity detected)
  2. EXIT:    Stop allocating to a domain (risk or drawdown detected)
  3. ADJUST:  Increase or decrease domain allocation weight

Decision inputs:
  - OSINT events (from osint_processor.OSINTPipelineResult)
  - Domain performance (is Arka profitable in this domain right now?)
  - Regime probabilities (from HMM classifier)

Decision outputs:
  - DomainDecision list with weight modifiers + human-readable rationale
  - Modifiers feed into hypervisor/allocator/capital.apply_domain_overrides()

Public API:
    DomainRouter.evaluate(osint_result, edgar_signals, domain_performance, regime_probs)
        → list[DomainDecision]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class DomainAction(str, Enum):
    ENTER    = "enter"
    EXIT     = "exit"
    INCREASE = "increase"
    DECREASE = "decrease"
    HOLD     = "hold"


@dataclass
class DomainDecision:
    domain:          str
    action:          DomainAction
    weight_modifier: float       # 0.0 (exit) to 2.0 (double allocation)
    confidence:      float       # 0.0 to 1.0
    rationale:       str         # Human-readable for dashboard
    triggered_by:    list[str]   # Which OSINT sources contributed
    expires_at:      str         # ISO timestamp when to re-evaluate

    def to_dict(self) -> dict:
        return {
            "domain":          self.domain,
            "action":          self.action.value,
            "weight_modifier": round(self.weight_modifier, 3),
            "confidence":      round(self.confidence, 3),
            "rationale":       self.rationale,
            "triggered_by":    self.triggered_by,
            "expires_at":      self.expires_at,
        }


@dataclass
class DomainState:
    """Tracks performance and OSINT context per domain."""
    domain:                  str
    active:                  bool  = True
    current_pnl_pct:         float = 0.0
    pnl_7d_pct:              float = 0.0
    last_osint_score:        float = 0.0   # 0=safe, 100=dangerous
    last_opportunity_score:  float = 0.0   # 0=no opportunity, 100=strong
    consecutive_loss_days:   int   = 0
    allocation_weight:       float = 0.0


# ── Threat / opportunity mappings ─────────────────────────────────────────────

# Which event types threaten which domains
_DOMAIN_THREAT_MAP: dict[str, frozenset[str]] = {
    "crypto_perps": frozenset({"armed_conflict", "sanctions", "supply_disruption"}),
    "prediction":   frozenset({"political_instability"}),
    "us_equities":  frozenset({"political_instability", "sanctions", "corporate_event"}),
    "commodities":  frozenset({"armed_conflict", "supply_disruption",
                                "maritime_threat", "natural_disaster",
                                "infrastructure_fire", "earthquake"}),
    "fixed_income": frozenset({"natural_disaster", "earthquake"}),
}

# Which workers map to which domains (for weight override application)
DOMAIN_WORKER_MAP: dict[str, list[str]] = {
    "crypto_perps":  ["nautilus"],
    "prediction":    ["prediction_markets"],
    "us_equities":   ["analyst"],          # advisory only until IBKR
    "commodities":   ["nautilus"],          # gold/oil instruments on OKX
    "fixed_income":  ["core_dividends"],
}


def _expiry(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class DomainRouter:
    """
    Combines OSINT intelligence with performance tracking to route
    capital allocation decisions at the domain level.

    Sits between the OSINT processor and the capital allocator.
    The allocator's per-worker weights are multiplied by domain
    weight modifiers before normalisation.
    """

    def __init__(self):
        self.domain_states: dict[str, DomainState] = {
            domain: DomainState(domain=domain)
            for domain in DOMAIN_WORKER_MAP
        }

    def evaluate(
        self,
        osint_events:       list,        # list[OSINTEvent] from osint_processor
        edgar_signals:      list,        # list[dict] from edgar_client
        domain_performance: dict,        # {domain: {"pnl_pct": float, "7d_pnl": float}}
        regime_probs:       dict,        # {"RISK_ON": 0.7, "CRISIS": 0.1, ...}
    ) -> list[DomainDecision]:
        """
        Evaluate all domains and produce entry/exit/adjust decisions.

        Decision priority order:
          EXIT   > ENTER  > ADJUST > HOLD

        EXIT triggers (any one sufficient):
          1. OSINT risk score > 80 for domain-relevant events
          2. Crisis regime probability > 0.6 (exit all except fixed_income)
          3. Domain PnL < -10% over 7 days AND no positive catalyst

        ENTER triggers (all required):
          1. OSINT opportunity score > 60
          2. Domain not currently active OR recently exited
          3. Regime CRISIS probability < 0.3
          4. ≥2 OSINT sources contributing

        ADJUST triggers:
          OSINT opportunity 40-60      → 1.2x
          OSINT risk 40-60             → 0.7x
          Insider cluster buy          → 1.3x (us_equities / crypto_perps)
          8-K negative event           → 0.5x (us_equities)
        """
        decisions: list[DomainDecision] = []
        crisis_prob = max(
            regime_probs.get("CRISIS", 0.0),
            regime_probs.get("CRISIS_ACUTE", 0.0),
        )

        for domain, state in self.domain_states.items():
            # ── Update state from performance ─────────────────────────────────
            perf = domain_performance.get(domain, {})
            state.current_pnl_pct = perf.get("pnl_pct", 0.0)
            state.pnl_7d_pct      = perf.get("7d_pnl",  0.0)

            domain_risk        = self._compute_domain_risk(domain, osint_events, edgar_signals)
            domain_opportunity = self._compute_domain_opportunity(domain, osint_events, edgar_signals)
            state.last_osint_score       = domain_risk
            state.last_opportunity_score = domain_opportunity

            contributing = self._get_contributing_sources(domain, osint_events)

            # ── EXIT checks ───────────────────────────────────────────────────
            if domain_risk > 80:
                decisions.append(DomainDecision(
                    domain          = domain,
                    action          = DomainAction.EXIT,
                    weight_modifier = 0.0,
                    confidence      = min(1.0, domain_risk / 100),
                    rationale       = (
                        f"OSINT risk score {domain_risk:.0f}/100 for {domain}. "
                        f"Sources: {', '.join(contributing) or 'aggregated'}. "
                        f"Exiting to preserve capital."
                    ),
                    triggered_by    = contributing,
                    expires_at      = _expiry(4),
                ))
                state.active = False
                continue

            if crisis_prob > 0.6 and domain != "fixed_income":
                decisions.append(DomainDecision(
                    domain          = domain,
                    action          = DomainAction.DECREASE,
                    weight_modifier = 0.3,
                    confidence      = crisis_prob,
                    rationale       = (
                        f"Crisis probability {crisis_prob:.0%}. "
                        f"Reducing {domain} exposure to 30%."
                    ),
                    triggered_by    = ["regime_hmm"],
                    expires_at      = _expiry(2),
                ))
                continue

            if state.pnl_7d_pct < -10.0 and domain_opportunity < 30:
                decisions.append(DomainDecision(
                    domain          = domain,
                    action          = DomainAction.EXIT,
                    weight_modifier = 0.0,
                    confidence      = 0.8,
                    rationale       = (
                        f"{domain} down {state.pnl_7d_pct:.1f}% over 7 days "
                        f"with no recovery catalyst (opportunity={domain_opportunity:.0f}). Exiting."
                    ),
                    triggered_by    = ["performance", "no_catalyst"],
                    expires_at      = _expiry(24),
                ))
                state.active = False
                continue

            # ── ENTER checks ──────────────────────────────────────────────────
            if not state.active and domain_opportunity > 60 and crisis_prob < 0.3:
                if len(contributing) >= 2:
                    decisions.append(DomainDecision(
                        domain          = domain,
                        action          = DomainAction.ENTER,
                        weight_modifier = 1.0,
                        confidence      = domain_opportunity / 100,
                        rationale       = (
                            f"Opportunity detected in {domain} "
                            f"(score {domain_opportunity:.0f}/100). "
                            f"Re-entering with standard allocation."
                        ),
                        triggered_by    = contributing,
                        expires_at      = _expiry(12),
                    ))
                    state.active = True
                    continue

            # ── ADJUST checks ─────────────────────────────────────────────────
            modifier     = 1.0
            rationale_parts: list[str] = []

            if domain_opportunity > 40:
                modifier *= 1.2
                rationale_parts.append(f"opportunity {domain_opportunity:.0f}/100")

            if domain_risk > 40:
                modifier *= 0.7
                rationale_parts.append(f"risk {domain_risk:.0f}/100")

            for sig in edgar_signals:
                if sig.get("signal") == "insider_cluster_buy":
                    if domain in ("us_equities", "crypto_perps"):
                        modifier *= 1.3
                        rationale_parts.append(
                            f"insider cluster buy: {sig.get('ticker', '?')} "
                            f"({sig.get('count', 0)} buys)"
                        )
                elif sig.get("signal") == "insider_cluster_sell" and domain == "us_equities":
                    modifier *= 0.7
                    rationale_parts.append(f"insider cluster sell: {sig.get('ticker', '?')}")

            if abs(modifier - 1.0) > 0.05:
                action = DomainAction.INCREASE if modifier > 1.0 else DomainAction.DECREASE
                decisions.append(DomainDecision(
                    domain          = domain,
                    action          = action,
                    weight_modifier = round(modifier, 3),
                    confidence      = 0.6,
                    rationale       = (
                        f"Adjusting {domain} by {modifier:.2f}x: "
                        + (", ".join(rationale_parts) or "no specific signal")
                    ),
                    triggered_by    = contributing or ["aggregated"],
                    expires_at      = _expiry(6),
                ))
            else:
                decisions.append(DomainDecision(
                    domain          = domain,
                    action          = DomainAction.HOLD,
                    weight_modifier = 1.0,
                    confidence      = 0.5,
                    rationale       = (
                        f"{domain}: No significant signals. Maintaining allocation."
                    ),
                    triggered_by    = [],
                    expires_at      = _expiry(1),
                ))

        return decisions

    def _compute_domain_risk(
        self,
        domain:       str,
        events:       list,
        edgar_signals: list,
    ) -> float:
        """Compute 0-100 risk score for a domain from OSINT events."""
        relevant_types = _DOMAIN_THREAT_MAP.get(domain, frozenset())
        relevant = [e for e in events if e.event_type in relevant_types]
        if not relevant:
            base = 0.0
        else:
            avg_severity = sum(e.severity.value for e in relevant) / len(relevant)
            base = min(100.0, avg_severity * 11.1)

        # EDGAR risk boost for us_equities
        if domain == "us_equities":
            for sig in edgar_signals:
                if sig.get("signal") == "insider_cluster_sell":
                    base = min(100.0, base + sig.get("strength", 0.5) * 15)

        return round(base, 1)

    def _compute_domain_opportunity(
        self,
        domain:       str,
        events:       list,
        edgar_signals: list,
    ) -> float:
        """Compute 0-100 opportunity score for a domain."""
        score = 0.0

        # De-escalating conflict = recovery opportunity
        de_escalating = [e for e in events if e.escalation_trajectory == "de-escalating"]
        if de_escalating and domain in ("crypto_perps", "commodities"):
            score += min(40.0, len(de_escalating) * 15)

        # EDGAR bullish signals
        for sig in edgar_signals:
            if sig.get("signal") == "insider_cluster_buy":
                if domain == "us_equities":
                    score += sig.get("strength", 0) * 40
                elif domain == "crypto_perps":
                    score += sig.get("strength", 0) * 15

        # Low-severity stable events = background noise, slight positive for crypto
        stable_low = [
            e for e in events
            if e.escalation_trajectory == "stable" and e.severity.value <= 3
        ]
        if stable_low and domain == "crypto_perps":
            score += min(20.0, len(stable_low) * 5)

        return round(min(100.0, score), 1)

    def _get_contributing_sources(self, domain: str, events: list) -> list[str]:
        """Return list of distinct OSINT sources with domain-relevant events."""
        relevant_types = _DOMAIN_THREAT_MAP.get(domain, frozenset())
        sources = {
            e.source for e in events
            if e.event_type in relevant_types
        }
        return sorted(sources) or []


def apply_domain_overrides(
    base_allocations:  dict,
    domain_decisions:  list[DomainDecision],
    domain_worker_map: Optional[dict] = None,
) -> dict:
    """
    Multiply base allocation weights by domain router modifiers.

    After applying modifiers, re-normalise so the total deployment
    fraction stays equal to what the HMM allocator originally computed.
    Workers in domains that EXIT receive 0.0 allocation.

    Example:
        base_allocations = {"nautilus": 0.35, "prediction_markets": 0.15}
        domain_decisions includes crypto_perps EXIT (modifier=0.0)
        → nautilus becomes 0.0
        → freed capital normalised into remaining active domains

    Returns modified allocation fractions (NOT dollar amounts).
    """
    if domain_worker_map is None:
        domain_worker_map = DOMAIN_WORKER_MAP

    modified = dict(base_allocations)

    for decision in domain_decisions:
        workers = domain_worker_map.get(decision.domain, [])
        for worker in workers:
            if worker in modified:
                modified[worker] = round(
                    modified[worker] * decision.weight_modifier, 6
                )

    # Re-normalise to preserve total deployment fraction
    original_total = sum(base_allocations.values())
    new_total      = sum(modified.values())
    if new_total > 0 and original_total > 0:
        scale = original_total / new_total
        modified = {k: round(v * scale, 6) for k, v in modified.items()}

    return modified
