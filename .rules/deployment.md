# Deployment Architecture & Operations

Production and staging deployment topology, rebuild procedures, monitoring,
observability stack, and operational safety. Read this when deploying,
debugging production issues, modifying Docker/deploy configurations, or
setting up monitoring.

**Safety rule** (from AGENTS.md): Do NOT operate production deployment
containers unless the user explicitly asks you to.

## Production Deployment Architecture (CPU-only)

The production environment uses **CPU-only Docker Compose** with host networking and
an immutable release manifest:

```bash
# Deploy command (from repo root)
bash deploy/release-production.sh
```

**Architecture overview:**

| Service | Image | Listen | Role |
|---------|-------|--------|------|
| `ainrf` | `deploy/Dockerfile` (built) | `127.0.0.1:18000` | FastAPI backend |
| `nginx` | `nginx:1.27-alpine` | `0.0.0.0:8192` | Reverse proxy + frontend static |
| `prometheus` | `prom/prometheus:v3.3.1` | `127.0.0.1:9091` | Metrics collection |
| `grafana` | `grafana/grafana:11.6.1` | `127.0.0.1:3000` | Monitoring dashboard |

- All services use `network_mode: host` (no Docker NAT).
- External access: `http://<host>:8192` → nginx → backend on 18000.
- WebUI assets and nginx configuration are baked into the release web image.
- API, domain worker, and literature worker use the same API image reference.
- Production services have no source, configuration, or host `dist` bind mounts.
- Backend runs as `ainrf` user (uid=1000) after privilege drop by entrypoint.
- Config: `deploy/config/nginx-host.conf` for nginx, `deploy/docker-compose.cpu.yml` for service layout.

### Default ports and coexistence

| Environment | Browser/Web entry | Backend | Prometheus | Grafana | Binding contract |
|-------------|-------------------|---------|------------|---------|------------------|
| Production CPU | `0.0.0.0:8192` | `127.0.0.1:18000` | `127.0.0.1:9091` | `127.0.0.1:3000` | Only nginx is the routine external entry |
| Staging | `127.0.0.1:7192` | `127.0.0.1:17000` | `127.0.0.1:9092` | `127.0.0.1:2300` | Loopback-only unless an operator adds a separate authenticated tunnel/proxy |
| Worktree development | derived `127.0.0.1:41000-43999` | derived adjacent port | n/a | n/a | Three-port slot: frontend, API `+1`, CDP `+2` |

The default ranges do not overlap, so production, staging, and worktree development normally coexist. A rare hash-slot collision between worktrees fails closed and requires an explicit dev-port override; the tool never kills the existing listener. Do not reuse `8192/18000` or `7192/17000` for local development. Direct production monitoring ports are loopback-only; browser access goes through the authenticated `:8192/grafana` and `:8192/prometheus` paths. Production SSH uses `2222`; staging reserves `2223` only when its normally-disabled SSH/runtime path is explicitly enabled. Optional Litefuse overlays use `13000` (production) and `13001` (staging).

### Monitoring & Alerting (production default)

The CPU-only deployment includes Prometheus + Grafana with pre-configured dashboards and alert rules:

- **Grafana dashboard**: `http://<host>:8192/grafana` — pre-provisioned `ainrf-overview` dashboard shows HTTP request rates, auth events, SSH connections, terminal exec denials, and DB query latency. Auth proxy is enabled (login via AINRF session).
- **Prometheus**: scrapes `http://localhost:18000/metrics` every 15s; alert rules in `deploy/examples/prometheus-rules.example.yml` cover login failure rate, account lockouts, terminal exec denials, sensitive file access, high request/error rate. Copy to `deploy/config/prometheus/rules/ainrf.yml` and adjust thresholds.
- **Alert routing**: Prometheus evaluates rules; to receive notifications, configure Alertmanager or Grafana alert channels (not included by default — add a Grafana contact point for email/Slack/webhook).

### LLM Observability (optional overlay)

An independent Litefuse (Langfuse fork) stack provides trace-level LLM observability — token usage per call, prompt/completion logging, latency breakdown, cost tracking:

```bash
# Layer the observability stack on top of the base deployment
docker compose -f docker-compose.cpu.yml -f docker-compose.observability.yml up -d
```

