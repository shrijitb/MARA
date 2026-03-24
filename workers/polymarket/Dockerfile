FROM python:3.11-slim
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY src/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir fastapi uvicorn httpx structlog
COPY src/ src/
COPY adapter/main.py adapter/main.py
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "adapter.main:app", "--host", "0.0.0.0", "--port", "8002"]