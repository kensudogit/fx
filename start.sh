#!/bin/sh
set -e

cd /app
uvicorn src.main:app --host 127.0.0.1 --port 8000 &
cd /app/frontend
exec npm start -- -p "${PORT:-3000}" -H 0.0.0.0
