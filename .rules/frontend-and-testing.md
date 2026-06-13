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

## Agent E2E Testing

AINRF uses a coding-agent-driven E2E testing approach. A coding agent (Claude Code, Codex, etc.) uses Playwright MCP to drive a browser against a production-like Docker container, executing the test scenarios defined in `testing/e2e/CHECKLIST.md`.

- **Test environment**: `testing/e2e/` — isolated Docker Compose with ephemeral tmpfs volumes, seeded test users, no TLS.
- **Start**: `testing/e2e/run.sh up` — builds image, starts containers, seeds users, prints credentials.
- **Stop**: `testing/e2e/run.sh down` — removes all containers and volumes.
- **Prerequisites**: `testing/e2e/check-prereqs.sh` — verifies Docker, Node.js, Playwright MCP, curl.
- **Agent prompt**: `testing/e2e/AGENT_PROMPT.md` — system prompt for the test agent.
- **MCP config**: `testing/e2e/config/mcp-servers.json` — Playwright MCP server configuration.
- **Results**: Agent writes reports to `testing/e2e/results/` (gitignored).

Ports: frontend on 8198, backend on 8199 (configurable via `AIWebPort`/`AITestPort`).
