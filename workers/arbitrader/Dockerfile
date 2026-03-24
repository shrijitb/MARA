# workers/arbitrader/Dockerfile
#
# Build context: ./workers/arbitrader
# After COPY sidecar/ the container layout is:
#   /app/main.py          (sidecar/main.py)
#
# Java notes:
#   The Python sidecar manages the Arbitrader JVM process lifecycle.
#   In paper/backtest mode (MARA_LIVE=false, default) the JVM is never
#   launched — sidecar runs entirely as a Python paper arb simulator.
#   Java is NOT installed in this image. When MARA_LIVE=true is set for
#   Phase 3, switch to the openjdk variant (see comment at bottom).

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# httpx: sidecar imports httpx at module scope (fetch_jvm_metrics)
# structlog: sidecar uses structlog.get_logger at module scope
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    httpx \
    structlog

COPY sidecar/ .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]


# ── Phase 3: Live arb with real JVM ──────────────────────────────────────────
# When you're ready to run the actual Java Arbitrader process, replace the
# FROM line above with this multi-stage build:
#
# FROM --platform=linux/arm64 eclipse-temurin:21-jre-jammy AS jre
#
# FROM --platform=linux/arm64 python:3.12-slim
# COPY --from=jre /opt/java/openjdk /opt/java/openjdk
# ENV PATH="/opt/java/openjdk/bin:$PATH"
# ENV JAVA_HOME="/opt/java/openjdk"
# RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
# WORKDIR /app
# RUN pip install --no-cache-dir fastapi uvicorn httpx structlog
# COPY sidecar/ .
# COPY arbitrader.jar .          # pre-built JAR from agonyforge/arbitrader
# ENV ARBITRADER_JAR=/app/arbitrader.jar
# EXPOSE 8004
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
