"""Literature conversion saga recovers through the standard Task creator."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.db import connect
from ainrf.domain import DomainService, ProjectContextService
from ainrf.literature.task_saga import LiteratureTaskSagaService

pytestmark = [pytest.mark.unit]


def test_literature_conversion_saga_is_idempotent(state_root: Path) -> None:
    owner: dict[str, object] = {"id": "owner", "role": "member"}
    admin: dict[str, object] = {"id": "admin", "role": "admin"}
    domain = DomainService(state_root)
    environment = domain.create_environment(admin, alias="host", display_name="Host", connection={})
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=str(environment["environment_id"]),
        user_id="owner",
        max_tasks=None,
        granted_by="admin",
        reason="literature task saga test",
    )
    project = domain.create_project(owner, name="Project")
    workspace = domain.create_workspace(
        owner,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/lit",
        label="Lit",
    )
    domain.attach_workspace(
        str(project["project_id"]), str(workspace["workspace_id"]), owner, idempotency_key="link"
    )
    context = ProjectContextService(state_root)
    context.save_draft(str(project["project_id"]), "context", owner)
    context.publish(str(project["project_id"]), owner)
    literature_db = state_root / "runtime" / "literature.sqlite3"
    from ainrf.db import run_pending

    with connect(literature_db) as conn:
        run_pending(conn, "literature")
        conn.execute(
            "INSERT INTO literature_subscriptions(subscription_id, user_id, label, keywords_json, arxiv_categories_json, seed_paper_ids_json, frequency, is_active, created_at, max_results) VALUES ('sub', 'owner', '', '[]', '[]', '[]', 'daily', 1, 'now', 10)"
        )
        conn.execute(
            "INSERT INTO literature_papers(paper_id, title, authors_json, abstract, published_at, arxiv_category, created_at) VALUES ('paper', 'Paper', '[]', 'Abstract', '', '', 'now')"
        )
        conn.execute(
            "INSERT INTO literature_subscription_papers(subscription_id, paper_id, created_at) VALUES ('sub', 'paper', 'now')"
        )
        conn.commit()
    saga = LiteratureTaskSagaService(state_root)
    first = saga.convert(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=str(project["project_id"]),
        workspace_id=str(workspace["workspace_id"]),
    )
    second = saga.convert(
        owner,
        paper_id="paper",
        subscription_id="sub",
        project_id=str(project["project_id"]),
        workspace_id=str(workspace["workspace_id"]),
    )

    assert first == second
