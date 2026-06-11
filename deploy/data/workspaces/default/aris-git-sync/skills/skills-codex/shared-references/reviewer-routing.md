# Reviewer Routing

## Default Reviewer Contract

All reviewer-heavy Codex base skills use the same default contract:

- executor: current Codex main agent
- reviewer: second Codex reviewer
- reasoning effort: `xhigh`
- round 1: `spawn_agent`
- follow-up rounds: `send_input`

This is the base default for `skills/skills-codex/`. No effort level or unrelated parameter changes it.

> ⚠️ **Same-family by default — Type-A only, NOT a cross-family verdict.** The executor here is Codex (GPT family) and this default reviewer is a *second Codex agent* — same family. That is a valid **Type-A** review (it finds omissions, ranks weaknesses, drives the fix loop), but it is **NOT** the cross-model **Type-B acquittal** ARIS's invariant requires — one model family judging itself voids the verdict (mainline `acceptance-gate.md`). For a Type-B cross-family verdict, install the **`skills-codex-claude-review`** or **`skills-codex-gemini-review`** overlay (the only genuinely cross-family reviewers for a Codex executor). Note `oracle-pro` (gpt-5.x-pro) is **also GPT family**, so it does NOT cross the family boundary for a Codex executor either.

## Default Pattern

Single-round review:

```text
spawn_agent:
  model: gpt-5.5
  reasoning_effort: xhigh
  message: |
    [role + task]
    Read the listed files directly.
```

Multi-round review:

```text
spawn_agent:
  model: gpt-5.5
  reasoning_effort: xhigh
  message: |
    [initial review prompt]
```

Save the returned reviewer id, then continue with:

```text
send_input:
  target: <saved reviewer id>
  message: |
    [follow-up materials only]
```

## Oracle Pro Override

When the user explicitly passes `--reviewer: oracle-pro`, switch only the reviewer route:

- default reviewer remains Codex xhigh if no reviewer is specified
- `oracle-pro` is optional, not the base default

Routing rule:

```text
If reviewer is omitted or reviewer=codex:
  use spawn_agent / send_input with Codex reviewer at xhigh

If reviewer=oracle-pro:
  check Oracle MCP availability
  if available:
    call mcp__oracle__consult with model gpt-5.5-pro
  if unavailable:
    print a clear warning
    fall back to the default Codex xhigh reviewer
```

## Invariants

- Base skills do not use the legacy Codex MCP thread path as the default reviewer route.
- Reviewer independence still applies: pass file paths and task framing, not executor summaries.
- Overlay packages may replace only the reviewer route.
- Overlay packages do not change executor semantics.
- Browser-based Oracle review is acceptable for one-shot stress tests, not ideal for tight multi-round loops.

## Skills That Commonly Benefit From `oracle-pro`

- `research-review`
- `auto-review-loop`
- `experiment-audit`
- `proof-checker`
- `rebuttal`
- `idea-creator`
- `research-lit`
