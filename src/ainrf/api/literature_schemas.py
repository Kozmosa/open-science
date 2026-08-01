"""Authoritative Literature HTTP transport Interface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LiteratureTransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


LiteratureCheckStatus = Literal["planned", "checking", "partial", "completed", "retrying", "failed"]
LiteratureSummaryStatus = Literal[
    "not_requested", "queued", "generating", "completed", "stale", "failed"
]
LiteratureTopicStatus = Literal["pending_first_check", "active", "paused", "attention_needed"]


class LiteratureTopicRequest(LiteratureTransportModel):
    label: str = Field(min_length=1)
    include_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    categories: list[str] = Field(min_length=1)


class LiteratureTopicUpdateRequest(LiteratureTransportModel):
    label: str | None = Field(default=None, min_length=1)
    include_terms: list[str] | None = None
    exclude_terms: list[str] | None = None
    categories: list[str] | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class LiteratureTopicResponse(LiteratureTransportModel):
    topic_id: str
    user_id: str
    label: str
    include_terms: list[str]
    exclude_terms: list[str]
    categories: list[str]
    status: LiteratureTopicStatus
    is_active: bool
    created_at: str
    updated_at: str
    last_matched_at: str | None


class LiteratureTopicListResponse(LiteratureTransportModel):
    items: list[LiteratureTopicResponse]
    total: int
    next_cursor: str | None = None


class LiteratureTopicPreviewSample(LiteratureTransportModel):
    paper_id: str
    title: str
    primary_category: str


class LiteratureLocalCoverage(LiteratureTransportModel):
    paper_count: int
    complete: bool


class LiteratureTopicPreviewResponse(LiteratureTransportModel):
    matched_count: int
    samples: list[LiteratureTopicPreviewSample]
    local_coverage: LiteratureLocalCoverage
    needs_check: bool


class LiteratureCheckRequest(LiteratureTransportModel):
    topic_ids: list[str] | None = None


class LiteratureCheckResponse(LiteratureTransportModel):
    check_id: str
    status: LiteratureCheckStatus
    trigger: str
    window_start: str | None
    window_end: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    next_attempt_at: str | None
    error: str | None


class LiteratureCheckListResponse(LiteratureTransportModel):
    items: list[LiteratureCheckResponse]
    total: int
    next_cursor: str | None = None


class LiteratureOverviewCounts(LiteratureTransportModel):
    today: int
    unread: int
    saved: int
    updated: int


class LiteratureOverviewResponse(LiteratureTransportModel):
    last_successful_check_at: str | None
    next_scheduled_check_at: str | None
    active_check: LiteratureCheckResponse | None
    counts: LiteratureOverviewCounts


class LiteratureTopicMatchResponse(LiteratureTransportModel):
    topic_id: str
    label: str
    reasons: list[str]


class LiteratureUserPaperStateResponse(LiteratureTransportModel):
    is_read: bool
    is_saved: bool
    is_ignored: bool
    first_seen_at: str
    last_seen_at: str
    latest_seen_version_id: str | None


class LiteraturePaperResponse(LiteratureTransportModel):
    paper_id: str
    provider: str
    external_id: str
    title: str
    authors: list[str]
    abstract: str
    primary_category: str
    categories: list[str]
    published_at: str | None
    updated_at: str | None
    source_url: str
    pdf_url: str
    current_version_id: str | None
    matched_topics: list[LiteratureTopicMatchResponse]
    user_state: LiteratureUserPaperStateResponse


class LiteraturePaperVersionResponse(LiteratureTransportModel):
    version_id: str
    provider_version: str
    published_at: str | None
    updated_at: str | None
    first_seen_at: str


class LiteraturePaperDetailResponse(LiteraturePaperResponse):
    versions: list[LiteraturePaperVersionResponse]


class LiteraturePaperListResponse(LiteratureTransportModel):
    items: list[LiteraturePaperResponse]
    total: int
    next_cursor: str | None


class LiteraturePaperVersionListResponse(LiteratureTransportModel):
    items: list[LiteraturePaperVersionResponse]
    total: int
    next_cursor: str | None = None


class LiteraturePaperStateRequest(LiteratureTransportModel):
    is_read: bool | None = None
    is_saved: bool | None = None
    is_ignored: bool | None = None


class LiteratureSummaryRequest(LiteratureTransportModel):
    language: str = Field(default="zh", min_length=1)


class LiteratureSummaryResponse(LiteratureTransportModel):
    summary_id: str | None = None
    status: LiteratureSummaryStatus
    text: str | None = None
    practice_note: str | None = None
    error: str | None = None
    version_id: str | None = None


class LiteratureResearchTaskRequest(LiteratureTransportModel):
    project_id: str = Field(min_length=1)
    workspace_id: str | None = None
    task_preset: str = Field(default="structured-research-default", min_length=1)
    title: str | None = None


class LiteratureResearchTaskResponse(LiteratureTransportModel):
    intent_id: str
    paper_id: str
    project_id: str
    workspace_id: str
    task_preset: str
    title: str
    task_id: str | None
    status: str
    idempotency_key: str
    work_item_id: str
    attempt_count: int
    last_error: str | None
    next_retry_at: str | None
    heartbeat_at: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


class LiteratureResearchTaskListResponse(LiteratureTransportModel):
    items: list[LiteratureResearchTaskResponse]
    total: int
    next_cursor: str | None = None


class LegacyLiteratureSubscriptionRequest(LiteratureTransportModel):
    label: str = ""
    keywords: list[str] = Field(default_factory=list)
    arxiv_categories: list[str] = Field(default_factory=list)
    frequency: str = "daily"
    max_results: int = Field(default=50, ge=1, le=100)


class LegacyLiteratureSubscriptionUpdateRequest(LiteratureTransportModel):
    label: str | None = None
    keywords: list[str] | None = None
    arxiv_categories: list[str] | None = None
    frequency: str | None = None
    max_results: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None


class LegacyLiteratureSubscriptionResponse(LiteratureTransportModel):
    subscription_id: str
    user_id: str
    label: str
    keywords: list[str]
    arxiv_categories: list[str]
    frequency: str
    max_results: int
    is_active: bool
    created_at: str
    updated_at: str


class LegacyLiteratureSubscriptionListResponse(LiteratureTransportModel):
    items: list[LegacyLiteratureSubscriptionResponse]


class LegacyLiteratureFetchStatusResponse(LiteratureTransportModel):
    status: str
    error: str | None


class LegacyLiteratureFetchResponse(LiteratureTransportModel):
    status: Literal["fetch_started"]
    subscription_id: str
    check_id: str


class LegacyLiteratureReadRequest(LiteratureTransportModel):
    subscription_id: str | None = None
