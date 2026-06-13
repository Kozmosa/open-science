# Repository Guidelines

## Instruction Priority

Agents working in this repository must treat [`PROJECT_BASIS.md`](PROJECT_BASIS.md) as a required long-lived constraints document.

- Follow `PROJECT_BASIS.md` for project goals, directory boundaries, documentation placement, coding standards, command entrypoints, and maintenance rules.
- If this file and `PROJECT_BASIS.md` overlap, apply the stricter rule.
- If a task-specific user instruction conflicts with `PROJECT_BASIS.md`, follow the user instruction for that task and keep other `PROJECT_BASIS.md` rules intact.

- Review [`dev-bitter-lesson.md`](dev-bitter-lesson.md) before debugging frontend deployment, browser/devtools tooling, multi-tenant permissions, or session-scoped config issues. It captures recurring high-cost mistakes and the corresponding fixed workflow.

## Project Structure & Module Organization

This repository's active product surface is the AINRF runtime plus WebUI, while the docs tree remains the long-lived product/reference knowledge base:

- `frontend/`: React + Vite WebUI for AINRF.
- `src/ainrf/`: Python package, CLI, backend API, and runtime code.
- `docs/`: Obsidian-style research notes and design docs. Key areas are `docs/framework/`, `docs/projects/`, and `docs/summary/`.
- `docs-site/`: Astro + Starlight product documentation site (deployed to GitHub Pages).
- `tests/`: CLI smoke tests for the Python package.
- `scripts/`: local build helpers.

Reference repositories live under `ref-repos/` and are treated as read-only research inputs.

## Project Overview

`scholar-agent` currently centers on the AINRF frontend/backend product surface. `src/ainrf/` and `frontend/` contain the active CLI, backend API, WebUI, and runtime capabilities, while `docs/`, `ref-repos/`, and the historical research notes remain long-lived knowledge and reference assets that support product design, implementation choices, and traceability. Notes continue to use Chinese content with English file slugs. Product documentation is built with Astro + Starlight in `docs-site/` and deployed to GitHub Pages.

## LLM Working Log

- `docs/LLM-Working/` is versioned working memory for plans, checklists, smoke notes, and agent-side implementation records.
- Daily work logs must live under `docs/LLM-Working/worklog/` using one file per day named `YYYY-MM-DD.md`.
- Before or during a work session, if today's file does not exist yet, create it first and keep appending to that same file for the rest of the day.
- The default unit is one changelog entry per completed modification plan or work slice, not one line per atomic edit/validation/commit action.
- Each changelog entry must record at least the time, the completed slice or plan label, the substantive change summary, and the validation outcome. If that slice produced commits, append the commit hash and subject in the same entry.
- Do not use the worklog as a transcript of commit subjects or atomic slice labels; summarize what the completed batch actually changed and verified.
- Treat the worklog as append-only session history. Do not silently rewrite earlier entries unless you are correcting an objective factual mistake.

## Build, Test, and Development Commands

- `cd docs-site && npm run dev`: start the docs site dev server with hot reload.
- `cd docs-site && npm run build`: build the static docs site for production.
- `cd docs-site && npm run preview`: preview the production build locally.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ainrf --help`: inspect the CLI scaffold.
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -n auto`: run the Python test suite in parallel across CPU cores via pytest-xdist (the `addopts` default is serial, so pass `-n auto` explicitly). Use `-n 0` or drop `-n` for serial execution when debugging an ordered failure.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src tests`: run lint checks.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src tests`: verify formatting.

### Build & Serve Shortcuts

- `cd docs-site && npm run build`: build the static docs site.
- `cd docs-site && npm run dev`: run the local docs dev server with hot reload.

Dependencies are managed by `uv`. Prefer `uv run ...` over manual venv activation so execution stays aligned with the lockfile.

### Frontend Command Constraints

- Frontend type-check must run from `frontend/`: `cd frontend && node_modules/.bin/tsc -b`
- Frontend tests: `cd frontend && npm run test:run` (vitest runs test files in parallel by default; pass `--no-file-parallelism` for serial execution).
- Frontend build: `cd frontend && npm run build`
- Do **not** use `npx tsc --noEmit`, `npx tsc -p tsconfig.app.json`, or run plain `tsc` from the repo root.
- This frontend uses project references; always use `tsc -b` from the `frontend/` directory.

## Coding Style & Naming Conventions

Use 4-space indentation and keep Python compatible with `>=3.13`. All Python code in `src/ainrf/`, `tests/`, and `scripts/` must include strict type annotations. Treat missing annotations as defects, not optional cleanup. Use `snake_case` for files, functions, and variables; use `PascalCase` for classes.

