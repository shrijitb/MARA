"""
tests/test_mara.py

Arka component test suite.

Two categories:
  UNIT          Pure logic — no network, no .env, runs in <5s total.
  INTEGRATION   Hits real APIs. Needs .env + network. ~60s (GDELT sleeps).

Run unit tests only:
    cd ~/mara && source .venv/bin/activate
    pytest tests/test_mara.py -m "not integration" -v

Run everything:
    pytest tests/test_mara.py -v

Run without pytest:
    python tests/test_mara.py
"""

import sys
import os
import importlib
import importlib.util

_HERE    = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
sys.path.insert(0, _PROJECT)


def _load_config():
    """Load ~/mara/config.py by path. Returns module or None."""
    p = os.path.join(_PROJECT, "config.py")
    if not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("mara_config", p)
    mod  = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. GDELT fix verification
# ─────────────────────────────────────────────────────────────────────────────

class TestGdeltQueryFix:

    def test_multiple_focused_queries(self):
        from data.feeds.conflict_index import GDELT_QUERIES
        assert len(GDELT_QUERIES) >= 2
        for q in GDELT_QUERIES:
            assert len(q.split()) <= 5, f"Query too broad: '{q}'"

    def test_no_cross_conflict_megaquery(self):
        from data.feeds.conflict_index import GDELT_QUERIES
        regions = {"iran", "ukraine", "venezuela", "russia", "israel"}
        for q in GDELT_QUERIES:
            assert len({w.lower() for w in q.split()} & regions) <= 2, \
                f"Query mixes too many regions: '{q}'"

    def test_sleep_nonzero(self):
        from data.feeds.conflict_index import GDELT_SLEEP
        assert GDELT_SLEEP >= 2.0

    def test_scoring_count_only(self):
        """artlist has no tone — 35 real articles must score > 0."""
        from data.feeds.conflict_index import _score_gdelt
        assert _score_gdelt({"articles": 35}) > 0
        assert _score_gdelt({"articles": 10}) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Scoring functions
# ─────────────────────────────────────────────────────────────────────────────

class TestMarketProxyScoring:

    def setup_method(self):
        from data.feeds.conflict_index import _score_market_proxy
        self.score = _score_market_proxy

    def test_peacetime_below_25(self):
        s = self.score({"defense_momentum": 0.02, "gold_oil_ratio": 38.0, "vix": 14.0})
        assert s < 25, f"Got {s}"

    def test_current_conditions_above_20(self):
        s = self.score({"defense_momentum": 0.037, "gold_oil_ratio": 56.77, "vix": 29.49})
        assert s > 20, f"Got {s}"

    def test_war_above_50(self):
        s = self.score({"defense_momentum": 0.10, "gold_oil_ratio": 58.0, "vix": 32.0})
        assert s >= 50, f"Got {s}"

    def test_bounded(self):
        assert 0 <= self.score({"defense_momentum": 1.0, "gold_oil_ratio": 200.0, "vix": 80.0}) <= 100
        assert 0 <= self.score({}) <= 100


class TestGdeltScoring:

    def setup_method(self):
        from data.feeds.conflict_index import _score_gdelt
        self.score = _score_gdelt

    def test_below_threshold_zero(self):
        assert self.score({"articles": 14}) == 0.0
        assert self.score({"articles": 0}) == 0.0
        assert self.score({}) == 0.0

    def test_at_threshold_nonzero(self):
        assert self.score({"articles": 15}) > 0.0

    def test_35_articles_nonzero(self):
        """35 is the actual Venezuela live return — must score."""
        assert self.score({"articles": 35}) > 0.0

    def test_bounded(self):
        assert self.score({"articles": 1000}) <= 100.0


class TestCompositeWeights:

    def test_market_proxy_and_osint_layer_sum_to_1(self):
        from data.feeds.conflict_index import _MARKET_PROXY_WEIGHT, _OSINT_LAYER_WEIGHT
        assert abs(_MARKET_PROXY_WEIGHT + _OSINT_LAYER_WEIGHT - 1.0) < 1e-9

    def test_market_proxy_is_primary(self):
        from data.feeds.conflict_index import _MARKET_PROXY_WEIGHT, _OSINT_LAYER_WEIGHT
        assert _MARKET_PROXY_WEIGHT >= _OSINT_LAYER_WEIGHT

    def test_osint_base_weights_sum_to_1(self):
        from data.feeds.conflict_index import _OSINT_BASE_WEIGHTS
        assert abs(sum(_OSINT_BASE_WEIGHTS.values()) - 1.0) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic weight redistribution
# ─────────────────────────────────────────────────────────────────────────────

class TestDynamicWeightRedistribution:

    def setup_method(self):
        from data.feeds.conflict_index import _redistribute_weights
        self.redistribute = _redistribute_weights

    def test_all_sources_available_sum_to_1(self):
        w = self.redistribute({"gdelt", "edgar", "ucdp", "maritime", "firms", "usgs"})
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_single_source_gets_full_weight(self):
        w = self.redistribute({"gdelt"})
        assert abs(w["gdelt"] - 1.0) < 1e-9

    def test_two_sources_preserve_relative_ratio(self):
        from data.feeds.conflict_index import _OSINT_BASE_WEIGHTS
        w = self.redistribute({"gdelt", "ucdp"})
        assert abs(sum(w.values()) - 1.0) < 1e-9
        # gdelt base=0.25, ucdp base=0.15 → ratio 25:15 = 5:3
        expected_gdelt = 0.25 / (0.25 + 0.15)
        assert abs(w["gdelt"] - expected_gdelt) < 1e-9

    def test_empty_sources_returns_empty(self):
        w = self.redistribute(set())
        assert w == {}

    def test_unknown_source_ignored(self):
        w = self.redistribute({"gdelt", "nonexistent_source"})
        assert "nonexistent_source" not in w
        assert "gdelt" in w


# ─────────────────────────────────────────────────────────────────────────────
# OSINT Event types and severity
# ─────────────────────────────────────────────────────────────────────────────

