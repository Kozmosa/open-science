# ══════════════════════════════════════════════════════════════════
# AINRF multi-stage production Dockerfile
# ══════════════════════════════════════════════════════════════════
#
# Stages:
#   frontend-build  — build React app with Node
#   backend-build   — install Python package with uv
#   agent-tools     — download Claude Code binary + install Codex CLI
#   runtime         — minimal production image
#
# Build:
#   docker build -f deploy/Dockerfile -t ainrf:latest .
#
# Run:
#   docker run -e AINRF_JWT_SECRET=... -e AINRF_API_KEY_HASHES=... ainrf:latest
#
# Agent tool config (set via environment):
#   CLAUDE_API_KEY     — Anthropic API key
#   CLAUDE_BASE_URL    — Anthropic API base URL
#   CLAUDE_MODEL       — default model (e.g. claude-sonnet-4-6)
#   CODEX_API_KEY      — OpenAI API key
#   CODEX_BASE_URL     — OpenAI API base URL
#   CODEX_MODEL        — default model (e.g. gpt-5.5)
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

# ── Stage 3: Agent tools ─────────────────────────────────────────
# Downloads Claude Code native binary from GitHub via ghfast mirror,
# and installs Codex CLI via npm (npmmirror).
FROM docker.1ms.run/node:24-slim AS agent-tools

# Claude Code: download native binary via GitHub mirror
ARG CLAUDE_CODE_VERSION=latest
RUN apt-get update && apt-get install -y --no-install-recommends curl tar && \
    rm -rf /var/lib/apt/lists/* && \
    if [ "$CLAUDE_CODE_VERSION" = "latest" ]; then \
      VERSION=$(curl -sL https://api.github.com/repos/anthropics/claude-code/releases/latest | \
        grep '"tag_name"' | head -1 | sed -E 's/.*"v([^"]+)".*/\1/'); \
    else \
      VERSION="$CLAUDE_CODE_VERSION"; \
    fi && \
    echo "Installing Claude Code v${VERSION}" && \
    curl -sL "https://ghfast.top/https://github.com/anthropics/claude-code/releases/download/v${VERSION}/claude-linux-x64.tar.gz" \
      -o /tmp/claude.tar.gz && \
    mkdir -p /opt/claude-code && \
    tar xzf /tmp/claude.tar.gz -C /opt/claude-code && \
    rm /tmp/claude.tar.gz && \
    /opt/claude-code/claude --version

# Codex CLI: install via npm with China mirror
RUN npm config set registry https://registry.npmmirror.com && \
    npm install -g @openai/codex@latest

# ── Stage 4: Runtime ──────────────────────────────────────────────
FROM docker.1ms.run/python:3.13-slim AS runtime

# Runtime OS packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tmux && \
    rm -rf /var/lib/apt/lists/*

# Claude Code: standalone native binary (no Node.js needed)
COPY --from=agent-tools /opt/claude-code /opt/claude-code
RUN ln -s /opt/claude-code/claude /usr/local/bin/claude

# Node.js runtime + Codex CLI from agent-tools stage
COPY --from=agent-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-tools /usr/local/bin/codex /usr/local/bin/codex
COPY --from=agent-tools /usr/local/lib/node_modules /usr/local/lib/node_modules

# Copy installed Python packages from build stage
COPY --from=backend-build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=backend-build /usr/local/bin/ainrf /usr/local/bin/ainrf

# Copy frontend build output
COPY --from=frontend-build /build/frontend/dist /opt/ainrf/frontend/dist

# Agent tool config templates (entrypoint substitutes env vars)
COPY deploy/config/ /opt/ainrf/config/
COPY deploy/config/entrypoint.py /opt/ainrf/bin/entrypoint.py

# State directory (mount volume here)
RUN mkdir -p /opt/ainrf/state /opt/ainrf/.ainrf_workspaces /opt/ainrf/bin
VOLUME /opt/ainrf/state

# Non-root user
RUN groupadd --gid 1000 ainrf && \
    useradd --uid 1000 --gid ainrf --create-home --shell /bin/bash ainrf && \
    mkdir -p /opt/ainrf/state /opt/ainrf/.ainrf_workspaces /opt/ainrf/bin && \
    chown -R ainrf:ainrf /opt/ainrf
ENV HOME=/opt/ainrf
USER ainrf

# Verify agent tools are functional
RUN claude --version && codex --version

# Default agent tool config (placeholder values — override via env)
ENV CLAUDE_API_KEY=sk-placeholder-change-me
ENV CLAUDE_BASE_URL=https://api.anthropic.com
ENV CLAUDE_MODEL=claude-sonnet-4-6
ENV CLAUDE_HAIKU_MODEL=claude-haiku-4-5-20251001
ENV CLAUDE_SONNET_MODEL=claude-sonnet-4-6
ENV CLAUDE_OPUS_MODEL=claude-opus-4-6
ENV CODEX_API_KEY=sk-placeholder-change-me
ENV CODEX_BASE_URL=https://api.openai.com/v1
ENV CODEX_MODEL=gpt-5.5
ENV CODEX_REVIEW_MODEL=gpt-5.4

ENV AINRF_PRODUCTION=1
ENV AINRF_HOST=0.0.0.0
ENV AINRF_PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${AINRF_PORT:-8000}/health')"]

ENTRYPOINT ["python", "/opt/ainrf/bin/entrypoint.py"]
CMD ["python", "-m", "ainrf", "serve", "--host", "0.0.0.0", "--port", "8000", "--state-root", "/opt/ainrf/state"]