For notes, keep file slugs in English and content in Chinese. Use Obsidian wikilinks like `[[framework/v1-rfc]]`, YAML frontmatter, and Mermaid fences when needed.

Formatting and linting are enforced with `ruff`; static type checking must pass with `ty`; pre-commit hooks are defined in `.pre-commit-config.yaml`.

## Architecture

### AgenticResearcher 架构

任务系统采用两层架构：

- `agentic_researcher/` - 研究员层，负责任务管理和预设配置
- `harness_engine/` - 执行引擎层，负责底层执行能力

废弃的模块：

- `tasks/` - 旧的 ManagedTask 系统（已删除）
- `task_harness/` - 旧的 TaskHarness 系统（已删除）


### Multi-Tenant Permission Model

AINRF uses Linux user isolation for multi-tenancy. Understanding the permission model is critical to avoid silent failures.

**User roles:**
- `ainrf` (uid=1000) — the backend process user. Owns `/opt/ainrf/state/`, `/opt/ainrf/.ainrf_workspaces/`.
- `ainrf_<username>` (gid=2000/`ainrf_tenants`) — one Linux user per registered tenant. Home at `/home/ainrf_tenants/<username>/` with mode `0700`.
- `root` — runs entrypoint.py which provisions tenant users, homes, and workspace directories.

**Execution flow:**
1. Backend (ainrf) receives task → resolves `tenant_user = ainrf_<owner>`
2. Engine builds command → prefixes with `sudo -u ainrf_<owner>`
3. `sudoers` grants: `ainrf ALL=(%ainrf_tenants) NOPASSWD: ALL`
4. Agent process (claude/codex) runs as tenant user with tenant's workspace as cwd

**Permission constraints:**
- `ainrf` **cannot write** to tenant home dirs (mode 0700, owned by tenant)
- `ainrf` **cannot write** to tenant workspace dirs (owned by tenant, group ainrf_tenants, ainrf is not in that group)
- Any file/directory creation by `ainrf` inside tenant paths will EPERM
- Temp files created by `ainrf` (e.g., MCP config) must be `chmod 0644` if tenant subprocess needs to read them
- `sudo -u <tenant>` does NOT inherit `ainrf`'s env vars for API keys — these must be explicitly passed via the engine's env setup

**Known permission-sensitive code paths:**

| Path | Operation | Status |
|------|-----------|--------|
| `claude_code.py` | MCP config temp file → chmod 0644 | Fixed |
| `claude_code.py` | `_prepare_workspace_skills` creates dirs/symlinks via `sudo -u <tenant>` | Fixed |
| `service.py` | `_resolve_working_directory` uses `sudo -u <tenant> mkdir -p` for tenant workspaces | Fixed |
| `workspaces/service.py` | `ensure_tenant_workspace` uses `sudo -u <tenant> mkdir -p` | Fixed |
| `auth/service.py` | `provision_tenant_user` mkdir + chown | OK — runs during registration |
| `files.py` | Upload → chown to tenant | Fixed |
| `agent_sdk.py` | No `user=` param (removed) | Fixed |

**Guidelines for new code:**
- Never assume `ainrf` can write to `/home/ainrf_tenants/<username>/` paths
- If a file must be readable by a tenant subprocess (via `sudo -u`), set `chmod 0644` after creation
- If a directory must be created in tenant space, use `subprocess.run(["sudo", "-u", tenant_user, "mkdir", "-p", path])`
- Workspace dirs for new labels should be created via the tenant user, not directly by ainrf
### Docs Build Pipeline

Product documentation lives in `docs-site/` and is built with Astro + Starlight:

1. Content files are in `docs-site/src/content/docs/` (MDX format).
2. Sidebar and navigation configured in `docs-site/astro.config.mjs`.
3. `npm run build` generates static HTML to `docs-site/dist/`.
4. CI deploys `docs-site/dist/` to GitHub Pages on push to master.

Internal research notes in `docs/` use Obsidian-style Markdown with wikilinks and are not part of the public docs site.

### Directory Layout Notes

- `docs/index.md`: top-level docs/research index.
- `docs/projects/`: per-project research reports.
- `docs/framework/`: AI-Native Research Framework design notes.
- `docs/summary/`: cross-project comparison and synthesis.
- `.codex-skill-staging/`: Codex skill definitions and staging assets.

### Frontend Layout Components

