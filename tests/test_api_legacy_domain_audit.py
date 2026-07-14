"""Admin-only inspection of unmapped legacy domain records."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.db import connect
from tests.testutil import get_jwt_headers

pytestmark = [pytest.mark.api]


def _app(state_root: Path) -> FastAPI:
    return create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("legacy-audit-api-key")}),
            state_root=state_root,
        )
    )


def _seed_legacy_record(state_root: Path) -> None:
    db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO domain_migration_runs
                (run_id, mode, source_manifest_json, code_version, status, started_at)
            VALUES ('audit-run', 'apply', '{}', 'test', 'finished',
                '2026-07-12T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO legacy_domain_records (
                legacy_record_id, run_id, record_type, payload_json, created_at,
                source_path, source_record_id, source_payload_sha256, reason
            ) VALUES (?, 'audit-run', 'session', ?, '2026-07-12T00:00:00+00:00',
                'runtime/sessions.sqlite3', 'legacy-session-1', ?, 'no Task mapping')
            """,
            (
                "legacy-session-1",
                json.dumps(
                    {
                        "session_id": "legacy-session-1",
                        "api_key": "must-not-leak",
                        "nested": {"password": "must-not-leak"},
                    }
                ),
                "a" * 64,
            ),
        )
        conn.commit()


@pytest.mark.anyio
async def test_admin_can_list_and_inspect_redacted_unmapped_legacy_records(
    state_root: Path,
) -> None:
    app = _app(state_root)
    _seed_legacy_record(state_root)
    admin_headers = get_jwt_headers(app, "legacy-auditor", "legacy-audit-password")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed = await client.get("/admin/domain/legacy-records", headers=admin_headers)
        inspected = await client.get(
            "/admin/domain/legacy-records/legacy-session-1", headers=admin_headers
        )
        denied = await client.get("/admin/domain/legacy-records?api_key=legacy-audit-api-key")

    assert listed.status_code == 200
    assert listed.json() == {
        "items": [
            {
                "legacy_record_id": "legacy-session-1",
                "run_id": "audit-run",
                "record_type": "session",
                "source_path": "runtime/sessions.sqlite3",
                "source_record_id": "legacy-session-1",
                "source_payload_sha256": "a" * 64,
                "reason": "no Task mapping",
                "created_at": "2026-07-12T00:00:00+00:00",
            }
        ],
        "has_more": False,
        "next_cursor": None,
    }
    assert inspected.status_code == 200
    assert inspected.json()["payload"] == {
        "session_id": "legacy-session-1",
        "api_key": "[redacted]",
        "nested": {"password": "[redacted]"},
    }
    assert denied.status_code == 403
