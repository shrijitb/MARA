# workers/arbitrader/Dockerfile
#
# Build context: ./workers/arbitrader
# After COPY sidecar/ the container layout is:
#   /app/main.py          (sidecar/main.py)
#
# Architecture:
#   The former Java Arbitrader JVM has been replaced by NautilusTrader.
#   The Python sidecar IS the arb engine — no JVM process management needed.
#
#   In paper/backtest mode (PAPER_TRADING=true, default) the NT TradingNode
#   is skipped entirely — sidecar runs as a pure-Python paper arb simulator.
#   In live mode (PAPER_TRADING=false) NT connects to OKX demo/live API.
#
# Rust toolchain:
#   Required to build nautilus_trader from source when a pre-built wheel is
#   unavailable for this platform.  On ARM64 Python 3.12 (Raspberry Pi 5)
#   pre-built wheels exist as of nautilus_trader >= 1.200; the Rust path
#   is a fallback only.  Install is best-effort — sidecar degrades to paper
#   simulator if NT is absent.

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl \
       gcc \
       g++ \
       make \
       libssl-dev \
       pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain (fallback build path for nautilus_trader)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    httpx \
    structlog

# nautilus_trader — best-effort (pre-built wheel first, source fallback via Rust)
RUN pip install --no-cache-dir nautilus_trader \
    || echo "WARNING: nautilus_trader install failed. Starting in paper arb simulation mode."

COPY sidecar/ .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]


# ── Phase 3 note ──────────────────────────────────────────────────────────────
# When live OKX arb is ready, set in .env:
#   OKX_API_KEY=<key>
#   OKX_API_SECRET=<secret>
#   OKX_API_PASSPHRASE=<passphrase>
#   PAPER_TRADING=false
#   ARB_LEG_A=BTC-USDT-SWAP.OKX
#   ARB_LEG_B=ETH-USDT-SWAP.OKX
# The NT TradingNode will connect automatically.  No image rebuild needed.