- Reusable layout shells live in `frontend/src/components/layout/`.
- `PageShell`: standard outer card wrapper.
- `SplitPane`: left-right split layout with drag handle, keyboard resizing, and ARIA support.
- `SectionStack`: vertical section spacing with optional actions slot.
- `CardGrid`: draggable card grid with DnD and localStorage persistence.
- Prefer these shared layout primitives over duplicating layout patterns.

### Tailwind CSS Constraints

- Dynamic Tailwind classes such as `space-y-${gap}` or `gap-${n}` do not work reliably with Tailwind v4 JIT in this repo.
- Use static lookup maps instead, e.g. `const GAP_CLASSES: Record<number, string> = { 2: 'gap-2', 4: 'gap-4' }`.

### `@dnd-kit` Gotcha

- Do not nest `useDraggable` / `useDroppable` wrappers.
- `CardGrid` already provides an internal draggable wrapper; content passed via `renderCard` must not add another draggable layer.

### API Key Middleware

- External tools may probe Anthropic-compatible endpoints such as `/v1/models` and `/v1/messages`.
- These are exempted from API key auth in `src/ainrf/api/middleware.py` to avoid local 401 log spam.
- If new externally probed paths are added, update `_EXEMPT_PATH_PREFIXES` consistently.

### Runtime Fallback Notes

- Localhost environment detection is SSH-first.
- After repeated bounded SSH failure, runtime must fall back to the user's personal tmux session and surface a warning in the WebUI.
- Keep localhost tmux probe marker output newline-safe; a previous `printf %s\n` style bug produced literal `n` characters and broke parsing.

### Spec & Plan Documents

- Design specs: `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
- Implementation plans: `docs/superpowers/plans/YYYY-MM-DD-<topic>.md`

**Commit rules for spec/plan documents:**
- Design specs (`docs/superpowers/specs/`) are part of the long-lived knowledge base and should be committed.
- Implementation plans (`docs/superpowers/plans/`) are transient agent working artifacts and must **not** be committed to git. They should be kept in the working directory only and discarded after implementation completes.

### Note Conventions

- Frontmatter: YAML with fields such as `aliases`, `tags`, `source_repo`, `source_path`.
- Internal links: use Obsidian wikilinks like `[[note-name]]` or `[[note-name|label]]`.
- Callouts: use Obsidian `> [!type]` syntax, not MkDocs admonitions directly in source notes.
- Diagrams: use Mermaid fenced code blocks.
- File naming: English slugs, Chinese content.

## Testing Guidelines
Tests use `pytest`. Place new tests under `tests/` and name files `test_*.py`. Match function names to behavior, for example `test_serve_stub_runs`. Add or update smoke tests for every new CLI surface, parser behavior, or build-script contract you change.
### Test Markers
Every test file must declare a module-level `pytestmark` to categorize its tests:
| Marker | Scope | Count | Run |
|--------|-------|-------|-----|
| `api` | HTTP API route integration tests (full request/response) | 76 | `pytest -m api` |
| `unit` | Pure unit tests (no HTTP server, isolated logic) | 156 | `pytest -m unit` |
| `middleware` | Security, auth, audit, and request middleware | 72 | `pytest -m middleware` |
| `engine` | Execution engine, SSH, terminal, harness | 70 | `pytest -m engine` |
| `cli` | CLI commands, build scripts, server lifecycle | 61 | `pytest -m cli` |
| `integration` | Production-like integration tests (SPA, /api prefix) | 12 | `pytest -m integration` |
| `slow` | Tests that take >1s (opt-in marker for slow tests) | — | `pytest -m 'not slow'` |
When adding a new test file, add the appropriate marker:
```python
import pytest

