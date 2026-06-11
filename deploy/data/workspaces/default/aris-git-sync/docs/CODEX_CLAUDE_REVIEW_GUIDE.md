# Codex + Claude Reviewer Guide

Run ARIS with:

- **Codex** as the main executor
- **Claude Code CLI** as the reviewer
- the local `claude-review` MCP bridge as the transport layer

This guide is **additive** to the upstream Codex-native path. It does not replace `skills/skills-codex/`.

## Architecture

- Base skill set: `skills/skills-codex/`
- Reviewer override layer: `skills/skills-codex-claude-review/`
- Reviewer bridge: `mcp-servers/claude-review/`

The install order matters:

1. install `skills/skills-codex/*`
2. install `skills/skills-codex-claude-review/*`
3. register `claude-review` MCP

## Install

```bash
git clone https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git
cd Auto-claude-code-research-in-sleep

mkdir -p ~/.codex/skills
cp -a skills/skills-codex/* ~/.codex/skills/
cp -a skills/skills-codex-claude-review/* ~/.codex/skills/

mkdir -p ~/.codex/mcp-servers/claude-review
cp mcp-servers/claude-review/server.py ~/.codex/mcp-servers/claude-review/server.py
codex mcp add claude-review -- python3 ~/.codex/mcp-servers/claude-review/server.py
```

If your Claude login depends on a shell helper such as `claude-aws`, use the wrapper:

```bash
cp mcp-servers/claude-review/run_with_claude_aws.sh ~/.codex/mcp-servers/claude-review/run_with_claude_aws.sh
chmod +x ~/.codex/mcp-servers/claude-review/run_with_claude_aws.sh
codex mcp add claude-review -- ~/.codex/mcp-servers/claude-review/run_with_claude_aws.sh
```

Optional reviewer model override:

```bash
codex mcp remove claude-review
codex mcp add claude-review --env CLAUDE_REVIEW_MODEL=claude-opus-4-1 -- python3 ~/.codex/mcp-servers/claude-review/server.py
```

## Verify

1. Check MCP registration:

```bash
codex mcp list
```

2. Check Claude CLI login:

```bash
claude -p "Reply with exactly READY" --output-format json --tools ""
```

3. Start Codex in your project:

```bash
codex -C /path/to/your/project
```

## What gets overridden

The overlay only replaces review-heavy skills:

- `research-review`
- `novelty-check`
- `research-refine`
- `auto-review-loop`
- `paper-plan`
- `paper-figure`
- `paper-write`
- `auto-paper-improvement-loop`

Everything else still comes from the upstream `skills/skills-codex/` package.

## Async reviewer flow

For long paper or project reviews, use:

- `review_start`
- `review_reply_start`
- `review_status`

Why: in this host path, the review hop is:

`Codex -> claude-review MCP -> local Claude CLI -> Claude backend`

That extra local CLI hop is what makes long synchronous reviewer calls more likely to hit the observed Codex-hosted MCP timeout.

## Project config

No special project config file is required for this path.

- keep using your existing `CLAUDE.md`
- keep your current project layout
- only switch the installed Codex skill files and MCP registration

## Maintenance

Regenerate the overlay package with:

```bash
python3 tools/generate_codex_claude_review_overrides.py
```
