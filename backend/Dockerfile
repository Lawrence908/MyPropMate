# --- Frontend build -----------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- API ------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

# System deps:
#   gcc              - build wheels if needed
#   libreoffice-calc - headless xlsx -> pdf receipt rendering
#   fonts-liberation - fonts so rendered PDFs look right
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libreoffice-calc \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code and receipt template. Data (DB, tenants.json) is a volume.
COPY backend/app/ ./app/
COPY backend/templates/ ./templates/

# Built UI, served by FastAPI at / (see FRONTEND_DIR in app/main.py)
COPY --from=frontend /frontend/dist/ ./frontend/

# Runtime dirs (mounted as volumes in compose so state persists)
RUN mkdir -p /app/credentials /app/receipts /app/data /app/backups

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
