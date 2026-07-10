# Repository Guidelines

## Instruction Priority

Agents working in this repository must treat [`PROJECT_BASIS.md`](PROJECT_BASIS.md) as a required long-lived constraints document.

- Follow `PROJECT_BASIS.md` for project goals, directory boundaries, documentation placement, coding standards, command entrypoints, and maintenance rules.
- If this file and `PROJECT_BASIS.md` overlap, apply the stricter rule.
- If a task-specific user instruction conflicts with `PROJECT_BASIS.md`, follow the user instruction for that task and keep other `PROJECT_BASIS.md` rules intact.

- Review [`dev-bitter-lesson.md`](dev-bitter-lesson.md) before debugging frontend deployment, browser/devtools tooling, multi-tenant permissions, or session-scoped config issues. It captures recurring high-cost mistakes and the corresponding fixed workflow.

## Project Structure & Module Organization

This repository's active product surface is the OpenScience runtime plus WebUI, while the docs tree remains the long-lived product/reference knowledge base:

- `frontend/`: React + Vite WebUI for OpenScience.
- `src/ainrf/`: Python package, CLI, backend API, and runtime code.
- `docs/`: Obsidian-style research notes and design docs. Key areas are `docs/framework/`, `docs/projects/`, and `docs/summary/`.
- `docs-site/`: Astro + Starlight product documentation site (deployed to GitHub Pages).
- `tests/`: CLI smoke tests for the Python package.
- `scripts/`: local build helpers.

Reference repositories live under `ref-repos/` and are treated as read-only research inputs.

## Project Overview

`scholar-agent` currently centers on the OpenScience frontend/backend product surface. `src/ainrf/` and `frontend/` contain the active CLI, backend API, WebUI, and runtime capabilities; `src/ainrf/` remains the compatibility Python package name during the OpenScience transition. The legacy `ainrf` CLI remains available during the OpenScience compatibility phase. `docs/`, `ref-repos/`, and the historical research notes remain long-lived knowledge and reference assets that support product design, implementation choices, and traceability. Notes continue to use Chinese content with English file slugs. Product documentation is built with Astro + Starlight in `docs-site/` and deployed to GitHub Pages.

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
- `UV_CACHE_DIR=/tmp/uv-cache uv run openscience --help`: inspect the CLI scaffold.
  The legacy `ainrf` CLI remains available during the OpenScience compatibility phase.
- `bash scripts/ci.sh l0`: run the bounded agent/developer inner loop.
- `bash scripts/ci.sh l1`: run the complete deterministic backend/frontend/docs gate without Docker or external services.
- `bash scripts/test.sh all`: run the backend suite with a bounded parallel lane and a separate serial race/contention lane. The default worker limit is 8; lower it with `OPENSCIENCE_PYTEST_WORKERS`. Do not use `-n auto` on the shared production/development host.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src tests scripts`: run lint checks.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src tests scripts`: verify formatting.

### Build & Serve Shortcuts

- `cd docs-site && npm run build`: build the static docs site.
- `cd docs-site && npm run dev`: run the local docs dev server with hot reload.

Dependencies are managed by `uv`. Prefer `uv run ...` over manual venv activation so execution stays aligned with the lockfile.

### Five-Layer Hybrid CI

- `L0` agent/developer inner loop: `bash scripts/ci.sh l0`.
- `L1` deterministic gate: `bash scripts/ci.sh l1`; GitHub-hosted jobs run backend, frontend, and docs lanes separately.
- `L2` isolated container integration: reserved for per-SHA local CI cells; never reuse shared staging.
- `L3` deep system verification: trusted, serialized local tests for tenant permissions, SSH/tmux, backup/restore, full runtime, and performance.
- `L4` release acceptance: immutable artifacts promoted through release staging, manual production approval, read-only post-smoke, and rollback.
- Public pull-request code must never execute on a self-hosted runner attached to the production machine or its Docker daemon.
- Backend pytest defaults to at most 8 workers and frontend Vitest defaults to at most 4; lower them with `OPENSCIENCE_PYTEST_WORKERS` and `OPENSCIENCE_VITEST_WORKERS` when the shared host is under load.
- The long-lived design is documented in [`docs/superpowers/specs/2026-07-11-five-layer-hybrid-ci-design.md`](docs/superpowers/specs/2026-07-11-five-layer-hybrid-ci-design.md).

