# AINRF Skill Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 AINRF Skill 注入系统。

**Architecture:** SkillInjectionService 作为核心协调器，从 AINRF skill 仓库加载完整 skill 定义，在任务工作目录生成 `.ainrf/` 目录，然后通过软链接/拷贝同步到 `.claude/`。

**Tech Stack:** Python 3.13, FastAPI, Pydantic, React + TypeScript, React Query, pytest, uv

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `src/ainrf/skills/loader.py` | Load complete skill definition from `.ainrf/skills/<id>/` directory |
| `src/ainrf/skills/merge.py` | Deep merge settings dicts and resolve `${ENV}` placeholders |
| `src/ainrf/skills/sync.py` | Local filesystem sync: symlink / hardlink / copy strategies |
| `src/ainrf/skills/injection.py` | `SkillInjectionService`: generate `.ainrf/`, merge settings, sync to `.claude/` |
| `tests/skills/test_loader.py` | Test skill loading from directory |
| `tests/skills/test_merge.py` | Test settings merge and env resolution |
| `tests/skills/test_sync.py` | Test filesystem sync strategies |
| `tests/skills/test_injection.py` | Test SkillInjectionService |
| `tests/api/test_skills.py` | Test skill API endpoints (detail, preview, import) |
| `tests/task_harness/test_prompting.py` | Test prompt integration with inject_mode |
| `tests/test_skill_injection_e2e.py` | End-to-end integration test |

### Modified Files

| File | Responsibility |
|------|---------------|
| `src/ainrf/skills/models.py` | Expand `SkillItem`, add `SkillDefinition`, `SkillManifest`, `InjectMode` |
| `src/ainrf/skills/discovery.py` | Extend with `discover_full()` for complete skill definitions |
| `src/ainrf/skills/__init__.py` | Export new classes |
| `src/ainrf/task_harness/prompting.py` | Check `skill.inject_mode` before fusing skill instructions |
| `src/ainrf/task_harness/launcher.py` | Upload `.ainrf/` for remote; prefer `.ainrf/settings.json` |
| `src/ainrf/task_harness/service.py` | Call `SkillInjectionService` during task startup |
| `src/ainrf/api/schemas.py` | Add `SkillDetailResponse`, `SkillPreviewResponse`, `SkillImportRequest` |
| `src/ainrf/api/routes/skills.py` | Add detail, preview, import endpoints |
| `frontend/src/types/index.ts` | Add `SkillDetail`, `SkillPreview`, `SkillImportRequest` |
| `frontend/src/api/endpoints.ts` | Add `getSkillDetail`, `previewSkillSettings`, `importSkill` |
| `frontend/src/api/mock.ts` | Add mock implementations |
| `frontend/src/pages/SettingsPage.tsx` | Add "Skill Repository" tab |
| `frontend/src/pages/tasks/TaskCreateForm.tsx` | Show skill inject_mode and dependencies |

---

## Task 1: Expand Skill Models

**Files:** Modify `src/ainrf/skills/models.py`, Create `tests/skills/test_models.py`

Add `InjectMode` enum (`auto`, `prompt_only`, `disabled`), `SkillDefinition` dataclass with `from_json()` classmethod, and `SkillManifest` dataclass.

Tests verify enum values, `from_json` parses all fields correctly, and `SkillManifest` stores tool lists.

---

## Task 2: Settings Merge Utility

**Files:** Create `src/ainrf/skills/merge.py`, Create `tests/skills/test_merge.py`

Implement `deep_merge_settings(base, overlay)` with recursive dict merge and `resolve_env_placeholders(data)` that resolves `${VAR}` from `os.environ`.

Tests verify dict merge, overlay wins, env resolution, and missing placeholder preservation.

---

## Task 3: Skill Loader

**Files:** Create `src/ainrf/skills/loader.py`, Create `tests/skills/test_loader.py`

Implement `SkillLoader` with `load_from_directory(skill_dir)` that requires `skill.json` and `SKILL.md`, and `load_all_from_root(root)` that scans subdirectories.

Tests verify successful load, missing manifest error, missing SKILL.md error, and batch loading.

---

## Task 4: Filesystem Sync Utility

**Files:** Create `src/ainrf/skills/sync.py`, Create `tests/skills/test_sync.py`

Implement `sync_ainrf_to_claude(ainrf_skills, claude_skills)` that tries symlink first, falls back to copy, and writes `.claude/.ainrf-managed` marker.

Tests verify symlink creation, copy fallback when directory exists, and marker file creation.

---

## Task 5: SkillInjectionService

**Files:** Create `src/ainrf/skills/injection.py`, Create `tests/skills/test_injection.py`

Implement `SkillInjectionService(skill_root)` with:
- `generate_ainrf(workdir, selected_skills, task_settings_override)`: resolves dependencies, copies active skills, merges settings (Base ⊕ Skill Fragments ⊕ Task Overrides), resolves env placeholders, generates `settings.json` and `tool-manifest.json`
- `sync_to_claude(workdir)`: calls sync utility and copies settings.json

