FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-railway.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# テストレポートをビルド時に生成 (失敗しても起動は続行)
RUN mkdir -p tests/report && \
    python -m pytest tests/presentation/ \
        --html=tests/report/test_report.html \
        --self-contained-html \
        --tb=short \
        -q || true

ENV PYTHONUNBUFFERED=1

CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}
