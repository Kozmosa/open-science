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

# Build-args that must be declared before the first FROM so they can be used
# in FROM lines (e.g. selecting the runtime base image for CPU vs GPU).
ARG RUNTIME_BASE_IMAGE="docker.1ms.run/python:3.13-slim"
ARG PYTHON_VERSION="3.13"

# ── Stage 1: Frontend build ────────────────────────────────────────
FROM docker.1ms.run/node:24-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm config set registry https://registry.npmmirror.com && npm ci --ignore-scripts
COPY frontend/ ./
# Stamp frontend build provenance with the same commit as the backend.
# The host redeploy wrapper sets these; if unset, write-build-info.mjs
# falls back to git or the existing public/build-info.json.
ARG AINRF_BUILD_COMMIT=""
ARG AINRF_BUILD_COMMITTED_AT=""
ENV AINRF_BUILD_COMMIT=${AINRF_BUILD_COMMIT}
ENV AINRF_BUILD_COMMITTED_AT=${AINRF_BUILD_COMMITTED_AT}
RUN npm run build

# ── Stage 2: Backend build ────────────────────────────────────────
FROM docker.1ms.run/python:3.13-slim AS backend-build

COPY --from=ghcr.1ms.run/astral-sh/uv:0.11.20 /uv /usr/local/bin/uv

ENV UV_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple
ENV PIP_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple

WORKDIR /build
# Layer 1: install dependencies only (cached when pyproject.toml unchanged)
COPY pyproject.toml README.md ./
RUN mkdir -p src/ainrf && \
    UV_CACHE_DIR=/tmp/uv-cache uv pip install --system --no-cache-dir .
# Layer 2: overlay real source (invalidates only when Python code changes)
COPY src/ainrf/ src/ainrf/
RUN UV_CACHE_DIR=/tmp/uv-cache uv pip install --system --no-cache-dir .
# Stamp backend build provenance from host git (passed via build-args by the
# compose deploy wrapper). This is the backend's OWN version, independent of
# the frontend build — /settings/deployment-version reads it at runtime.
ARG AINRF_BUILD_COMMIT=""
ARG AINRF_BUILD_COMMITTED_AT=""
RUN python3 -c "import json,os; \
    c=(os.environ.get('AINRF_BUILD_COMMIT') or '').strip(); \
    t=(os.environ.get('AINRF_BUILD_COMMITTED_AT') or '').strip(); \
    json.dump({'short_commit': c[:6] or None, 'committed_at': t or None}, \
              open('/build/backend-build-info.json','w'), indent=2)"

# ── Stage 3: Agent tools ─────────────────────────────────────────
# Pin versions via build-arg so Docker layer cache is stable.
# Override at build time: --build-arg CLAUDE_CODE_VERSION=2.1.170

FROM docker.1ms.run/node:24-slim AS agent-tools
ARG CLAUDE_CODE_VERSION=2.1.170
ARG CODEX_VERSION=0.139.0
RUN --mount=type=cache,target=/root/.npm \
    npm config set registry https://registry.npmmirror.com && \
    npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}
RUN --mount=type=cache,target=/root/.npm \
    npm install -g @openai/codex@${CODEX_VERSION} && \
    if [ -d /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64 ]; then \
      cp -r /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64 \
             /usr/local/lib/node_modules/@openai/codex-linux-x64; \
    fi

# ── Stage 4: Runtime ──────────────────────────────────────────────
# Default runtime image ships Python 3.13.  Override with a CUDA runtime image
# for GPU deployments (e.g. nvidia/cuda:*-runtime-ubuntu24.04); the Python
# bootstrap step below will install python3.13 from deadsnakes if needed.
FROM ${RUNTIME_BASE_IMAGE} AS runtime
ARG PYTHON_VERSION

# If the chosen runtime base does not provide the required Python version,
# install it via deadsnakes.  This keeps the default CPU image unchanged while
# allowing nvidia/cuda-based GPU images to work without baking a custom image.
RUN set -eux; \
    installed_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo ""); \
    if [ "${installed_version}" != "${PYTHON_VERSION}" ]; then \
        sed -i 's|archive.ubuntu.com|mirrors.ustc.edu.cn|g; s|security.ubuntu.com|mirrors.ustc.edu.cn|g' /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true; \
        apt-get update; \
        apt-get install -y --no-install-recommends software-properties-common; \
        add-apt-repository -y ppa:deadsnakes/ppa; \
        apt-get update; \
        apt-get install -y --no-install-recommends python${PYTHON_VERSION} python${PYTHON_VERSION}-venv; \
        update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1; \
        update-alternatives --install /usr/bin/python python /usr/bin/python${PYTHON_VERSION} 1; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Runtime OS packages (USTC mirror) — includes SSH server for localhost self-test