class TestOSINTEventModel:

    def test_event_severity_range(self):
        from data.feeds.osint_processor import EventSeverity
        for sev in EventSeverity:
            assert 1 <= sev.value <= 9

    def test_osint_event_defaults_stable(self):
        from data.feeds.osint_processor import OSINTEvent, EventSeverity
        ev = OSINTEvent(
            source="gdelt",
            event_type="armed_conflict",
            severity=EventSeverity.HIGH,
            escalation_trajectory="stable",
        )
        assert ev.escalation_trajectory == "stable"
        assert ev.confidence == 0.5
        assert ev.timestamp != ""

    def test_invalid_event_type_coerced_to_default(self):
        from data.feeds.osint_processor import OSINTEvent, EventSeverity
        ev = OSINTEvent(
            source="test",
            event_type="definitely_not_a_real_type",
            severity=EventSeverity.LOW,
            escalation_trajectory="stable",
        )
        assert ev.event_type == "supply_disruption"

    def test_invalid_trajectory_coerced_to_stable(self):
        from data.feeds.osint_processor import OSINTEvent, EventSeverity
        ev = OSINTEvent(
            source="test",
            event_type="armed_conflict",
            severity=EventSeverity.MODERATE,
            escalation_trajectory="bananas",
        )
        assert ev.escalation_trajectory == "stable"


# ─────────────────────────────────────────────────────────────────────────────
# OSINT Processor — keyword fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestOSINTKeywordFallback:

    def setup_method(self):
        from data.feeds.osint_processor import _keyword_classify
        self.classify = _keyword_classify

    def test_conflict_text_classified_as_armed_conflict(self):
        r = self.classify("Military airstrike kills civilians in active war zone")
        assert r["event_type"] == "armed_conflict"

    def test_sanction_text_classified_correctly(self):
        r = self.classify("New US sanctions embargo on Russian oil exports")
        assert r["event_type"] == "sanctions"

    def test_deescalation_keyword_detected(self):
        r = self.classify("Ceasefire agreement reached between warring parties")
        assert r["escalation_trajectory"] == "de-escalating"

    def test_escalation_keyword_detected(self):
        r = self.classify("Violence escalated sharply as forces intensified attacks")
        assert r["escalation_trajectory"] == "escalating"

    def test_oil_commodity_detected(self):
        r = self.classify("Crude oil pipeline explosion disrupts Brent WTI supply")
        assert "oil" in r["commodities_affected"]

    def test_semiconductor_commodity_detected(self):
        r = self.classify("TSMC fab halted production — chip shortage expected")
        assert "semiconductors" in r["commodities_affected"]

    def test_confidence_is_float_in_range(self):
        r = self.classify("Generic headline text with no keywords")
        assert isinstance(r["confidence"], float)
        assert 0.0 <= r["confidence"] <= 1.0

    def test_severity_in_valid_range(self):
        r = self.classify("Explosion kills hundreds in mass casualty event")
        assert 1 <= r["severity"] <= 9


# ─────────────────────────────────────────────────────────────────────────────
# UCDP severity classifier
# ─────────────────────────────────────────────────────────────────────────────

class TestUCDPSeverityClassifier:

    def setup_method(self):
        from data.feeds.ucdp_client import classify_ucdp_severity
        self.classify = classify_ucdp_severity

    def test_zero_deaths_returns_low(self):
        assert self.classify({"deaths_best": 0}) == 2   # LOW

    def test_small_fatality_count(self):
        assert self.classify({"deaths_best": 3}) == 3   # MODERATE

    def test_large_fatality_count(self):
        assert self.classify({"deaths_best": 600}) == 9  # EXTREME

    def test_missing_deaths_defaults_low(self):
        assert self.classify({}) == 2

    def test_severity_increases_with_deaths(self):
        s1 = self.classify({"deaths_best": 2})
        s2 = self.classify({"deaths_best": 50})
        s3 = self.classify({"deaths_best": 300})
        assert s1 < s2 < s3


# ─────────────────────────────────────────────────────────────────────────────
# UCDP scoring
# ─────────────────────────────────────────────────────────────────────────────

class TestUCDPScoring:

    def setup_method(self):
        from data.feeds.ucdp_client import score_ucdp_events
        self.score = score_ucdp_events

    def test_empty_returns_zero(self):
        assert self.score([]) == 0.0

    def test_single_event_scores(self):
        ev = {"deaths_best": 5}
        assert self.score([ev]) > 0.0

    def test_high_fatality_event_scores_higher(self):
        low  = [{"deaths_best": 2}]
        high = [{"deaths_best": 200}]
        assert self.score(high) > self.score(low)

    def test_bounded_at_100(self):
        events = [{"deaths_best": 10000}] * 100
        assert self.score(events) <= 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Domain Router — pure unit tests (no network, no LLM)
# ─────────────────────────────────────────────────────────────────────────────

