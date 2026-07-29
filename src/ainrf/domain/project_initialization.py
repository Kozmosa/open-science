"""Transactional initialization for a new authoritative Project."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from uuid import uuid4


def initialize_project_context(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    owner_user_id: str,
    created_at: str,
) -> str:
    """Create the empty Draft and initial immutable Active Version atomically."""

    context_version_id = f"context-{uuid4().hex}"
    content = ""
    manifest_json = json.dumps([], ensure_ascii=False, separators=(",", ":"))
    fingerprint_payload = json.dumps(
        {"content": content, "fragment_manifest": [], "version_format": 1},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()
    evidence_json = json.dumps(
        {
            "kind": "published_fragment_manifest",
            "manifest_sha256": hashlib.sha256(manifest_json.encode("utf-8")).hexdigest(),
            "fragment_count": 0,
            "source": "project_context_publish_transaction",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    conn.execute(
        """INSERT INTO project_context_drafts
           (project_id, content, updated_by_user_id, updated_at)
           VALUES (?, ?, ?, ?)""",
        (project_id, content, owner_user_id, created_at),
    )
    conn.execute(
        """INSERT INTO project_context_versions
           (context_version_id, project_id, content, fingerprint, fragment_manifest_json,
            is_active, created_by_user_id, created_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (
            context_version_id,
            project_id,
            content,
            fingerprint,
            manifest_json,
            owner_user_id,
            created_at,
        ),
    )
    conn.execute(
        """INSERT INTO project_context_version_provenance (
               context_version_id, fragment_provenance_status, evidence_json, recorded_at
           ) VALUES (?, 'verified', ?, ?)""",
        (context_version_id, evidence_json, created_at),
    )
    return context_version_id
