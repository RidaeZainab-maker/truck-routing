# Single-container build: Django API + built React app on one port.
# Target: Hugging Face Docker Space (app_port 7860, runs as uid 1000). Also runs anywhere:
#   docker build -t saferoute . && docker run -p 7860:7860 -e ORS_API_KEY=... saferoute

# ---- 1. Build the React (Vite) frontend ----
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Empty VITE_API_URL => the app calls /api/... on its own origin.
ENV VITE_API_URL=""
RUN npm run build

# ---- 2. Python runtime ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Hugging Face runs the container as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=user backend/ ./
COPY --chown=user --from=frontend /frontend/dist ./frontend_dist

# Non-secret defaults. Secrets (ORS_API_KEY, DJANGO_SECRET_KEY) come from the
# Space's "Variables and secrets" settings at runtime.
ENV HOME=/home/user \
    PORT=7860 \
    DJANGO_DEBUG=False \
    ALLOWED_HOSTS=".hf.space,localhost,127.0.0.1" \
    CSRF_TRUSTED_ORIGINS="https://*.hf.space" \
    FRONTEND_DIST=/home/user/app/frontend_dist \
    WEB_CONCURRENCY=2 \
    GUNICORN_THREADS=4

USER user
# Static files for admin/DRF + precompressed gzip copies of the SPA assets.
RUN python manage.py collectstatic --noinput \
 && python -m whitenoise.compress frontend_dist

EXPOSE 7860
# No database is used by the API (sqlite would live in the user-owned app dir anyway).
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY} --threads ${GUNICORN_THREADS} --timeout 120 --access-logfile -"]
