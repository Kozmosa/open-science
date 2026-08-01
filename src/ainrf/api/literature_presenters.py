"""Present Literature application results at the HTTP transport Seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from ainrf.api.literature_schemas import (
    LegacyLiteratureSubscriptionResponse,
    LiteratureCheckListResponse,
    LiteraturePaperVersionListResponse,
    LiteratureResearchTaskListResponse,
    LiteratureTopicListResponse,
)

TransportModel = TypeVar("TransportModel", bound=BaseModel)


def present(model: type[TransportModel], result: Mapping[str, Any]) -> TransportModel:
    """Whitelist an application result through its declared transport Interface."""

    allowed = {name: result.get(name) for name in model.model_fields}
    return model.model_validate(allowed)


def present_topic_list(items: Sequence[Mapping[str, Any]]) -> LiteratureTopicListResponse:
    values = list(items)
    return LiteratureTopicListResponse.model_validate(
        {"items": values, "total": len(values), "next_cursor": None}
    )


def present_check_list(items: Sequence[Mapping[str, Any]]) -> LiteratureCheckListResponse:
    values = list(items)
    return LiteratureCheckListResponse.model_validate(
        {"items": values, "total": len(values), "next_cursor": None}
    )


def present_version_list(items: Sequence[Mapping[str, Any]]) -> LiteraturePaperVersionListResponse:
    values = list(items)
    return LiteraturePaperVersionListResponse.model_validate(
        {"items": values, "total": len(values), "next_cursor": None}
    )


def present_research_task_list(
    items: Sequence[Mapping[str, object]],
) -> LiteratureResearchTaskListResponse:
    values = list(items)
    return LiteratureResearchTaskListResponse.model_validate(
        {"items": values, "total": len(values), "next_cursor": None}
    )


def present_legacy_subscription(result: Mapping[str, Any]) -> LegacyLiteratureSubscriptionResponse:
    return LegacyLiteratureSubscriptionResponse(
        subscription_id=str(result["topic_id"]),
        user_id=str(result["user_id"]),
        label=str(result["label"]),
        keywords=list(result["include_terms"]),
        arxiv_categories=list(result["categories"]),
        frequency="daily",
        max_results=50,
        is_active=bool(result["is_active"]),
        created_at=str(result["created_at"]),
        updated_at=str(result["updated_at"]),
    )
