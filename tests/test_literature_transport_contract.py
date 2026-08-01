from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.api.transport_schema import build_transport_openapi

pytestmark = [pytest.mark.unit]

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_legacy_literature_routes_are_explicitly_retained_and_not_frontend_callers() -> None:
    schema = build_transport_openapi()
    legacy = {
        ("get", "/api/literature/subscriptions"),
        ("post", "/api/literature/subscriptions"),
        ("put", "/api/literature/subscriptions/{subscription_id}"),
        ("delete", "/api/literature/subscriptions/{subscription_id}"),
        ("get", "/api/literature/subscriptions/{subscription_id}/fetch-status"),
        ("post", "/api/literature/subscriptions/{subscription_id}/fetch"),
        ("post", "/api/literature/papers/{paper_id}/read"),
    }
    assert len(legacy) == 7
    for method, path in legacy:
        assert method in schema["paths"][path]

    frontend_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((_REPO_ROOT / "frontend" / "src").rglob("*.ts*"))
        if "generated/transport" not in path.as_posix()
    )
    assert "/literature/subscriptions" not in frontend_sources
    assert "/papers/:paperId/read" not in frontend_sources


def test_literature_generated_interface_has_no_singular_research_task_query() -> None:
    schema = build_transport_openapi()
    operation = schema["paths"]["/api/literature/papers/{paper_id}/research-task"]
    assert set(operation) == {"post"}


def test_literature_transport_models_are_owned_outside_shared_schema_module() -> None:
    shared_schema = (_REPO_ROOT / "src" / "ainrf" / "api" / "schemas.py").read_text(
        encoding="utf-8"
    )
    feature_schema = (_REPO_ROOT / "src" / "ainrf" / "api" / "literature_schemas.py").read_text(
        encoding="utf-8"
    )
    assert "class Literature" not in shared_schema
    assert "class LiteratureOverviewResponse" in feature_schema