pytestmark = [pytest.mark.api]  # or unit, middleware, engine, cli, integration
```
### Before Submitting
Before submitting changes to Python code, run both runtime and static checks:
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -n auto`
- `UV_CACHE_DIR=/tmp/uv-cache uv run ty check`
### Command Reference
- Backend tests must run from the repo root: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -n auto` (parallel; add `-n 0` for serial). Backend tests must not rely on the process working directory for output — write to `tmp_path` so parallel workers never collide.
- Frontend tests and type-check must run from `frontend/`.
- Start manual service testing with `uv run ainrf serve --host 127.0.0.1 --port 8000 --state-root ~/.ainrf`.
- Selective runs (also parallel by default): `pytest -m api -n auto`, `pytest -m unit -n auto`, `pytest -m 'not slow' -n auto`.
- Frontend test command: `cd frontend && npm run test:run`.

### Agent E2E Testing

AINRF uses a coding-agent-driven E2E testing approach. A coding agent (Claude Code, Codex, etc.) uses Playwright MCP to drive a browser against a production-like Docker container, executing the test scenarios defined in `testing/e2e/CHECKLIST.md`.

- **Test environment**: `testing/e2e/` — isolated Docker Compose with ephemeral tmpfs volumes, seeded test users, no TLS.
- **Start**: `testing/e2e/run.sh up` — builds image, starts containers, seeds users, prints credentials.
- **Stop**: `testing/e2e/run.sh down` — removes all containers and volumes.
- **Prerequisites**: `testing/e2e/check-prereqs.sh` — verifies Docker, Node.js, Playwright MCP, curl.
- **Agent prompt**: `testing/e2e/AGENT_PROMPT.md` — system prompt for the test agent.
- **MCP config**: `testing/e2e/config/mcp-servers.json` — Playwright MCP server configuration.
- **Results**: Agent writes reports to `testing/e2e/results/` (gitignored).

Ports: frontend on 8198, backend on 8199 (configurable via `AIWebPort`/`AITestPort`).

## Workspace Cleanliness

Agents must not leave temporary, backup, or one-off files in the repository root or any tracked directory. Specifically:

- **No backup archives** in the repo tree: `*.tar.gz`, `*.zip`, `*.iso`, `*.bak` must never be committed. If generated locally, they must stay gitignored and be cleaned up after use.
- **No one-off exports**: files like `kimi-export-*.md`, `session-*.md`, `*.log` are gitignored for a reason — do not `git add -f` them.
- **No large binaries**: PDF, PNG, JPEG, MP4, ISO and other binary blobs do not belong in the main repo. If needed for docs, host externally and link. The exceptions are `frontend/public/` assets and `docs/assets/` for small diagrams.
- **No temp scripts**: Do not create throwaway scripts in `scripts/` or at the root. If a script is needed for a task, put it in a worktree or `.claude/` scratch space and do not commit it.
- **Clean up after yourself**: Remove any files you created during investigation (profiling output, debug logs, temp configs) before finishing a session.
- **Runtime data is local**: `deploy/data/tenants/` and `deploy/data/workspaces/` are runtime state — never track them in git. If you need seed data for testing, put it in `deploy/examples/` or `testing/`.

## Commit & Pull Request Guidelines

Follow the existing commit style: short, imperative, and scoped when useful, e.g. `docs: revise framework...` or `chore: update gitignore`. Keep commits focused.

- Follow Conventional Commits for the first line: `feat: ...`, `fix: ...`, `refactor: ...`, `docs: ...`, `chore: ...`.
- Prefer one logical change per commit. Do not mix unrelated frontend, backend, docs, and hygiene changes in the same commit unless they are inseparable.
- Do not create commits from a dirty branch without first understanding whether unrelated changes belong to another work slice.
- Do not commit secrets, `.env` files, local API keys, or local investigation artifacts.
- Daily worklog updates under `docs/LLM-Working/worklog/` do not require a standalone `docs:`/`chore:` commit; they should normally be committed together with the corresponding `feat:`/`fix:`/`refactor:` work slice they record.
- Root-level governance documents such as `AGENTS.md`, `CLAUDE.md`, and `PROJECT_BASIS.md` must be committed in a dedicated `docs:` or `chore:` commit when they change. A single dedicated commit may update multiple such root-level governance files together.

### Git Workflow

- `master` is the protected stable branch. Treat it as read-mostly: sync from it, review from it, and merge into it via PR only.
- `develop` is the pre-release integration buffer. It may accept direct merges for validation/integration, but it is not the default branch to start feature work from.
- Start every new feature, fix, refactor, docs, or chore branch from the latest `master`, not from `develop`.
- Preferred branch prefixes are: `feat/`, `fix/`, `refactor/`, `docs/`, and `chore/`.
- Agent-only temporary branches should not be pushed to the remote and should be deleted after their useful changes are merged or extracted.

### Worktree Hygiene

- Default to worktree-first development for non-trivial work.
- The main workspace should stay clean and should not be the default place for feature implementation.
- Use `/.worktrees/<branch>` for formal development worktrees.
- Treat `/.claude/worktrees/` as temporary agent execution space only, not as a long-lived development location.
- After a branch is merged or abandoned, remove its corresponding worktree and delete the local branch.
- Regularly prune stale remote-tracking refs with `git fetch --prune origin` when reviewing repository hygiene.
- When auditing hygiene, inspect `git worktree list --porcelain` and `git branch -vv` before deleting anything.
- Preserve dirty or unaudited worktrees until their state is understood.

Pull requests should include:

- a brief summary of what changed,
- the commands you ran to validate it,
- screenshots only for docs/site rendering changes,
- links to related issues or design notes when applicable.

## Production Environment Safety

Do NOT operate production deployment containers (Docker, Kubernetes, etc.) — including `docker exec`, `docker compose restart`, `docker logs`, or any other container interaction — unless the user explicitly asks you to. This applies to any environment that serves real users or holds production data. When in doubt, ask first.

### Production Deployment Architecture (CPU-only)

The current production environment uses **CPU-only Docker Compose** with host networking:

```bash
# Deploy command (from repo root)
docker compose -f deploy/docker-compose.cpu.yml up -d --build
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
- Frontend static files served by nginx from `frontend/dist` (host-mounted, read-only).
- Backend runs as `ainrf` user (uid=1000) after privilege drop by entrypoint.
- Config: `deploy/config/nginx-host.conf` for nginx, `deploy/docker-compose.cpu.yml` for service layout.

