# ============================================================
# CryptoStream AI — FastAPI Backend
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# System deps (for psycopg2-binary, matplotlib, ta)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-build frontend static assets into /app/static
# (frontend must be built separately or via docker-compose build stage)

EXPOSE 8888

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8888/api/health || exit 1

CMD ["uvicorn", "chat_server:app", "--host", "0.0.0.0", "--port", "8888", "--workers", "2"]