### Frontend Command Constraints

- All frontend tooling lives under `frontend/`. Commands must either `cd frontend && ...` or use `npm --prefix frontend ...`.
- **Prefer `--prefix`**: `npm --prefix frontend run <script>` works regardless of current `pwd` and avoids the most common worktree mistake (running `npm` from the repo root).
- Frontend type-check: `npm --prefix frontend run build` wraps `tsc -b`. Do **not** invoke `tsc -b` directly from outside `frontend/`.
- Frontend tests: `npm --prefix frontend run test:run` (vitest runs test files in parallel by default; pass `--no-file-parallelism` for serial execution).
- Frontend lint: `npm --prefix frontend run lint`.
- Do **not** use `npx tsc --noEmit`, `npx tsc -p tsconfig.app.json`, or run plain `tsc` / `npx tsc -b` from the repo root — the latter may install an unrelated `tsc` npm package.
- This frontend uses TypeScript project references; always use `tsc -b` from the `frontend/` directory.
- When installing dependencies: `npm --prefix frontend install [-D] <pkg>`.

## Worktree Working Guide

Worktree sessions differ from working in the main repo tree:

- **CWD is the repo root**, not `frontend/`. Shell state (including `cd`) does not persist across tool calls.
- All frontend commands must use `npm --prefix frontend ...` or explicit `cd frontend && ...`.
- `sed` batch import rewrites are fast but brittle — grep the full match set before running a batch, replace most-specific paths first, and verify with `npm --prefix frontend run build` immediately after.
- `git mv <src> <target>` silently nests when `<target>` already exists; check target existence first.
- When multiple planning documents exist (e.g., proposal vs implementation plan), their Phase 1 scopes may differ — cross-reference and clarify priority before starting.

> **Full details (CWD discipline, tsc hazards, sed mitigation, git mv pitfalls, config paths, dual-plan scoping)**: [.rules/worktree-working-guide.md](.rules/worktree-working-guide.md)

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

OpenScience uses Linux user isolation for multi-tenancy (`ainrf` backend user, `ainrf_<tenant>` per tenant, `sudo -u` execution). Any code creating files/dirs in tenant paths must use the tenant user. Never assume the `ainrf` user can write to `/home/ainrf_tenants/`.

> **Full details including code-path audit table**: [.rules/multi-tenant-permissions.md](.rules/multi-tenant-permissions.md)

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
- `docs/framework/`: OpenScience design notes.
- `docs/summary/`: cross-project comparison and synthesis.
- `.codex-skill-staging/`: Codex skill definitions and staging assets.

### Frontend Patterns

Use shared layout primitives (`PageShell`, `SplitPane`, `SectionStack`, `CardGrid`) from `frontend/src/components/layout/`. Dynamic Tailwind classes do not work — use static lookup maps. Do not nest `@dnd-kit` draggable wrappers.

