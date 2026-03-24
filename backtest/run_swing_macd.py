#!/usr/bin/env python3
"""
backtest/run_swing_macd.py

Standalone backtest for the MACD + Williams Fractals swing strategy.

No NautilusTrader, no BaseWorker, no PortfolioState — just the pure
indicator math replayed against historical OHLCV bars.

Usage:
    # Synthetic data (no API key needed):
    python3 backtest/run_swing_macd.py

    # Live OKX historical data:
    pip install ccxt
    python3 backtest/run_swing_macd.py --live --pair BTC/USDT --bars 500

    # All pairs, save CSV report:
    python3 backtest/run_swing_macd.py --live --all-pairs --output backtest/results/

Output:
    - Trade log table (entry, exit, reason, pnl, R:R)
    - Per-pair summary (win rate, total pnl, sharpe, max drawdown)
    - Portfolio summary across all pairs

Strategy spec (mirrors swing_macd.py exactly):
    Entry LONG:  bullish fractal ≤15 bars ago + MACD bullish cross ≤3 bars ago
                 + MACD > 0 + RSI 40-70
    Entry SHORT: bearish fractal ≤15 bars ago + MACD bearish cross ≤3 bars ago
                 + MACD < 0 + RSI 30-60
    Exit:        hard stop 2% beyond fractal, take profit 1:2 R:R,
                 MACD reversal after ≥2 hold bars, trailing stop at 1:1

MACD params: (8, 21, 5) — tuned for 4h crypto swing.
RSI period:  14
Timeframe:   H4
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# ── Strategy constants (match config.py) ─────────────────────────────────────
MACD_FAST           = 8
MACD_SLOW           = 21
MACD_SIGNAL         = 5
RSI_PERIOD          = 14
RSI_BULL_MIN        = 40
RSI_BULL_MAX        = 70
RSI_BEAR_MIN        = 30
RSI_BEAR_MAX        = 60
STOP_LOSS_PCT       = 0.02      # 2% beyond fractal
TAKE_PROFIT_RATIO   = 2.0       # 1:2 R:R
FRACTAL_LOOKBACK    = 15        # bars
CROSS_LOOKBACK      = 3         # bars for MACD cross detection
MIN_BARS_WARMUP     = MACD_SLOW + RSI_PERIOD + 10   # bars before first signal
CAPITAL_PER_TRADE   = 0.40      # 40% of allocated capital per position (max 2)
MAX_POSITIONS       = 2

OKX_PAIRS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "AVAX/USDT",
]

BASE_PRICES = {
    "BTC/USDT":  65_000.0,
    "ETH/USDT":   3_500.0,
    "SOL/USDT":     150.0,
    "AVAX/USDT":     35.0,
    "BNB/USDT":     580.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# Indicator Library (mirrors swing_macd.py 1:1)
# ─────────────────────────────────────────────────────────────────────────────

def ema(data: np.ndarray, period: int) -> np.ndarray:
    k = 2.0 / (period + 1)
    result = np.empty_like(data, dtype=np.float64)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = data[i] * k + result[i - 1] * (1.0 - k)
    return result


def macd(closes: np.ndarray, fast: int, slow: int, signal: int
         ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    ema_fast    = ema(closes, fast)
    ema_slow    = ema(closes, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    if len(closes) < period + 1:
        return np.full(len(closes), 50.0)
    deltas   = np.diff(closes)
    gains    = np.where(deltas > 0, deltas, 0.0)
    losses   = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.zeros(len(closes))
    avg_loss = np.zeros(len(closes))
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss > 1e-12, avg_gain / avg_loss, 100.0)
    rsi_vals = 100.0 - (100.0 / (1.0 + rs))
    rsi_vals[:period] = 50.0
    return rsi_vals


def find_fractals(highs: np.ndarray, lows: np.ndarray
                  ) -> Tuple[List[int], List[int]]:
    bull, bear = [], []
    for i in range(2, len(highs) - 2):
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2]
                and highs[i] > highs[i+1] and highs[i] > highs[i+2]):
            bear.append(i)
        if (lows[i] < lows[i-1] and lows[i] < lows[i-2]
                and lows[i] < lows[i+1] and lows[i] < lows[i+2]):
            bull.append(i)
    return bull, bear


def bullish_cross_within(macd_line: np.ndarray, signal_line: np.ndarray,
                         lookback: int) -> bool:
    for i in range(1, min(lookback + 1, len(macd_line))):
        if macd_line[-(i+1)] <= signal_line[-(i+1)] and macd_line[-i] > signal_line[-i]:
            return True
    return False


def bearish_cross_within(macd_line: np.ndarray, signal_line: np.ndarray,
                          lookback: int) -> bool:
    for i in range(1, min(lookback + 1, len(macd_line))):
        if macd_line[-(i+1)] >= signal_line[-(i+1)] and macd_line[-i] < signal_line[-i]:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Data Layer
# ─────────────────────────────────────────────────────────────────────────────

def fetch_live_ohlcv(pair: str, n_bars: int = 500) -> List:
    """Fetch historical H4 OHLCV from OKX via ccxt."""
    try:
        import ccxt
        exchange = ccxt.okx()
        bars = exchange.fetch_ohlcv(pair, "4h", limit=n_bars)
        print(f"  Fetched {len(bars)} H4 bars for {pair} from OKX")
        return bars
    except ImportError:
        raise SystemExit("ccxt not installed. Run: pip install ccxt")
    except Exception as exc:
        print(f"  OKX fetch failed for {pair}: {exc} — falling back to synthetic")
        return generate_synthetic_ohlcv(pair, n_bars)


def generate_synthetic_ohlcv(pair: str, n_bars: int = 500,
                               seed: Optional[int] = None) -> List:
    """
    Synthetic H4 OHLCV via GBM. Uses fixed seed for reproducibility.
    Mild trend drift so MACD signals form naturally.
    """
    base = BASE_PRICES.get(pair, 100.0)
    rng  = np.random.RandomState(seed if seed is not None else abs(hash(pair)) % (2**31))

    drift = rng.choice([-0.0001, 0.0, 0.0001, 0.0002])
    sigma = 0.008

    shocks = rng.normal(drift, sigma, n_bars)
    closes = [base]
    for s in shocks:
        closes.append(closes[-1] * (1 + s))
    closes = closes[1:]

    ohlcv = []
    ts = int(time.time()) - n_bars * 14_400
    for i, close in enumerate(closes):
        r     = close * rng.uniform(0.005, 0.02)
        high  = close + r * rng.uniform(0.3, 0.7)
        low   = close - r * rng.uniform(0.3, 0.7)
        open_ = closes[i - 1] if i > 0 else close
        vol   = rng.uniform(1e6, 5e7)
        ohlcv.append([ts + i * 14_400, open_, high, low, close, vol])
    return ohlcv


# ─────────────────────────────────────────────────────────────────────────────
# Position and Trade Records
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Position:
    pair:         str
    side:         str           # "long" | "short"
    entry_bar:    int
    entry_price:  float
    stop_loss:    float
    take_profit:  float
    size_usd:     float
    hold_bars:    int = 0
    stop_trailed: bool = False


@dataclass
class Trade:
    pair:        str
    side:        str
    entry_bar:   int
    exit_bar:    int
    entry_price: float
    exit_price:  float
    stop_loss:   float
    take_profit: float
    size_usd:    float
    pnl:         float
    pnl_pct:     float
    hold_bars:   int
    exit_reason: str           # "stop_loss" | "take_profit" | "macd_reversal" | "end_of_data"

    @property
    def rr_realised(self) -> float:
        risk = abs(self.entry_price - self.stop_loss) / self.entry_price
        return (self.pnl_pct / risk) if risk > 1e-12 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Engine — bar-by-bar replay
# ─────────────────────────────────────────────────────────────────────────────

class SwingMACDBacktest:
    """
    Replays the MACD+Williams Fractals strategy bar-by-bar over a fixed
    OHLCV series.  No lookahead: at bar i, only bars 0..i are visible.
    """

    def __init__(self, pair: str, ohlcv: List, capital: float = 200.0,
                 position_pct: float = CAPITAL_PER_TRADE,
                 max_positions: int = MAX_POSITIONS,
                 verbose: bool = False):
        self.pair          = pair
        self.ohlcv         = ohlcv
        self.capital       = capital
        self.position_pct  = position_pct
        self.max_positions = max_positions
        self.verbose       = verbose

        self.trades:     List[Trade]    = []
        self.positions:  List[Position] = []
        self.equity_curve: List[float] = [capital]

    def run(self) -> "BacktestResult":
        bars   = self.ohlcv
        n      = len(bars)
        equity = self.capital

        for i in range(MIN_BARS_WARMUP, n):
            window = bars[:i + 1]

            closes = np.array([b[4] for b in window], dtype=np.float64)
            highs  = np.array([b[2] for b in window], dtype=np.float64)
            lows   = np.array([b[3] for b in window], dtype=np.float64)

            macd_line, sig_line, _ = macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
            rsi_vals               = rsi(closes, RSI_PERIOD)

            current_price = float(closes[-1])
            current_rsi   = float(rsi_vals[-1])
            current_macd  = float(macd_line[-1])

            # ── Manage open positions ─────────────────────────────────────────
            equity += self._manage_positions(i, current_price, macd_line, sig_line)

            # ── Scan for new entry ────────────────────────────────────────────
            if len(self.positions) < self.max_positions:
                # Confirmed fractals exclude last 2 bars (still forming)
                conf_highs = highs[:-2]
                conf_lows  = lows[:-2]
                bull_frac, bear_frac = find_fractals(conf_highs, conf_lows)

                entry = self._evaluate_long(
                    i, current_price, current_rsi, current_macd,
                    macd_line, sig_line, bull_frac, conf_lows, equity,
                )
                if entry:
                    self.positions.append(entry)
                    if self.verbose:
                        print(f"  [{i}] LONG  {self.pair} @ {current_price:.4f} "
                              f"SL={entry.stop_loss:.4f} TP={entry.take_profit:.4f}")
                else:
                    entry = self._evaluate_short(
                        i, current_price, current_rsi, current_macd,
                        macd_line, sig_line, bear_frac, conf_highs, equity,
                    )
                    if entry:
                        self.positions.append(entry)
                        if self.verbose:
                            print(f"  [{i}] SHORT {self.pair} @ {current_price:.4f} "
                                  f"SL={entry.stop_loss:.4f} TP={entry.take_profit:.4f}")

            self.equity_curve.append(equity)

        # Close any open positions at last bar price
        last_price = float(self.ohlcv[-1][4])
        for pos in list(self.positions):
            pnl = self._close(pos, len(self.ohlcv) - 1, last_price, "end_of_data")
            equity += pnl

        return BacktestResult(
            pair         = self.pair,
            trades       = self.trades,
            equity_curve = self.equity_curve,
            initial_cap  = self.capital,
            n_bars       = len(self.ohlcv),
        )

    # ── Entry logic ───────────────────────────────────────────────────────────

    def _evaluate_long(self, bar_i, price, cur_rsi, cur_macd,
                       macd_line, sig_line, bull_frac, conf_lows, equity
                       ) -> Optional[Position]:
        if not bull_frac:
            return None
        if len(conf_lows) - bull_frac[-1] > FRACTAL_LOOKBACK:
            return None
        if not bullish_cross_within(macd_line, sig_line, CROSS_LOOKBACK):
            return None
        if cur_macd <= 0:
            return None
        if not (RSI_BULL_MIN <= cur_rsi <= RSI_BULL_MAX):
            return None

        fractal   = float(conf_lows[bull_frac[-1]])
        stop_loss = fractal * (1 - STOP_LOSS_PCT)
        risk      = price - stop_loss
        if risk <= 0:
            return None
        take_profit = price + risk * TAKE_PROFIT_RATIO
        size_usd    = round(equity * self.position_pct, 2)

        return Position(
            pair=self.pair, side="long", entry_bar=bar_i,
            entry_price=price, stop_loss=stop_loss,
            take_profit=take_profit, size_usd=size_usd,
        )

    def _evaluate_short(self, bar_i, price, cur_rsi, cur_macd,
                        macd_line, sig_line, bear_frac, conf_highs, equity
                        ) -> Optional[Position]:
        if not bear_frac:
            return None
        if len(conf_highs) - bear_frac[-1] > FRACTAL_LOOKBACK:
            return None
        if not bearish_cross_within(macd_line, sig_line, CROSS_LOOKBACK):
            return None
        if cur_macd >= 0:
            return None
        if not (RSI_BEAR_MIN <= cur_rsi <= RSI_BEAR_MAX):
            return None

        fractal     = float(conf_highs[bear_frac[-1]])
        stop_loss   = fractal * (1 + STOP_LOSS_PCT)
        risk        = stop_loss - price
        if risk <= 0:
            return None
        take_profit = price - risk * TAKE_PROFIT_RATIO
        size_usd    = round(equity * self.position_pct, 2)

        return Position(
            pair=self.pair, side="short", entry_bar=bar_i,
            entry_price=price, stop_loss=stop_loss,
            take_profit=take_profit, size_usd=size_usd,
        )

    # ── Position management ───────────────────────────────────────────────────

    def _manage_positions(self, bar_i: int, price: float,
                          macd_line: np.ndarray, sig_line: np.ndarray) -> float:
        """Returns net pnl delta for this bar."""
        pnl_delta = 0.0
        to_close  = []

        for pos in self.positions:
            pos.hold_bars += 1
            reason = self._check_exit(pos, price, macd_line, sig_line)
            if reason:
                to_close.append((pos, reason))

        for pos, reason in to_close:
            pnl_delta += self._close(pos, bar_i, price, reason)

        return pnl_delta

    def _check_exit(self, pos: Position, price: float,
                    macd_line: np.ndarray, sig_line: np.ndarray) -> Optional[str]:
        # Hard stop
        if pos.side == "long"  and price <= pos.stop_loss:
            return "stop_loss"
        if pos.side == "short" and price >= pos.stop_loss:
            return "stop_loss"

        # Take profit
        if pos.side == "long"  and price >= pos.take_profit:
            return "take_profit"
        if pos.side == "short" and price <= pos.take_profit:
            return "take_profit"

        # MACD reversal (skip first 2 hold bars)
        if pos.hold_bars >= 2:
            if (pos.side == "long"
                    and macd_line[-2] >= sig_line[-2] and macd_line[-1] < sig_line[-1]):
                return "macd_reversal"
            if (pos.side == "short"
                    and macd_line[-2] <= sig_line[-2] and macd_line[-1] > sig_line[-1]):
                return "macd_reversal"

        # Trail stop to breakeven at 1:1
        if not pos.stop_trailed and pos.side == "long":
            initial_risk = pos.entry_price - pos.stop_loss
            if initial_risk > 0 and price >= pos.entry_price + initial_risk:
                pos.stop_loss    = pos.entry_price
                pos.stop_trailed = True
        elif not pos.stop_trailed and pos.side == "short":
            initial_risk = pos.stop_loss - pos.entry_price
            if initial_risk > 0 and price <= pos.entry_price - initial_risk:
                pos.stop_loss    = pos.entry_price
                pos.stop_trailed = True

        return None

    def _close(self, pos: Position, bar_i: int, price: float,
               reason: str) -> float:
        if pos.side == "long":
            pnl = pos.size_usd * (price - pos.entry_price) / pos.entry_price
        else:
            pnl = pos.size_usd * (pos.entry_price - price) / pos.entry_price
        pnl_pct = pnl / pos.size_usd

        trade = Trade(
            pair=pos.pair, side=pos.side,
            entry_bar=pos.entry_bar, exit_bar=bar_i,
            entry_price=pos.entry_price, exit_price=price,
            stop_loss=pos.stop_loss, take_profit=pos.take_profit,
            size_usd=pos.size_usd,
            pnl=round(pnl, 4), pnl_pct=round(pnl_pct, 6),
            hold_bars=pos.hold_bars, exit_reason=reason,
        )
        self.trades.append(trade)

        if pos in self.positions:
            self.positions.remove(pos)

        if self.verbose:
            sign = "✅" if pnl > 0 else "❌"
            print(f"  [{bar_i}] {sign} CLOSED {pos.side.upper()} "
                  f"@ {price:.4f} ({reason}) pnl=${pnl:+.2f} "
                  f"({pnl_pct*100:+.2f}%) held {pos.hold_bars} bars")
        return pnl


# ─────────────────────────────────────────────────────────────────────────────
# Result Statistics
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    pair:         str
    trades:       List[Trade]
    equity_curve: List[float]
    initial_cap:  float
    n_bars:       int

    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    def total_return_pct(self) -> float:
        return self.total_pnl() / self.initial_cap * 100

    def win_rate(self) -> float:
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades) if self.trades else 0.0

    def sharpe(self) -> float:
        if len(self.trades) < 5:
            return 0.0
        rets = [t.pnl_pct for t in self.trades]
        mean = sum(rets) / len(rets)
        try:
            std = statistics.stdev(rets)
        except Exception:
            return 0.0
        if std < 1e-12:
            return 0.0
        # Annualise: ~6 H4 trades per day
        return (mean / std) * math.sqrt(6 * 365)

    def max_drawdown(self) -> float:
        """Maximum peak-to-trough drawdown of equity curve."""
        peak = self.equity_curve[0]
        max_dd = 0.0
        for v in self.equity_curve:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def profit_factor(self) -> float:
        gross_wins  = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_losses = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        return gross_wins / gross_losses if gross_losses > 1e-12 else float("inf")

    def avg_hold_bars(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.hold_bars for t in self.trades) / len(self.trades)

    def exit_breakdown(self) -> Dict[str, int]:
        reasons: Dict[str, int] = {}
        for t in self.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        return reasons


# ─────────────────────────────────────────────────────────────────────────────
# Report Rendering
# ─────────────────────────────────────────────────────────────────────────────

def print_trade_log(trades: List[Trade], max_rows: int = 30):
    if not trades:
        print("  No trades.")
        return
    header = (f"{'#':>4}  {'Pair':<12} {'Side':<6} {'Entry':>10} "
              f"{'Exit':>10} {'PnL $':>8} {'PnL %':>7} {'Bars':>5}  Reason")
    print(header)
    print("-" * len(header))
    for i, t in enumerate(trades[:max_rows]):
        sign = "+" if t.pnl > 0 else ""
        print(f"{i+1:>4}  {t.pair:<12} {t.side:<6} {t.entry_price:>10.4f} "
              f"{t.exit_price:>10.4f} {sign}{t.pnl:>7.2f} "
              f"{t.pnl_pct*100:>+6.2f}% {t.hold_bars:>5}  {t.exit_reason}")
    if len(trades) > max_rows:
        print(f"  ... {len(trades) - max_rows} more trades not shown")


def print_result_summary(r: BacktestResult):
    print(f"\n{'─'*60}")
    print(f"  Pair          : {r.pair}")
    print(f"  Bars          : {r.n_bars}  ({r.n_bars * 4}h ≈ {r.n_bars * 4 / 24:.0f} days)")
    print(f"  Trades        : {len(r.trades)}")
    print(f"  Win rate      : {r.win_rate()*100:.1f}%")
    print(f"  Total PnL     : ${r.total_pnl():+.2f}  ({r.total_return_pct():+.2f}%)")
    print(f"  Sharpe        : {r.sharpe():.2f}")
    print(f"  Max drawdown  : {r.max_drawdown()*100:.1f}%")
    print(f"  Profit factor : {r.profit_factor():.2f}")
    print(f"  Avg hold      : {r.avg_hold_bars():.1f} bars ({r.avg_hold_bars()*4:.0f}h)")
    print(f"  Exit reasons  : {r.exit_breakdown()}")


def print_portfolio_summary(results: List[BacktestResult], initial_cap: float):
    all_trades = [t for r in results for t in r.trades]
    all_pnl    = sum(t.pnl for t in all_trades)
    wins       = sum(1 for t in all_trades if t.pnl > 0)

    print(f"\n{'═'*60}")
    print("  PORTFOLIO SUMMARY")
    print(f"{'═'*60}")
    print(f"  Pairs tested  : {len(results)}")
    print(f"  Total trades  : {len(all_trades)}")
    print(f"  Win rate      : {wins/len(all_trades)*100:.1f}%" if all_trades else "  No trades")
    print(f"  Total PnL     : ${all_pnl:+.2f}  ({all_pnl/initial_cap*100:+.2f}%)")

    if len(all_trades) >= 5:
        rets  = [t.pnl_pct for t in all_trades]
        mean  = sum(rets) / len(rets)
        std   = statistics.stdev(rets)
        sharpe = (mean / std) * math.sqrt(6 * 365) if std > 1e-12 else 0.0
        print(f"  Portfolio Sharpe: {sharpe:.2f}")

    worst = min(results, key=lambda r: r.total_pnl()) if results else None
    best  = max(results, key=lambda r: r.total_pnl()) if results else None
    if worst and best:
        print(f"  Best pair     : {best.pair}  ${best.total_pnl():+.2f}")
        print(f"  Worst pair    : {worst.pair}  ${worst.total_pnl():+.2f}")
    print(f"{'═'*60}\n")


def save_csv(results: List[BacktestResult], output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    all_trades = [t for r in results for t in r.trades]
    path = os.path.join(output_dir, "trades.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pair", "side", "entry_bar", "exit_bar", "entry_price",
                    "exit_price", "stop_loss", "take_profit", "size_usd",
                    "pnl", "pnl_pct", "hold_bars", "exit_reason"])
        for t in all_trades:
            w.writerow([t.pair, t.side, t.entry_bar, t.exit_bar,
                        t.entry_price, t.exit_price, t.stop_loss, t.take_profit,
                        t.size_usd, t.pnl, t.pnl_pct, t.hold_bars, t.exit_reason])
    print(f"  Trade log saved → {path}")

    summary_path = os.path.join(output_dir, "summary.csv")
    with open(summary_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pair", "n_trades", "win_rate", "total_pnl", "total_return_pct",
                    "sharpe", "max_drawdown_pct", "profit_factor", "avg_hold_bars"])
        for r in results:
            w.writerow([r.pair, len(r.trades), round(r.win_rate(), 4),
                        round(r.total_pnl(), 4), round(r.total_return_pct(), 2),
                        round(r.sharpe(), 3), round(r.max_drawdown() * 100, 2),
                        round(r.profit_factor(), 3), round(r.avg_hold_bars(), 1)])
    print(f"  Summary saved  → {summary_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MARA SwingMACD Backtest")
    parser.add_argument("--live",       action="store_true",
                        help="Fetch real OKX historical data (requires ccxt)")
    parser.add_argument("--pair",       default=None,
                        help="Single pair to test, e.g. BTC/USDT")
    parser.add_argument("--all-pairs",  action="store_true",
                        help="Run all OKX_PAIRS")
    parser.add_argument("--bars",       type=int, default=500,
                        help="Number of H4 bars (default 500 ≈ 83 days)")
    parser.add_argument("--capital",    type=float, default=200.0,
                        help="Starting capital USD (default 200)")
    parser.add_argument("--output",     default=None,
                        help="Directory to save CSV reports")
    parser.add_argument("--verbose",    action="store_true",
                        help="Print every trade entry/exit")
    parser.add_argument("--seed",       type=int, default=42,
                        help="RNG seed for synthetic data (default 42)")
    args = parser.parse_args()

    pairs = OKX_PAIRS if args.all_pairs else ([args.pair] if args.pair else OKX_PAIRS)

    print(f"\nMARA SwingMACD Backtest")
    print(f"{'─'*60}")
    print(f"  Pairs    : {pairs}")
    print(f"  Bars     : {args.bars} H4 ({args.bars * 4 / 24:.0f} days)")
    print(f"  Capital  : ${args.capital:.2f}")
    print(f"  Data     : {'OKX live' if args.live else 'synthetic GBM'}")
    print(f"  MACD     : ({MACD_FAST}, {MACD_SLOW}, {MACD_SIGNAL})")
    print(f"  RSI      : {RSI_PERIOD} period")
    print()

    results = []
    for pair in pairs:
        print(f"Running {pair}...")
        if args.live:
            ohlcv = fetch_live_ohlcv(pair, args.bars)
        else:
            # XOR base seed with pair hash so each pair gets a distinct price path
            pair_seed = (args.seed ^ (abs(hash(pair)) % (2**16))) % (2**31)
            ohlcv = generate_synthetic_ohlcv(pair, args.bars, seed=pair_seed)

        bt = SwingMACDBacktest(
            pair=pair, ohlcv=ohlcv,
            capital=args.capital,
            verbose=args.verbose,
        )
        result = bt.run()
        results.append(result)

        print_result_summary(result)
        if result.trades:
            print()
            print_trade_log(result.trades)

    print_portfolio_summary(results, args.capital)

    if args.output:
        save_csv(results, args.output)


if __name__ == "__main__":
    main()
