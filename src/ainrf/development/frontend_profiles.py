from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import DomainService
from ainrf.literature.tracking import LiteratureTrackingService


FRONTEND_DEV_FIXTURE_VERSION = 2
_USER_ID = "api-key-user"
_NOW = "2026-07-14T09:00:00+00:00"
_LATER = "2026-07-14T10:00:00+00:00"


class FrontendDevProfile(StrEnum):
    FULL = "full"
    EMPTY = "empty"
    PERMISSIONS = "permissions"
    FAILURES = "failures"
    LARGE = "large"


@dataclass(frozen=True, slots=True)
class FrontendDevSeedResult:
    project_id: str | None
    primary_workspace_id: str | None
    blocked_workspace_id: str | None
    environment_id: str | None
    counts: dict[str, int]


def normalize_frontend_dev_profile(value: FrontendDevProfile | str) -> FrontendDevProfile:
    if isinstance(value, FrontendDevProfile):
        return value
    try:
        return FrontendDevProfile(value.strip().lower())
    except ValueError as exc:
        choices = ", ".join(profile.value for profile in FrontendDevProfile)
        raise ValueError(
            f"unknown frontend development profile; expected one of: {choices}"
        ) from exc


def seed_frontend_dev_profile(
    state_root: Path,
    *,
    artifact_sha: str,
    profile: FrontendDevProfile,
) -> FrontendDevSeedResult:
    DomainService(state_root, artifact_sha=artifact_sha)
    LiteratureTrackingService(state_root).initialize()
    if profile is FrontendDevProfile.EMPTY:
        _remove_cutover_default_project(state_root)
        result = FrontendDevSeedResult(None, None, None, None, _fixture_counts(state_root))
        _assert_no_claimable_work(state_root)
        return result
    if profile is FrontendDevProfile.LARGE:
        result = _seed_large_profile(state_root)
    else:
        result = _seed_core_profile(state_root)
        _seed_representative_tasks(
            state_root, include_failures=profile is FrontendDevProfile.FAILURES
        )
        _seed_literature(
            state_root, count=8, include_failures=profile is FrontendDevProfile.FAILURES
        )
        if profile is FrontendDevProfile.PERMISSIONS:
            _seed_permission_matrix(state_root)
        _seed_overview(state_root, failed=profile is FrontendDevProfile.FAILURES)
        result = FrontendDevSeedResult(
            result.project_id,
            result.primary_workspace_id,
            result.blocked_workspace_id,
            result.environment_id,
            _fixture_counts(state_root),
        )
    _assert_no_claimable_work(state_root)
    return result