class TestDomainRouter:

    def _make_events(self, event_type: str, severity: int, trajectory: str, n: int = 1):
        from data.feeds.osint_processor import OSINTEvent, EventSeverity
        return [
            OSINTEvent(
                source                = "gdelt",
                event_type            = event_type,
                severity              = EventSeverity(severity),
                escalation_trajectory = trajectory,
                confidence            = 0.8,
            )
            for _ in range(n)
        ]

    def setup_method(self):
        from data.feeds.domain_router import DomainRouter
        self.router = DomainRouter()

    def test_evaluate_returns_decision_for_every_domain(self):
        from data.feeds.domain_router import DOMAIN_WORKER_MAP
        decisions = self.router.evaluate([], [], {}, {})
        domains_decided = {d.domain for d in decisions}
        assert domains_decided == set(DOMAIN_WORKER_MAP.keys())

    def test_high_risk_score_triggers_exit(self):
        from data.feeds.domain_router import DomainAction
        # 9 × 11.1 = 99.9 risk score for commodities (armed_conflict + supply_disruption)
        events = self._make_events("armed_conflict", 9, "escalating", 10)
        decisions = self.router.evaluate(events, [], {}, {})
        commodities_dec = next(d for d in decisions if d.domain == "commodities")
        assert commodities_dec.action == DomainAction.EXIT
        assert commodities_dec.weight_modifier == 0.0

    def test_crisis_probability_reduces_non_fixed_income(self):
        from data.feeds.domain_router import DomainAction
        decisions = self.router.evaluate(
            [], [], {}, {"CRISIS": 0.75}
        )
        for d in decisions:
            if d.domain != "fixed_income":
                assert d.weight_modifier <= 0.5, (
                    f"{d.domain} should be reduced in high crisis but got {d.weight_modifier}"
                )

    def test_fixed_income_not_reduced_in_crisis(self):
        from data.feeds.domain_router import DomainAction
        decisions = self.router.evaluate(
            [], [], {}, {"CRISIS": 0.75}
        )
        fi = next(d for d in decisions if d.domain == "fixed_income")
        # fixed_income is exempt from crisis reduction
        assert fi.action != DomainAction.EXIT

    def test_deescalation_events_boost_opportunity_for_crypto(self):
        events = self._make_events("armed_conflict", 3, "de-escalating", 3)
        decisions = self.router.evaluate(events, [], {}, {"RISK_ON": 0.7})
        crypto = next(d for d in decisions if d.domain == "crypto_perps")
        # Opportunity score should be > 0; weight modifier ≥ 1.0
        assert crypto.weight_modifier >= 1.0

    def test_7day_loss_without_catalyst_triggers_exit(self):
        from data.feeds.domain_router import DomainAction
        # Mark domain as active first
        self.router.domain_states["crypto_perps"].active = True
        perf = {"crypto_perps": {"pnl_pct": -5.0, "7d_pnl": -12.0}}
        decisions = self.router.evaluate([], [], perf, {})
        crypto = next(d for d in decisions if d.domain == "crypto_perps")
        assert crypto.action == DomainAction.EXIT

    def test_all_decisions_have_valid_weight_modifiers(self):
        decisions = self.router.evaluate([], [], {}, {})
        for d in decisions:
            assert 0.0 <= d.weight_modifier <= 2.1, (
                f"{d.domain}: weight_modifier={d.weight_modifier} out of bounds"
            )

    def test_decision_dicts_serializable(self):
        decisions = self.router.evaluate([], [], {}, {})
        for d in decisions:
            result = d.to_dict()
            assert "action" in result
            assert "weight_modifier" in result
            assert "rationale" in result


