from __future__ import annotations

from pathlib import Path

import pytest
import structlog

from ainrf.literature.broker import LiteratureRuntimeConfig
from ainrf.literature.providers.arxiv_rss import parse_rss
from ainrf.literature.tracking import (
    DiscoveredPaper,
    LiteratureTrackingService,
    canonical_arxiv_id,
)

pytestmark = [pytest.mark.unit]


def test_literature_runtime_prefers_ainrf_backend_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AINRF_LITERATURE_REDIS_URL", "redis://ainrf:6379/0")
    monkeypatch.setenv("OPENSCIENCE_LITERATURE_REDIS_URL", "redis://compatibility:6379/0")
    monkeypatch.setenv("AINRF_LITERATURE_REDIS_NAMESPACE", "ainrf:literature")
    monkeypatch.setenv("OPENSCIENCE_LITERATURE_REDIS_NAMESPACE", "compatibility:literature")

    config = LiteratureRuntimeConfig.from_env()

    assert config.redis_url == "redis://ainrf:6379/0"
    assert config.redis_namespace == "ainrf:literature"


def _service(tmp_path: Path) -> LiteratureTrackingService:
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    return service


def _paper(version: str = "v1") -> DiscoveredPaper:
    return DiscoveredPaper(
        provider="arxiv",
        external_id="2401.00001",
        provider_version=version,
        title="Agent memory for science",
        authors=["Ada"],
        abstract="A long-term memory method for research agents.",
        primary_category="cs.AI",
        categories=["cs.AI", "cs.LG"],
        published_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        source_url="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
    )


def test_arxiv_ids_only_strip_a_trailing_version_suffix() -> None:
    assert canonical_arxiv_id("solv-int/9709001v2") == ("9709001", "v2")
    assert canonical_arxiv_id("https://arxiv.org/abs/2401.00001v3") == ("2401.00001", "v3")
    assert canonical_arxiv_id("math/0001001") == ("0001001", "v1")


def test_topic_requires_category_and_matches_once_per_user(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="category"):
        service.create_topic(
            user_id="u1", label="Broken", include_terms=[], exclude_terms=[], categories=[]
        )
    first = service.create_topic(
        user_id="u1",
        label="Agents",
        include_terms=["agent"],
        exclude_terms=[],
        categories=["cs.AI"],
    )
    second = service.create_topic(
        user_id="u1",
        label="Memory",
        include_terms=["memory"],
        exclude_terms=[],
        categories=["cs.AI"],
    )
    service.store_discovered_papers("check_seed", [_paper()])

    papers = service.list_papers("u1", view="all")
    assert len(papers["items"]) == 1
    assert {topic["topic_id"] for topic in papers["items"][0]["matched_topics"]} == {
        first["topic_id"],
        second["topic_id"],
    }


def test_duplicate_checks_share_one_durable_work_item(tmp_path: Path) -> None:
    service = _service(tmp_path)
    topic = service.create_topic(
        user_id="u1", label="Agents", include_terms=[], exclude_terms=[], categories=["cs.AI"]
    )
    first = service.create_check(user_id="u1", topic_ids=[topic["topic_id"]])
    second = service.create_check(user_id="u1", topic_ids=[topic["topic_id"]])
    assert first["check_id"] == second["check_id"]
    assert len(service.pending_outbox_work_ids()) == 1


def test_check_log_contains_durable_workflow_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ainrf.literature.tracking as tracking_module

    service = _service(tmp_path)
    topic = service.create_topic(
        user_id="u1", label="Agents", include_terms=[], exclude_terms=[], categories=["cs.AI"]
    )

    with structlog.testing.capture_logs() as logs:
        # The production module logger may have been initialized by an earlier
        # test with a different structlog backend; use a fresh proxy here.
        monkeypatch.setattr(tracking_module, "logger", structlog.get_logger("test-literature"))
        result = service.create_check(user_id="u1", topic_ids=[topic["topic_id"]])

    event = next(item for item in logs if item["event"] == "literature_check_created")
    assert event["check_id"] == result["check_id"]
    assert isinstance(event["scope_id"], str)
    assert isinstance(event["work_item_id"], str)
    assert event["categories"] == ["cs.AI"]


def test_summary_is_version_keyed_and_deduplicated(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_topic(
        user_id="u1", label="Agents", include_terms=[], exclude_terms=[], categories=["cs.AI"]
    )
    service.store_discovered_papers("check_seed", [_paper()])
    paper_id = "arxiv:2401.00001"
    first = service.request_summary("u1", paper_id)
    second = service.request_summary("u1", paper_id)
    assert first["summary_id"] == second["summary_id"]
    service.store_discovered_papers("check_update", [_paper("v2")])
    assert service.get_summary("u1", paper_id)["status"] == "stale"


def test_paper_versions_do_not_expose_persistence_columns(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_topic(
        user_id="u1", label="Agents", include_terms=[], exclude_terms=[], categories=["cs.AI"]
    )
    service.store_discovered_papers("check_seed", [_paper()])

    version = service.get_paper("u1", "arxiv:2401.00001")["versions"][0]

    assert set(version) == {
        "version_id",
        "provider_version",
        "published_at",
        "updated_at",
        "first_seen_at",
    }


def test_rss_parser_keeps_announcement_version_and_type() -> None:
    body = b"""<?xml version='1.0'?><rss xmlns:arxiv='http://arxiv.org/schemas/atom'><channel>
      <item><title>Example</title><link>https://arxiv.org/abs/2401.00001v2</link>
      <guid>oai:arXiv.org:2401.00001v2</guid><description>Abstract</description>
      <author>Ada</author><category>cs.AI</category><arxiv:primary_category>cs.AI</arxiv:primary_category>
      <arxiv:announce_type>replace</arxiv:announce_type><pubDate>Mon, 01 Jan 2026 00:00:00 -0500</pubDate></item>
    </channel></rss>"""
    papers = parse_rss(body)
    assert len(papers) == 1
    assert papers[0].external_id == "2401.00001"
    assert papers[0].provider_version == "v2"
    assert papers[0].announce_type == "replace"
