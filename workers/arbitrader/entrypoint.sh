#!/bin/bash
# Start Arbitrader in background, pipe to log file
java $JAVA_OPTS -jar /app/arbitrader.jar > /app/logs/arbitrader.log 2>&1 &

# Start sidecar
cd /app/sidecar && uvicorn main:app --host 0.0.0.0 --port 8004