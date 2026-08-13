# Build context is the repo root (Tunnel/), not this directory — see
# cloudbuild-staging.yaml. That lets this isolated service reuse the real
# backend/v1 core engine + PAR-131 auth helpers at build time without
# forking them into a second copy that can drift from the source of truth.
FROM python:3.11-slim

WORKDIR /app

COPY parity-classify-sandbox/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY parity-classify-sandbox/app ./app
COPY parity-classify-sandbox/tests ./tests

# Only the core-engine + scoped-auth slice of backend/v1 this service
# actually imports (classifier.py, metrics_engine.py, integrations/auth.py,
# db/supabase_client.py) — not the rest of the v1 package (api.py, ingestion,
# parsing, musa, etc.), which this service has no business importing.
COPY backend/v1/__init__.py ./backend/v1/__init__.py
COPY backend/v1/core/__init__.py ./backend/v1/core/__init__.py
COPY backend/v1/core/classifier.py ./backend/v1/core/classifier.py
COPY backend/v1/core/metrics_engine.py ./backend/v1/core/metrics_engine.py
COPY backend/v1/integrations/__init__.py ./backend/v1/integrations/__init__.py
COPY backend/v1/integrations/auth.py ./backend/v1/integrations/auth.py
COPY backend/v1/db/__init__.py ./backend/v1/db/__init__.py
COPY backend/v1/db/supabase_client.py ./backend/v1/db/supabase_client.py

ENV PORT=8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