Tests verify `.ainrf/` generation, settings merge, `prompt_only` mode filtering, and `.claude/` sync.

---

## Task 6: Extend Skill Discovery

**Files:** Modify `src/ainrf/skills/discovery.py`, Modify `src/ainrf/skills/__init__.py`

Add `discover_full()` method that returns `list[SkillDefinition]` by scanning skill root with `SkillLoader`. Update `__init__.py` exports.

Tests verify `discover_full` returns complete metadata including `inject_mode`.

---

## Task 7: Prompt Integration

**Files:** Modify `src/ainrf/task_harness/prompting.py`, Create `tests/task_harness/test_prompting.py`

Add `compose_skill_prompt_lines(skills, skills_prompt)` helper. Update `compose_task_prompt` to use it. The existing skill listing behavior is preserved; `inject_mode` filtering happens at `SkillInjectionService` level.

Tests verify prompt includes skill list and skills_prompt.

---

## Task 8: Launcher Integration - Local

**Files:** Modify `src/ainrf/task_harness/launcher.py`, Modify `src/ainrf/task_harness/service.py`

In `build_local_launcher`: prefer `.ainrf/settings.json` over passed `settings_path`.

In `service.py` `_run_task`: before launcher creation, instantiate `SkillInjectionService`, call `generate_ainrf()` and `sync_to_claude()` if `research_agent_profile.skills` is non-empty.

Tests verify existing task harness tests still pass.

---

## Task 9: Launcher Integration - Remote

**Files:** Modify `src/ainrf/task_harness/launcher.py`

In `build_remote_launcher`:
1. After uploading prompt.txt and settings, check for local `.ainrf/` directory
2. If exists, create tarball, upload to remote, extract
3. Run sync script on remote to create `.claude/skills` symlink/copy
4. Update `helper_lines` to check for `.ainrf/settings.json` first

Tests verify SSH execution tests still pass.

---

## Task 10: API Routes - Skill Detail & Preview

**Files:** Modify `src/ainrf/api/schemas.py`, Modify `src/ainrf/api/routes/skills.py`, Create `tests/api/test_skills.py`

Add `SkillDetailResponse` and `SkillPreviewResponse` schemas.

Add endpoints:
- `GET /skills/{skill_id}`: returns full skill metadata + SKILL.md content
- `GET /skills/{skill_id}/preview`: returns settings fragment + merged preview

Tests verify 200 for existing skill, 404 for missing skill.

---

## Task 11: API Routes - Skill Import

**Files:** Modify `src/ainrf/api/schemas.py`, Modify `src/ainrf/api/routes/skills.py`

Add `SkillImportRequest` schema and `POST /skills/import` endpoint.

Supports `source: "git"` (clones repo, requires `url`) and `source: "local"` (copies from `local_path`). Optional `skill_id` override.

---

## Task 12: Frontend Types & API

**Files:** Modify `frontend/src/types/index.ts`, Modify `frontend/src/api/endpoints.ts`

Add TypeScript interfaces: `SkillDetail`, `SkillPreview`, `SkillImportRequest`.

Add API functions: `getSkillDetail`, `previewSkillSettings`, `importSkill`.

---

## Task 13: Frontend - SettingsPage Skill Repository Tab

**Files:** Modify `frontend/src/pages/SettingsPage.tsx`

Add "Skill Repository" tab with:
- Skill list with version and inject_mode badges
- Detail panel showing SKILL.md content and metadata
- Import button with dialog for git URL / local path

---

## Task 14: Frontend - TaskCreateForm Skill Enhancements

**Files:** Modify `frontend/src/pages/tasks/TaskCreateForm.tsx`

Add inject_mode badges (auto=green, prompt_only=yellow, disabled=gray) and dependency hints to skill selection UI.

---

## Task 15: Integration Tests & Final Validation

**Files:** Create `tests/test_skill_injection_e2e.py`

Write end-to-end test that:
1. Creates a skill repository with one skill
2. Calls `SkillInjectionService.generate_ainrf()` and `sync_to_claude()`
3. Verifies `.ainrf/skills/`, `.ainrf/settings.json`, `.ainrf/tool-manifest.json`
4. Verifies `.claude/skills/`, `.claude/.ainrf-managed`, `.claude/settings.json`

Final validation:
- `uv run pytest tests/ -x --no-header -q`
- `cd frontend && node_modules/.bin/tsc -b`
- `uv run ruff check src/ainrf/skills/ tests/skills/`

---

## Self-Review

**Spec coverage:** All 7 design sections mapped to tasks.
**Placeholder scan:** No TBD/TODO. All steps have code or exact commands.
**Type consistency:** `InjectMode`, `SkillDefinition`, `settings_fragment` types consistent throughout.
**Gaps:** Git auth for private repos not handled; hook chain wrapper not fully implemented (MVP acceptable).

---

## Execution Handoff

**Plan saved to `docs/superpowers/plans/2026-05-06-skill-injection.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - Fresh subagent per task, review between tasks
**2. Inline Execution** - Batch execution with checkpoints

**Which approach?**