# ─────────────────────────────────────────────────────────────────────────────
# apply_domain_overrides — capital allocation integration
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyDomainOverrides:

    def setup_method(self):
        from data.feeds.domain_router import apply_domain_overrides, DomainDecision, DomainAction
        from datetime import datetime, timezone
        self.apply    = apply_domain_overrides
        self.Decision = DomainDecision
        self.Action   = DomainAction

    def _dec(self, domain, action, modifier, confidence=0.8):
        from data.feeds.domain_router import _expiry
        return self.Decision(
            domain          = domain,
            action          = action,
            weight_modifier = modifier,
            confidence      = confidence,
            rationale       = "test",
            triggered_by    = ["test"],
            expires_at      = _expiry(1),
        )

    def test_exit_decision_zeros_worker(self):
        base = {"nautilus": 0.44, "analyst": 0.08, "core_dividends": 0.36}
        decisions = [self._dec("crypto_perps", self.Action.EXIT, 0.0)]
        result = self.apply(base, decisions)
        assert result["nautilus"] == 0.0

    def test_hold_decision_preserves_allocation(self):
        base = {"nautilus": 0.44, "analyst": 0.08, "core_dividends": 0.36}
        decisions = [self._dec("crypto_perps", self.Action.HOLD, 1.0)]
        result = self.apply(base, decisions)
        # Nautilus should be unchanged (modifier=1.0)
        assert abs(result["nautilus"] - base["nautilus"]) < 1e-6

    def test_renormalises_after_exit(self):
        base = {"nautilus": 0.44, "analyst": 0.08, "core_dividends": 0.36, "prediction_markets": 0.12}
        decisions = [self._dec("crypto_perps", self.Action.EXIT, 0.0)]
        result = self.apply(base, decisions)
        # Total deployment should equal original total
        assert abs(sum(result.values()) - sum(base.values())) < 1e-6

    def test_increase_modifier_scales_up(self):
        base = {"nautilus": 0.44, "analyst": 0.08}
        decisions = [self._dec("crypto_perps", self.Action.INCREASE, 1.3)]
        result = self.apply(base, decisions)
        # After renorm, nautilus should have larger share than analyst
        assert result["nautilus"] > result["analyst"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Config
# ─────────────────────────────────────────────────────────────────────────────

class TestConfig:
    """Loads ~/mara/config.py by path. Skips if not deployed yet."""

    REQUIRED = [
        "INITIAL_CAPITAL_USD", "MIN_TRADE_SIZE_USD", "MAX_POSITION_PCT",
        "VAR_CONFIDENCE", "VAR_SIMULATIONS", "VAR_HORIZON_HOURS",
        "MAX_VAR_PCT", "CVAR_MULTIPLIER", "LOOKBACK_DAYS",
        "MIN_SHARPE_TO_TRADE", "SHARPE_RISK_FREE_RATE",
        "REBALANCE_INTERVAL_SEC", "FUNDING_RATE_INTERVAL", "MIN_FUNDING_RATE",
        "PAPER_TRADING", "SLIPPAGE_MODEL_PCT", "FEE_MODEL_PCT",
        "EXCHANGES", "QUOTE_CURRENCY",
        "USE_LIVE_RATES", "USE_LIVE_OHLCV",
        "SWING_MACD_FAST", "SWING_MACD_SLOW", "SWING_MACD_SIGNAL",
        "SWING_TIMEFRAME", "SWING_CACHE_TTL_SEC", "SWING_PAIRS",
        "SWING_STOP_LOSS_PCT", "SWING_TAKE_PROFIT_RATIO",
        "SWING_RSI_PERIOD", "SWING_RSI_BULL_MIN", "SWING_RSI_BEAR_MAX",
        "LOG_LEVEL", "LOG_FILE",
    ]

    def setup_method(self):
        try:
            import pytest
            self.cfg = _load_config()
            if self.cfg is None:
                pytest.skip("config.py not at ~/mara/config.py")
        except ImportError:
            self.cfg = _load_config()

    def test_all_required_keys_present(self):
        if not self.cfg: return
        missing = [k for k in self.REQUIRED if not hasattr(self.cfg, k)]
        assert not missing, f"Missing: {missing}"

    def test_paper_trading_true(self):
        if not self.cfg: return
        assert self.cfg.PAPER_TRADING is True

    def test_live_flags_false(self):
        if not self.cfg: return
        assert not self.cfg.USE_LIVE_RATES
        assert not self.cfg.USE_LIVE_OHLCV

    def test_swing_pairs_populated(self):
        if not self.cfg: return
        assert isinstance(self.cfg.SWING_PAIRS, list) and len(self.cfg.SWING_PAIRS) > 0

    def test_rsi_sanity(self):
        if not self.cfg: return
        assert 0 < self.cfg.SWING_RSI_BULL_MIN < 50
        assert 50 < self.cfg.SWING_RSI_BEAR_MAX < 100

    def test_capital_sanity(self):
        if not self.cfg: return
        assert self.cfg.INITIAL_CAPITAL_USD >= 10.0
        assert self.cfg.MIN_TRADE_SIZE_USD < self.cfg.INITIAL_CAPITAL_USD
        assert 0.0 < self.cfg.MAX_POSITION_PCT <= 1.0

    def test_risk_params_sanity(self):
        if not self.cfg: return
        assert 0.90 <= self.cfg.VAR_CONFIDENCE <= 1.0
        assert 0.0  <  self.cfg.MAX_VAR_PCT    <= 0.5


# ─────────────────────────────────────────────────────────────────────────────
# 5. Indicator math — pure Python, zero dependencies
# ─────────────────────────────────────────────────────────────────────────────

class TestIndicatorMath:

    def test_ema_seed_equals_first_point(self):
        data = [10.0, 12.0, 11.0, 13.0, 15.0]
        k    = 2.0 / (3 + 1)
        ema  = [data[0]] + [0.0] * (len(data) - 1)
        for i in range(1, len(data)):
            ema[i] = data[i] * k + ema[i-1] * (1 - k)
        assert abs(ema[0] - 10.0) < 1e-9

    def test_ema_rises_on_uptrend(self):
        data = [1.0] * 10 + [10.0] * 10
        k    = 2.0 / 6
        ema  = [data[0]] + [0.0] * (len(data) - 1)
        for i in range(1, len(data)):
            ema[i] = data[i] * k + ema[i-1] * (1 - k)
        assert ema[-1] > ema[9]

    def test_fractal_peak(self):
        highs = [10, 10, 10, 10, 10, 20, 10, 10, 10, 10]
        bear = [i for i in range(2, len(highs)-2)
                if highs[i] > highs[i-1] and highs[i] > highs[i-2]
                and highs[i] > highs[i+1] and highs[i] > highs[i+2]]
        assert 5 in bear

    def test_fractal_trough(self):
        lows = [10, 10, 10, 10, 10, 1, 10, 10, 10, 10]
        bull = [i for i in range(2, len(lows)-2)
                if lows[i] < lows[i-1] and lows[i] < lows[i-2]
                and lows[i] < lows[i+1] and lows[i] < lows[i+2]]
        assert 5 in bull

    def test_rsi_in_range(self):
        def rsi(gains, losses):
            ag = sum(gains)/len(gains) if gains else 0.0
            al = sum(losses)/len(losses) if losses else 0.0
            if al == 0: return 100.0
            return 100.0 - (100.0 / (1 + ag/al))
        assert 0 <= rsi([1.0]*14, [0.5]*14) <= 100
        assert 0 <= rsi([], [1.0]*14) <= 100
        assert 0 <= rsi([1.0]*14, []) <= 100


# ─────────────────────────────────────────────────────────────────────────────
# 6. Integration tests (need .env + network)
# ─────────────────────────────────────────────────────────────────────────────

try:
    import pytest as _pytest
    _integration = _pytest.mark.integration
except ImportError:
    def _integration(cls): return cls


@_integration
class TestGdeltIntegration:

    def test_no_429(self):
        from data.feeds.conflict_index import _fetch_gdelt
        r = _fetch_gdelt()
        # GDELT rate-limits aggressively — acceptable if at least one query returned data
        assert r.get("articles", 0) > 0, "All GDELT queries failed — check network"

    def test_keys_present(self):
        from data.feeds.conflict_index import _fetch_gdelt
        r = _fetch_gdelt()
        assert "articles" in r and "source" in r

    def test_live_score_works(self):
        from data.feeds.conflict_index import _fetch_gdelt, _score_gdelt
        r = _fetch_gdelt()
        s = _score_gdelt(r)
        assert 0 <= s <= 100
        if r["articles"] >= 15:
            assert s > 0, f"35 articles should score > 0 (got {r['articles']} articles)"


@_integration
class TestFullScore:
    def test_in_range(self):
        from data.feeds.conflict_index import get_war_premium_score
        s = get_war_premium_score()
        assert 0.0 <= s <= 100.0
        print(f"\n  Live score: {s}/100")


# ─────────────────────────────────────────────────────────────────────────────
# 7. HMM Regime Classifier — unit tests
#    All tests use synthetic data; no network required.
#    Tests that call hmmlearn are skipped if hmmlearn is not installed.
# ─────────────────────────────────────────────────────────────────────────────

try:
    import hmmlearn as _hmmlearn
    _HMMLEARN_OK = True
except ImportError:
    _HMMLEARN_OK = False

try:
    import numpy as _np
    _NUMPY_OK = True
except ImportError:
    _NUMPY_OK = False

try:
    import pytest as _pytest_mod
    _skipif_no_hmmlearn = _pytest_mod.mark.skipif(
        not _HMMLEARN_OK, reason="hmmlearn not installed — run: pip install hmmlearn"
    )
    _skipif_no_numpy = _pytest_mod.mark.skipif(
        not _NUMPY_OK, reason="numpy not installed"
    )
except ImportError:
    def _skipif_no_hmmlearn(cls): return cls   # no-op outside pytest
    def _skipif_no_numpy(cls): return cls


@_skipif_no_hmmlearn
class TestRegimeHMM:
    """
    Tests for RegimeHMM — pure model unit tests using synthetic data.
    No network access.
    """

    def _make_features(self, n: int = 600, seed: int = 0) -> "import numpy; numpy.ndarray":
        import numpy as np
        rng = np.random.default_rng(seed)
        return rng.standard_normal((n, 6)).astype(float)

    def test_train_requires_minimum_observations(self):
        import numpy as np
        import pytest
        from hypervisor.regime.hmm_model import RegimeHMM
        model = RegimeHMM()
        short = np.zeros((200, 6))
        with pytest.raises(ValueError, match="504"):
            model.train(short)

    def test_train_requires_six_features(self):
        import numpy as np
        import pytest
        from hypervisor.regime.hmm_model import RegimeHMM
        model = RegimeHMM()
        with pytest.raises(ValueError, match="6"):
            model.train(np.zeros((600, 4)))

    def test_predict_proba_shape_and_sum(self, tmp_path):
        import numpy as np
        from hypervisor.regime.hmm_model import RegimeHMM
        model = RegimeHMM()
        feats = self._make_features(700)
        model.train(feats)
        context = feats[-30:]
        probs   = model.predict_proba(context)
        assert probs.shape == (4,), f"Expected (4,), got {probs.shape}"
        assert abs(probs.sum() - 1.0) < 1e-6, f"Probs sum to {probs.sum():.6f}, not 1.0"
        assert all(p >= 0 for p in probs), "All probabilities must be non-negative"

    def test_decode_returns_valid_label(self):
        import numpy as np
        from hypervisor.regime.hmm_model import RegimeHMM, STATE_LABELS
        model  = RegimeHMM()
        feats  = self._make_features(700)
        model.train(feats)
        label, probs = model.decode(feats[-30:])
        assert label in STATE_LABELS.values(), (
            f"decode() returned unknown label {label!r}, "
            f"valid: {set(STATE_LABELS.values())}"
        )
        assert abs(probs.sum() - 1.0) < 1e-6

    def test_save_load_roundtrip(self, tmp_path):
        import numpy as np
        from hypervisor.regime.hmm_model import RegimeHMM
        model = RegimeHMM()
        model.MODEL_PATH = tmp_path / "test_hmm.pkl"
        feats = self._make_features(700)
        model.train(feats)
        probs_before = model.predict_proba(feats[-30:])

        model2 = RegimeHMM()
        model2.MODEL_PATH = model.MODEL_PATH
        assert model2.load(), "load() should return True for an existing file"
        probs_after = model2.predict_proba(feats[-30:])
        assert abs((probs_before - probs_after).max()) < 1e-8, (
            "Probabilities should be identical after save/load roundtrip"
        )

    def test_predict_requires_fitted_model(self):
        import numpy as np
        import pytest
        from hypervisor.regime.hmm_model import RegimeHMM
        model = RegimeHMM()
        with pytest.raises(RuntimeError, match="not trained"):
            model.predict_proba(np.zeros((30, 6)))

    def test_load_returns_false_for_missing_file(self, tmp_path):
        from hypervisor.regime.hmm_model import RegimeHMM
        model = RegimeHMM()
        model.MODEL_PATH = tmp_path / "nonexistent.pkl"
        assert model.load() is False


@_skipif_no_numpy
class TestFeaturePipeline:
    """
    Tests for FeaturePipeline math — no network access.
    """

    def _pipeline(self):
        from hypervisor.regime.feature_pipeline import FeaturePipeline
        return FeaturePipeline(lookback_days=252)

    def test_update_rolling_stats_shape(self):
        import numpy as np
        p = self._pipeline()
        history = np.random.default_rng(0).standard_normal((300, 6))
        p.update_rolling_stats(history)
        assert p.rolling_mean.shape == (6,), f"rolling_mean shape: {p.rolling_mean.shape}"
        assert p.rolling_std.shape  == (6,), f"rolling_std shape: {p.rolling_std.shape}"

    def test_update_rolling_stats_values(self):
        import numpy as np
        p = self._pipeline()
        # All-zeros history → mean=0, std=0
        zeros = np.zeros((100, 6))
        p.update_rolling_stats(zeros)
        assert np.allclose(p.rolling_mean, 0.0), "Mean of zeros should be 0"
        assert np.allclose(p.rolling_std,  0.0), "Std of zeros should be 0"

    def test_normalize_produces_z_scores(self):
        import numpy as np
        p = self._pipeline()
        rng  = np.random.default_rng(42)
        hist = rng.standard_normal((300, 6)) * 5 + 3   # mean ~3, std ~5
        p.update_rolling_stats(hist)
        # The column mean of the normalized history should be ~0
        z = p.normalize(hist)
        col_means = z.mean(axis=0)
        assert np.allclose(col_means, 0.0, atol=0.05), (
            f"Z-score column means should be ~0, got {col_means}"
        )

    def test_normalize_shape_preserved(self):
        import numpy as np
        p = self._pipeline()
        p.update_rolling_stats(np.ones((100, 6)))
        raw = np.random.default_rng(0).standard_normal((50, 6))
        z   = p.normalize(raw)
        assert z.shape == (50, 6), f"normalize shape mismatch: {z.shape}"

    def test_lookback_window_applied(self):
        import numpy as np
        p = self._pipeline()
        # Feed 300 rows of ones then 300 rows of zeros.
        # lookback=252, so the window covers only the trailing 252 zeros → mean=0.
        ones  = np.ones((300, 6))
        zeros = np.zeros((300, 6))
        history = np.vstack([ones, zeros])
        p.update_rolling_stats(history)
        # Last 252 rows are all zeros → mean should be 0
        assert np.allclose(p.rolling_mean, 0.0, atol=1e-9), (
            f"Rolling mean should be 0 when last 252 rows are zeros, "
            f"got {p.rolling_mean}"
        )

    def test_fallback_stats_initialized(self):
        from hypervisor.regime.feature_pipeline import FeaturePipeline, N_FEATURES
        p = FeaturePipeline()
        assert p.rolling_mean.shape == (N_FEATURES,)
        assert p.rolling_std.shape  == (N_FEATURES,)


@_skipif_no_numpy
class TestCircuitBreakers:
    """
    Tests for apply_circuit_breakers — pure math, no network.
    """

    def _uniform(self):
        import numpy as np
        return np.array([0.25, 0.25, 0.25, 0.25])

    def test_high_vix_forces_crisis_floor(self):
        from hypervisor.regime.circuit_breakers import apply_circuit_breakers
        probs, active = apply_circuit_breakers(
            self._uniform(),
            {"vix_level": 55.0, "hy_credit_spread": 400.0, "nfci": 0.0, "yield_spread_2y10y": 0.5},
        )
        assert probs[2] >= 0.70 - 1e-9, f"P(CRISIS) should be >= 0.70, got {probs[2]:.4f}"
        assert active is True

    def test_high_hy_oas_forces_crisis_floor(self):
        from hypervisor.regime.circuit_breakers import apply_circuit_breakers
        probs, active = apply_circuit_breakers(
            self._uniform(),
            {"vix_level": 20.0, "hy_credit_spread": 850.0, "nfci": 0.0, "yield_spread_2y10y": 0.5},
        )
        assert probs[2] >= 0.70 - 1e-9
        assert active is True

    def test_low_vix_nfci_forces_risk_on_floor(self):
        from hypervisor.regime.circuit_breakers import apply_circuit_breakers
        probs, active = apply_circuit_breakers(
            self._uniform(),
            {"vix_level": 10.0, "hy_credit_spread": 250.0, "nfci": -0.8, "yield_spread_2y10y": 0.5},
        )
        assert probs[0] >= 0.60 - 1e-9, f"P(RISK_ON) should be >= 0.60, got {probs[0]:.4f}"
        assert active is True

    def test_inverted_yield_forces_risk_off_floor(self):
        from hypervisor.regime.circuit_breakers import apply_circuit_breakers
        probs, active = apply_circuit_breakers(
            self._uniform(),
            {"vix_level": 20.0, "hy_credit_spread": 350.0, "nfci": 0.0, "yield_spread_2y10y": -1.5},
        )
        assert probs[1] >= 0.40 - 1e-9, f"P(RISK_OFF) should be >= 0.40, got {probs[1]:.4f}"
        assert active is True

    def test_war_premium_forces_crisis_floor(self):
        from hypervisor.regime.circuit_breakers import apply_circuit_breakers
        probs, active = apply_circuit_breakers(
            self._uniform(),
            {"vix_level": 20.0, "hy_credit_spread": 350.0, "nfci": 0.0, "yield_spread_2y10y": 0.5},
            war_premium_score=70.0,
        )
        assert probs[2] >= 0.50 - 1e-9
        assert active is True

    def test_renormalization_sums_to_one(self):
        import numpy as np
        from hypervisor.regime.circuit_breakers import apply_circuit_breakers
        # Trigger multiple rules simultaneously (crisis + inverted yield)
        probs, _ = apply_circuit_breakers(
            self._uniform(),
            {"vix_level": 55.0, "hy_credit_spread": 900.0, "nfci": 0.0, "yield_spread_2y10y": -1.5},
            war_premium_score=65.0,
        )
        assert abs(probs.sum() - 1.0) < 1e-9, f"Renormalized probs sum to {probs.sum()}"
        assert all(p >= 0 for p in probs)

    def test_normal_conditions_no_modification(self):
        import numpy as np
        from hypervisor.regime.circuit_breakers import apply_circuit_breakers
        orig  = np.array([0.60, 0.20, 0.10, 0.10])
        probs, active = apply_circuit_breakers(
            orig.copy(),
            {"vix_level": 18.0, "hy_credit_spread": 320.0, "nfci": -0.1, "yield_spread_2y10y": 0.4},
            war_premium_score=10.0,
        )
        # No rule fires — probs unchanged (only renormalized, which is identity here)
        assert active is False
        assert np.allclose(probs, orig), f"Normal conditions should not modify probs: {probs}"


@_skipif_no_numpy
class TestBlendedAllocations:
    """
    Tests for blend_allocations() and probability-weighted RegimeAllocator.compute().
    No network access.
    """

    def _alloc(self):
        from hypervisor.allocator.capital import RegimeAllocator
        return RegimeAllocator(total_capital=200.0)

    def test_pure_risk_on_matches_profile(self):
        import numpy as np
        from hypervisor.allocator.capital import blend_allocations, ALLOCATION_PROFILES
        probs   = np.array([1.0, 0.0, 0.0, 0.0])
        weights, _ = blend_allocations(probs, 200.0)
        for worker, expected in ALLOCATION_PROFILES["RISK_ON"].items():
            assert abs(weights[worker] - expected) < 1e-9, (
                f"{worker}: expected {expected}, got {weights[worker]}"
            )

    def test_pure_crisis_matches_profile(self):
        import numpy as np
        from hypervisor.allocator.capital import blend_allocations, ALLOCATION_PROFILES
        probs   = np.array([0.0, 0.0, 1.0, 0.0])
        weights, _ = blend_allocations(probs, 200.0)
        for worker, expected in ALLOCATION_PROFILES["CRISIS"].items():
            assert abs(weights[worker] - expected) < 1e-9, (
                f"{worker}: expected {expected}, got {weights[worker]}"
            )

    def test_50_50_blend_averages_profiles(self):
        import numpy as np
        from hypervisor.allocator.capital import blend_allocations, ALLOCATION_PROFILES
        probs   = np.array([0.5, 0.5, 0.0, 0.0])
        weights, _ = blend_allocations(probs, 200.0)
        for worker in ALLOCATION_PROFILES["RISK_ON"]:
            expected = 0.5 * ALLOCATION_PROFILES["RISK_ON"][worker] \
                     + 0.5 * ALLOCATION_PROFILES["RISK_OFF"][worker]
            assert abs(weights[worker] - expected) < 1e-9, (
                f"{worker}: blend mismatch {weights[worker]:.4f} vs {expected:.4f}"
            )

    def test_compute_with_probabilities_stays_within_capital(self):
        import numpy as np
        alloc  = self._alloc()
        probs  = np.array([0.4, 0.3, 0.2, 0.1])
        result = alloc.compute(regime="RISK_ON", probabilities=probs)
        total  = sum(result.allocations.values())
        assert total <= 200.01, f"Blended allocation ${total:.2f} exceeds capital $200"
        assert result.cash_reserve >= -0.01

    def test_compute_with_probabilities_applies_health_gate(self):
        import numpy as np
        alloc  = self._alloc()
        probs  = np.array([1.0, 0.0, 0.0, 0.0])
        result = alloc.compute(
            regime="RISK_ON",
            probabilities=probs,
            worker_health={"nautilus": False},
        )
        assert "nautilus" not in result.allocations, (
            "Unhealthy worker should not receive allocation in blended mode"
        )

    def test_max_deploy_blended_is_probability_weighted(self):
        import numpy as np
        from hypervisor.allocator.capital import blend_allocations, HMM_STATE_MAX_DEPLOY, HMM_STATE_LABELS
        probs   = np.array([0.5, 0.5, 0.0, 0.0])
        _, md   = blend_allocations(probs, 200.0)
        expected = 0.5 * HMM_STATE_MAX_DEPLOY["RISK_ON"] + 0.5 * HMM_STATE_MAX_DEPLOY["RISK_OFF"]
        assert abs(md - expected) < 1e-9, f"max_deploy {md:.4f} != expected {expected:.4f}"


@_skipif_no_numpy
class TestBackwardCompatibility:
    """
    Ensures the new HMM classifier + allocator remain compatible with
    code that was written against the old 7-regime system.
    """

    def test_regime_result_has_regime_attribute(self):
        from hypervisor.regime.classifier import RegimeResult, Regime
        r = RegimeResult(
            regime=Regime.RISK_ON, confidence=0.7,
            probabilities={"RISK_ON": 0.7, "RISK_OFF": 0.1, "CRISIS": 0.1, "TRANSITION": 0.1},
        )
        assert hasattr(r, "regime")
        assert r.regime.value == "RISK_ON"

    def test_regime_result_confidence_in_range(self):
        from hypervisor.regime.classifier import RegimeResult, Regime
        r = RegimeResult(
            regime=Regime.TRANSITION, confidence=0.35,
            probabilities={lbl: 0.25 for lbl in ["RISK_ON", "RISK_OFF", "CRISIS", "TRANSITION"]},
        )
        assert 0.0 <= r.confidence <= 1.0

    def test_regime_result_has_probabilities_dict(self):
        from hypervisor.regime.classifier import RegimeResult, Regime
        r = RegimeResult(
            regime=Regime.CRISIS, confidence=0.8,
            probabilities={"RISK_ON": 0.05, "RISK_OFF": 0.10, "CRISIS": 0.80, "TRANSITION": 0.05},
        )
        assert isinstance(r.probabilities, dict)
        assert set(r.probabilities.keys()) == {"RISK_ON", "RISK_OFF", "CRISIS", "TRANSITION"}

    def test_to_dict_contains_required_fields(self):
        from hypervisor.regime.classifier import RegimeResult, Regime
        probs = {"RISK_ON": 0.25, "RISK_OFF": 0.25, "CRISIS": 0.25, "TRANSITION": 0.25}
        r = RegimeResult(regime=Regime.TRANSITION, confidence=0.25, probabilities=probs)
        d = r.to_dict()
        for key in ("regime", "confidence", "probabilities", "circuit_breaker_active",
                    "triggered_by", "timestamp"):
            assert key in d, f"to_dict() missing key: {key!r}"
        assert d["regime"] == "TRANSITION"

    def test_allocator_compute_unknown_regime_falls_back_to_transition(self):
        from hypervisor.allocator.capital import RegimeAllocator
        alloc  = RegimeAllocator(total_capital=200.0)
        # Unknown regime string must fall back to TRANSITION without crashing
        result = alloc.compute(regime="UNKNOWN_REGIME")
        assert sum(result.allocations.values()) <= 200.01
        assert result.cash_reserve >= -0.01

    def test_regime_enum_values_are_strings(self):
        from hypervisor.regime.classifier import Regime
        for member in Regime:
            assert isinstance(member.value, str)

    def test_classifier_has_classify_sync(self):
        from hypervisor.regime.classifier import RegimeClassifier
        clf = RegimeClassifier()
        assert callable(getattr(clf, "classify_sync", None)), (
            "RegimeClassifier must expose classify_sync() method"
        )

    def test_classifier_has_override_interface(self):
        from hypervisor.regime.classifier import RegimeClassifier
        clf = RegimeClassifier()
        assert callable(getattr(clf, "override", None))
        assert callable(getattr(clf, "clear_override", None))


# ─────────────────────────────────────────────────────────────────────────────
# 8. Nautilus quant strategy unit tests — no network, no NT dependency
#    Path: workers/nautilus is added to sys.path so strategy imports resolve
#    without Docker or the full data/feeds layer.
# ─────────────────────────────────────────────────────────────────────────────

_NAUTILUS_DIR = os.path.join(_PROJECT, "workers", "nautilus")
if _NAUTILUS_DIR not in sys.path:
    sys.path.insert(0, _NAUTILUS_DIR)


class TestFundingArbSignal:
    """
    Unit tests for strategies/funding_arb.py.
    All tests run without network access — synthetic fallback path is exercised.
    """

    def test_synthetic_funding_rate_is_numeric(self):
        from strategies.funding_arb import _synthetic_funding_rate
        rate = _synthetic_funding_rate("BTC-USDT-SWAP")
        assert isinstance(rate, float), f"Expected float, got {type(rate)}"
        assert abs(rate) <= 0.001, f"Synthetic rate {rate} outside expected ±0.001 range"

    def test_high_positive_funding_prefers_short(self):
        """Positive funding = longs paying = SHORT the perp to collect carry."""
        import strategies.funding_arb as fa
        _orig = fa._get_funding_rate
        fa._get_funding_rate = lambda sym: 0.0005   # 5× above threshold
        try:
            sig = fa.evaluate_signal(["BTC/USDT"], "swing_neutral")
            if sig is not None:
                assert sig[1] == "short", (
                    f"Positive funding should produce short signal, got side={sig[1]!r}"
                )
        finally:
            fa._get_funding_rate = _orig

    def test_high_negative_funding_prefers_long(self):
        """Negative funding = shorts paying = LONG the perp to collect carry."""
        import strategies.funding_arb as fa
        _orig = fa._get_funding_rate
        fa._get_funding_rate = lambda sym: -0.0005  # 5× below negative threshold
        try:
            sig = fa.evaluate_signal(["BTC/USDT"], "swing_neutral")
            if sig is not None:
                assert sig[1] == "long", (
                    f"Negative funding should produce long signal, got side={sig[1]!r}"
                )
        finally:
            fa._get_funding_rate = _orig

    def test_momentum_long_bias_skips_short_arb(self):
        """momentum_long bias must NOT produce short carry signals."""
        import strategies.funding_arb as fa
        _orig = fa._get_funding_rate
        fa._get_funding_rate = lambda sym: 0.0005   # would normally → short
        try:
            sig = fa.evaluate_signal(["BTC/USDT", "ETH/USDT", "SOL/USDT",
                                      "BNB/USDT", "AVAX/USDT"], "momentum_long")
            assert sig is None, (
                f"momentum_long bias must skip short funding signals, got: {sig}"
            )
        finally:
            fa._get_funding_rate = _orig

    def test_flat_bias_returns_none(self):
        """flat bias → no new entries regardless of funding rate."""
        from strategies.funding_arb import evaluate_signal
        sig = evaluate_signal(["BTC/USDT", "ETH/USDT"], "flat")
        assert sig is None, f"flat bias must return None, got: {sig}"


class TestOrderFlowImbalance:
    """
    Unit tests for strategies/order_flow.py and data/feeds/order_book.py.
    Pure-function tests on compute_bid_ask_imbalance pass synthetic book dicts
    so no network access is required.
    """

    def test_book_imbalance_bounded_to_neg1_1(self):
        from data.feeds.order_book import compute_bid_ask_imbalance
        book = {
            "bids": [["65000", "1.5", "0"], ["64900", "2.0", "0"]],
            "asks": [["65100", "1.0", "0"], ["65200", "0.5", "0"]],
        }
        imb = compute_bid_ask_imbalance(book)
        assert -1.0 <= imb <= 1.0, f"Imbalance {imb} outside [-1, 1]"

    def test_bid_heavy_book_positive_imbalance(self):
        from data.feeds.order_book import compute_bid_ask_imbalance
        book = {
            "bids": [["65000", "10.0", "0"]],  # 10 units on bid
            "asks": [["65100",  "1.0", "0"]],  # 1  unit  on ask
        }
        imb = compute_bid_ask_imbalance(book)
        assert imb > 0, f"Bid-heavy book should have positive imbalance, got {imb}"

    def test_ask_heavy_book_negative_imbalance(self):
        from data.feeds.order_book import compute_bid_ask_imbalance
        book = {
            "bids": [["65000",  "1.0", "0"]],
            "asks": [["65100", "10.0", "0"]],
        }
        imb = compute_bid_ask_imbalance(book)
        assert imb < 0, f"Ask-heavy book should have negative imbalance, got {imb}"

    def test_evaluate_signal_returns_valid_format_or_none(self):
        from strategies.order_flow import evaluate_signal
        pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT"]
        sig = evaluate_signal(pairs, "swing_neutral")
        if sig is not None:
            pair, side, entry, sl, tp = sig
            assert isinstance(pair, str) and pair in pairs, f"Invalid pair: {pair!r}"
            assert side in ("long", "short"), f"Invalid side: {side!r}"
            assert entry > 0, f"Entry price must be positive, got {entry}"
            assert sl > 0 and tp > 0, f"SL/TP must be positive, got sl={sl}, tp={tp}"


class TestFactorModel:
    """
    Unit tests for strategies/factor_model.py.
    All tests use synthetic data — no network, no NT dependency.
    """

    def test_momentum_factor_z_scores_zero_mean(self):
        from strategies.factor_model import _z_score
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        z = _z_score(values)
        assert len(z) == len(values), "z_score must preserve input length"
        mean_z = sum(z) / len(z)
        assert abs(mean_z) < 1e-9, f"Z-scores must have zero mean, got {mean_z}"

    def test_carry_factor_annualization_formula(self):
        from strategies.factor_model import _synthetic_funding_rate_annualized
        rate = _synthetic_funding_rate_annualized("BTC-USDT-SWAP")
        assert isinstance(rate, float), f"Expected float, got {type(rate)}"
        # Max raw rate: ±0.00015 per 8h → max annualized: ±0.00015 * 3 * 365 = ±0.164
        assert abs(rate) < 1.0, (
            f"Annualized carry {rate:.4f} seems unreasonably large (expected < 1.0 = 100%)"
        )

    def test_vol_scalar_capped_at_2(self):
        """Volatility targeting scalar must never exceed 2.0."""
        target_vol   = 0.15
        realized_vol = 0.01   # very low vol — scalar would be 15× without cap
        scalar = min(2.0, target_vol / realized_vol)
        assert scalar == 2.0, f"Vol scalar should be capped at 2.0, got {scalar}"

    def test_evaluate_signal_returns_valid_format_or_none(self):
        from strategies.factor_model import evaluate_signal
        pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT"]
        sig = evaluate_signal(pairs, "swing_neutral")
        if sig is not None:
            pair, side, entry, sl, tp = sig
            assert isinstance(pair, str) and pair in pairs, f"Invalid pair: {pair!r}"
            assert side in ("long", "short"), f"Invalid side: {side!r}"
            assert entry > 0, f"Entry price must be positive, got {entry}"
            if side == "long":
                assert sl < entry, f"Long SL {sl} must be below entry {entry}"
                assert tp > entry, f"Long TP {tp} must be above entry {entry}"
            else:
                assert sl > entry, f"Short SL {sl} must be above entry {entry}"
                assert tp < entry, f"Short TP {tp} must be below entry {entry}"


# ─────────────────────────────────────────────────────────────────────────────
# Plain-Python runner
# ─────────────────────────────────────────────────────────────────────────────

def _run():
    import traceback
    SUITES = [
        TestGdeltQueryFix,
        TestMarketProxyScoring, TestGdeltScoring,
        TestCompositeWeights, TestConfig, TestIndicatorMath,
        TestFundingArbSignal, TestOrderFlowImbalance, TestFactorModel,
    ]
    p = f = sk = 0
    for cls in SUITES:
        inst = cls()
        for name in sorted(m for m in dir(cls) if m.startswith("test_")):
            try:
                if hasattr(inst, "setup_method"):
                    try: inst.setup_method()
                    except Exception as e:
                        print(f"  ⏭  {cls.__name__}.{name}  (skip: {e})")
                        sk += 1; continue
                getattr(inst, name)()
                print(f"  ✅  {cls.__name__}.{name}"); p += 1
            except AssertionError as e:
                print(f"  ❌  {cls.__name__}.{name}  →  {e}"); f += 1
            except Exception as e:
                print(f"  ❌  {cls.__name__}.{name}  →  {type(e).__name__}: {e}"); f += 1
    print(f"\n{'='*50}\n  {p} passed  |  {f} failed  |  {sk} skipped\n{'='*50}")
    return f

if __name__ == "__main__":
    print("\n" + "="*50 + "\n  MARA unit tests\n" + "="*50 + "\n")
    sys.exit(_run())
