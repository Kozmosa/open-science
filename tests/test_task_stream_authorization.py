"""Ownership boundary coverage for task output streams."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ainrf.api.routes import tasks

pytestmark = [pytest.mark.unit]


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/tasks/task-1/stream",
            "headers": [],
            "query_string": b"api_key=valid-key",
        }
    )


def test_unscoped_api_key_cannot_stream_another_users_task(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SimpleNamespace(
        get_task=lambda task_id: SimpleNamespace(task_id=task_id, owner_user_id="tenant-a")
    )
    monkeypatch.setattr(tasks, "_get_service", lambda request: service)
    monkeypatch.setattr(
        tasks,
        "get_current_user",
        lambda request: {"id": "api-key-user", "role": "user"},
    )

    with pytest.raises(HTTPException) as raised:
        tasks._assert_task_stream_access(_request(), "task-1")

    assert raised.value.status_code == 404


def test_task_owner_can_stream_their_own_task(monkeypatch: pytest.MonkeyPatch) -> None:
    task = SimpleNamespace(task_id="task-1", owner_user_id="tenant-a")
    service = SimpleNamespace(get_task=lambda task_id: task)
    monkeypatch.setattr(tasks, "_get_service", lambda request: service)
    monkeypatch.setattr(
        tasks,
        "get_current_user",
        lambda request: {"id": "tenant-a", "role": "user"},
    )

    returned_service, returned_task = tasks._assert_task_stream_access(_request(), "task-1")

    assert returned_service is service
    assert returned_task is task
