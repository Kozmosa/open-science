# Repository Guidelines

## Authority and Conflict Handling

[`PROJECT_BASIS.md`](PROJECT_BASIS.md) is the highest-authority, human-reviewed
source of long-lived OpenScience facts and rules.

- Agents must never edit `PROJECT_BASIS.md`. Only the user may change it after
  human review.
- Repository instructions, local guidance, current docs, specs, plans, code,
  schemas, tests, and deployment configuration must not silently override it.
- If another instruction contradicts `PROJECT_BASIS.md`, stop the affected
  decision and ask the user how the drift should be resolved. Do not choose the
  stricter, newer, or more implementation-aligned statement automatically.
- If reliable engineering evidence appears to contradict `PROJECT_BASIS.md`,
  report the evidence and ask the user to choose an implementation correction
  or a manual `PROJECT_BASIS.md` revision.
- A task-specific user instruction may override ordinary repository workflow
  for that task, but a durable project-basis change remains user-owned.

## Working Principles

- State assumptions when they materially affect behavior, architecture, data,
  safety, or scope. Resolve high-impact ambiguity before implementing.
- Prefer the smallest coherent change that fully satisfies the request. Do not
  add speculative configurability, abstractions, or adjacent cleanup.
- Keep changes surgical. Preserve unrelated code, comments, formatting, and
  user-owned work; remove only artifacts made obsolete by the current change.
- Convert work into verifiable outcomes. For a bug, obtain a reproducer or
  regression test when practical; for a multi-step change, identify the check
  that proves each step.
- Fix rules at the module, authority, or seam that owns them. Surface the
  tradeoff before introducing a downstream workaround for an upstream limit.
- Use repository or framework facilities before creating custom machinery.
- Report which validations ran and why any relevant validation was skipped.

## Context Routing

Read only the task-relevant material below; do not recursively load unrelated
reference or archived documents. A directory README is navigational context,
not an authority that can override `PROJECT_BASIS.md`, current code, schemas, or
tests.

| Task touches | Required context |
| --- | --- |
| Backend, API, domain, runtime, or CLI | [`src/ainrf/README.md`](src/ainrf/README.md) and [`docs-site/docs/architecture.md`](docs-site/docs/architecture.md) |
| Frontend implementation, tests, or browser behavior | [`frontend/README.md`](frontend/README.md) and [`.rules/frontend-and-testing.md`](.rules/frontend-and-testing.md) |
| Frontend deployment, DevTools, session-scoped config, or recurring environment failures | [`dev-bitter-lesson.md`](dev-bitter-lesson.md) before diagnosis |
| Tenant provisioning, auth, uploads, workspace paths, or cross-user execution | [`.rules/multi-tenant-permissions.md`](.rules/multi-tenant-permissions.md) and the relevant `dev-bitter-lesson.md` section |
| Worktrees, branch synchronization, merges, or cleanup | [`.rules/git-workflow.md`](.rules/git-workflow.md) and [`.rules/worktree-working-guide.md`](.rules/worktree-working-guide.md) |
| Active specs, plans, authority, archival, or long-lived docs | [`docs/documentation-governance.md`](docs/documentation-governance.md) and the active spec inventory |
| Staging | [`.rules/staging-environment.md`](.rules/staging-environment.md) |
| Production, release, rollback, backup, or observability operations | [`.rules/deployment.md`](.rules/deployment.md); production actions still require explicit user authorization |
| Generated HTTP transport | [`frontend/src/generated/transport/README.md`](frontend/src/generated/transport/README.md) and the architecture contract |

## Project Surface

The active product is the OpenScience runtime and WebUI:

- `src/ainrf/`: canonical Python package, CLI, backend API, domain Modules, and
  runtime code.
- `frontend/`: React + Vite WebUI.
- `docs-site/`: current public product documentation.
- `docs/`: internal design, engineering reference, research input, history, and
  working memory governed by `docs/documentation-governance.md`.
- `tests/`: backend, API, middleware, engine, CLI, integration, and regression
  tests.
- `scripts/`: repository-level build, validation, development, and release
  helpers.
- `ref-repos/`: read-only research inputs; never treat them as product source.

OpenScience is the user-facing brand. `ainrf` is the canonical backend package,
runtime, state-path, Linux, deployment, telemetry, and backend configuration
identity. Backend variables use `AINRF_*`; corresponding `OPENSCIENCE_*`
variables are compatibility aliases. Repository development and orchestration
variables may use the OpenScience prefix as defined by `PROJECT_BASIS.md`.

## LLM Working Log

