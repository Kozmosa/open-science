# Worktree Working Guide

Practical guidance for avoiding common worktree pitfalls. Read this
when starting a worktree session, switching between worktrees, or debugging
command failures that seem like "it should work."

Background: AGENTS.md (Git Workflow & Worktree Hygiene) covers branch strategy,
worktree lifecycle, and PR expectations. This document covers the *mechanics*
of working inside an active worktree — CWD, tool invocation, batch editing,
and import hygiene.

## CWD Discipline

A worktree's root is the repo root, NOT the frontend subdirectory.

- `package.json` lives in `frontend/`, not in the repo root.
- `node_modules/` and `node_modules/.bin/` live under `frontend/`, not the repo root.
- Shell state does not persist across `Bash` tool calls within a session.

### The `--prefix` Rule

**Prefer `npm --prefix frontend <command>` over `cd frontend && npm <command>`.**

This is safe regardless of current `pwd` and avoids the most common worktree
failure mode: running `npm run test:run` from the repo root.

### Command Reference

| Purpose | Correct | Wrong (from worktree root) |
|---------|---------|---------------------------|
| Lint | `npm --prefix frontend run lint` | `npm run lint` |
| Tests | `npm --prefix frontend run test:run` | `npm run test:run` |
| Build | `npm --prefix frontend run build` | `npm run build` |
| Type-check | `npm --prefix frontend run build` (wraps `tsc -b`) | `npx tsc -b` |
| Add dep | `npm --prefix frontend install -D <pkg>` | `npm install -D <pkg>` |

### TypeScript Hazards

1. **Never use `npx tsc` from the repo root.** The npm registry has an unrelated
   `tsc` package; `npx` will install it instead of using the project's TypeScript.
   The correct type-check invocation is `npm --prefix frontend run build` (which
   runs `tsc -b && vite build`).

2. **`node_modules/.bin/tsc -b` fails from the repo root** because
   `node_modules` is under `frontend/`. Even `frontend/node_modules/.bin/tsc -b`
   will fail with `Cannot read file '.../<repo>/tsconfig.json'` because `tsc -b`
   resolves tsconfig relative to CWD, not the binary location.

3. **AGENTS.md mandates `tsc -b` from `frontend/`** — the project uses
   TypeScript project references, and `--noEmit` / `-p tsconfig.app.json` are
   explicitly disallowed.

## `sed` Batch Import Rewriting

When migrating directories in bulk, `sed` one-liners are efficient but brittle.

### Risks

- **Overbroad matches**: `from '../types'` exists in both settings (→ settings types)
  and shared/api, chat components (→ shared types). A blanket `sed` will break one.
- **Barrel collapse**: When an old barrel is deleted, any remaining `from '../ui'`
  imports break at Vite resolution time (not tsc), so they may pass type-check
  but fail at test/build time.
- **Nested directory artifacts**: `git mv src/test src/shared/test` creates
  `src/shared/test/test/` if the target directory already exists.

### Mitigations

1. **Grep first, then sed**: Before running a batch replace, grep for all
   `from '...` patterns to understand the full set of matches.
2. **Most-specific-first**: Replace the most concrete paths (e.g.
   `from './settings/types'`) before generic ones (e.g. `from '../types'`).
3. **Verify immediately**: After every sed batch, run
   `npm --prefix frontend run build` (which includes `tsc -b`). Don't wait
   until the end of a migration batch.
4. **Check for nested dirs**: After `git mv`, `ls` the target to verify no
   intermediate nesting occurred. If you see `target/dir/dir/`, move contents
   up with `git mv target/dir/dir/* target/dir/ && rmdir target/dir/dir`.

## `git mv` Directory Movement

When moving a directory into a location that already exists:

```bash
# WRONG — creates src/shared/test/test/
git mv src/test src/shared/test

# RIGHT — moves contents into the existing directory
git mv src/test/* src/shared/test/
```

Pre-check: `[ -d <target> ] && echo "target exists — use contents move" || git mv <src> <target>`.

## Worktree Paths in Config Files

When adding path aliases (Vite, TS, Vitest), remember:

- `__dirname` in `vite.config.ts` / `vitest.config.ts` resolves to `frontend/`,
  so aliases point to `./src/...` relative to `frontend/`.
- `baseUrl` in `tsconfig.app.json` is `.` relative to the tsconfig's directory
  (i.e. `frontend/`), so paths are `src/*`.
- Vitest aliases must match Vite aliases exactly, or test imports will fail at
  resolution time with "Does the file exist?" errors.

## Plan Documents vs Implementation Reality

When multiple planning documents exist, their scope boundaries may differ:

- The `redesign-proposal.md` defines phases by feature area (tokens, fonts,
  Storybook in Phase 1).
- The `implementation-plan.md` defines phases by migration order (aliases,
  shared layer, design-system, context split, feature migration).
- Before starting work, cross-reference both documents and explicitly ask the
  user which scope takes priority. When asked to check completion, check
  against **both** documents and report discrepancies.