def _seed_core_profile(state_root: Path) -> FrontendDevSeedResult:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    workspace_root = state_root.parent / f"{state_root.name}-workspaces"
    primary_path = workspace_root / "primary"
    blocked_path = workspace_root / "blocked"
    primary_path.mkdir(parents=True, exist_ok=True)
    blocked_path.mkdir(parents=True, exist_ok=True)
    context_content = "Synthetic Project Context for the frontend development profiles."
    context_fingerprint = sha256(context_content.encode("utf-8")).hexdigest()
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO projects (
                project_id, owner_user_id, name, description, status, is_default,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'active', 1, ?, ?)
            """,
            (
                "project-frontend-dev",
                _USER_ID,
                "Frontend Development",
                "Synthetic v2 project for frontend implementation",
                _NOW,
                _NOW,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO projects (
                project_id, owner_user_id, name, description, status, is_default,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'active', 0, ?, ?)
            """,
            (
                "project-needs-workspace",
                _USER_ID,
                "Frontend Needs Workspace",
                "Synthetic attention state without a Workspace",
                _NOW,
                _NOW,
            ),
        )
        environments = (
            (
                "environment-frontend-dev",
                "frontend-dev-local",
                "Frontend Dev Local",
                "Synthetic local Environment for frontend implementation",
                json.dumps({"host": "127.0.0.1", "default_workdir": str(workspace_root)}),
            ),
            (
                "environment-frontend-blocked",
                "frontend-dev-blocked",
                "Frontend Dev Blocked",
                "Synthetic Environment with a revoked execution grant",
                json.dumps({"host": "127.0.0.1", "default_workdir": str(blocked_path)}),
            ),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO environments (
                environment_id, alias, owner_user_id, display_name, description,
                connection_json, status, created_at, updated_at
            ) VALUES (?, ?, NULL, ?, ?, ?, 'active', ?, ?)
            """,
            [(*environment, _NOW, _NOW) for environment in environments],
        )
        workspaces = (
            (
                "workspace-frontend-primary",
                "environment-frontend-dev",
                str(primary_path),
                "Primary frontend workspace",
                "Executable synthetic Workspace",
                "Use this synthetic Workspace for frontend development.",
            ),
            (
                "workspace-frontend-blocked",
                "environment-frontend-blocked",
                str(blocked_path),
                "Unavailable frontend workspace",
                "Linked Workspace without an active Environment grant",
                "Exercise linked-but-not-executable frontend states.",
            ),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO workspaces (
                workspace_id, owner_user_id, environment_id, canonical_path, label,
                description, workspace_context, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            [
                (
                    workspace_id,
                    _USER_ID,
                    environment_id,
                    path,
                    label,
                    description,
                    context,
                    _NOW,
                    _NOW,
                )
                for workspace_id, environment_id, path, label, description, context in workspaces
            ],
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO project_workspace_links (
                project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
            ) VALUES ('project-frontend-dev', ?, 'active', ?, 'frontend-dev-fixture', ?, ?)
            """,
            [
                ("workspace-frontend-primary", 1, _NOW, _NOW),
                ("workspace-frontend-blocked", 0, _NOW, _NOW),
            ],
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO project_context_drafts (
                project_id, content, updated_by_user_id, updated_at
            ) VALUES ('project-frontend-dev', ?, ?, ?)
            """,
            (context_content, _USER_ID, _NOW),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO project_context_versions (
                context_version_id, project_id, content, fingerprint, is_active,
                created_by_user_id, created_at, fragment_manifest_json
            ) VALUES (
                'context-version-frontend-dev', 'project-frontend-dev', ?, ?, 1, ?, ?, '[]'
            )
            """,
            (context_content, context_fingerprint, _USER_ID, _NOW),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO context_snapshots (
                context_snapshot_id, context_version_id, fingerprint, content,
                created_at, source_manifest_json, byte_budget, truncated
            ) VALUES (
                'context-snapshot-frontend-dev', 'context-version-frontend-dev',
                ?, ?, ?, '[]', 65536, 0
            )
            """,
            (context_fingerprint, context_content, _NOW),
        )
        conn.commit()

    auth = AuthService(state_root=state_root)
    auth.grant_environment(
        env_id="environment-frontend-dev",
        user_id=_USER_ID,
        max_tasks=None,
        granted_by="frontend-dev-fixture",
        reason="frontend development fixture",
    )
    auth.grant_environment(
        env_id="environment-frontend-blocked",
        user_id=_USER_ID,
        max_tasks=None,
        granted_by="frontend-dev-fixture",
        reason="prepare blocked frontend fixture",
    )
    auth.revoke_environment(
        "environment-frontend-blocked",
        _USER_ID,
        revoked_by="frontend-dev-fixture",
        reason="exercise linked-but-not-executable frontend state",
    )
    return FrontendDevSeedResult(
        "project-frontend-dev",
        "workspace-frontend-primary",
        "workspace-frontend-blocked",
        "environment-frontend-dev",
        {},
    )


def _seed_representative_tasks(state_root: Path, *, include_failures: bool) -> None:
    statuses = ["completed", "failed", "cancelled", "stopped", "launch_unknown"]
    if include_failures:
        statuses.extend(["stopped_by_project_archive", "stopped_permission_revoked"])
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        for index, status in enumerate(statuses, start=1):
            task_id = f"task-frontend-{status}"
            attempt_id = f"attempt-frontend-{status}"
            conn.execute(
                """
                INSERT OR IGNORE INTO tasks (
                    task_id, project_id, workspace_id, environment_id, researcher_type,
                    harness_engine, status, title, prompt, created_at, updated_at,
                    started_at, completed_at, owner_user_id, error_summary,
                    project_context_version_id, project_context_snapshot_id,
                    latest_attempt_id, token_usage_json
                ) VALUES (
                    ?, 'project-frontend-dev', 'workspace-frontend-primary',
                    'environment-frontend-dev', 'vsa', 'codex-app-server', ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, 'context-version-frontend-dev',
                    'context-snapshot-frontend-dev', ?, ?
                )
                """,
                (
                    task_id,
                    status,
                    f"Frontend {status.replace('_', ' ').title()} Task",
                    f"Synthetic {status} Task for frontend state coverage.",
                    _NOW,
                    _LATER,
                    _NOW,
                    _LATER,
                    _USER_ID,
                    None if status == "completed" else f"Synthetic {status} detail",
                    attempt_id,
                    json.dumps({"input_tokens": 100 * index, "output_tokens": 50 * index}),
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_task_attempts (
                    attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id,
                    runtime_config_fingerprint, created_at, started_at, finished_at,
                    token_usage_json, cost_usd, failure_reason, stop_reason
                ) VALUES (?, ?, 1, 'initial', ?, 'context-snapshot-frontend-dev', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    task_id,
                    status,
                    sha256(task_id.encode("utf-8")).hexdigest(),
                    _NOW,
                    _NOW,
                    _LATER,
                    json.dumps({"input_tokens": 100 * index, "output_tokens": 50 * index}),
                    round(index * 0.013, 3),
                    f"Synthetic {status} failure"
                    if status in {"failed", "launch_unknown"}
                    else None,
                    status if status.startswith("stopped") or status == "cancelled" else None,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_runtime_sessions (
                    runtime_session_id, attempt_id, launch_key, status, created_at,
                    engine_name, engine_session_key, runtime_metadata_json,
                    started_at, finished_at, failure_reason
                ) VALUES (?, ?, ?, ?, ?, 'codex-app-server', ?, ?, ?, ?, ?)
                """,
                (
                    f"runtime-frontend-{status}",
                    attempt_id,
                    f"launch-frontend-{status}",
                    status,
                    _NOW,
                    f"session-frontend-{status}",
                    json.dumps({"profile": "frontend-dev", "status": status}),
                    _NOW,
                    _LATER,
                    f"Synthetic {status} runtime"
                    if status in {"failed", "launch_unknown"}
                    else None,
                ),
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO task_relationships (
                source_task_id, target_task_id, relationship_type, created_at,
                relationship_id, metadata_json
            ) VALUES (
                'task-frontend-failed', 'task-frontend-completed', 'derived_from', ?,
                'relationship-frontend-derived', '{}'
            )
            """,
            (_LATER,),
        )
        conn.commit()


def _seed_permission_matrix(state_root: Path) -> None:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        projects = (
            ("project-permission-viewer", "fixture-viewer-owner", "Viewer Project", "active"),
            ("project-permission-editor", "fixture-editor-owner", "Editor Project", "active"),
            ("project-permission-archived", _USER_ID, "Archived Project", "archived"),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO projects (
                project_id, owner_user_id, name, status, is_default,
                archived_at, archive_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            [
                (
                    project_id,
                    owner_id,
                    name,
                    status,
                    _LATER if status == "archived" else None,
                    "Synthetic archived Project" if status == "archived" else None,
                    _NOW,
                    _LATER,
                )
                for project_id, owner_id, name, status in projects
            ],
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO project_members (
                project_id, user_id, role, can_publish, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("project-permission-viewer", _USER_ID, "viewer", 0, _NOW, _NOW),
                ("project-permission-editor", _USER_ID, "editor", 1, _NOW, _NOW),
            ],
        )
        conn.commit()


def _seed_literature(state_root: Path, *, count: int, include_failures: bool) -> None:
    db_path = state_root / "runtime" / "literature.sqlite3"
    with closing(connect(db_path)) as conn:
        for topic_index in range(3):
            conn.execute(
                """
                INSERT OR IGNORE INTO literature_topics (
                    topic_id, user_id, label, include_terms_json, categories_json,
                    status, is_active, created_at, updated_at, last_matched_at
                ) VALUES (?, ?, ?, ?, '["cs.AI"]', 'active', 1, ?, ?, ?)
                """,
                (
                    f"topic-frontend-{topic_index + 1}",
                    _USER_ID,
                    f"Frontend Topic {topic_index + 1}",
                    json.dumps([f"topic-{topic_index + 1}"]),
                    _NOW,
                    _NOW,
                    _LATER,
                ),
            )
        for index in range(count):
            paper_id = f"paper-frontend-{index + 1:03d}"
            version_id = f"version-frontend-{index + 1:03d}"
            conn.execute(
                """
                INSERT OR IGNORE INTO literature_catalog_papers (
                    paper_id, provider, external_id, title, authors_json,
                    primary_category, categories_json, abstract, source_url, pdf_url,
                    published_at, updated_at, current_version_id, first_seen_at, last_seen_at
                ) VALUES (?, 'arxiv', ?, ?, ?, 'cs.AI', '["cs.AI"]', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    f"2607.{index + 1:05d}",
                    f"Synthetic Frontend Paper {index + 1}",
                    json.dumps(["OpenScience Fixture"]),
                    f"Deterministic abstract for frontend paper {index + 1}.",
                    f"https://arxiv.org/abs/2607.{index + 1:05d}",
                    f"https://arxiv.org/pdf/2607.{index + 1:05d}",
                    _NOW,
                    _LATER,
                    version_id,
                    _NOW,
                    _LATER,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO literature_paper_versions (
                    version_id, paper_id, provider_version, title, authors_json,
                    abstract, categories_json, published_at, updated_at,
                    content_hash, first_seen_at
                ) VALUES (?, ?, 'v1', ?, ?, ?, '["cs.AI"]', ?, ?, ?, ?)
                """,
                (
                    version_id,
                    paper_id,
                    f"Synthetic Frontend Paper {index + 1}",
                    json.dumps(["OpenScience Fixture"]),
                    f"Deterministic abstract for frontend paper {index + 1}.",
                    _NOW,
                    _LATER,
                    sha256(paper_id.encode("utf-8")).hexdigest(),
                    _NOW,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO literature_topic_matches (
                    topic_id, paper_id, reason_json, matched_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    f"topic-frontend-{index % 3 + 1}",
                    paper_id,
                    json.dumps(["deterministic fixture match"]),
                    _LATER,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO literature_user_paper_states (
                    user_id, paper_id, is_read, is_saved, is_ignored,
                    first_seen_at, last_seen_at, latest_seen_version_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _USER_ID,
                    paper_id,
                    int(index % 4 == 0),
                    int(index % 4 == 1),
                    int(index % 7 == 0),
                    _NOW,
                    _LATER,
                    version_id,
                ),
            )
        if include_failures:
            conn.execute(
                """
                INSERT OR IGNORE INTO literature_checks (
                    check_id, user_id, trigger, request_fingerprint, status,
                    created_at, started_at, completed_at, last_error
                ) VALUES (
                    'check-frontend-failed', ?, 'manual', 'frontend-failed-check',
                    'failed', ?, ?, ?, 'Synthetic provider failure'
                )
                """,
                (_USER_ID, _NOW, _NOW, _LATER),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO literature_summaries (
                    summary_id, paper_id, version_id, content_hash, recipe_version,
                    model, language, status, error_message, created_at, completed_at
                ) VALUES (
                    'summary-frontend-failed', 'paper-frontend-001',
                    'version-frontend-001', 'frontend-summary-failure', 'v1',
                    'fixture-model', 'en', 'failed', 'Synthetic summary failure', ?, ?
                )
                """,
                (_NOW, _LATER),
            )
        conn.commit()


def _seed_overview(state_root: Path, *, failed: bool) -> None:
    status = "partial" if failed else "ok"
    card_statuses = {
        "attention": "partial" if failed else "ok",
        "progress": "stale" if failed else "ok",
        "literature": "failed" if failed else "ok",
        "continue": "ok",
        "resources": "partial" if failed else "ok",
    }
    display_cards = [
        {
            "id": card_id,
            "data": _overview_card_data(card_id, failed=failed),
            "data_cutoff_at": _LATER,
            "source_status": card_status,
            "attention_required": card_id == "attention" or (failed and card_id == "resources"),
            "error_summary": f"Synthetic {card_id} failure" if card_status != "ok" else None,
        }
        for card_id, card_status in card_statuses.items()
    ]
    payload = {
        "snapshot_id": "overview-frontend-dev",
        "owner_user_id": _USER_ID,
        "snapshot_date": "2026-07-14",
        "data_cutoff_at": _LATER,
        "source_status": status,
        "attention_required": True,
        "cards": [],
        "display_cards": display_cards,
        "next_scheduled_at": "2026-07-14T22:00:00+00:00",
        "source": "synthetic_fixture",
        "projects_active": 2,
        "tasks_by_status": {"completed": 1, "failed": 1},
        "active_attempts": 0,
    }
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO overview_snapshots (
                snapshot_id, owner_user_id, snapshot_date, payload_json, created_at,
                data_cutoff_at, source_status, attention_required
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(owner_user_id, snapshot_date) DO UPDATE SET
                snapshot_id = excluded.snapshot_id,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                data_cutoff_at = excluded.data_cutoff_at,
                source_status = excluded.source_status,
                attention_required = excluded.attention_required
            """,
            (
                "overview-frontend-dev",
                _USER_ID,
                "2026-07-14",
                json.dumps(payload, sort_keys=True),
                _LATER,
                _LATER,
                status,
            ),
        )
        conn.commit()


def _overview_card_data(card_id: str, *, failed: bool) -> dict[str, object]:
    if card_id == "attention":
        return {"items": [{"kind": "fixture_attention", "title": "Review synthetic state"}]}
    if card_id == "progress":
        return {"tasks": [{"task_id": "task-frontend-completed", "title": "Completed Task"}]}
    if card_id == "literature":
        return {
            "unread_count": 6,
            "updated_count": 2,
            "papers": [{"paper_id": "paper-frontend-001", "title": "Synthetic Frontend Paper 1"}],
        }
    if card_id == "continue":
        return {"items": [{"kind": "project", "id": "project-frontend-dev"}]}
    return {
        "environments": ([{"environment_id": "environment-frontend-dev"}] if failed else []),
        "environment_count": 2,
    }


def _seed_large_profile(state_root: Path) -> FrontendDevSeedResult:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    workspace_root = state_root.parent / f"{state_root.name}-large-workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        conn.execute("DELETE FROM projects WHERE project_id = 'project-frontend-dev'")
        conn.execute(
            """
            INSERT OR IGNORE INTO environments (
                environment_id, alias, owner_user_id, display_name, description,
                connection_json, status, created_at, updated_at
            ) VALUES (
                'environment-large', 'frontend-dev-large', NULL, 'Frontend Large Fixture',
                'Deterministic large-list Environment', ?, 'active', ?, ?
            )
            """,
            (json.dumps({"host": "127.0.0.1", "default_workdir": str(workspace_root)}), _NOW, _NOW),
        )
        for project_index in range(40):
            project_id = f"project-large-{project_index + 1:03d}"
            conn.execute(
                """
                INSERT OR IGNORE INTO projects (
                    project_id, owner_user_id, name, description, status, is_default,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'Large deterministic fixture', 'active', ?, ?, ?)
                """,
                (
                    project_id,
                    _USER_ID,
                    f"Large Project {project_index + 1:03d}",
                    int(project_index == 0),
                    _NOW,
                    _LATER,
                ),
            )
            for workspace_index in range(3):
                ordinal = project_index * 3 + workspace_index + 1
                workspace_id = f"workspace-large-{ordinal:03d}"
                path = workspace_root / f"workspace-{ordinal:03d}"
                path.mkdir(parents=True, exist_ok=True)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO workspaces (
                        workspace_id, owner_user_id, environment_id, canonical_path,
                        label, description, workspace_context, status, created_at, updated_at
                    ) VALUES (?, ?, 'environment-large', ?, ?, 'Large fixture Workspace',
                              'Large list and scrolling coverage', 'active', ?, ?)
                    """,
                    (
                        workspace_id,
                        _USER_ID,
                        str(path),
                        f"Large Workspace {ordinal:03d}",
                        _NOW,
                        _LATER,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO project_workspace_links (
                        project_id, workspace_id, status, is_primary, actor_id,
                        created_at, updated_at
                    ) VALUES (?, ?, 'active', ?, 'frontend-dev-fixture', ?, ?)
                    """,
                    (project_id, workspace_id, int(workspace_index == 0), _NOW, _LATER),
                )
        for task_index in range(500):
            project_index = task_index % 40
            workspace_ordinal = project_index * 3 + task_index % 3 + 1
            conn.execute(
                """
                INSERT OR IGNORE INTO tasks (
                    task_id, project_id, workspace_id, environment_id, researcher_type,
                    harness_engine, status, title, prompt, created_at, updated_at,
                    completed_at, owner_user_id
                ) VALUES (?, ?, ?, 'environment-large', 'vsa', 'codex-app-server', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"task-large-{task_index + 1:04d}",
                    f"project-large-{project_index + 1:03d}",
                    f"workspace-large-{workspace_ordinal:03d}",
                    "completed" if task_index % 5 else "failed",
                    f"Large Task {task_index + 1:04d}",
                    "Synthetic terminal Task for large-list coverage.",
                    _NOW,
                    _LATER,
                    _LATER,
                    _USER_ID,
                ),
            )
        conn.commit()
    AuthService(state_root=state_root).grant_environment(
        env_id="environment-large",
        user_id=_USER_ID,
        max_tasks=None,
        granted_by="frontend-dev-fixture",
        reason="large frontend development fixture",
    )
    _seed_literature(state_root, count=250, include_failures=False)
    _seed_overview(state_root, failed=False)
    return FrontendDevSeedResult(
        "project-large-001",
        "workspace-large-001",
        None,
        "environment-large",
        _fixture_counts(state_root),
    )


def _remove_cutover_default_project(state_root: Path) -> None:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute("DELETE FROM projects WHERE project_id = 'project-frontend-dev'")
        conn.commit()


def _fixture_counts(state_root: Path) -> dict[str, int]:
    domain_db = state_root / "runtime" / "agentic_researcher.sqlite3"
    literature_db = state_root / "runtime" / "literature.sqlite3"
    counts: dict[str, int] = {}
    with closing(connect(domain_db)) as conn:
        for key, table in (
            ("projects", "projects"),
            ("workspaces", "workspaces"),
            ("tasks", "tasks"),
            ("attempts", "agent_task_attempts"),
        ):
            counts[key] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    with closing(connect(literature_db)) as conn:
        counts["papers"] = int(
            conn.execute("SELECT COUNT(*) FROM literature_catalog_papers").fetchone()[0]
        )
    return counts


def _assert_no_claimable_work(state_root: Path) -> None:
    domain_db = state_root / "runtime" / "agentic_researcher.sqlite3"
    literature_db = state_root / "runtime" / "literature.sqlite3"
    with closing(connect(domain_db)) as conn:
        claimable_dispatches = int(
            conn.execute(
                "SELECT COUNT(*) FROM task_dispatch_outbox WHERE status IN ('pending', 'claimed')"
            ).fetchone()[0]
        )
    with closing(connect(literature_db)) as conn:
        claimable_literature = int(
            conn.execute(
                "SELECT COUNT(*) FROM literature_work_items WHERE status IN ('pending', 'retryable')"
            ).fetchone()[0]
        )
        pending_outbox = int(
            conn.execute(
                "SELECT COUNT(*) FROM literature_outbox WHERE status = 'pending'"
            ).fetchone()[0]
        )
    if claimable_dispatches or claimable_literature or pending_outbox:
        raise RuntimeError("frontend fixture must not enqueue external runtime or Literature work")
