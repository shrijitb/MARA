#!/bin/bash
set -e
PI_USER="pi"
PI_HOST="192.168.1.xx"    # <-- SET THIS after finding Pi IP
PI_PATH="/home/pi/mara"

echo "Syncing to Pi at $PI_HOST..."
rsync -avz --exclude='.env' --exclude='data/db' --exclude='workers/*/src' \
  ./ $PI_USER@$PI_HOST:$PI_PATH/
scp .env $PI_USER@$PI_HOST:$PI_PATH/.env
ssh $PI_USER@$PI_HOST "cd $PI_PATH && docker compose pull && docker compose up -d"
