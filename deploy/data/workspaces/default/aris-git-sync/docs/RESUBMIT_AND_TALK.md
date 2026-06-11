# 🔁🎤 Resubmit & Conference-Talk Pipelines

> [← back to README](../README.md) · ARIS's two late-stage workflows — port a paper to a new venue (text-only), and turn an accepted paper into a conference talk.

## Workflow 5: Resubmit Pipeline 🔁 (port a paper to a new venue, text-only)

> **"Paper accepted somewhere or rejected from venue A. Port it to venue B under hard constraints."**

`/resubmit-pipeline` ports a polished paper from one venue to another with strict guardrails — **no new experiments, no bib edits, no framework changes, never overwrites prior submissions**. Use it for journal version of a conference paper, ML venue → other ML venue, anonymized re-submit after a non-anonymous workshop. Not for major revisions (use `/paper-writing` for those).

1. 📁 **Physical isolation** — copy into `<NEW_VENUE_DIR>/`; the original submission directory is never touched.
2. 🛡️ **5-layer anonymity check** — author names, affiliations, self-citations, GitHub / Overleaf URLs, in-text "we" patterns that break double-blind.
3. 🔬 **Audits (soft-only)** — `/proof-checker`, `/paper-claim-audit`, `/citation-audit --soft-only`. The `--soft-only` mode translates `KEEP/FIX/REPLACE/REMOVE` verdicts to text-rewrite proposals when the bib is frozen; hallucinated citations get a `drop_cite_in_body_only` action.
4. ✏️ **Microedit** — `/auto-paper-improvement-loop --edit-whitelist <path>` with a YAML schema (`allowed_paths` / `forbidden_paths` / `forbidden_operations` like `new_cite` / `new_theorem_env` / `numerical_claim`, `forbidden_deletions`, `max_edits_per_round`) + per-round diff gate.
5. 🗡 **Adversarial gate** — `/kill-argument` final attack/adjudication pass; rejection if any `still_unresolved` at critical severity.
6. 📤 **Compile + push** — `/paper-compile` + optional `/overleaf-sync push`.

<details>
<summary><b>Show W5 resubmit flow diagram</b> — isolated copy → 5-layer anonymity → soft-only audits → whitelist microedit → kill-argument adversarial gate → compile + Overleaf push</summary>

```
┌──────────────────────────────────────────────────────────────────────┐
│              Workflow 5: Text-only Resubmit                          │
│                                                                      │
│  Polished paper                                                      │
│       │                                                              │
│       ▼                                                              │
│  Isolate → Anonymity (5-layer) → Audits (--soft-only)                │
│       │                                                              │
│       ▼                                                              │
│  Microedit (whitelist + diff gate) → /kill-argument adversarial gate │
│       │                                                              │
│       ▼                                                              │
│  Compile + Overleaf push     →    <NEW_VENUE_DIR>/                   │
└──────────────────────────────────────────────────────────────────────┘
```

</details>

**Skills involved:** `resubmit-pipeline` (orchestrator), `auto-paper-improvement-loop --edit-whitelist`, `citation-audit --soft-only`, `proof-checker`, `paper-claim-audit`, `kill-argument`, `paper-compile`, `overleaf-sync` (optional)

**Hard constraints (cannot be overridden):**
- 🔒 **No new experiments** — every numerical claim must already exist in the source paper.
- 🔒 **No bib edits** — citation issues become body-text rewrites via `--soft-only`.
- 🔒 **No framework changes** — theorem environment, claim shape, contribution scope are frozen.
- 🔒 **Never overwrites prior submissions** — the new venue gets its own directory.

**Master ledger:** `RESUBMIT_REPORT.json` with the 7-verdict failure-mode table (including `USER_DECISION` runtime state) per `shared-references/assurance-contract.md`. See the [2026-05-05 News entry](#whats-new) for the full feature breakdown.

## Workflow 6: Conference Talk Pipeline 🎤 (paper → slides → polish → audits)

> **"Paper is in. Now prepare the conference talk."**

`/paper-talk` orchestrates the full talk-prep flow as a sister workflow to `/paper-writing` and `/paper-poster-html`. `/slides-polish` is the post-generation visual pass invoked internally — you do not need to call it separately.

1. 📋 **Outline** — extract from `paper/` (or `NARRATIVE_REPORT.md`); one slide-cluster per contribution; map sections to talk beats.
2. 🎨 **Generate** — `/paper-slides` produces Beamer source + PPTX + speaker notes + Q&A prep.
3. 💎 **Polish** — `/slides-polish` per-page Codex review against the reference PDF, applying a fix-pattern catalog (PPTX font scaling 1.5-1.8× for projector legibility, text-frame resize after font bump, banner-as-tcolorbox, italic style leak guard, em-dash spacing, Chinese EA font hint via PingFang SC, anonymity placeholder discipline).
4. 🛡️ **Audit** (when `assurance: conference-ready`) — `/paper-claim-audit` + `/citation-audit` run against a synthetic paper directory at `.aris/paper-talk/audit-input/sections/*.tex` + symlinked `.bib` / `results/` / `figures/`. Each emits a 6-state JSON verdict per `shared-references/assurance-contract.md`; non-green blocks the Final Report.

<details>
<summary><b>Show W6 talk-prep flow diagram</b> — paper → outline → /paper-slides → /slides-polish → optional conference-ready audit gate</summary>

```
┌──────────────────────────────────────────────────────────────────────┐
│             Workflow 6: Conference Talk                              │
│                                                                      │
│  paper/  →  outline  →  /paper-slides  (Beamer + PPTX + notes)       │
│                                  │                                   │
│                                  ▼                                   │
│                         /slides-polish  (per-page Codex pass)        │
│                                  │                                   │
│                                  ▼                                   │
│               assurance: conference-ready ?                          │
│                 ├─ yes → /paper-claim-audit + /citation-audit        │
│                 │        on synthetic-paper staging adapter          │
│                 │        → 6-state verdict gates Final Report        │
│                 └─ no  → Final Report directly                       │
└──────────────────────────────────────────────────────────────────────┘
```

</details>

**Skills involved:** `paper-talk` (orchestrator), `paper-slides`, `slides-polish`, `paper-claim-audit` + `citation-audit` (at `assurance: conference-ready`)

**Assurance ladder** (independent from the `effort` axis): `draft / polished (default) / conference-ready`. Legal combination: `— effort: lite, assurance: conference-ready` means "fast pipeline, every audit must emit a verdict before final report."

**Standalone slide / poster tools:** if you only want the artifact and not the full orchestration, `/paper-slides "paper/"` and `/paper-poster-html "paper/"` work directly without `/paper-talk`. See the [2026-05-06 News entry](#whats-new) for the full feature breakdown.

<a id="-research-wiki--persistent-research-memory"></a>