- When a task actually modifies, develops, validates, or commits repository
  state, use `docs/LLM-Working/worklog/YYYY-MM-DD.md`. Read-only explanation,
  review, or investigation does not create a worklog entry by itself.
- Create today's file if needed, then append one changelog entry per completed
  work slice rather than one line per atomic edit or command.
- Record the time, slice label, substantive result, and validation outcome. If
  the slice creates commits, identify them in the same entry.
- Keep the log append-only except when correcting an objective factual error.

## Build, Test, and Development Commands

- Fast inner loop: `bash scripts/ci.sh l0`.
- Complete deterministic gate: `bash scripts/ci.sh l1`.
- Backend lanes: `bash scripts/test.sh api`, `unit`, `middleware`, `engine`, or
  `all`.
- Frontend contract/lint/tests/build: `npm --prefix frontend run
  check:transport`, `lint`, `test:run`, and `build`.
- Public docs build: `npm --prefix docs-site run build`.
- Local full-profile development: `bash scripts/dev.sh up --profile full`, then
  `bash scripts/dev.sh smoke --profile full`.
- Browser preflight: `bash scripts/dev.sh doctor --profile full --browser`.

Use `uv run` so Python execution follows the lockfile. Backend pytest defaults
to at most 8 workers and frontend Vitest to at most 4; lower them with
`OPENSCIENCE_PYTEST_WORKERS` and `OPENSCIENCE_VITEST_WORKERS`. Never use
unbounded `-n auto` on the shared host.

All frontend tooling lives under `frontend/`. Prefer `npm --prefix frontend ...`
from the repository root. Do not invoke root-level `npx tsc`, `tsc --noEmit`, or
an ad-hoc `tsc -b`; the supported build uses TypeScript project references
through `npm --prefix frontend run build`.

`VITE_USE_MOCK=true` is an offline, contract-validated MSW browser scenario. It
must not be cited as real backend, worker, permission, or persistence evidence.

### Verification by Change Type

- Python or repository scripts: run the relevant focused lane and
  `bash scripts/ci.sh l1` before submission.
- Frontend: run transport drift, lint, relevant Vitest tests, and the production
  build; use DevTools when the claim concerns DOM, styles, network, focus, or
  loaded assets.
- Public docs: run `npm --prefix docs-site run build`.
- Agent instruction or governance docs: run
  `uv run python scripts/check_agent_instructions.py` and `git diff --check`;
  run the docs-site build when public docs are affected.

The five-layer CI model is defined in
[`docs/superpowers/specs/2026-07-11-five-layer-hybrid-ci-design.md`](docs/superpowers/specs/2026-07-11-five-layer-hybrid-ci-design.md).
L0/L1 do not use Docker or external services. Public PR code must never run on a
self-hosted runner attached to the production machine or Docker daemon.

## Coding and Architecture Rules

- Python under `src/ainrf/`, `tests/`, and `scripts/` targets `>=3.13`, uses
  4-space indentation, and requires strict type annotations. Use `snake_case`
  for modules/functions/variables and `PascalCase` for classes.
- Ruff owns Python formatting and lint; `ty` owns static type checking.
- Current Task behavior is owned by the Conversation Domain's Task, Turn, Item,
  TurnSubmission, RuntimeExecution, and EngineConversationBinding model.
  `agentic_researcher/` owns presets, engine configuration, and explicit
  compatibility types; it does not own Task CRUD or lifecycle writes.
- `harness_engine/` owns execution-engine adapters. Product application Modules
  must not depend on the HTTP Adapter in `ainrf.api`, including through lazy,
  dynamic, or string imports.
- Canonical product HTTP routes use `/api`. `/v1/models` and `/v1/messages` are
  separate, supported external-model protocol interfaces.
- Frontend dependency direction is `app -> features -> shared/design-system`.
  Pages consume feature view models, not raw generated transport payloads.
- Use shared layout primitives from `frontend/src/components/layout/`; dynamic
  Tailwind classes do not work, and `@dnd-kit` draggable wrappers must not be
  nested.

### Multi-Tenant Permissions

Linux user isolation is authoritative: the backend runs as `ainrf`, tenants as
`ainrf_<tenant>`, and tenant execution through `sudo -u`. Never assume `ainrf`
can write below `/home/ainrf_tenants/`; create tenant files and directories as
the tenant user. Follow the permission rule document for every affected path.

### API and Runtime Guardrails

- External tools probe `/v1/models` and `/v1/messages`; keep their API-key
  middleware exemptions consistent when related protocol paths change.
- Localhost environment detection is SSH-first. After bounded repeated failure,
  fall back to the user's personal tmux session and surface a WebUI warning.
