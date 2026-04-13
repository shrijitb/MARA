FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] structlog python-dotenv

COPY worker_api.py .

EXPOSE 8002

CMD ["uvicorn", "worker_api:app", "--host", "0.0.0.0", "--port", "8002"]
