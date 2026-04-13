"""
hypervisor/regime/circuit_breakers.py

Emergency threshold overrides for the 4-state HMM regime classifier.

These rules apply minimum probability FLOORS for unambiguous market extremes.
They do NOT replace the HMM — they adjust its output when market conditions
are beyond the range of historical training data.

State index mapping (must stay consistent with hmm_model.STATE_LABELS):
  0 = RISK_ON
  1 = RISK_OFF
  2 = CRISIS
  3 = TRANSITION

Rules applied in priority order:
  1. VIX > 50  OR  HY OAS > 800 bp   → P(CRISIS)   >= 0.70
  2. VIX < 12  AND NFCI < -0.5        → P(RISK_ON)  >= 0.60
  3. Yield spread < -1.0              → P(RISK_OFF)  >= 0.40
  4. war_premium_score > 60           → P(CRISIS)   >= 0.50

Rules 1 and 2 are mutually exclusive (VIX can't be > 50 and < 12 simultaneously).
Multiple rules can fire together — e.g. a deep inversion (rule 3) during a VIX
spike (rule 1) raises both CRISIS and RISK_OFF floors before renormalization.
After all rules are applied the vector is renormalized to sum to 1.0.
"""

from __future__ import annotations

import numpy as np


def apply_circuit_breakers(
    probs: np.ndarray,
    raw_features: dict,
    war_premium_score: float = 0.0,
) -> tuple:
    """
    Apply threshold floors to an HMM probability vector.

    Args:
        probs:             shape (4,) probability vector from HMM.
        raw_features:      dict with keys: vix_level, hy_credit_spread,
                           nfci, yield_spread_2y10y (raw, un-normalized values).
        war_premium_score: composite 0-100 war score from conflict_index.py.

    Returns:
        (modified_probs, circuit_breaker_active)
        modified_probs:        shape (4,), renormalized, sums to 1.0.
        circuit_breaker_active: True if any rule fired.
    """
    modified = probs.copy().astype(float)
    active   = False

    vix          = float(raw_features.get("vix_level",          20.0))
    hy_oas       = float(raw_features.get("hy_credit_spread",  350.0))
    nfci         = float(raw_features.get("nfci",                0.0))
    yield_spread = float(raw_features.get("yield_spread_2y10y",  0.5))

    # Rule 1: acute crisis — VIX explosion or credit blowout
    if vix > 50 or hy_oas > 800:
        if modified[2] < 0.70:
            _enforce_floor(modified, 2, 0.70)
            active = True

    # Rule 2: maximum risk-on — compressed vol + accommodative conditions
    elif vix < 12 and nfci < -0.5:
        if modified[0] < 0.60:
            _enforce_floor(modified, 0, 0.60)
            active = True

    # Rule 3: inverted yield curve (independent of rules 1 & 2)
    if yield_spread < -1.0:
        if modified[1] < 0.40:
            _enforce_floor(modified, 1, 0.40)
            active = True

    # Rule 4: war premium (independent of other rules)
    if war_premium_score > 60:
        if modified[2] < 0.50:
            _enforce_floor(modified, 2, 0.50)
            active = True

    # Renormalize to clean up floating-point drift (sum should already be ~1.0)
    total = modified.sum()
    if total > 0:
        modified /= total

    return modified, active


def _enforce_floor(modified: np.ndarray, state_idx: int, floor: float) -> None:
    """
    Set modified[state_idx] = floor and scale the other states down proportionally
    so the vector continues to sum to 1.0 after the floor is applied.

    This ensures the floor value is maintained in the *final normalized* output,
    not just pre-normalization (where a later renormalization would dilute it).
    """
    modified[state_idx] = floor
    remaining   = 1.0 - floor
    other_idxs  = [i for i in range(len(modified)) if i != state_idx]
    other_sum   = sum(modified[i] for i in other_idxs)
    if other_sum > 0:
        scale = remaining / other_sum
        for i in other_idxs:
            modified[i] *= scale
    else:
        per = remaining / len(other_idxs)
        for i in other_idxs:
            modified[i] = per