- Keep tmux probe marker output newline-safe; literal `n` output previously
  broke parsing.

## Generated Artifacts

| Generated path | Authority | Supported action |
| --- | --- | --- |
| `frontend/src/generated/transport/` | FastAPI/Pydantic OpenAPI | Change backend schemas/routes, then run `npm --prefix frontend run generate:transport` |
| `frontend/dist/` and target-specific frontend bundles | Frontend source and Vite/build configuration | Rebuild; never edit generated bundles manually |
| `docs-site/dist/` | `docs-site/docs/` and VitePress configuration | Run `npm --prefix docs-site run build`; never edit output manually |

Generated transport is imported only at API, adapter, and mock boundaries. Run
`npm --prefix frontend run check:transport` to detect schema or generated-file
drift.

## Specs, Plans, and Notes

- Active design specs live at
  `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and must declare
  `status`, `last_reviewed`, and `review_by`; the review period is at most 30
  days.
- Implementation plans under `docs/superpowers/plans/` are transient,
  uncommitted artifacts and must be removed after implementation.
- Implemented, superseded, retired, or conflicting specs move to
  `docs/superpowers/specs/archived/` with the inventory updated.
- Internal notes use English slugs, Chinese content, YAML frontmatter, Obsidian
  wikilinks, Obsidian callouts, and Mermaid fences where useful.

## Testing Guidelines

Tests use pytest and belong under `tests/`. Every new test file must declare a
module-level marker:

| Marker | Scope |
| --- | --- |
| `api` | Full HTTP API request/response tests |
| `unit` | Isolated non-HTTP logic |
| `middleware` | Security, auth, audit, and request middleware |
| `engine` | Execution engine, SSH, terminal, and harness behavior |
| `cli` | CLI, repository scripts, and server lifecycle |
| `integration` | In-process production-mode API/SPA contracts |
| `slow` | Tests taking more than one second |

Name test files `test_*.py` and tests after behavior. Add or update smoke tests
for every changed CLI surface, parser behavior, or build-script contract.
Backend tests must use repository commands and `tmp_path` for output so parallel
workers do not collide.

`testing/e2e/` is a legacy exploratory Playwright-MCP harness, not reproducible
L2 evidence. Do not run it for untrusted PRs or cite its mutable shared resources
as a merge gate.

## Workspace, Git, and Commit Hygiene

- Do not leave temporary files, archives, logs, profiling output, debug configs,
  one-off exports, or large binaries in tracked directories. Runtime state under
  `deploy/data/tenants/` and `deploy/data/workspaces/` must remain untracked.
- Preserve unrelated dirty-worktree changes. Do not commit secrets, `.env`
  files, local keys, or investigation artifacts.
- Use Conventional Commits with one logical change per commit. Worklog updates
  normally travel with the corresponding work slice. Root governance documents
  must be changed in a dedicated `docs:` or `chore:` commit.
- All code changes use the worktree-first flow. Base a new worktree on the main
  workspace's current `master`, implement/test/commit there, then merge back in
  the main workspace and remove the worktree and local branch.
- Preferred branch prefixes are `feat/`, `fix/`, `refactor/`, `docs/`, and
  `chore/`; follow the host's required namespace prefix when present.

## Production and Staging Safety

Do not operate production containers, orchestration, logs, ports, databases, or
data unless the user explicitly requests that production action. This includes
read-only-looking commands such as `docker logs` or `docker exec` because they
still touch a real-user environment.

Production releases use `bash deploy/release-production.sh` and one
version-consistent release manifest for frontend, API, worker, and monitoring
artifacts. The maintenance-window contract requires verified backup/restore,
stopped writers, necessary migration, read-only post-smoke, and an executable
manual rollback. Never publish frontend and backend independently.

Staging uses `bash scripts/staging.sh up` with its isolated project, volumes,
ports, and lifecycle. Do not substitute staging activity for production
authorization.

## Agent Instruction Planes

- Contributor-agent instructions are versioned by `PROJECT_BASIS.md`, this
  `AGENTS.md`, task-routed `.rules`, and governed current docs. Root `CLAUDE.md`
  is only a host adapter that imports the two canonical root files.
- Product-spawned research-agent guardrails originate in
  `deploy/config/CLAUDE.md` and are copied into the container Claude config.
  They govern transport and tool behavior for runtime sessions; they do not
  override repository contributor authority.
- Private or machine-local instructions may describe non-normative machine
  facts, but they must not override project identity, architecture, security,
  production safety, or other durable `PROJECT_BASIS.md` rules.

The ownership and lifecycle of these planes are documented in
[`docs/documentation-governance.md`](docs/documentation-governance.md).
