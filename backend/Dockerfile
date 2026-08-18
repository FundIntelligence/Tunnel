FROM python:3.11-slim

WORKDIR /app

# Install system deps
# libpango/libcairo/libgdk-pixbuf/shared-mime-info are weasyprint's native
# runtime deps (GET /deals/{id}/report) — pip install succeeds without them,
# but weasyprint.HTML().write_pdf() OSErrors at call time on libgobject-2.0-0.
RUN apt-get update && apt-get install -y \
    build-essential \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Cloud Run expects PORT env
ENV PORT=8080

# Cloud Run's LB terminates TLS and forwards from an internal (non-loopback)
# address, so uvicorn needs --proxy-headers + --forwarded-allow-ips to trust
# its X-Forwarded-Proto header — otherwise request.base_url resolves to
# http:// even though the client connected over https:// (PAR-160 follow-up).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
