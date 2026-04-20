"""
data/feeds/edgar_client.py

SEC EDGAR corporate intelligence.

Uses edgartools (MIT, free, no API key) which wraps data.sec.gov.
The SEC EDGAR REST APIs require no authentication — only a User-Agent
header identifying who you are.

Signal types extracted:
  1. 8-K filings: Material events (M&A, leadership changes, earnings surprises)
  2. Form 4: Insider buying/selling (cluster insider buys = bullish signal)
  3. 10-Q/10-K: Upcoming earnings proxy (estimate next filing from last)

Install:  pip install edgartools>=3.0.0
Auth:     None — only User-Agent header required by SEC Fair Access Policy

Public API:
    EdgarIntelClient.check_recent_8k_filings(tickers, hours_back) → list[dict]
    EdgarIntelClient.check_insider_trading(tickers, days_back)    → list[dict]
    EdgarIntelClient.get_earnings_calendar(tickers)               → list[dict]
    score_edgar_signals(signals)                                   → float (0-100)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── edgartools availability guard ─────────────────────────────────────────────

try:
    from edgar import Company, set_identity
    _EDGAR_AVAILABLE = True
except ImportError:
    _EDGAR_AVAILABLE = False
    logger.warning(
        "edgartools not installed — EDGAR signals disabled. "
        "Install with: pip install edgartools>=3.0.0"
    )


# ── 8-K item codes relevant for trading decisions ─────────────────────────────
MATERIAL_8K_ITEMS = {
    "1.01": "material_agreement",        # M&A, partnerships
    "1.02": "agreement_termination",     # Terminated material contract
    "2.01": "acquisition_completion",    # Completed deal
    "2.02": "earnings_results",          # Quarterly results
    "2.05": "restructuring",             # Exits/disposals
    "2.06": "impairment",                # Asset write-down
    "5.02": "leadership_change",         # C-suite change
    "7.01": "regulation_fd",             # Guidance/preview
    "8.01": "other_material",            # Catch-all
}


class EdgarIntelClient:
    """
    Monitor SEC filings for trading-relevant corporate events.

    Update frequency: 15-minute polling on 8-K stream, daily on others.
    The SEC's data.sec.gov APIs update in real-time as filings are
    disseminated, with typical processing delay under 1 second.
    """

    # Watchlist: companies whose filings we track for trading signals.
    # Dynamically extended from the Hypervisor watchlist via update_watchlist().
    DEFAULT_WATCHLIST_CIKS: dict[str, str] = {
        "AAPL": "0000320193",
        "MSFT": "0000789019",
        "NVDA": "0001045810",
        "TSLA": "0001318605",
        "AMZN": "0001018724",
        "META": "0001326801",
        "GOOG": "0001652044",
    }

    def __init__(self, user_agent: str = "Arca Trading System arca@localhost"):
        if _EDGAR_AVAILABLE:
            set_identity(user_agent)
        self._watchlist: dict[str, str] = dict(self.DEFAULT_WATCHLIST_CIKS)

    def update_watchlist(self, tickers: list[str]) -> None:
        """
        Add tickers to the active watchlist.
        Unknown tickers (not in DEFAULT_WATCHLIST_CIKS) are accepted;
        edgartools resolves them by ticker symbol.
        """
        for t in tickers:
            if t not in self._watchlist:
                self._watchlist[t] = ""   # edgartools resolves CIK by ticker

    async def check_recent_8k_filings(
        self,
        tickers:    Optional[list[str]] = None,
        hours_back: int = 24,
    ) -> list[dict]:
        """
        Find 8-K filings (material events) from watched companies.

        Returns list of event dicts, each with keys:
          source, ticker, form_type, filed_at, description, items, url
        """
        if not _EDGAR_AVAILABLE:
            return []

        events: list[dict] = []
        target = tickers or list(self._watchlist.keys())

        for ticker in target:
            try:
                company  = Company(ticker)
                filings  = company.get_filings(form="8-K").latest(5)
                for filing in filings:
                    filed_dt = filing.filing_date
                    # edgartools may return datetime or date — normalise
                    if hasattr(filed_dt, "tzinfo") and filed_dt.tzinfo is not None:
                        age_hours = (
                            datetime.now(tz=filed_dt.tzinfo) - filed_dt
                        ).total_seconds() / 3600
                    else:
                        filed_dt_naive = (
                            filed_dt if isinstance(filed_dt, datetime)
                            else datetime.combine(filed_dt, datetime.min.time())
                        )
                        age_hours = (
                            datetime.now() - filed_dt_naive
                        ).total_seconds() / 3600

                    if age_hours > hours_back:
                        continue

                    items = []
                    try:
                        items = list(getattr(filing, "items", []) or [])
                    except Exception:
                        pass

                    events.append({
                        "source":      "edgar_8k",
                        "ticker":      ticker,
                        "form_type":   "8-K",
                        "filed_at":    filed_dt.isoformat() if hasattr(filed_dt, "isoformat") else str(filed_dt),
                        "description": (filing.description or "")[:500],
                        "items":       items,
                        "url":         getattr(filing, "url", ""),
                    })
            except Exception as exc:
                logger.debug(f"EDGAR 8-K [{ticker}]: {exc}")
                continue

        logger.info(f"EDGAR 8-K: found {len(events)} filings (last {hours_back}h)")
        return events

    async def check_insider_trading(
        self,
        tickers:  Optional[list[str]] = None,
        days_back: int = 7,
    ) -> list[dict]:
        """
        Detect insider buying/selling clusters via Form 4 filings.

        Signal logic:
          3+ insiders buying within 7 days = strong bullish signal
          CEO/CFO buying > $100K = notable bullish signal
          Cluster selling outside lockup = bearish signal

        Returns list of signal dicts, each with:
          ticker, signal, strength, count, period_days
        """
        if not _EDGAR_AVAILABLE:
            return []

        signals: list[dict] = []
        target  = tickers or list(self._watchlist.keys())

        for ticker in target:
            try:
                company  = Company(ticker)
                filings  = company.get_filings(form="4").latest(20)
                buys:  list[dict] = []
                sells: list[dict] = []

                for filing in filings:
                    filed_dt = filing.filing_date
                    # normalise date arithmetic
                    if hasattr(filed_dt, "tzinfo") and filed_dt.tzinfo is not None:
                        age_days = (
                            datetime.now(tz=filed_dt.tzinfo) - filed_dt
                        ).days
                    else:
                        filed_dt_naive = (
                            filed_dt if isinstance(filed_dt, datetime)
                            else datetime.combine(filed_dt, datetime.min.time())
                        )
                        age_days = (datetime.now() - filed_dt_naive).days

                    if age_days > days_back:
                        continue

                    try:
                        obj = filing.obj()
                        transactions = getattr(obj, "transactions", None) or []
                        for txn in transactions:
                            code = getattr(txn, "transaction_code", "")
                            shares = float(getattr(txn, "shares", 0) or 0)
                            if code in ("P", "A"):   # Purchase / Acquisition
                                buys.append({"code": code, "shares": shares})
                            elif code in ("S", "D"): # Sale / Disposition
                                sells.append({"code": code, "shares": shares})
                    except Exception:
                        pass

                if len(buys) >= 3:
                    signals.append({
                        "ticker":     ticker,
                        "signal":     "insider_cluster_buy",
                        "strength":   min(1.0, len(buys) / 5.0),
                        "count":      len(buys),
                        "period_days": days_back,
                    })
                elif len(sells) >= 4:
                    signals.append({
                        "ticker":     ticker,
                        "signal":     "insider_cluster_sell",
                        "strength":   min(1.0, len(sells) / 6.0),
                        "count":      len(sells),
                        "period_days": days_back,
                    })

            except Exception as exc:
                logger.debug(f"EDGAR Form4 [{ticker}]: {exc}")
                continue

        logger.info(f"EDGAR insider: {len(signals)} signals (last {days_back}d)")
        return signals

    async def get_earnings_calendar(
        self,
        tickers: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Estimate upcoming 10-Q/10-K earnings filing dates.

        Returns list of calendar dicts with:
          ticker, estimated_filing_date, days_until, action
          action: "widen_stops" (< 7 days) | "monitor" (< 30 days)
        """
        if not _EDGAR_AVAILABLE:
            return []

        calendar: list[dict] = []
        target   = tickers or list(self._watchlist.keys())

        for ticker in target:
            try:
                company = Company(ticker)
                filings = company.get_filings(form="10-Q").latest(1)
                if not filings:
                    continue
                last_filing = filings[0]
                last_dt = last_filing.filing_date
                last_dt_naive = (
                    last_dt if isinstance(last_dt, datetime)
                    else datetime.combine(last_dt, datetime.min.time())
                )
                est_next  = last_dt_naive + timedelta(days=90)
                days_until = (est_next - datetime.now()).days
                if 0 < days_until < 30:
                    calendar.append({
                        "ticker":                ticker,
                        "estimated_filing_date": est_next.isoformat(),
                        "days_until":            days_until,
                        "action": "widen_stops" if days_until < 7 else "monitor",
                    })
            except Exception as exc:
                logger.debug(f"EDGAR earnings [{ticker}]: {exc}")
                continue

        return calendar


def score_edgar_signals(
    filings: list[dict],
    insider_signals: list[dict],
) -> float:
    """
    Convert EDGAR outputs to 0-100 score for conflict/risk index.

    EDGAR signals negative corporate events as risk indicators:
      8-K impairment / restructuring / agreement termination → risk signal
      Cluster insider selling → mild risk signal
      Cluster insider buying  → opportunity (reduces overall risk score)
    """
    score = 0.0

    negative_items = {"impairment", "restructuring", "agreement_termination"}
    for f in filings:
        items = f.get("items", [])
        for item_code in items:
            desc = MATERIAL_8K_ITEMS.get(str(item_code), "")
            if desc in negative_items:
                score += 5.0

    for sig in insider_signals:
        if sig.get("signal") == "insider_cluster_sell":
            score += sig.get("strength", 0.5) * 10
        elif sig.get("signal") == "insider_cluster_buy":
            score -= 5.0 * sig.get("strength", 0.5)   # buying = good news

    return round(max(0.0, min(100.0, score)), 1)
