"""
hypervisor/allocator/capital.py

Regime-Gated Capital Allocator.

Maps the current market regime → worker allocation weights, adjusted for:
  - Worker health (unhealthy workers get 0 regardless of regime profile)
  - Worker performance (Sharpe below MIN_SHARPE cuts allocation in half)
  - Cash buffer (enforced minimum reserve, scaled up in crisis regimes)
  - Domain routing (OSINT domain decisions multiply base weights)

Worker keys match docker-compose service names exactly:
    nautilus             — NautilusTrader MACD/Fractals swing strategies (port 8001)
    prediction_markets   — Kalshi/Polymarket binary market-making stub (port 8002)
    analyst              — AI advisory pipeline via Ollama (port 8003, advisory_only)
    core_dividends       — Passive dividend sleeve: SCHD + VYM buy-and-hold (port 8006)

NOTE: swing strategies run inside NautilusTrader (workers/nautilus/) and are
allocated via the 'nautilus' key.

Domain override integration:
    from data.feeds.domain_router import apply_domain_overrides
    Use apply_domain_overrides(base_weights, domain_decisions) before passing
    weights to RegimeAllocator.compute() to incorporate OSINT domain signals.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

MIN_SHARPE_FULL_ALLOC = 1.0
MIN_SHARPE_FLOOR      = 0.5

# ── 4-state HMM allocation profiles ─────────────────────────────────────────
# Used for probability-weighted blending when the HMM classifier is active.
# Worker keys must match REGIME_PROFILES and WORKER_REGISTRY exactly.

HMM_STATE_LABELS: list = ["RISK_ON", "RISK_OFF", "CRISIS", "TRANSITION"]

ALLOCATION_PROFILES: Dict[str, Dict[str, float]] = {
    "RISK_ON": {
        # Bullish, low vol. Max directional and passive exposure.
        "nautilus":             0.44,
        "prediction_markets":   0.12,
        "analyst":              0.08,
        "core_dividends":       0.36,
    },
    "RISK_OFF": {
        # Elevated vol, deteriorating macro. Trim directional, hold passive.
        "nautilus":             0.34,
        "prediction_markets":   0.18,
        "analyst":              0.08,
        "core_dividends":       0.40,
    },
    "CRISIS": {
        # Acute stress. Reduce all directional exposure; max passive + cash.
        "nautilus":             0.10,
        "prediction_markets":   0.20,
        "analyst":              0.00,
        "core_dividends":       0.30,
    },
    "TRANSITION": {
        # Ambiguous regime. Balanced, defensive tilt.
        "nautilus":             0.32,
        "prediction_markets":   0.16,
        "analyst":              0.08,
        "core_dividends":       0.44,
    },
}

HMM_STATE_MAX_DEPLOY: Dict[str, float] = {
    "RISK_ON":    0.80,
    "RISK_OFF":   0.75,
    "CRISIS":     0.50,
    "TRANSITION": 0.70,
}

# Minimum relative weight change (fraction of total capital) that triggers a
# rebalance. Prevents excessive turnover on tiny probability shifts.
_TURNOVER_THRESHOLD = 0.02   # 2 % of total capital


def blend_allocations(
    probs: np.ndarray,
    total_capital: float,
) -> tuple:
    """
    Compute probability-weighted worker allocation weights and max-deploy fraction.

    allocation_worker = Σ_i  P(state_i) × profile_i[worker]
    max_deploy        = Σ_i  P(state_i) × HMM_STATE_MAX_DEPLOY[state_i]

    Returns:
        (blended_profile, max_deploy_fraction)
        blended_profile:    {worker: blended_weight}  — raw weights, sum ≤ 1.
        max_deploy_fraction: float representing the blended max-deploy fraction.
    """
    if len(probs) != len(HMM_STATE_LABELS):
        raise ValueError(
            f"probs length {len(probs)} != number of HMM states {len(HMM_STATE_LABELS)}"
        )

    workers = list(ALLOCATION_PROFILES[HMM_STATE_LABELS[0]].keys())
    blended: Dict[str, float] = {}
    for worker in workers:
        blended[worker] = float(sum(
            probs[i] * ALLOCATION_PROFILES[HMM_STATE_LABELS[i]][worker]
            for i in range(len(HMM_STATE_LABELS))
        ))

    max_deploy = float(sum(
        probs[i] * HMM_STATE_MAX_DEPLOY[HMM_STATE_LABELS[i]]
        for i in range(len(HMM_STATE_LABELS))
    ))

    return blended, max_deploy


@dataclass
class AllocationResult:
    regime:          str
    total_capital:   float
    max_deployable:  float
    allocations:     Dict[str, float] = field(default_factory=dict)
    skipped_workers: Dict[str, str]   = field(default_factory=dict)
    cash_reserve:    float = 0.0

    def summary(self) -> str:
        lines = [
            f"Regime: {self.regime}  |  Total: ${self.total_capital:.2f}  "
            f"|  Max deploy: ${self.max_deployable:.2f}  |  Cash: ${self.cash_reserve:.2f}",
        ]
        for w, amt in self.allocations.items():
            lines.append(f"  {w:<16} → ${amt:.2f}")
        for w, reason in self.skipped_workers.items():
            lines.append(f"  {w:<16} → SKIPPED ({reason})")
        return "\n".join(lines)


class RegimeAllocator:
    def __init__(self, total_capital: float):
        self.total_capital  = total_capital
        self._prev_weights: Dict[str, float] = {}   # for turnover filter

    def compute(
        self,
        regime:          str,
        worker_health:   Optional[Dict[str, bool]]   = None,
        worker_sharpe:   Optional[Dict[str, float]]  = None,
        registered_only: Optional[list]              = None,
        probabilities:   Optional[np.ndarray]        = None,
    ) -> AllocationResult:
        """
        Compute capital allocations for all eligible workers.

        *probabilities* (shape (4,) HMM state vector) drives probability-weighted
        blending across the 4 HMM state profiles. When absent, falls back to
        TRANSITION profile weights.

        The turnover filter skips rebalancing if the maximum change in any
        worker's fractional weight is below _TURNOVER_THRESHOLD (2 %) of
        total capital.  This prevents churn on tiny probability shifts.
        """
        worker_health = worker_health or {}
        worker_sharpe = worker_sharpe or {}

        # ── Choose profile and max_deploy ─────────────────────────────────────
        if probabilities is not None:
            profile_weights, max_deploy_frac = blend_allocations(
                probabilities, self.total_capital
            )
            max_deploy = self.total_capital * max_deploy_frac

            # Turnover filter: skip rebalance if change is negligible
            if self._prev_weights:
                max_delta = max(
                    abs(profile_weights.get(w, 0.0) - self._prev_weights.get(w, 0.0))
                    for w in profile_weights
                )
                if max_delta < _TURNOVER_THRESHOLD:
                    logger.debug(
                        f"Allocator: turnover filter suppressed rebalance "
                        f"(max_delta={max_delta:.4f} < {_TURNOVER_THRESHOLD})"
                    )
                    profile_weights = dict(self._prev_weights)

            self._prev_weights = dict(profile_weights)
            profile = profile_weights
        else:
            # Fallback: use TRANSITION profile (balanced, defensive)
            profile    = ALLOCATION_PROFILES["TRANSITION"]
            max_deploy = self.total_capital * HMM_STATE_MAX_DEPLOY["TRANSITION"]

        result = AllocationResult(
            regime        = regime,
            total_capital = self.total_capital,
            max_deployable = max_deploy,
        )

        eligible: Dict[str, float] = {}

        for worker, base_weight in profile.items():
            if base_weight == 0.0:
                result.skipped_workers[worker] = "regime_profile_zero"
                continue

            if registered_only is not None and worker not in registered_only:
                result.skipped_workers[worker] = "not_registered"
                continue

            healthy = worker_health.get(worker, True)
            if not healthy:
                result.skipped_workers[worker] = "unhealthy"
                logger.warning(f"Allocator: skipping {worker} — health check failed")
                continue

            sharpe = worker_sharpe.get(worker)
            if sharpe is not None:
                if sharpe < MIN_SHARPE_FLOOR:
                    result.skipped_workers[worker] = f"sharpe_too_low ({sharpe:.2f})"
                    continue
                if sharpe < MIN_SHARPE_FULL_ALLOC:
                    eligible[worker] = base_weight * 0.5
                    logger.info(f"Allocator: {worker} Sharpe {sharpe:.2f} — halved weight")
                    continue

            eligible[worker] = base_weight

        if not eligible:
            logger.warning(f"Allocator: no eligible workers for {regime}. Staying cash.")
            result.cash_reserve = self.total_capital
            return result

        # Normalise against the SUM OF ALL NON-ZERO PROFILE WEIGHTS, not just the
        # eligible subset.  This means a single healthy worker only receives its
        # intended profile share, even if all other workers are still starting up.
        # Without this, a single eligible worker absorbs all of max_deploy and
        # exceeds the risk manager's per-worker cap (50%).
        profile_nonzero_sum = sum(w for w in profile.values() if w > 0.0)
        result.allocations = {
            w: round(max_deploy * (wt / profile_nonzero_sum), 2)
            for w, wt in eligible.items()
        }
        result.cash_reserve = round(
            self.total_capital - sum(result.allocations.values()), 2
        )

        logger.info(
            f"Allocator [{regime}]: "
            + ", ".join(f"{w}=${v:.2f}" for w, v in result.allocations.items())
            + f" | cash=${result.cash_reserve:.2f}"
        )
        return result

    def update_capital(self, new_total: float) -> None:
        self.total_capital = new_total


# ── Domain override helper (re-exported for hypervisor convenience) ───────────

def apply_domain_overrides(
    base_allocations: dict,
    domain_decisions: list,
    domain_worker_map: dict | None = None,
) -> dict:
    """
    Apply OSINT domain router decisions to HMM-blended allocation weights.

    Thin wrapper around data.feeds.domain_router.apply_domain_overrides
    so the hypervisor can import this from capital.py without an extra
    import path.

    Parameters
    ----------
    base_allocations : dict
        {worker: weight_fraction} from blend_allocations() or compute().
    domain_decisions : list[DomainDecision]
        Decisions from DomainRouter.evaluate().
    domain_worker_map : dict, optional
        Override the default domain→worker mapping.

    Returns
    -------
    dict
        Modified and re-normalised {worker: weight_fraction}.
    """
    try:
        from data.feeds.domain_router import apply_domain_overrides as _apply
        return _apply(base_allocations, domain_decisions, domain_worker_map)
    except ImportError:
        # OSINT layer not yet deployed — return base allocations unchanged
        return base_allocations
