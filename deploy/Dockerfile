# ══════════════════════════════════════════════════════════════════
# AINRF multi-stage production Dockerfile
# ══════════════════════════════════════════════════════════════════
#
# Stages:
#   frontend-build  — build React app with Node
#   backend-build   — install Python package with uv
#   runtime         — minimal production image (no build tools)
#
# Build:
#   docker build -f deploy/Dockerfile -t ainrf:latest .
#
# Run:
#   docker run -e AINRF_JWT_SECRET=... -e AINRF_API_KEY_HASHES=... ainrf:latest
#
# ══════════════════════════════════════════════════════════════════

# ── Stage 1: Frontend build ────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Backend build ────────────────────────────────────────
FROM python:3.13-slim AS backend-build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml ./
COPY src/ainrf/ src/ainrf/
RUN UV_CACHE_DIR=/tmp/uv-cache uv pip install --system --no-cache-dir .

# ── Stage 3: Runtime ──────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Runtime dependencies only (no Node, no uv, no git)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tmux && \
    rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from build stage
COPY --from=backend-build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=backend-build /usr/local/bin/ainrf /usr/local/bin/ainrf

# Copy frontend build output
COPY --from=frontend-build /build/frontend/dist /opt/ainrf/frontend/dist

# State directory (mount volume here)
RUN mkdir -p /opt/ainrf/state /opt/ainrf/.ainrf_workspaces
VOLUME /opt/ainrf/state

# Non-root user
RUN groupadd --gid 1000 ainrf && \
    useradd --uid 1000 --gid ainrf --no-create-home --shell /usr/sbin/nologin ainrf && \
    chown -R ainrf:ainrf /opt/ainrf
USER ainrf

EXPOSE 8000

ENV AINRF_PRODUCTION=1
ENV AINRF_HOST=0.0.0.0
ENV AINRF_PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["python", "-m", "ainrf", "serve", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--state-root", "/opt/ainrf/state"]
