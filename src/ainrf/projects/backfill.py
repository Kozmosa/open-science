"""One-time, idempotent backfill of per-user default projects.

Every OpenScience user owns a default project named ``<username>_default``. New users
get one at registration time; this module provisions one for users that pre-date
that behaviour (e.g. created before the feature shipped, or the bootstrap admin
created directly during lifespan startup).

``backfill_user_default_projects`` is safe to call repeatedly: users that already
own a default project are skipped.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ainrf.projects import ProjectRegistryService


class _UserLike(Protocol):
    """Structural type covering :class:`ainrf.auth.models.User` and test fakes."""

    username: str
    id: str


def backfill_user_default_projects(
    *,
    project_service: ProjectRegistryService,
    users: Iterable[_UserLike],
) -> tuple[int, int]:
    """Ensure every supplied user owns a per-user default project.

    Returns ``(created, skipped)`` where ``skipped`` counts users whose
    ``<username>_default`` project already existed.
    """
    existing = {project.project_id for project in project_service.list_projects()}
    created = 0
    skipped = 0
    for user in users:
        project_id = f"{user.username}_default"
        if project_id in existing:
            skipped += 1
            continue
        project_service.get_or_create_user_default(username=user.username, owner_user_id=user.id)
        existing.add(project_id)
        created += 1
    return created, skipped