**Named Docker volumes (persistent data):**

| Volume | Mount point | Content |
|--------|-------------|---------|
| `ainrf-state` | `/opt/ainrf/state` | SQLite databases, config, logs |
| `ainrf-workspaces` | `/opt/ainrf/.ainrf_workspaces` | User workspaces |
| `ainrf-tenants` | `/home/ainrf_tenants` | Tenant home directories |

**Key configuration (set in `.env`):**

- `AINRF_JWT_SECRET` — JWT signing key (required)
- `AINRF_API_KEY_HASHES` — SHA-256 hashes of API keys (required)
- `AINRF_PUBLIC_REGISTRATION_ENABLED` — defaults to `false`
- Agent tool keys: `ANTHROPIC_API_KEY`, `CODEX_API_KEY`, etc.

**Known operational issues:**

- **sshd session proliferation**: Each terminal health-check spawns an SSH session pair (root priv + ainrf child). These accumulate over the container lifetime. Container restart is the current cleanup path.

### Rebuild & Redeploy

```bash
# Backend-only changes — use the wrapper so the host git commit is stamped
# into the image (otherwise the backend reports "Unavailable" for its version).
bash deploy/redeploy-backend.sh

# Frontend-only changes — rebuilds host frontend/dist, then restarts nginx.
bash deploy/redeploy-frontend.sh

# Bare fallback (no commit stamping; backend version shows "Unavailable"):
# docker compose -f deploy/docker-compose.cpu.yml up -d --build ainrf
```

**Version provenance is split**: the backend bakes its OWN commit into
`/opt/ainrf/backend-build-info.json` (via `redeploy-backend.sh` build-args),
and the frontend ships its OWN `frontend/dist/build-info.json` (built on the
host). Because the two build at different times, they may differ — the
Settings page shows both and flags a mismatch.

**Why host build is required**: nginx serves frontend from a **host-mounted** volume (`frontend/dist:/usr/share/nginx/html:ro`), not from the container's built-in `/opt/ainrf/frontend/dist`. After frontend changes, the host `frontend/dist` must be rebuilt or nginx will serve stale files. Verify by checking the `index-*.js` hash in `frontend/dist/index.html` matches what the browser requests.

### Browser & DevTools (Working)

Both the OMP built-in browser tool and the chrome-devtools MCP are functional. Use the **chrome-devtools MCP** (via `browser` tool) as the primary tool for frontend inspection; fall back to the OMP browser tool when needed.

The system snap chromium at `/snap/bin/chromium` is **broken** (snap namespace fails on non-standard HOME `/data/yile.chen`). All browser tools use the Puppeteer-cached Chrome for Testing binary instead:

```
/data/yile.chen/.cache/puppeteer/chrome/linux-149.0.7827.22/chrome-linux64/chrome
```

This is configured via:
- `PUPPETEER_EXECUTABLE_PATH` in `~/.omp/agent/config.yml` `env` section
- `~/.local/bin/chromium` wrapper (symlinked as `chromium-browser`, `google-chrome`) shadows the snap binary via PATH priority
- `~/.omp/agent/mcp.json` — chrome-devtools MCP server definition
- `~/.claude/settings.json` — Claude Code env (`PUPPETEER_EXECUTABLE_PATH`) + `mcpServers`

**Note**: OMP config `env` vars only take effect at session start. Mid-session changes require a session restart.

### First-Time Admin Password

```bash
docker compose -f deploy/docker-compose.cpu.yml exec ainrf cat /opt/ainrf/state/admin_initial_password.txt
```

## Security & Configuration Tips

Do not commit secrets, SSH keys, or generated artifacts. Keep runtime state under `.ainrf/` out of version control. Prefer `uv run` over manual venv management so local execution matches the project lockfile.