- **Litefuse UI**: `http://<host>:13000` — after first start, create admin account and generate API keys.
- **Configuration**: set `AINRF_OBSERVABILITY_ENABLED=true` plus `AINRF_OBSERVABILITY_SECRET_KEY` / `PUBLIC_KEY` / `BASE_URL` in `.env`, then restart the ainrf service. See `deploy/docker-compose.observability.yml` header for full secret generation instructions.
- **Integration points**: `AgenticResearcherService` wraps each task lifecycle as a trace with per-turn generation spans; `LiteratureScheduler` wraps each subscription fetch. Both coexist with existing SQLite token tracking (dual-write).
- **Graceful degradation**: when Litefuse is disabled or unreachable, `SafeReporter` wraps all calls in try/except — observability failures never affect the main application.

| Observability Stack | Service | Port | What it shows |
|---------------------|---------|------|---------------|
| **Grafana** | Infrastructure + API metrics | `:8192/grafana` | HTTP rates, auth events, SSH, DB latency |
| **Prometheus** | Time-series metrics + queries | `:8192/prometheus` | Query builder, scrape targets, rules |
| **Litefuse** | LLM call traces | `:8192/litefuse/` | Per-call tokens, prompts, latency, cost |

### Named Docker Volumes (persistent data)

| Volume | Mount point | Content |
|--------|-------------|---------|
| `ainrf-state` | `/opt/ainrf/state` | SQLite databases, config, logs |
| `ainrf-workspaces` | `/opt/ainrf/.ainrf_workspaces` | User workspaces |
| `ainrf-tenants` | `/home/ainrf_tenants` | Tenant home directories |

### Key Configuration (set in `.env`)

- `AINRF_JWT_SECRET` — JWT signing key (required)
- `AINRF_API_KEY_HASHES` — SHA-256 hashes of API keys (required)
- `AINRF_PUBLIC_REGISTRATION_ENABLED` — defaults to `false`
- Agent tool keys: `ANTHROPIC_API_KEY`, `CODEX_API_KEY`, etc.

### Known Operational Issues

- **sshd session proliferation**: Each terminal health-check spawns an SSH session pair (root priv + ainrf child). These accumulate over the container lifetime. Container restart is the current cleanup path.

## Rebuild & Redeploy

```bash
# Build every artifact, write a release manifest, then deploy the matching set.
bash deploy/release-production.sh

# Build only; useful before pushing the tagged images to a registry.
OPENSCIENCE_RELEASE_MANIFEST=/secure/releases/<sha>.env \
  bash deploy/build-production.sh

# Staging is managed only through its isolated lifecycle preflight:
OPENSCIENCE_STAGING_ENV_FILE=/secure/path/staging.env bash scripts/staging.sh up

# Deploy prebuilt/pulled images by exporting the four image references from a
# reviewed release manifest, then running Compose with --no-build.
```

`build-production.sh` derives one release ID from the committed Git SHA, rejects
dirty builds by default, builds the API, web, Prometheus, and Grafana targets,
and records their exact image references in a mode-0600 manifest. Build all
artifacts before changing running services. Keep the previous manifest as the
rollback unit. Production containers require only images, runtime configuration,
secrets, and named data volumes after deployment; deleting a checkout or worktree
cannot break their code, frontend, or service configuration.

The legacy `redeploy-backend.sh` and `redeploy-frontend.sh` production targets
delegate to the same atomic release entrypoint. GPU remains a mutable laboratory
target and staging remains development-oriented.

Direct staging calls through the production redeploy wrappers are rejected.
`staging.sh up` rebuilds the current staging bundle and force-recreates its nginx
container so the bind mount follows any Vite output-directory replacement. A
default L0/L1 frontend build preserves all three target-specific bundle
directories while cleaning only the shared `frontend/dist` root artifacts.

Deployment wrappers explicitly clear `VITE_OPENSCIENCE_API_KEY` and
`VITE_AINRF_API_KEY` while building. Local WebUI credentials belong only to
the Vite proxy process and must never be embedded into a deployed browser
bundle through a lingering `.env.local` file.

## First-Time Admin Password

```bash
docker compose -f deploy/docker-compose.cpu.yml exec ainrf cat /opt/ainrf/state/admin_initial_password.txt
```

## Security & Configuration Tips

Do not commit secrets, SSH keys, or generated artifacts. Keep runtime state under `.ainrf/` out of version control. Prefer `uv run` over manual venv management so local execution matches the project lockfile.
