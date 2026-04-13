"""
hypervisor/regime/hmm_model.py

4-state Gaussian HMM for market regime detection.

States:
  0 = RISK_ON      — low vol, positive momentum, tight spreads
  1 = RISK_OFF     — elevated vol, negative returns, widening spreads
  2 = CRISIS       — VIX spike, credit blowout, flight to safety
  3 = TRANSITION   — ambiguous / mixed signals

The HMM learns:
  - Transition matrix A     : P(state_t | state_{t-1}),  shape (4, 4)
  - Emission means μ_k      : mean feature vector per state,  shape (4, 6)
  - Emission covariances Σ_k: full covariance per state,  shape (4, 6, 6)
  - Initial distribution π  : shape (4,)
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "model_state" / "hmm_4state.pkl"

STATE_LABELS: dict[int, str] = {
    0: "RISK_ON",
    1: "RISK_OFF",
    2: "CRISIS",
    3: "TRANSITION",
}

N_STATES   = 4
N_FEATURES = 6


class RegimeHMM:
    """4-state Gaussian HMM for market regime detection."""

    MODEL_PATH = MODEL_PATH

    def __init__(self, n_states: int = N_STATES):
        self.n_states = n_states
        self.model    = None
        self._fitted  = False

    # ── Public API ────────────────────────────────────────────────────────────

    def train(self, features: np.ndarray) -> None:
        """
        Fit the HMM on a historical z-scored feature matrix.

        Args:
            features: shape (T, 6).  T must be >= 504 (2 years of daily data).

        Raises:
            ValueError: if shape constraints are not met.
            ImportError: if hmmlearn is not installed.
        """
        if features.shape[0] < 504:
            raise ValueError(
                f"Need >= 504 observations for stable HMM training, got {features.shape[0]}. "
                "Fetch at least 2 years of daily data."
            )
        if features.shape[1] != N_FEATURES:
            raise ValueError(f"Expected {N_FEATURES} features per row, got {features.shape[1]}")

        logger.info(f"RegimeHMM.train: fitting on {features.shape[0]} observations...")
        self.model = self._build_model()
        self.model.fit(features)
        self._fitted = True
        self._save()
        logger.info("RegimeHMM.train: complete, model persisted to disk")

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """
        Posterior state probabilities for the latest observation.

        Uses the forward algorithm via hmmlearn's predict_proba().
        For stable filtering, pass at least 20 recent observations.

        Args:
            features: shape (T, 6) context window ending at current time.

        Returns:
            shape (4,) probability vector summing to 1.0.
        """
        self._require_fitted()
        if features.ndim != 2 or features.shape[1] != N_FEATURES:
            raise ValueError(
                f"features must be shape (T, {N_FEATURES}), got {features.shape}"
            )
        posteriors = self.model.predict_proba(features)
        return posteriors[-1]   # posterior for the last (current) timestep

    def decode(self, features: np.ndarray) -> tuple:
        """
        Return (argmax_label: str, probability_vector: np.ndarray).
        Convenience wrapper around predict_proba.
        """
        probs     = self.predict_proba(features)
        state_idx = int(np.argmax(probs))
        return STATE_LABELS[state_idx], probs

    def select_n_states(
        self,
        features: np.ndarray,
        max_states: int = 6,
    ) -> dict:
        """
        BIC-based model selection for n_states in [2, max_states].
        Log retrains of the monthly job so we can monitor whether 4 states stays optimal.

        BIC = −2 · LL · T  +  k · ln(T)
        where k = n² + 2·n·d + n·d·(d+1)//2 − 1  (free parameters, full cov)

        Returns:
            dict keyed by n_states: {"bic": float, "log_likelihood": float}
        """
        from hmmlearn import hmm as _hmm

        T, d = features.shape
        results: dict = {}
        for n in range(2, max_states + 1):
            m = _hmm.GaussianHMM(
                n_components=n, covariance_type="full",
                n_iter=200, random_state=42,
            )
            m.fit(features)
            ll  = float(m.score(features))
            k   = n**2 + 2 * n * d + n * d * (d + 1) // 2 - 1
            bic = -2.0 * ll * T + k * np.log(T)
            results[n] = {"bic": round(bic, 2), "log_likelihood": round(ll, 6)}
            logger.info(f"  HMM BIC[n={n}]: {bic:.1f}  LL={ll:.4f}")
        return results

    @property
    def is_fitted(self) -> bool:
        return self._fitted and self.model is not None

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        self.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.MODEL_PATH, "wb") as f:
            pickle.dump(self.model, f)
        logger.debug(f"RegimeHMM: model saved to {self.MODEL_PATH}")

    def load(self) -> bool:
        """Load a persisted model from disk. Returns True if successful."""
        if not self.MODEL_PATH.exists():
            return False
        try:
            with open(self.MODEL_PATH, "rb") as f:
                self.model = pickle.load(f)
            self._fitted = True
            logger.info(f"RegimeHMM: loaded model from {self.MODEL_PATH}")
            return True
        except Exception as e:
            logger.warning(f"RegimeHMM: failed to load model ({e})")
            return False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_model(self):
        from hmmlearn import hmm as _hmm
        return _hmm.GaussianHMM(
            n_components=self.n_states,
            covariance_type="full",   # captures feature correlations
            n_iter=200,
            random_state=42,
            init_params="stmc",       # initialise all parameters
            params="stmc",            # train all parameters
        )

    def _require_fitted(self) -> None:
        if not self.is_fitted:
            raise RuntimeError(
                "RegimeHMM is not trained. Call train() or load() first."
            )
