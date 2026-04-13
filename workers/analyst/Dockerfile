# workers/autohedge/Dockerfile
#
# Build context: ./workers/autohedge

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl gcc g++ make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Core deps — must succeed
RUN pip install --no-cache-dir fastapi uvicorn httpx structlog pyyaml

# AI pipeline deps — best-effort. worker_api.py catches ImportError at runtime
# and starts in stub mode (advisory_only=True, /signal returns []).
RUN pip install --no-cache-dir litellm \
    || echo "WARNING: litellm unavailable — autohedge stub mode"

RUN pip install --no-cache-dir swarms \
    || echo "WARNING: swarms unavailable — autohedge stub mode"

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8003

CMD ["uvicorn", "worker_api:app", "--host", "0.0.0.0", "--port", "8003"]
