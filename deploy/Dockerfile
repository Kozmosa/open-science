# ══════════════════════════════════════════════════════════════════
# AINRF multi-stage production Dockerfile
# ══════════════════════════════════════════════════════════════════
#
# Stages:
#   frontend-build  — build React app with Node
#   backend-build   — install Python package with uv
#   agent-tools     — install Claude Code + Codex CLI (global npm)
#   runtime         — minimal production image
#
# Build:
#   docker build -f deploy/Dockerfile -t ainrf:latest .
#
# Run:
#   docker run -e AINRF_JWT_SECRET=... -e AINRF_API_KEY_HASHES=... ainrf:latest
#
# ══════════════════════════════════════════════════════════════════

# ── Stage 1: Frontend build ────────────────────────────────────────
FROM docker.1ms.run/node:24-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Backend build ────────────────────────────────────────
FROM docker.1ms.run/python:3.13-slim AS backend-build

COPY --from=ghcr.1ms.run/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

WORKDIR /build
COPY pyproject.toml ./
COPY README.md ./
COPY src/ainrf/ src/ainrf/
RUN UV_CACHE_DIR=/tmp/uv-cache uv pip install --system --no-cache-dir .

# ── Stage 3: Agent tools (Claude Code + Codex CLI) ────────────────
# Uses the same Node base so we can copy both the Node runtime and
# the globally-installed agent CLIs from this single stage.
FROM docker.1ms.run/node:24-slim AS agent-tools

RUN npm config set registry https://registry.npmmirror.com && \
    npm install -g \
      @anthropic-ai/claude-code@latest \
      @openai/codex@latest

# ── Stage 4: Runtime ──────────────────────────────────────────────
FROM docker.1ms.run/python:3.13-slim AS runtime

# Runtime OS packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tmux && \
    rm -rf /var/lib/apt/lists/*

# Node.js runtime + agent CLIs (claude, codex) from agent-tools stage.
# agent-tools is based on node:24-slim, so it carries the full Node binary.
COPY --from=agent-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-tools /usr/local/bin/claude /usr/local/bin/claude
COPY --from=agent-tools /usr/local/bin/codex /usr/local/bin/codex
COPY --from=agent-tools /usr/local/lib/node_modules /usr/local/lib/node_modules

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
    useradd --uid 1000 --gid ainrf --create-home --shell /bin/bash ainrf && \
    mkdir -p /opt/ainrf/state /opt/ainrf/.ainrf_workspaces && \
    chown -R ainrf:ainrf /opt/ainrf
ENV HOME=/opt/ainrf
USER ainrf

# Verify agent tools are functional (runs as ainrf user)
RUN claude --version && codex --version

ENV AINRF_PRODUCTION=1
ENV AINRF_HOST=0.0.0.0
ENV AINRF_PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${AINRF_PORT:-8000}/health')"]

CMD python -m ainrf serve --host ${AINRF_HOST:-0.0.0.0} --port ${AINRF_PORT:-8000} --state-root /opt/ainrf/state
