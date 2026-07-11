"""arXiv RSS discovery adapter.

RSS is an announcement stream, not a history search endpoint.  This adapter
therefore exposes HTTP validators and the exact raw body to the durable layer.
"""

from __future__ import annotations

import email.utils
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass
from typing import Iterable

import httpx

from ainrf.literature.tracking import DiscoveredPaper, canonical_arxiv_id

_RSS_BASE_URL = "https://rss.arxiv.org/rss"


@dataclass(frozen=True, slots=True)
class RssFetchResult:
    status_code: int
    body: bytes | None
    etag: str | None
    last_modified: str | None
    cache_control: str | None
    papers: list[DiscoveredPaper]


class ArxivRssProvider:
    name = "arxiv-rss"

    async def fetch(
        self,
        categories: Iterable[str],
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> RssFetchResult:
        scope = "+".join(sorted(set(categories)))
        if not scope:
            raise ValueError("RSS discovery requires at least one category")
        headers = {"User-Agent": "OpenScience literature tracker/1.0"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        owns_client = client is None
        request_client = client or httpx.AsyncClient(timeout=30)
        try:
            response = await request_client.get(f"{_RSS_BASE_URL}/{scope}", headers=headers)
        finally:
            if owns_client:
                await request_client.aclose()
        body = response.content if response.status_code == 200 else None
        return RssFetchResult(
            status_code=response.status_code,
            body=body,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
            cache_control=response.headers.get("Cache-Control"),
            papers=parse_rss(body) if body else [],
        )


def parse_rss(body: bytes) -> list[DiscoveredPaper]:
    """Parse arXiv RSS 2.0 without assuming a particular namespace prefix."""
    root = element_tree.fromstring(body)
    papers: list[DiscoveredPaper] = []
    for item in _children_named(root, "item"):
        title = _text(item, "title")
        description = _text(item, "description")
        link = _text(item, "link")
        guid = _text(item, "guid")
        raw_id = _extract_identifier(guid or link or description)
        if not raw_id:
            continue
        external_id, provider_version = canonical_arxiv_id(raw_id)
        categories = [
            child.text.strip()
            for child in _children_named(item, "category")
            if child.text and child.text.strip()
        ]
        primary = _text(item, "primary_category") or (categories[0] if categories else "")
        authors = [
            child.text.strip()
            for child in _children_named(item, "author")
            if child.text and child.text.strip()
        ]
        announced_at = _parse_date(_text(item, "pubDate"))
        papers.append(
            DiscoveredPaper(
                provider="arxiv",
                external_id=external_id,
                provider_version=provider_version,
                title=title,
                authors=authors,
                abstract=description,
                primary_category=primary,
                categories=categories or ([primary] if primary else []),
                published_at=None,
                updated_at=announced_at,
                source_url=link or f"https://arxiv.org/abs/{external_id}",
                pdf_url=f"https://arxiv.org/pdf/{external_id}",
                announce_type=_text(item, "announce_type") or "new",
                announced_at=announced_at,
            )
        )
    return papers


def _children_named(element: element_tree.Element, name: str) -> list[element_tree.Element]:
    return [child for child in element.iter() if child.tag.rsplit("}", 1)[-1] == name]


def _text(element: element_tree.Element, name: str) -> str:
    child = next(iter(_children_named(element, name)), None)
    return child.text.strip() if child is not None and child.text else ""


def _extract_identifier(value: str) -> str:
    if "arXiv.org:" in value:
        return value.split("arXiv.org:", 1)[1].split()[0]
    for part in value.replace("?", "/").split("/"):
        if "arxiv.org/abs/" in part:
            return part.rsplit("/", 1)[-1]
    if "arxiv:" in value.lower():
        return value.lower().split("arxiv:", 1)[1].split()[0]
    return value.rsplit("/", 1)[-1] if value else ""


def _parse_date(value: str) -> str | None:
    if not value:
        return None
    parsed = email.utils.parsedate_to_datetime(value)
    return parsed.isoformat()
