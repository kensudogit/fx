# Combined Dockerfile: Frontend (Next.js) + Backend (FastAPI) on single port
FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
ENV NEXT_PUBLIC_API_URL=
ENV NODE_ENV=production
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements-railway.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY --from=frontend-builder /app/frontend /app/frontend

# 商用グレード HTML レポートを生成して Next.js public/ へコピー
# results.json が存在すれば generate_report.py で美麗レポートを再生成する
# なければコミット済みの test_report.html をそのままコピーする
RUN pip install --no-cache-dir pytest-json-report && \
    mkdir -p /app/frontend/public/test-report && \
    if [ -f tests/report/results.json ]; then \
        python generate_report.py && \
        cp tests/report/test_report.html /app/frontend/public/test-report/index.html; \
    else \
        cp tests/report/test_report.html /app/frontend/public/test-report/index.html || true; \
    fi

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV PYTHONUNBUFFERED=1
ENV NODE_ENV=production

CMD ["/app/start.sh"]
