# workers/nautilus/Dockerfile
#
# Build context: ./workers/nautilus
# After COPY the container layout is:
#   /app/worker_api.py
#   /app/strategies/swing_macd.py
#
# nautilus_trader notes:
#   Requires Rust toolchain to build from source on ARM64 slim images.
#   The install is attempted but does NOT fail the build on error — worker_api.py
#   already handles ImportError gracefully and falls back to the internal
#   paper trading simulator (engine_ready=False, engine_error set).
#   For the Raspberry Pi 5 (ARM64 Python 3.12) pre-built wheels are available
#   from PyPI as of nautilus_trader >= 1.200. If they're missing for this exact
#   platform/Python combo, the fallback activates automatically.

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl \
       gcc \
       g++ \
       make \
       libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Core runtime deps — these must succeed
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    httpx \
    structlog \
    yfinance \
    pandas \
    requests \
    pyyaml

# nautilus_trader — best-effort. If ARM64 wheel is unavailable, the worker
# starts in paper simulation mode without it. Do not fail the build.
RUN pip install --no-cache-dir nautilus_trader \
    || echo "WARNING: nautilus_trader wheel not found for this platform. Starting in paper simulation mode."

COPY . .

# strategies/ subdir is included in the COPY above.
# worker_api.py imports: from strategies.swing_macd import evaluate_signal
# PYTHONPATH=/app ensures this resolves correctly.

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["uvicorn", "worker_api:app", "--host", "0.0.0.0", "--port", "8001"]
