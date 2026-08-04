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
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code, receipt template, and seed data
COPY app/ ./app/
COPY templates/ ./templates/
COPY data/ ./data/

# Runtime dirs (mounted as volumes in compose so state persists)
RUN mkdir -p /app/credentials /app/receipts /app/data /app/backups

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
