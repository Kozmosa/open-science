export type LiteratureInboxView =
  "today" | "unread" | "saved" | "updated" | "all";
export type LiteratureCheckStatus =
  "planned" | "checking" | "partial" | "completed" | "retrying" | "failed";
export type LiteratureSummaryStatus =
  "not_requested" | "queued" | "generating" | "completed" | "stale" | "failed";

export interface LiteratureTopic {
  topic_id: string;
  user_id: string;
  label: string;
  include_terms: string[];
  exclude_terms: string[];
  categories: string[];
  status: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_matched_at: string | null;
}
export interface LiteratureTopicInput {
  label: string;
  include_terms: string[];
  exclude_terms: string[];
  categories: string[];
}
export interface LiteratureTopicPreview {
  matched_count: number;
  samples: Array<{ paper_id: string; title: string; primary_category: string }>;
  local_coverage: { paper_count: number; complete: boolean };
  needs_check: boolean;
}
export interface LiteratureCheck {
  check_id: string;
  status: LiteratureCheckStatus;
  trigger: string;
  window_start: string | null;
  window_end: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  next_attempt_at: string | null;
  error: string | null;
}
export interface LiteratureOverview {
  last_successful_check_at: string | null;
  next_scheduled_check_at: string | null;
  active_check: LiteratureCheck | null;
  counts: { today: number; unread: number; saved: number; updated: number };
}
export interface LiteratureTopicMatch {
  topic_id: string;
  label: string;
  reasons: string[];
}
export interface LiteratureUserPaperState {
  is_read: boolean;
  is_saved: boolean;
  is_ignored: boolean;
  first_seen_at: string;
  last_seen_at: string;
  latest_seen_version_id: string | null;
}
export interface LiteraturePaperListItem {
  paper_id: string;
  provider: string;
  external_id: string;
  title: string;
  authors: string[];
  abstract: string;
  primary_category: string;
  categories: string[];
  published_at: string | null;
  updated_at: string | null;
  source_url: string;
  pdf_url: string;
  current_version_id: string | null;
  matched_topics: LiteratureTopicMatch[];
  user_state: LiteratureUserPaperState;
}
export interface LiteraturePaperVersion {
  version_id: string;
  provider_version: string;
  published_at: string | null;
  updated_at: string | null;
  first_seen_at: string;
}
export interface LiteraturePaperDetail extends LiteraturePaperListItem {
  versions: LiteraturePaperVersion[];
}
export interface LiteraturePaperListParams {
  view?: LiteratureInboxView;
  topic_id?: string;
  category?: string;
  summary_status?: LiteratureSummaryStatus;
  has_research_task?: boolean;
  cursor?: string;
  limit?: number;
}
export interface LiteraturePaperListResponse {
  items: LiteraturePaperListItem[];
  next_cursor: string | null;
  total: number;
}
export interface LiteratureSummary {
  summary_id?: string | null;
  status: LiteratureSummaryStatus;
  text?: string | null;
  practice_note?: string | null;
  error?: string | null;
  version_id?: string | null;
}
export interface LiteratureTaskIntent {
  intent_id: string;
  paper_id: string;
  project_id: string;
  workspace_id: string;
  task_preset: string;
  title: string;
  task_id: string | null;
  status: string;
  idempotency_key: string;
  work_item_id: string;
  attempt_count: number;
  last_error: string | null;
  next_retry_at: string | null;
  heartbeat_at: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}
export interface LiteratureList<T> {
  items: T[];
  total: number;
  next_cursor: string | null;
}
