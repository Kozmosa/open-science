# ══════════════════════════════════════════════════════════════════
# AINRF multi-stage production Dockerfile
# ══════════════════════════════════════════════════════════════════
#
# Stages:
#   frontend-build  — build React app with Node
#   backend-build   — install Python package with uv
#   agent-tools     — install Claude Code CLI + Codex CLI via npm
#   runtime         — minimal production image
#
# Build:
#   docker build -f deploy/Dockerfile -t ainrf:latest .
#
# Run:
#   docker run -e AINRF_JWT_SECRET=... -e AINRF_API_KEY_HASHES=... ainrf:latest
#
# Agent tool config (set via environment):
#   ANTHROPIC_API_KEY   — Anthropic API key
#   ANTHROPIC_BASE_URL  — Anthropic API base URL
#   ANTHROPIC_MODEL     — default model (e.g. claude-sonnet-4-6)
#   CODEX_API_KEY       — OpenAI API key
#   CODEX_BASE_URL      — OpenAI API base URL
#   CODEX_MODEL         — default model (e.g. gpt-5.5)
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

ENV UV_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple
ENV PIP_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple

WORKDIR /build
COPY pyproject.toml ./
COPY README.md ./
COPY src/ainrf/ src/ainrf/
RUN UV_CACHE_DIR=/tmp/uv-cache uv pip install --system --no-cache-dir .

# ── Stage 3: Agent tools ─────────────────────────────────────────
# Installs Claude Code CLI and Codex CLI via npm.

FROM docker.1ms.run/node:24-slim AS agent-tools
RUN npm config set registry https://registry.npmmirror.com && \
    npm install -g @anthropic-ai/claude-code@latest && \
    npm install -g --registry https://registry.npmjs.org @openai/codex@latest
# Copy codex-linux-x64 to top level for require.resolve
RUN if [ -d /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64 ]; then \
      cp -r /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64 \
             /usr/local/lib/node_modules/@openai/codex-linux-x64; \
    fi

# ── Stage 4: Runtime ──────────────────────────────────────────────
FROM docker.1ms.run/python:3.13-slim AS runtime

# Runtime OS packages (USTC mirror)
RUN sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        bubblewrap procps tmux git && \
    rm -rf /var/lib/apt/lists/*

# Node.js runtime + Claude Code CLI + Codex CLI from agent-tools stage
COPY --from=agent-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-tools /usr/local/bin/claude /usr/local/bin/claude
COPY --from=agent-tools /usr/local/bin/codex /usr/local/bin/codex
COPY --from=agent-tools /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN ln -s /usr/local/lib/node_modules /usr/local/bin/node_modules

# Copy installed Python packages from build stage
COPY --from=backend-build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=backend-build /usr/local/bin/ainrf /usr/local/bin/ainrf

# Copy frontend build output
COPY --from=frontend-build /build/frontend/dist /opt/ainrf/frontend/dist

# Agent tool config templates (entrypoint substitutes env vars)
COPY deploy/config/ /opt/ainrf/config/
COPY deploy/config/entrypoint.py /opt/ainrf/bin/entrypoint.py

# State and workspace directories (mount volumes here for persistence)
RUN mkdir -p /opt/ainrf/state /opt/ainrf/.ainrf_workspaces /opt/ainrf/bin
VOLUME /opt/ainrf/state /opt/ainrf/.ainrf_workspaces

# Non-root user
RUN groupadd --gid 1000 ainrf && \
    useradd --uid 1000 --gid ainrf --create-home --shell /bin/bash ainrf && \
    mkdir -p /opt/ainrf/state /opt/ainrf/.ainrf_workspaces /opt/ainrf/bin && \
    chown -R ainrf:ainrf /opt/ainrf
ENV HOME=/opt/ainrf
# Verify agent tools (Claude Code is required; Codex may need runtime fix)
RUN claude --version && (codex --version || echo "WARNING: codex platform binary not available at build time")

# Default agent tool config (placeholder values — override via env)
ENV ANTHROPIC_API_KEY=sk-placeholder-change-me
ENV ANTHROPIC_BASE_URL=https://api.anthropic.com
ENV ANTHROPIC_MODEL=claude-sonnet-4-6
ENV CODEX_API_KEY=sk-placeholder-change-me
ENV CODEX_BASE_URL=https://api.openai.com/v1
ENV CODEX_MODEL=gpt-5.5

ENV AINRF_PRODUCTION=1
ENV AINRF_HOST=0.0.0.0
ENV AINRF_PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${AINRF_PORT:-8000}/health')"]

ENTRYPOINT ["python", "/opt/ainrf/bin/entrypoint.py"]
CMD ["sh", "-c", "python -m ainrf serve --host ${AINRF_HOST:-0.0.0.0} --port ${AINRF_PORT:-8000} --state-root /opt/ainrf/state"]
