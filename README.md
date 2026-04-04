# Arka (alpha build, formerly MARA): Agentic Risk-Kinetic Allocator

An open-source, autonomous trading system for turbulent macro environments. Arka coordinates specialized AI agents across crypto, futures, commodities, and prediction markets using dynamic regime-aware capital allocation.

**Status**: Needs papertesting (April 2026) | **License**: LGPL-3.0

---

## Quick Start

```bash
git clone https://github.com/shrijitb/mara
cd mara && python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in credentials — never commit .env
docker compose up -d
curl -s http://localhost:8000/status | python3 -m json.tool
```

→ Full setup per OS (Windows 11 / Ubuntu 24.04 / macOS): [Setup](#setup)

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Regime-Gated Capital Allocation](#regime-gated-capital-allocation)
- [Conflict Index](#conflict-index)
- [Setup](#setup)
  - [Windows 11](#windows-11)
  - [Ubuntu 24.04](#ubuntu-2404)
  - [macOS](#macos)
- [Configuration](#configuration)
- [Running the Stack](#running-the-stack)
- [Session Re-entry](#session-re-entry)
- [Tests](#test-suite)
- [Telegram Bot](#telegram-bot)
- [REST Contract](#rest-contract)
- [Risk Limits](#risk-limits)
- [Feature Status](#feature-status)
- [Known Constraints](#known-constraints)
- [Architecture Deep Dive](#architecture-deep-dive)
- [Data Sources](#data-sources)
- [Production Deploy](#production-deploy-raspberry-pi-5)
- [Development](#development)
- [License](#license)

---

## Project Overview

Arka targets **futures, crypto, forex, ETFs, and prediction markets** in regime-driven trading. The system operates in sequence: **backtest → paper trading (current) → live**.

### Core Design

A **FastAPI Hypervisor** orchestrates five specialized worker agents:

- **Nautilus**: ADX-routed strategy engine — MACD+Fractals for trending markets, mean-reversion for ranging markets, silence for ambiguous ADX
- **Polymarket**: CLOB market-making on prediction markets (stub until Phase 3)
- **Analyst**: Regime-aware market thesis via Ollama phi3:mini (advisory-only, no capital execution)
- **Arbitrader**: Cross-exchange spread arbitrage (Java + Python sidecar)
- **Core Dividends**: Passive SCHD + VYM ETF buy-and-hold sleeve

Capital flows dynamically based on **7 market regimes** (WAR_PREMIUM, CRISIS_ACUTE, BEAR_RECESSION, etc.). The hypervisor includes:
- Regime classifier (market data + ACLED + GDELT conflict index)
- Capital allocator (regime → per-worker weights, normalised)
- Risk manager (drawdown, VaR, cooldown, position limits)
- Quarterly profit sweep (APScheduler, Jan/Apr/Jul/Oct 7th @ 09:00)

### Environment

| Layer | Spec |
|-------|------|
| **Dev (pre-March 2026)** | Windows 11 → WSL2 Ubuntu-24.04 → Docker Desktop 4.63.0 |
| **Dev (March 2026+)** | Ubuntu 24.04 native |
| **Production** | Raspberry Pi 5 (16GB) → Docker ARM64 (buildx + QEMU) |
| **Exchange** | OKX only (Binance HTTP 451, Bybit HTTP 403 — geo-blocked) |
| **Data** | yfinance, FRED, ACLED, GDELT, live order books |

---

## Architecture

```
                        ┌─────────────────────────────┐
                        │  Hypervisor (port 8000)     │
                        │  FastAPI orchestrator       │
                        │  ┌──────────────────────┐  │
                        │  │  Regime Classifier   │  │
                        │  │  Conflict Index      │  │
                        │  │  Capital Allocator   │  │
                        │  │  Risk Manager        │  │
                        │  └──────────────────────┘  │
                        └──┬─────────────────────────┘
                           │ allocates + commands
     ┌─────────────────────┼──────────────────────────┐
     ▼                     ▼                          ▼
┌──────────┐  ┌─────────────┐  ┌──────────┐  ┌────────────────┐
│arbitrader│  │  nautilus   │  │ analyst  │  │ core_dividends │
│ port 8004│  │  port 8001  │  │ port 8003│  │   port 8006    │
│ arb sim  │  │ ADX-routed  │  │phi3:mini │  │  SCHD+VYM hold │
└──────────┘  └─────────────┘  └──────────┘  └────────────────┘
                   │
           ┌───────┴────────┐
           │  ADX < 20      │  ADX > 25
           ▼                ▼
    range_mean_revert   swing_macd
    (BB+RSI+Fractal)    (MACD+Fractal)

┌──────────────┐  ┌──────────────┐  ┌─────────────────┐
│ telegram-bot │  │    ollama    │  │   polymarket    │
│  polling,    │  │  port 11434  │  │   port 8002     │
│  no port     │  │  phi3:mini   │  │   CLOB stub     │
└──────────────┘  └──────────────┘  └─────────────────┘
```

### Worker Map

| Container | Key | Port | Tech | Mode |
|-----------|-----|------|------|------|
| mara-hypervisor | — | 8000 | FastAPI | Orchestrator |
| mara-nautilus | `nautilus` | 8001 | NautilusTrader | Paper sim — ADX-routed dual strategy |
| mara-polymarket | `polymarket` | 8002 | Python CLOB | Stub — needs `POLY_PRIVATE_KEY` |
| mara-analyst | `analyst` | 8003 | FastAPI + Ollama | phi3:mini thesis (advisory-only) |
| mara-arbitrader | `arbitrader` | 8004 | Java + Python sidecar | Paper arb sim |
| mara-core-dividends | `core_dividends` | 8006 | FastAPI | Paper hold (SCHD + VYM) |
| mara-ollama | — | 11434 | Ollama | phi3:mini CPU inference |
| mara-telegram-bot | — | none | python-telegram-bot | Polling — no inbound port |
| workers/stocksharp | — | 8005 | .NET 8 | Phase 3 only (IBKR routing) |

---

## Regime-Gated Capital Allocation

The classifier outputs one of 7 regime labels. Capital is split across workers per profile, with a cash buffer enforced at all times. Weights normalise against the sum of all non-zero profile entries — not just healthy workers — so a single worker starting up cannot absorb more than its intended share.

| Regime | arbitrader | nautilus | polymarket | analyst | core_dividends | Max deploy |
|--------|-----------|---------|-----------|---------|----------------|-----------|
| `WAR_PREMIUM` | 36% | 20% | 24% | 0% | 20% | 70% |
| `CRISIS_ACUTE` | 40% | 10% | 20% | 0% | 0% | 50% |
| `BEAR_RECESSION` | 20% | 36% | 16% | 8% | 20% | 75% |
| `BULL_FROTHY` | 28% | 36% | 8% | 8% | 20% | 80% |
| `REGIME_CHANGE` | 32% | 24% | 16% | 8% | 20% | 70% |
| `SHADOW_DRIFT` | 32% | 28% | 12% | 8% | 20% | 75% |
| `BULL_CALM` | 24% | 36% | 8% | 12% | 20% | 80% |

The `analyst` worker receives 0% allocation in WAR_PREMIUM and CRISIS_ACUTE — it is advisory-only and never executes trades, but its capital slot is still passed to keep the allocator profile sum consistent.

Priority order (first match wins): `WAR_PREMIUM > CRISIS_ACUTE > BEAR_RECESSION > BULL_FROTHY > REGIME_CHANGE > SHADOW_DRIFT > BULL_CALM`

In `CRISIS_ACUTE`, 50%+ stays in cash by design — core_dividends gets 0%.

Sharpe penalty: if a worker's rolling Sharpe < 0.5, its allocation is halved. Fresh workers store `None` Sharpe (not `0.0`) to avoid false penalisation.

---

## Conflict Index

A 0–100 war premium score that feeds the `WAR_PREMIUM` regime classifier. Six independent data layers with dynamic weight redistribution — if an API key is absent, its weight is absorbed by the market proxy, so the total always sums to 100%.

| Layer | Source | Base weight | Auth |
|-------|--------|-------------|------|
| 1 | Market proxy (defense ETF + gold/oil ratio + VIX) | 60% | None |
| 2 | GDELT conflict queries (Goldstein score) | 15% | None |
| 3 | UCDP GED georeferenced conflict events | 10% | `UCDP_API_TOKEN` |
| 4 | AIS chokepoint vessel traffic (Hormuz, Suez, Malacca, Taiwan, Bab-el-Mandeb) | 10% | `AISSTREAM_API_KEY` |
| 5 | NASA FIRMS VIIRS thermal anomalies | 3% | `NASA_FIRMS_API_KEY` |
| 6 | USGS M4.5+ earthquakes near critical infrastructure | 2% | None |

`WAR_PREMIUM` fires when `war_premium_score > 25`. Without optional keys, the score falls back to market proxy (83%) + GDELT (15%) + USGS (2%).

**ACLED status:** OAuth token is acquired successfully but `/api/cast/read` and `/api/acled/read` return HTTP 403 on the free tier — requires an approved researcher account. Permanently removed from active scoring; code preserved for future use.

**Optional Ollama enrichment:** `parse_osint_with_llm()` calls phi3:mini to extract affected commodities and escalation likelihood from UCDP event text. Advisory-only — never in the scoring hot path.

**Data source decisions:**
- **DXY proxy**: `UUP` ETF — `DX=F` and `DX-Y.NYB` return empty frames intermittently
- **BDI proxy**: `BDRY` ETF — `^BDI` delisted from yfinance
- **Gold/oil ratio threshold**: 45.0 — gold near $5,000 puts the ratio at ~57; old threshold of 20 false-triggered WAR_PREMIUM
- **Market proxy primary (60%+)**: no single geopolitical source can unilaterally trigger a regime change

---

## Setup

### Windows 11

MARA runs in Docker containers. On Windows, all development happens inside WSL2.

**1. Install WSL2**

Open PowerShell as Administrator:
```powershell
wsl --install
# Reboot when prompted. Ubuntu 24.04 LTS is installed by default.
```

**2. Install Docker Desktop for Windows**

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/).

During install: select "Use WSL 2 instead of Hyper-V". After install:
- Open Docker Desktop → Settings → Resources → WSL Integration
- Enable integration for Ubuntu-24.04
- Apply & Restart

**3. Open Ubuntu 24.04 and install Python 3.12**

```bash
# Start → Ubuntu 24.04  (or: wsl -d Ubuntu-24.04 in PowerShell)
sudo apt update && sudo apt install -y python3.12 python3.12-venv python3.12-dev git curl
```

**4. Clone and create the virtual environment**

```bash
cd ~
git clone https://github.com/shrijitb/mara.git
cd mara
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**5. Configure `.env`** — see [Configuration](#configuration) below.

**6. Start the stack**

```bash
docker compose up -d
```

> Docker Desktop on Windows includes buildx and QEMU. ARM64 images for Pi cross-build work automatically — do **not** add `platform:` flags to `docker-compose.yml`.

---

### Ubuntu 24.04

**1. Install Docker Engine**

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Run docker without sudo (log out and back in after)
sudo usermod -aG docker $USER
```

**2. Install Python 3.12**

```bash
sudo apt install -y python3.12 python3.12-venv python3.12-dev git curl
```

**3. Clone and set up**

```bash
cd ~
git clone https://github.com/shrijitb/mara.git
cd mara
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**4. QEMU for ARM64 cross-build** (optional — only needed to build Pi images on x86)

```bash
sudo apt install -y qemu-user-static
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
```

**5. Configure `.env`**, then start:

```bash
docker compose up -d
```

---

### macOS

**1. Install Docker Desktop for Mac**

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/). Install and start it. Docker Desktop on Mac includes buildx, compose, and QEMU.

**2. Install Python 3.12 via Homebrew**

```bash
# Install Homebrew if needed:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12 git
```

**3. Clone and set up**

```bash
cd ~
git clone https://github.com/shrijitb/mara.git
cd mara
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**4. Configure `.env`**, then start:

```bash
docker compose up -d
```

> **Apple Silicon (M1/M2/M3):** Docker Desktop handles ARM64 natively. Do **not** add `platform:` flags — they cause `exec format error` when pre-built native binaries (e.g. `ollama/ollama`) are forced through QEMU.

---

## Configuration

Copy `.env.example` to `.env` and fill in credentials. **Never commit `.env` to git.**

```ini
# Trading mode
MARA_MODE=backtest
MARA_LIVE=false
CYCLE_INTERVAL_SEC=60

# Safety defaults — do not change until paper trading is validated
PAPER_TRADING=true
USE_LIVE_RATES=false
USE_LIVE_OHLCV=false
INITIAL_CAPITAL_USD=200.0
EXCHANGES=["okx"]

# Ollama (local LLM — used by analyst worker and OSINT enrichment)
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=phi3:mini

# Data sources
FRED_API_KEY=                         # optional — yfinance fallback works without it
ACLED_EMAIL=
ACLED_PASSWORD=                       # free tier: token works, data endpoints 403

# Conflict index — optional enrichment sources
UCDP_API_TOKEN=                       # free — email ucdp.uu.se to request
AISSTREAM_API_KEY=                    # free — register at aisstream.io
NASA_FIRMS_API_KEY=                   # free — register at firms.modaps.eosdis.nasa.gov

# Nautilus strategy router
ACTIVE_STRATEGY=auto                  # auto (ADX-routed) | swing | range
RANGE_BB_PERIOD=20
RANGE_BB_STD=2.0
RANGE_RSI_PERIOD=14
RANGE_STOP_LOSS_PCT=0.015
RANGE_TAKE_PROFIT_RATIO=1.5

# OKX (only active exchange)
OKX_API_KEY=                          # Phase 3 only — leave empty for paper trading
OKX_API_SECRET=
OKX_API_PASSPHRASE=

# Polymarket (Phase 3 — leave empty)
POLY_PRIVATE_KEY=
POLY_MAX_EXPOSURE_USD=1000.0
POLY_MIN_EXPOSURE_USD=-1000.0

# IBKR (Phase 3 — leave as-is)
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

# Telegram bot
TELEGRAM_BOT_TOKEN=                   # from @BotFather
TELEGRAM_ALLOWED_USER_ID=             # from @userinfobot
```

### Regime thresholds (`config/regimes.yaml`)

```yaml
war_defense_momentum:  0.08
war_premium_threshold: 25.0
war_gold_oil_ratio:    45.0   # gold ~$5000 → ratio ~57 at baseline
crisis_vix:            40.0
crisis_yield_curve:   -0.50
bear_yield_curve:      0.0
bear_vix:             25.0
frothy_vix:           15.0
frothy_funding_rate:   0.0003
```

---

## Running the Stack

```bash
# Start everything
docker compose up -d

# Tail hypervisor logs
docker compose logs -f hypervisor

# Check container health
docker compose ps

# Rebuild a service after a code change
docker compose build --no-cache <service-name>
docker compose up -d          # always restart the FULL stack after any rebuild

# Stop everything
docker compose down
```

> **Critical:** Always restart with `docker compose up -d` after any rebuild. Using `--force-recreate` on a single container disconnects it from the Docker network shared by other services.

### Check live state

```bash
curl -s http://localhost:8000/status | python3 -m json.tool
curl -s http://localhost:8000/regime
curl -s http://localhost:8000/watchlist
curl -s http://localhost:8000/thesis              # latest analyst thesis
curl -s http://localhost:8001/health              # nautilus (includes adx_value, adx_state)
curl -s http://localhost:8003/health              # analyst
curl -s http://localhost:8004/metrics             # arbitrader prometheus
curl -s http://localhost:8006/health              # core_dividends

# Override nautilus strategy at runtime (no restart needed)
curl -s -X POST http://localhost:8001/strategy -H "Content-Type: application/json" \
     -d '{"mode": "swing"}'                       # auto | swing | range
```

---

## Session Re-entry

### Windows 11 / WSL2

```powershell
wsl -d Ubuntu-24.04
```
```bash
cd ~/mara
source .venv/bin/activate
docker compose up -d
curl -s http://localhost:8000/status | python3 -m json.tool
```

### Ubuntu 24.04 / macOS

```bash
cd ~/mara
source .venv/bin/activate
docker compose up -d
curl -s http://localhost:8000/status | python3 -m json.tool
```

---

## Test Suite

**Always use the venv Python directly** — the system Python lacks `fastapi`, `httpx`, and other dependencies.

```bash
~/mara/.venv/bin/python -m pytest tests/ -v
# Expected: 124 passed, 8 skipped, 0 failed
```

### Test breakdown

| Class | What it tests | Count |
|-------|--------------|-------|
| `TestWorkerContract` | nautilus + arbitrader REST contract endpoints | Pass |
| `TestCapitalAllocator` | dollar splits, Sharpe penalty, cold-start single-worker cap regression | Pass |
| `TestRiskManagerIntegration` | all 7 risk limits, cooldown, re-allocation peak-reset regression | 10/10 |
| `TestHypervisorCycle` | registry keys, capital math, classifier shape | 4/4 |
| `TestEndToEndSignalSchema` | signal format, `advisory_only` enforcement | 4/6, 2 skip |
| `TestAcledIntegration` | token acquisition, CAST, live events | 1/3, 2 skip |
| `TestGdeltIntegration` | GDELT query, conflict scoring | 3/3 |
| `TestConflictIndexNewSources` | UCDP/AIS/FIRMS graceful skip, weight redistribution, LLM fallback | 5/5 |
| `TestAnalystWorker` | signal schema, advisory-only, thesis cache, Ollama timeout | 5/5 |
| `TestAdxCalculator` | classify trending/ranging/ambiguous, column output, value range | 5/5 |
| `TestRangeMeanRevertStrategy` | dead-market filter, insufficient bars, signal structure | 4/4 |
| `TestStrategyRouter` | forced swing mode, auto default, `/strategy` runtime change | 3/3 |

### Expected skips

- `polymarket` contract tests — `py_clob_client` not in venv (passes in Docker)
- ACLED CAST + live events — free tier 403 is permanent, not a bug

---

## Telegram Bot

Set `TELEGRAM_BOT_TOKEN` (from [@BotFather](https://t.me/BotFather)) and `TELEGRAM_ALLOWED_USER_ID` (from [@userinfobot](https://t.me/userinfobot)) in `.env`, then restart the stack.

The bot uses long-polling — no inbound port or webhook required. All commands are rejected for any Telegram user ID other than `TELEGRAM_ALLOWED_USER_ID`.

| Command | Description |
|---------|-------------|
| `/status` | Capital snapshot, regime, worker health, PnL |
| `/regime` | Current regime label + confidence |
| `/watchlist` | Dynamic ticker watchlist |
| `/pause <worker>` | Halt new entries for a specific worker |
| `/resume <worker>` | Resume a paused worker |
| `$TICKER` (free text) | Any message containing e.g. `$AAPL` adds the ticker to the watchlist |

---

## REST Contract

Every trading worker implements these endpoints:

```
GET  /health    → {"status": "ok", "paused": bool, ...worker-specific fields}
GET  /status    → {"pnl": float, "sharpe": float, "allocated_usd": float, "open_positions": int}
GET  /metrics   → Prometheus text format
POST /signal    → list of signal dicts (each has "action", "rationale", "advisory_only")
POST /execute   → executes trade or returns advisory
POST /allocate  → {"amount_usd": float, "paper_trading": bool}
POST /pause     → halt new entries
POST /resume    → resume entries
POST /regime    → {"regime": str, "confidence": float, "paper_trading": bool}
```

Hypervisor-only endpoints:

```
GET  /watchlist               → {"watchlist": ["AAPL", ...]}
POST /watchlist               → {"ticker": "AAPL"}
POST /workers/{worker}/pause  → pause a named worker
POST /workers/{worker}/resume → resume a named worker
```

> **`/metrics` pattern:** Always return `Response(content=text, media_type="text/plain")` from FastAPI. A bare string return causes JSON encoding that breaks Prometheus scraping.

---

## Risk Limits

The `RiskManager` enforces these limits every cycle. A breach triggers a 1-hour halt cooldown.

| Limit | Value |
|-------|-------|
| Max portfolio drawdown | 20% |
| Max single worker allocation | 50% of total capital |
| Max open positions | 6 |
| Min free capital | 15% of total capital |
| PnL floor | −$40 |
| Worker max drawdown | 30% of worker's peak capital |
| Cooldown after breach | 1 hour |

**Drawdown baseline:** `peak_capital` resets on every capital re-allocation. This prevents a hypervisor-initiated rebalance (more workers coming online mid-run) from being misread as a worker drawdown.

---

## Feature Status

| ID | Feature | Status | Notes |
|----|---------|--------|-------|
| F-01 | Telegram command bot | Done | Polling, auth-gated, all commands implemented |
| F-02 | Passive dividend sleeve (`core_dividends`) | Done | SCHD + VYM paper hold, port 8006 |
| F-03 | Inverse ETF recession signals (SH, PSQ) | Done | Advisory-only until IBKR wired (Phase 3) |
| F-04 | Quarterly profit sweep skeleton | Done | APScheduler cron Jan/Apr/Jul/Oct 7th @ 09:00 |
| F-05 | Analyst worker (AutoHedge replacement) | Done | Direct Ollama HTTP, 5-min thesis cache, `GET /thesis` |
| F-06 | Conflict index expansion (UCDP/AIS/FIRMS/USGS) | Done | 6-source scoring, dynamic weight redistribution |
| F-07 | Nautilus ADX strategy router | Done | ADX gate + `range_mean_revert` strategy, `/strategy` toggle |
| F-08 | Vectorized strategy backtest scaffold | Done | `backtest/strategy_comparison.py`, OKX parquet cache |
| F-09 | Polymarket far-book live test | Blocked | Requires `POLY_PRIVATE_KEY` |
| F-10 | NautilusTrader full backtest harness | Parked | After 4+ weeks paper trading data |

---

## Known Constraints

| Constraint | Detail |
|-----------|--------|
| **OKX only** | Binance HTTP 451, Bybit HTTP 403 from this region. OKX perp symbol format: `BTC-USDT-SWAP` |
| **ACLED free tier** | OAuth token acquired successfully. `/api/cast/read` and `/api/acled/read` return 403 — requires approved researcher account. Permanent. |
| **IBKR Phase 3** | StockSharp `.NET 8` scaffold exists in `workers/stocksharp/` but not wired until Phase 3 |
| **Polymarket stub** | No live CLOB trading until `POLY_PRIVATE_KEY` is configured |
| **`advisory_only=True`** | All recession pair (SH, PSQ) and dividend signals are logged but not executed until IBKR is connected |
| **No `platform:` flags** | Adding platform constraints causes `exec format error` for pre-built native binaries (e.g. `ollama/ollama`) under QEMU |
| **`ollama/ollama` has no curl** | Healthcheck uses `["CMD", "ollama", "list"]` — not curl |
| **`python:3.11-slim` has no curl** | Polymarket healthcheck uses `python3 -c "import urllib.request; ..."` |
| **ADX ambiguous = silence** | ADX 20–25 returns no signals in auto mode — this is intentional, not a bug. Use `POST /strategy {"mode":"swing"}` to override. |
| **Analyst worker is advisory-only** | `analyst` never calls `/execute`. Its allocation weight in WAR_PREMIUM/CRISIS_ACUTE is 0% by design. |
| **Conflict index optional keys** | UCDP/AIS/FIRMS keys are optional. Missing keys redistribute weight to market_proxy; total always sums to 100%. |

---

## Architecture Deep Dive

### Hypervisor Loop

Each cycle (default 60 seconds):

1. **Fetch market data** — yfinance, FRED, ACLED, GDELT
2. **Classify regime** — market proxy (70–75%) + conflict scores
3. **Allocate capital** — regime profile → per-worker amounts
4. **Check health** — concurrent `asyncio.gather` to all workers (sequential awaits caused httpx client state failures)
5. **Request signals** — POST `/signal` to all healthy workers
6. **Risk check** — drawdown, VaR, position limits, cooldown state
7. **Execute** — POST `/execute` to eligible workers (skips `advisory_only` signals)
8. **Log metrics** — Prometheus scrape points updated
9. **Sleep** — until next cycle

### Capital Allocator

```python
# Normalise against total profile weight, not just healthy workers.
# A single worker starting up must not absorb all of max_deploy.
profile_nonzero_sum = sum(w for w in profile.values() if w > 0.0)
allocations = {
    worker: round(max_deploy * (weight / profile_nonzero_sum), 2)
    for worker, weight in eligible.items()
}
```

Sharpe penalty halves allocation if rolling Sharpe < 0.5. Fresh workers start with `None` Sharpe — not `0.0` — to avoid false penalisation.

### Risk Manager — Seven Enforcement Points

1. **Portfolio drawdown** — DD > 20% → cooldown
2. **Cooldown** — 1-hour halt after any violation
3. **PnL floor** — realised PnL < −$40 → cooldown
4. **Max positions** — open positions > 6 → reject signal
5. **Free capital** — free USD < 15% → reject signal
6. **Worker cap** — single worker > 50% → cap allocation
7. **Worker drawdown** — worker DD > 30% of peak → exclude worker

---

## Data Sources

### Market Data

- **OHLCV**: yfinance (equities, ETFs, crypto)
- **Macro**: FRED (fed funds rate, 10Y–2Y yield spread, DXY via UUP ETF)
- **Commodities**: yfinance (gold, oil, BDI proxy via BDRY ETF)
- **Sentiment**: VIX, BTC funding rates

### Conflict Index Sources

| Source | Weight | Cache | Notes |
|--------|--------|-------|-------|
| Market proxy (defense ETF, gold/oil, VIX) | 60%+ | Live | Always active; absorbs weight of absent sources |
| GDELT conflict sentiment | 15% | Live | No auth — rate-limited |
| UCDP GED conflict events | 10% | 4 h | Requires `UCDP_API_TOKEN` |
| AIS chokepoint vessel traffic | 10% | 15 min | Requires `AISSTREAM_API_KEY`; WebSocket, 8 s collection |
| NASA FIRMS thermal anomalies | 3% | 3 h | Requires `NASA_FIRMS_API_KEY`; VIIRS NRT CSV |
| USGS seismic (M4.5+ near infrastructure) | 2% | 1 h | No auth required |

Without any optional keys: market proxy = 83%, GDELT = 15%, USGS = 2%.

- **ACLED CAST / live events**: Removed from scoring — free tier returns HTTP 403 permanently

---

## Production Deploy (Raspberry Pi 5)

Target: Raspberry Pi 5, 16GB RAM, Docker ARM64. Docker pulls native ARM64 images automatically — no `platform:` flags needed.

**Find the Pi on your local network (from Windows):**

```powershell
arp -a   # look for MAC prefix DC:A6:32 or E4:5F:01
```

**Deploy:**

```bash
# Edit scripts/deploy_pi.sh — fill in the Pi's IP address, then:
bash ~/mara/scripts/deploy_pi.sh
```

**Verify on the Pi:**

```bash
ssh pi@<PI_IP>
cd ~/mara && docker compose ps
curl -s http://localhost:8000/status | python3 -m json.tool
```

---

## Development

### Adding a worker

1. Create `workers/<name>/worker_api.py` implementing the [REST contract](#rest-contract)
2. Add `workers/<name>/Dockerfile` (no `platform:` flag)
3. Add the service to `docker-compose.yml` with `depends_on: hypervisor: condition: service_healthy`
4. Register the worker key + URL in `hypervisor/main.py` `WORKER_REGISTRY`
5. Add allocation weights to all 7 regime profiles in `hypervisor/allocator/capital.py` (weights must sum to 1.0 per regime)
6. Add tests to `tests/test_integration_dryrun.py`

### Inter-service URL convention

Use Docker DNS names, overridable via env vars. Never hardcode `localhost` or IPs — they break on Pi and across Docker networks.

```
NAUTILUS_URL        http://worker-nautilus:8001
POLYMARKET_URL      http://worker-polymarket:8002
ANALYST_URL         http://worker-analyst:8003
ARBITRADER_URL      http://worker-arbitrader:8004
CORE_DIVIDENDS_URL  http://worker-core-dividends:8006
HYPERVISOR_URL      http://hypervisor:8000
```

### Key design decisions

- **OKX only** — Binance HTTP 451, Bybit HTTP 403. Symbol format: `BTC-USDT-SWAP`
- **Market proxy primary (60–83%)** — prevents commodity bull markets from false-triggering WAR_PREMIUM; absorbs weight of absent conflict sources
- **2-of-N signal requirement per regime** — prevents single-indicator false positives
- **Workers are FastAPI processes** — not Python class hierarchies; pluggable and replaceable
- **`asyncio.gather` for health checks** — sequential awaits in a dict comprehension caused httpx shared-client state failures
- **`worker_sharpe` stores `None` for fresh workers** — `0.0` would trigger the Sharpe gate every cycle
- **Ollama healthcheck uses `ollama list`** — `ollama/ollama` image has no curl/wget
- **Telegram bot sends direct via Bot API** — hypervisor uses `requests.post` to `api.telegram.org`; no inter-container dependency on the bot container
- **ADX ambiguous zone returns `[]`** — ADX 20–25 is indeterminate; no signals until the market commits to a direction. Override with `POST /strategy {"mode":"swing"}`.
- **Analyst is advisory-only** — `/execute` always returns `advisory_only=true`; it never moves capital
- **Conflict index weight redistribution** — absent API keys add their weight to market_proxy; total always sums to 1.0 so the score stays calibrated

---

## License

MARA is distributed under the **GNU Lesser General Public License v3.0 (LGPL-3.0)**.

### Why LGPL-3.0?

MARA uses **NautilusTrader** (also LGPL-3.0), which requires the same license. This is a feature:

- Use MARA for free, forever
- Modify it for your needs
- Sell hardware devices running MARA
- Run it commercially
- Keep modifications private
- Source code remains open and auditable

### Third-party licenses

| Project | License |
|---------|---------|
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | LGPL-3.0 |
| [StockSharp](https://github.com/StockSharp/StockSharp) | Apache 2.0 |

All licenses compatible with LGPL-3.0.

### Distribution requirements

If you **distribute** MARA (e.g. as a Pi device or hosted deployment):
- Include `LICENSE` and `NOTICE.txt`
- Provide a link to source code
- Document any modifications

See [LGPL3_COMPLIANCE.md](./LGPL3_COMPLIANCE.md) and [HARDWARE_DISTRIBUTION.md](./HARDWARE_DISTRIBUTION.md) for full requirements.

Full license text: [LICENSE](./LICENSE) | [LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0.txt)

---

## File Structure

```
mara/
├── LICENSE                              # LGPL-3.0
├── NOTICE.txt                           # Third-party attributions
├── LGPL3_COMPLIANCE.md                  # Compliance guide
├── HARDWARE_DISTRIBUTION.md             # Pi device distribution guide
├── README.md                            # This file
├── conftest.py                          # Pytest venv guard + sys.modules stubs
├── config.py                            # Python constants
├── pytest.ini                           # asyncio_mode=auto, integration mark
├── requirements.txt                     # Python dependencies
├── docker-compose.yml                   # Multi-container definition
├── config/
│   ├── settings.yaml
│   ├── regimes.yaml                     # Classifier thresholds (recalibrated March 2026)
│   └── allocations.yaml                 # Weight documentation (mirrors capital.py)
├── hypervisor/
│   ├── Dockerfile                       # Build context is project root (.)
│   ├── main.py                          # FastAPI orchestrator + APScheduler sweep
│   ├── allocator/capital.py             # RegimeAllocator — 7 regimes, 5 workers
│   ├── regime/classifier.py             # Regime detector
│   └── risk/manager.py                  # Risk enforcement
├── workers/
│   ├── nautilus/
│   │   ├── worker_api.py                # FastAPI port 8001, ADX-routed strategy engine
│   │   ├── indicators/adx.py            # Pure Python ADX (Wilder's smoothing)
│   │   └── strategies/
│   │       ├── swing_macd.py            # MACD + Fractals (trending, ADX >= 25)
│   │       └── range_mean_revert.py     # BB + RSI + Fractal S/R (ranging, ADX <= 20)
│   ├── polymarket/adapter/main.py       # FastAPI port 8002, CLOB stub
│   ├── analyst/worker_api.py            # FastAPI port 8003, phi3:mini thesis (advisory-only)
│   ├── arbitrader/sidecar/main.py       # FastAPI port 8004, JVM lifecycle
│   ├── core_dividends/worker_api.py     # FastAPI port 8006, SCHD+VYM hold
│   ├── telegram_bot/main.py             # Polling bot, no port
│   └── stocksharp/                      # Phase 3 only — .NET 8 IBKR router
├── data/feeds/
│   ├── market_data.py                   # yfinance, FRED wrappers; UUP/BDRY proxies
│   └── conflict_index.py                # 6-source conflict index; dynamic weight redistribution
├── backtest/
│   ├── strategy_comparison.py           # Vectorized pandas backtest (swing vs range)
│   └── run_swing_macd.py                # Legacy single-strategy runner
├── tests/
│   ├── test_mara.py                     # 124 unit + integration tests
│   └── test_integration_dryrun.py       # Dry-run integration suite
└── scripts/
    └── deploy_pi.sh                     # Raspberry Pi deployment script
```

---

## CI/CD

GitHub Actions pipelines live in [.github/workflows/](.github/workflows/).

| Workflow | Trigger | Jobs |
|----------|---------|------|
| `ci.yml` | Push to any branch, PR to main | test → build (main only) → deploy-vps (main) → deploy-pi (tags only) |
| `pr-check.yml` | PR to main | lint (ruff) + test |

### Required GitHub Actions Secrets

| Secret | Purpose |
|--------|---------|
| `DOCKER_USERNAME` | Docker Hub username |
| `DOCKER_PASSWORD` | Docker Hub password / access token |
| `VPS_HOST` | VPS hostname or IP |
| `VPS_USER` | VPS SSH username |
| `VPS_SSH_KEY` | VPS private SSH key (PEM) |
| `PI_HOST` | Raspberry Pi hostname or IP |
| `PI_USER` | Pi SSH username |
| `PI_SSH_KEY` | Pi private SSH key (PEM) |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather (same as `.env`) |
| `TELEGRAM_ALLOWED_USER_ID` | Your Telegram numeric user ID (same as `.env`) |

### Deployment targets

- **VPS (x86)** — auto-deploys on every push to `main` after images are built.
- **Raspberry Pi (ARM64)** — deploys only on `v*.*.*` tags (manual release). Uses `docker-compose.pi.yml` override (slower cycle interval, single Ollama model).

Multi-arch images (`linux/amd64,linux/arm64`) are pushed to Docker Hub in the build job; `docker compose pull` on each host fetches the native arch automatically. No `platform:` flags are added to `docker-compose.yml`.

---

## Disclaimer

ARKA is a research and development system. Past performance does not guarantee future results. Trading involves risk of loss. Start with paper trading and thoroughly validate before live deployment. No warranty. Use at your own risk.

---

**MARA v1.1 | April 2026 | LGPL-3.0**
