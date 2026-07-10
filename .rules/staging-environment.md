# Staging Environment

Staging mirrors the production stack (nginx + Prometheus + Grafana + backend)
with offset ports and isolated volumes. Backend source is bind-mounted for
hot-reload. Read this when developing against staging or verifying changes
before production deploy.

Production deployment details: [deployment.md](deployment.md)

Staging uses its own Compose project (`openscience-staging`), frontend bundle
(`frontend/dist/staging`), authentication cookie namespace, and opt-in
observability variables. `down --remove-orphans` therefore cannot classify
production services as staging orphans.

The staging backend is capped at 8 CPUs and 4 GiB memory. On the current
112-thread host this leaves production and unrelated workloads ample CPU
headroom even when staging is under load.

The Compose project-name change intentionally starts staging with a new set of
project-scoped volumes. Previous `deploy_staging-*` volumes are not attached;
staging is treated as disposable test state as documented by `staging.sh down`.

## Quick Start

```bash
# Start staging (builds image, starts all services, prints URLs)
bash scripts/staging.sh up

# Tail backend logs (shows uvicorn reload events)
bash scripts/staging.sh logs

# Stop and destroy everything (including data)
bash scripts/staging.sh down
```

## Access URLs

| Service | URL | Notes |
|---------|-----|-------|
| App | `http://<host>:7192/` | Full AINRF WebUI |
| Grafana | `http://<host>:7192/grafana` | Auth-gated via AINRF session |
| Backend direct | `http://<host>:17000/health` | Bypasses nginx |
| Prometheus | `localhost:9090` | Internal only, no nginx proxy |

## Port Mapping (staging ↔ production)

| Service | Staging | Production |
|---------|---------|------------|
| nginx | `:7192` | `:8192` |
| backend | `:17000` | `:18000` |
| sshd | `:2223` | `:2222` |
| prometheus | `:9092` | `:9091` |
| grafana | `:2300` | `:3000` |

## Backend Hot-Reload Workflow

1. `bash scripts/staging.sh up` — builds image, starts all services
2. Edit files in `src/ainrf/` — uvicorn detects changes and reloads automatically
3. Verify changes at `http://localhost:7192/`
4. For dependency changes (`pyproject.toml`), rebuild: `bash scripts/staging.sh rebuild`

## Frontend Update Workflow

```bash
cd frontend && npm run build
bash deploy/redeploy-frontend.sh --target staging
```

## Data Isolation

All staging data lives in `staging-*` Docker volumes. Production (`ainrf-*`) volumes are never touched. Both environments can run simultaneously on the same host.

## Lifecycle Commands

```bash
bash scripts/staging.sh up        # build + start, wait for healthy
bash scripts/staging.sh status    # show running state and URLs
bash scripts/staging.sh logs      # tail backend logs
bash scripts/staging.sh rebuild   # rebuild image, keep data
bash scripts/staging.sh creds     # print admin initial password
bash scripts/staging.sh down      # stop + remove all containers and volumes
```

## Test and Debug Workflow on Staging

1. **Start staging**: `bash scripts/staging.sh up`
2. **Iterate on backend code**: edit files under `src/ainrf/` — uvicorn auto-reloads within seconds; watch reload events in `bash scripts/staging.sh logs`
3. **Test API changes**: `curl http://localhost:7192/api/...` or open `http://<host>:7192/` in browser
4. **Check metrics**: `curl http://localhost:7192/metrics` or Grafana at `/grafana`
5. **Verify health**: `curl http://localhost:17000/health` — shows SSH status, Claude version, runtime readiness
6. **Compare with production**: both stacks run simultaneously — test the same API on `:7192` (staging) vs `:8192` (production) to confirm behavior parity
7. **View container logs**: `docker logs ainrf-staging` (backend), `docker logs ainrf-staging-nginx` (nginx), `docker logs ainrf-staging-prometheus` (metrics)
8. **Reset state**: `bash scripts/staging.sh down && bash scripts/staging.sh up` — destroys all data and starts fresh
9. **Deploy to production**: once verified on staging, run `bash deploy/redeploy-backend.sh` (production target) and `bash deploy/redeploy-frontend.sh`

**Important**: staging runs `AINRF_PRODUCTION=1` (same as production) so middleware, auth, and security behavior match exactly. The only differences are ports and data volumes.
