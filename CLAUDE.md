# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Required Project Basis

Claude Code must treat [PROJECT_BASIS.md](PROJECT_BASIS.md) as a required repository policy document.

- Follow `PROJECT_BASIS.md` for long-lived engineering constraints, especially documentation placement, directory boundaries, coding style, command entrypoints, testing expectations, and maintenance rules.
- When `CLAUDE.md` and `PROJECT_BASIS.md` overlap, follow the stricter requirement.
- When a task-specific user instruction conflicts with `PROJECT_BASIS.md`, follow the user instruction for that task and keep the rest of `PROJECT_BASIS.md` in effect.

## Project Overview

scholar-agent currently centers on the AINRF frontend/backend product surface. `src/ainrf/` and `frontend/` contain the active CLI, backend API, WebUI, and runtime capabilities, while `docs/`, `ref-repos/`, and the historical research notes remain long-lived knowledge and reference assets that support product design, implementation choices, and traceability. Notes continue to use Chinese content with English file slugs, and the repository still generates a static HTML site from `docs/` with MkDocs.

## Build & Serve Commands

```bash
# Build static site (converts Obsidian syntax, then runs mkdocs build)
scripts/build.sh

# Start local preview server
scripts/serve.sh

# Or run directly via uv
uv run python scripts/build_html_notes.py build
uv run python scripts/build_html_notes.py serve
```

Dependencies are managed by `uv` (see `pyproject.toml`). No separate install step needed — `uv run` handles the venv automatically.

## Development Commands

```bash
# Run tests
uv run pytest

# Run linting and formatting checks
uv run ruff check .
uv run ruff format --check .

# Auto-fix linting issues and format code
uv run ruff check --fix .
uv run ruff format .

# Install pre-commit hooks (runs ruff on commit)
uv run pre-commit install

# Run the ainrf CLI and service entrypoints
uv run ainrf --version
uv run ainrf serve
uv run ainrf run
```

## Architecture

### Build Pipeline

`scripts/build_html_notes.py` is the core build script. It:

1. Reads all `.md` files from `docs/` (the source of truth)
2. Converts Obsidian-only syntax to MkDocs-compatible Markdown:
   - `[[wikilinks]]` → standard `[label](relative-path.md)` links
   - Obsidian callouts (`> [!type]`) → MkDocs admonitions (`!!! type`)
   - Validates all internal links and fails on unresolved wikilinks
3. Computes backlinks and appends a "反向链接" section to each note
4. Writes processed files to `.cache/html-notes/docs/` (the `docs_dir` in `mkdocs.yml`)
5. Runs `mkdocs build` or `mkdocs serve` against the generated output

Important: never edit files under `.cache/html-notes/` or `site/` — they are generated. Edit only files under `docs/`.

### Directory Layout

- `docs/` — Source markdown for the generated docs site, including product docs and reference notes
  - `docs/index.md` — Top-level research index
  - `docs/projects/` — Per-project research reports (one per reference repo)
  - `docs/framework/` — AI-Native Research Framework design notes
  - `docs/summary/` — Cross-project comparison and capability matrix
- `frontend/` — AINRF WebUI
- `src/ainrf/` — AINRF Python package, CLI, backend API, and runtime code
- `tests/` — Test suite (run with `uv run pytest`)
- `ref-repos/` — Cloned reference repositories (read-only research subjects, gitignored)
- `.codex-skill-staging/` — Codex skill definitions (build-obsidian-mkdocs-site, write-obsidian-project-docs)
- `scripts/` — Build tooling
- `mkdocs.yml` — MkDocs config (Material theme, Mermaid, zh language)

### Note Conventions

- Frontmatter: YAML with `aliases`, `tags`, `source_repo`, `source_path`
- Internal links: use `[[note-name]]` or `[[note-name|label]]` syntax (Obsidian wikilinks)
- Callouts: use Obsidian `> [!type]` syntax, not MkDocs admonitions directly
- Diagrams: use Mermaid fenced code blocks (vendored JS at `docs/assets/javascripts/vendor/`)
- File naming: English slugs, content in Chinese

## LLM Working Log Requirement

- `docs/LLM-Working/` is the repository's versioned area for working notes and agent-side execution records.
- Daily work logs must be stored in `docs/LLM-Working/worklog/` with one append-only file per day named `YYYY-MM-DD.md`.
- At the start of work, create today's file if it does not exist yet, then keep appending to that same file throughout the day.
- The default unit is one changelog entry per completed modification plan or work slice, not one line per edit, validation, or commit action.
- Each changelog entry must include the timestamp, the completed slice label, a concise summary of what changed, and the validation result. If commits were produced in that slice, append the commit hash and subject in the same entry.
- Do not treat the worklog as a transcript of commit messages or atomic slice labels; summarize the completed batch in higher-level changelog form.

## Runtime Fallback Notes

- Localhost environment detection is SSH-first: after 3 short failed SSH connection attempts, it must fall back to the user's personal tmux session and surface a toast warning in the WebUI. Keep the bounded tmux probe marker output newline-safe; an earlier `printf %s\n` wrapper emitted literal `n` characters, causing localhost tmux fallback parsing to time out.

## Git Maintenance

- Worktree/branch cleanup: run `git fetch --prune origin`, inspect `git worktree list --porcelain`, `git branch -vv`, and only remove clean, audited worktrees or fully merged branches; preserve any dirty worktree.

## Code Quality

- Python 3.13+ required (see `pyproject.toml`)
- Linting and formatting: Ruff (configured in `pyproject.toml` with line-length=100)
- Pre-commit hooks: automatically run `ruff check` and `ruff format` on commit
- Type hints: use modern Python type syntax (`type` aliases, `|` unions, etc.)
- The build script (`build_html_notes.py`) validates all wikilinks and fails on unresolved references