> **Full details (component API, Tailwind, DnD, DevTools config, E2E testing)**: [.rules/frontend-and-testing.md](.rules/frontend-and-testing.md)

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
| Marker | Scope | Run |
|--------|-------|-----|
| `api` | HTTP API route integration tests (full request/response) | `bash scripts/test.sh api` |
| `unit` | Pure unit tests (no HTTP server, isolated logic) | `bash scripts/test.sh unit` |
| `middleware` | Security, auth, audit, and request middleware | `bash scripts/test.sh middleware` |
| `engine` | Execution engine, SSH, terminal, harness | `bash scripts/test.sh engine` |
| `cli` | CLI commands, build scripts, server lifecycle | `pytest -m cli -n 4` |
| `integration` | In-process production-mode API/SPA contracts | `bash scripts/test.sh production-contract` |
| `slow` | Tests that take >1s (opt-in marker for slow tests) | `pytest -m 'not slow' -n 4` |
When adding a new test file, add the appropriate marker:
```python
import pytest

pytestmark = [pytest.mark.api]  # or unit, middleware, engine, cli, integration
```
### Before Submitting
Before submitting changes to Python code, run both runtime and static checks:
- `bash scripts/ci.sh l1`
### Command Reference
- Backend tests must run from the repo root through `bash scripts/test.sh <lane>` or `bash scripts/ci.sh <layer>`. Backend tests must not rely on the process working directory for output — write to `tmp_path` so parallel workers never collide.
- Frontend tests and type-check must run from `frontend/`.
- Start manual service testing with `uv run openscience serve --host 127.0.0.1 --port 8000 --state-root ~/.ainrf`.
- Selective runs: `bash scripts/test.sh api`, `bash scripts/test.sh unit`, or explicit pytest commands with a bounded numeric `-n` value.
- Frontend test command: `cd frontend && npm run test:run`.

### Agent E2E Testing

`testing/e2e/` is a legacy exploratory Playwright-MCP harness, not a reproducible merge gate. It currently uses a mutable local image and fixed shared resources; do not run it for untrusted pull requests or cite it as L2 evidence. The future isolated container integration layer is defined by the five-layer CI design.

> **Full details (environment, scripts, MCP config, ports)**: [.rules/frontend-and-testing.md](.rules/frontend-and-testing.md)

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

### Git Workflow & Worktree Hygiene

`master` is protected; start branches from the **main workspace's** latest `master` (not `develop`). **All code changes must use the worktree-first flow** and merge back into the main workspace:

1. In the **main workspace**, make `master` current:
   - `git checkout master`
   - `git pull` / `git fetch origin` and reset to the latest `master` as needed.
2. Create a new branch in a worktree from that `master`:
   - `git worktree add -b <prefix>/<topic> .claude/worktrees/<prefix>-<topic> master`
   - Or use the Claude Code `EnterWorktree` tool, explicitly basing it on the main workspace's `master`.
3. Do all implementation, testing, and committing inside the worktree. Keep the main workspace clean.
4. When finished, switch back to the **main workspace**, merge the branch into `master`, then remove the worktree and delete the local branch.

Preferred prefixes: `feat/`, `fix/`, `refactor/`, `docs/`, `chore/`.

> **Full details (branch strategy, worktree conventions, PR expectations)**: [.rules/git-workflow.md](.rules/git-workflow.md)

## Production Environment Safety

Do NOT operate production deployment containers (Docker, Kubernetes, etc.) — including `docker exec`, `docker compose restart`, `docker logs`, or any other container interaction — unless the user explicitly asks you to. This applies to any environment that serves real users or holds production data. When in doubt, ask first.

### Production Deployment

CPU-only Docker Compose with host networking. Backend on `:18000`, nginx on `:8192`, Prometheus + Grafana for monitoring. Deploy: `docker compose -f deploy/docker-compose.cpu.yml up -d --build`. Rebuild via `deploy/redeploy-backend.sh` / `deploy/redeploy-frontend.sh`.

> **Full details (architecture, volumes, monitoring, observability, rebuild, admin credentials)**: [.rules/deployment.md](.rules/deployment.md)

### Staging Environment

Staging mirrors production with offset ports (`:7192` nginx, `:17000` backend). Backend source is bind-mounted for hot-reload. Start: `bash scripts/staging.sh up`.

> **Full details (ports, hot-reload, test workflow, lifecycle)**: [.rules/staging-environment.md](.rules/staging-environment.md)

### Browser & DevTools

Use chrome-devtools MCP as primary frontend inspection tool. Snap chromium is broken; Puppeteer-cached Chrome for Testing binary is configured instead. Config changes may require session restart.

> **Full details (binary path, config locations, OMP setup)**: [.rules/frontend-and-testing.md](.rules/frontend-and-testing.md)
