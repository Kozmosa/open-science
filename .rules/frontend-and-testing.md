# Frontend Patterns, DevTools & E2E Testing

Frontend layout component conventions, CSS/DnD constraints, browser and
DevTools tooling configuration, and agent-driven E2E testing infrastructure.
Read this when modifying frontend components, debugging UI issues, or
running end-to-end tests.

Build and type-check commands remain in AGENTS.md (Build, Test, and Development Commands).
For frontend deployment pitfalls, see [dev-bitter-lesson.md](../dev-bitter-lesson.md).

## Frontend Layout Components

- Reusable layout shells live in `frontend/src/components/layout/`.
- `PageShell`: standard outer card wrapper.
- `SplitPane`: left-right split layout with drag handle, keyboard resizing, and ARIA support.
- `SectionStack`: vertical section spacing with optional actions slot.
- `CardGrid`: draggable card grid with DnD and localStorage persistence.
- Prefer these shared layout primitives over duplicating layout patterns.

## Tailwind CSS Constraints

- Dynamic Tailwind classes such as `space-y-${gap}` or `gap-${n}` do not work reliably with Tailwind v4 JIT in this repo.
- Use static lookup maps instead, e.g. `const GAP_CLASSES: Record<number, string> = { 2: 'gap-2', 4: 'gap-4' }`.

## `@dnd-kit` Gotcha

- Do not nest `useDraggable` / `useDroppable` wrappers.
- `CardGrid` already provides an internal draggable wrapper; content passed via `renderCard` must not add another draggable layer.

## Browser & DevTools (Working)

Use the **chrome-devtools MCP** as the primary frontend inspection tool when it is exposed by the current session. A headless host can still run real Chrome, inspect DOM/computed style/Network/focus, and connect through CDP; lack of a browser tool in one agent session is a session-configuration problem, not proof that the host cannot run a browser.

Before browser work, run:

```bash
bash scripts/dev.sh doctor --profile full --browser
```

The preflight discovers `PUPPETEER_EXECUTABLE_PATH`, PATH wrappers, and Puppeteer-cached Chrome in that order; rejects the broken system snap Chromium; checks Claude/OMP MCP declarations; and launches one isolated headless CDP probe. It never modifies user config, upgrades MCP packages, or adds `--no-sandbox` automatically.

OMP/Claude MCP configuration is loaded at session start. If preflight succeeds but the current session has no browser tool, restart the session before changing repository code based on guessed DOM or browser state.

## Development Feedback Lanes

- Fast inner loop: `bash scripts/dev.sh up --profile full --mode dev` provides Vite HMR, FastAPI reload, a marker-guarded deterministic fixture worker, and worktree-derived ports/state.
- Local production preview: `bash scripts/dev.sh up --profile full --mode preview` builds the production frontend first and then serves it against the same isolated API.
- Offline frontend support: `VITE_USE_MOCK=true` enables the lazy MSW browser scenario. It uses the same `/api` client transport and fails unhandled `/api/**` calls, but it is not a substitute for the managed synthetic API.
- Deterministic gates: L0/L1 remain separate from manual DevTools work and local HTTP smoke.
- Release evidence: L2–L4 remain isolated integration/deep/release layers; local dev/preview must not be cited as those layers.

Use `full`, `empty`, `permissions`, `failures`, or `large` fixture profiles rather than editing persisted state by hand. `reset` is allowed only for marker-owned synthetic instances and is forbidden for the personal `~/.ainrf` launcher.

The fixture worker is closed-world: Task execution, Literature checks/summaries, and Overview refreshes complete through the real persistence/projection paths without starting a real harness runtime or calling arXiv, an LLM, environment detect, Docker, staging, or production. Login credentials for owner/editor/viewer/admin identities are generated once in a repository-external `0600` JSON file reported by `dev.sh prepare --json`.

Fault profiles are selected with `--fault-profile none|latency|transient|resources|offline`. They require marker-owned synthetic state, never apply in production, and are forbidden for personal state roots. When changing fixture or fault profiles, reset the managed instance and pass the same options to the next `up` command.

Development ports use `41000 + slot*3` for Vite, `+1` for the API, and `+2` for CDP, where the stable slot is derived from absolute worktree path, branch, and profile. All three bind to `127.0.0.1` by default and remain below `44000`, separate from staging `7192/17000` and production `8192/18000`. Use `OPENSCIENCE_DEV_FRONTEND_PORT`, `OPENSCIENCE_DEV_API_PORT`, and `OPENSCIENCE_DEV_CDP_PORT` only for an explicit collision; `dev.sh` never kills an unknown listener.

## Legacy Agent E2E Testing (Exploratory, Non-Gating)

`testing/e2e/` is a legacy coding-agent exploration harness. It is not part of L0/L1, is not a merge gate, and must not be treated as reproducible E2E evidence until L2 replaces its fixed project/container names, mutable image tag, shared frontend bundle, direct DB seeding, and natural-language-only result contract.

- **Test environment**: `testing/e2e/` — isolated Docker Compose with ephemeral tmpfs volumes, seeded test users, no TLS.
- **Start**: `testing/e2e/run.sh up` — starts the existing local `ainrf:latest` image, seeds users, and prints credentials. It does **not** build the image or frontend bundle.
- **Stop**: `testing/e2e/run.sh down` — removes all containers and volumes.
- **Prerequisites**: `testing/e2e/check-prereqs.sh` — verifies Docker, Node.js, Playwright MCP, curl.
- **Agent prompt**: `testing/e2e/AGENT_PROMPT.md` — system prompt for the test agent.
- **MCP config**: `testing/e2e/config/mcp-servers.json` — Playwright MCP server configuration.
- **Results**: Agent writes reports to `testing/e2e/results/` (gitignored).

Do not run this harness from untrusted pull requests or on a self-hosted GitHub runner attached to the production Docker daemon. The five-layer replacement is specified in [`docs/superpowers/specs/2026-07-11-five-layer-hybrid-ci-design.md`](../docs/superpowers/specs/2026-07-11-five-layer-hybrid-ci-design.md).

The deterministic L0/L1 Vitest lane is capped at 4 workers by default. Lower it on the shared host with `OPENSCIENCE_VITEST_WORKERS=<n>`; do not let Vitest infer concurrency from the full machine CPU count.

Ports: frontend on 8198, backend on 8199 (configurable via `AIWebPort`/`AITestPort`).