RUN sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        sudo openssh-server bubblewrap socat procps tmux git && \
    rm -rf /var/lib/apt/lists/*

# uv from official image (needed for runtime Python dev commands)
COPY --from=ghcr.1ms.run/astral-sh/uv:0.11.20 /uv /usr/local/bin/uv

# Backend build provenance (own version, independent of frontend build)
COPY --from=backend-build /build/backend-build-info.json /opt/ainrf/backend-build-info.json

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

# ── Stage 3.5: ARIS skill registry ──────────────────────────────────
# Download the ARIS repo as a zip archive via codeload.github.com
# (separate from github.com, reachable where github.com is not)
# instead of git clone, which requires full github.com access.
# The entrypoint syncs skills into the workspace on startup.
ARG ARIS_REPO_OWNER=wanshuiyin
ARG ARIS_REPO_NAME=Auto-claude-code-research-in-sleep
ARG ARIS_REPO_REF=main
RUN python3 -c "import urllib.request, zipfile, os, shutil; url='https://codeload.github.com/${ARIS_REPO_OWNER}/${ARIS_REPO_NAME}/zip/refs/heads/${ARIS_REPO_REF}'; urllib.request.urlretrieve(url,'/tmp/aris.zip'); os.makedirs('/tmp/aris-extract',exist_ok=True); zipfile.ZipFile('/tmp/aris.zip').extractall('/tmp/aris-extract'); shutil.move(os.path.join('/tmp/aris-extract','${ARIS_REPO_NAME}-${ARIS_REPO_REF}'),'/opt/ainrf/aris-repo'); shutil.rmtree('/tmp/aris-extract',ignore_errors=True); os.unlink('/tmp/aris.zip')"

# Agent tool config templates (entrypoint substitutes env vars)
COPY deploy/config/ /opt/ainrf/config/
COPY deploy/config/entrypoint.py /opt/ainrf/bin/entrypoint.py

# State and workspace directories (mount volumes here for persistence)
# Multi-tenant isolation group (GID 2000) and backend user (GID 1000)
# Tenant users (ainrf_<username>) are created at runtime during registration.
RUN groupadd --gid 2000 ainrf_tenants && \
    mkdir -p /home/ainrf_tenants && \
    chown root:ainrf_tenants /home/ainrf_tenants && \
    chmod 0755 /home/ainrf_tenants && \
    groupadd --gid 1000 ainrf && \
    useradd --uid 1000 --gid ainrf --create-home --shell /bin/bash ainrf && \
    mkdir -p /opt/ainrf/state /opt/ainrf/.ainrf_workspaces /opt/ainrf/bin && \
    chown -R ainrf:ainrf /opt/ainrf
# Generate SSH host keys + login keys for localhost self-test
RUN mkdir -p /run/sshd /root/.ssh && \
    ssh-keygen -A && \
    mkdir -p /opt/ainrf/.ssh && \
    ssh-keygen -t ed25519 -f /opt/ainrf/.ssh/ainrf_local -N "" -C "ainrf-localhost" && \
    cat /opt/ainrf/.ssh/ainrf_local.pub > /root/.ssh/authorized_keys && \
    mkdir -p /home/ainrf/.ssh && \
    cat /opt/ainrf/.ssh/ainrf_local.pub > /home/ainrf/.ssh/authorized_keys && \
    chmod 600 /root/.ssh/authorized_keys /home/ainrf/.ssh/authorized_keys && \
    chown ainrf:ainrf /home/ainrf/.ssh /home/ainrf/.ssh/authorized_keys && \
    chown -R ainrf:ainrf /opt/ainrf/.ssh
RUN echo "PermitRootLogin prohibit-password" >> /etc/ssh/sshd_config.d/ainrf.conf
COPY deploy/config/ainrf-sudoers /etc/sudoers.d/ainrf
RUN chmod 440 /etc/sudoers.d/ainrf
ENV HOME=/opt/ainrf
# Agent tools verified at container start (health check), not at build time.

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
