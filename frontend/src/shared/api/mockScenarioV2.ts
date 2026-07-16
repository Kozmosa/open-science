import { http, HttpResponse } from 'msw';
import type {
  AdminUserItem,
  CollaboratorItem,
  EnvAccessItem,
  LiteratureCheck,
  LiteraturePaperDetail,
  LiteratureSummary,
  LiteratureTaskIntent,
  LiteratureTopic,
  MessageItem,
  ProjectRecord,
  SearchSettingsResponse,
  SessionDetailRecord,
  TaskCreatePayload,
  TaskEdge,
  TaskRecord,
  TaskStatus,
  WorkspaceRecord,
} from '@/shared/types';
import type {
  DomainCapabilities,
  DomainContextCandidate,
  DomainContextVersion,
  DomainProjectContext,
  DomainProjectMember,
  DomainProjectProjection,
  DomainTaskAttempt,
  DomainWorkspaceProjection,
  OverviewDisplayCard,
  OverviewRefreshJob,
  OverviewSnapshot,
} from '@/features/domain/types';

const OWNER_ID = 'mock-browser-user';
const BASE_TIME = '2026-07-16T08:00:00Z';
const LATER_TIME = '2026-07-16T08:05:00Z';

type Params = Record<string, string | readonly string[] | undefined>;

interface MockRefreshJob {
  job: OverviewRefreshJob;
  poll_count: number;
}

interface MockSummary {
  summary: LiteratureSummary;
  poll_count: number;
}

interface MockIntent {
  intent: LiteratureTaskIntent;
  poll_count: number;
}

interface FrontendV2MockState {
  task_counter: number;
  attempt_counter: number;
  project_counter: number;
  workspace_counter: number;
  context_version_counter: number;
  check_counter: number;
  intent_counter: number;
  projects: DomainProjectProjection[];
  workspaces: DomainWorkspaceProjection[];
  tasks: TaskRecord[];
  attempts: Record<string, DomainTaskAttempt[]>;
  messages: Record<string, MessageItem[]>;
  task_edges: TaskEdge[];
  contexts: Record<string, DomainProjectContext>;
  context_versions: Record<string, DomainContextVersion[]>;
  context_candidates: Record<string, DomainContextCandidate[]>;
  project_members: Record<string, DomainProjectMember[]>;
  topics: LiteratureTopic[];
  papers: LiteraturePaperDetail[];
  summaries: Record<string, MockSummary>;
  checks: LiteratureCheck[];
  check_polls: Record<string, number>;
  intents: Record<string, MockIntent>;
  overview: OverviewSnapshot;
  refresh_jobs: Record<string, MockRefreshJob>;
  sessions: SessionDetailRecord[];
  admin_users: AdminUserItem[];
  collaborators: Record<string, CollaboratorItem[]>;
  environment_access: Record<string, EnvAccessItem[]>;
  search_settings: SearchSettingsResponse;
}

function textParam(params: Params, name: string): string {
  const value = params[name];
  if (typeof value !== 'string') {
    throw new Error(`Missing mock route parameter: ${name}`);
  }
  return value;
}

async function requestJson<T>(request: Request): Promise<T> {
  return await request.json() as T;
}

function notFound(entity: string, id: string): Response {
  return HttpResponse.json({ detail: `${entity} ${id} was not found in the frontend v2 mock scenario` }, { status: 404 });
}

function noContent(): Response {
  return new HttpResponse(null, { status: 204 });
}

function idempotencyKey(request: Request): string {
  return request.headers.get('Idempotency-Key')?.trim() || 'mock-idempotency-key';
}

function makeCapabilities(): DomainCapabilities {
  return {
    domain_contract_version: 2,
    mode: 'synthetic-mock',
    standard_task_create: true,
    project_context: true,
    workspace_links: true,
    task_attempts: true,
    task_dispatcher: {
      participant_type: 'task-dispatcher',
      ready: true,
      maintenance_active: false,
      maintenance_epoch: null,
      stale_after_seconds: 30,
      registered_participant_ids: ['mock-dispatcher'],
      active_participant_ids: ['mock-dispatcher'],
      fresh_participant_ids: ['mock-dispatcher'],
      stale_participant_ids: [],
    },
    literature_research_task: true,
    overview_snapshot: true,
    overview_snapshot_job_store: true,
    overview_snapshot_planner: {
      job_store_ready: true,
      planner_ready: true,
      planner_status: 'ready',
    },
  };
}

function projectPermissions(isDefault: boolean) {
  return {
    can_edit: true,
    can_publish: true,
    can_manage_members: true,
    can_archive: !isDefault,
    can_unarchive: false,
    can_create_task: true,
  };
}

function makeProject(
  projectId: string,
  name: string,
  workspaceId: string,
  workspaceLabel: string,
  isDefault: boolean,
): DomainProjectProjection {
  return {
    project_id: projectId,
    name,
    description: `${name} is seeded by the deterministic frontend mock scenario.`,
    status: 'active',
    is_default: isDefault,
    owner_user_id: OWNER_ID,
    current_user_role: 'owner',
    created_at: BASE_TIME,
    updated_at: BASE_TIME,
    recent_activity_at: LATER_TIME,
    workspace_count: 1,
    executable_workspace_count: 1,
    task_count: 0,
    active_task_count: 0,
    running_task_count: 0,
    primary_workspace: {
      workspace_id: workspaceId,
      label: workspaceLabel,
      canonical_path: `/workspaces/${workspaceId}`,
      environment_id: 'env-localhost',
      environment_alias: 'localhost',
      environment_display_name: 'Localhost',
      is_primary: true,
      can_execute: true,
      cannot_execute_reason: null,
    },
    attention_required: false,
    attention_reasons: [],
    permissions: projectPermissions(isDefault),
  };
}

function makeWorkspace(
  workspaceId: string,
  label: string,
  projectId: string,
  projectName: string,
): DomainWorkspaceProjection {
  return {
    workspace_id: workspaceId,
    label,
    description: `${label} is available for deterministic frontend development.`,
    canonical_path: `/workspaces/${workspaceId}`,
    workspace_context: `Use ${label} for offline frontend interaction checks.`,
    status: 'active',
    owner_user_id: OWNER_ID,
    created_at: BASE_TIME,
    updated_at: BASE_TIME,
    recent_activity_at: LATER_TIME,
    environment: {
      environment_id: 'env-localhost',
      alias: 'localhost',
      display_name: 'Localhost',
      status: 'active',
    },
    project_links: [{
      project_id: projectId,
      project_name: projectName,
      project_status: 'active',
      current_user_role: 'owner',
      link_status: 'active',
      is_primary: true,
      can_execute: true,
      cannot_execute_reason: null,
    }],
    task_count: 0,
    active_task_count: 0,
    can_execute: true,
    cannot_execute_reason: null,
    can_manage_registry: true,
    git_status: {
      state: 'available',
      branch: 'feat/frontend-phases',
      is_dirty: false,
      observed_at: LATER_TIME,
    },
  };
}

function makeTask(
  taskId: string,
  projectId: string,
  workspaceId: string,
  title: string,
  prompt: string,
  status: TaskStatus = 'queued',
): TaskRecord {
  const isFinished = status === 'succeeded' || status === 'failed' || status === 'cancelled';
  return {
    task_id: taskId,
    project_id: projectId,
    workspace_id: workspaceId,
    environment_id: 'env-localhost',
    title,
    status,
    created_at: BASE_TIME,
    updated_at: isFinished ? LATER_TIME : BASE_TIME,
    started_at: status === 'queued' ? null : BASE_TIME,
    completed_at: isFinished ? LATER_TIME : null,
    archived_at: null,
    archive_reason: null,
    project_context_version_id: `context-${projectId}-v1`,
    error_summary: null,
    researcher_type: 'vanilla',
    harness_engine: 'claude-code',
    prompt,
    owner_user_id: OWNER_ID,
    exit_code: status === 'succeeded' ? 0 : null,
    latest_output_seq: 2,
    working_directory: `/workspaces/${workspaceId}`,
    binding: {
      workspace: {
        workspace_id: workspaceId,
        label: workspaceId === 'workspace-default' ? 'Repository Default' : 'Alpha Workspace',
        description: null,
        default_workdir: `/workspaces/${workspaceId}`,
      },
      environment: {
        environment_id: 'env-localhost',
        alias: 'localhost',
        display_name: 'Localhost',
        host: '127.0.0.1',
        default_workdir: `/workspaces/${workspaceId}`,
      },
      task_profile: 'claude-code',
      title,
      task_input: prompt,
      resolved_workdir: `/workspaces/${workspaceId}`,
      snapshot_path: `/mock/snapshots/${taskId}.json`,
      execution_engine: 'claude-code',
    },
    runtime: {
      runner_kind: 'synthetic-mock',
      working_directory: `/workspaces/${workspaceId}`,
      command: ['mock-worker', taskId],
      prompt_file: null,
      helper_path: null,
      launch_payload_path: null,
      codex_home: null,
    },
    result: {
      exit_code: status === 'succeeded' ? 0 : null,
      failure_category: null,
      error_summary: null,
      completed_at: isFinished ? LATER_TIME : null,
    },
  };
}

function makeAttempt(
  taskId: string,
  sequence: number,
  trigger: string,
  status: string,
): DomainTaskAttempt {
  const finished = status === 'succeeded';
  return {
    attempt_id: `attempt-${taskId}-${sequence}`,
    task_id: taskId,
    attempt_seq: sequence,
    trigger,
    status,
    context_snapshot_id: `snapshot-${taskId}-${sequence}`,
    context_version_id: null,
    created_at: BASE_TIME,
    started_at: status === 'queued' ? null : BASE_TIME,
    finished_at: finished ? LATER_TIME : null,
    duration_ms: finished ? 300000 : null,
    token_usage_json: finished ? '{"input_tokens":120,"output_tokens":80}' : null,
    cost_usd: finished ? 0.42 : null,
    failure_reason: null,
    stop_reason: null,
    runtime_sessions: finished ? [{
      runtime_session_id: `runtime-${taskId}-${sequence}`,
      attempt_id: `attempt-${taskId}-${sequence}`,
      status: 'completed',
      engine_name: 'claude-code',
      started_at: BASE_TIME,
      finished_at: LATER_TIME,
    }] : [],
    dispatch: {
      dispatch_id: `dispatch-${taskId}-${sequence}`,
      status: finished ? 'completed' : 'queued',
      launch_state: finished ? 'completed' : 'pending',
    },
  };
}

function makeContextVersion(projectId: string, sequence: number, content: string): DomainContextVersion {
  return {
    context_version_id: `context-${projectId}-v${sequence}`,
    project_id: projectId,
    content,
    fingerprint: `fingerprint-${projectId}-${sequence}`,
    fragment_manifest: [],
    fragment_provenance_status: 'complete',
    fragment_provenance_evidence: { source: 'frontend-v2-mock' },
    assembly_eligible: true,
    is_active: true,
    created_by_user_id: OWNER_ID,
    created_at: sequence === 1 ? BASE_TIME : LATER_TIME,
  };
}

function makeOverviewCards(): OverviewDisplayCard[] {
  return [
    {
      id: 'attention',
      data: { items: [], count: 0 },
      data_cutoff_at: LATER_TIME,
      source_status: 'ok',
      attention_required: false,
      error_summary: null,
    },
    {
      id: 'progress',
      data: { items: [{ task_id: 'task-seed', title: 'Review seeded frontend flow', status: 'succeeded' }] },
      data_cutoff_at: LATER_TIME,
      source_status: 'ok',
      attention_required: false,
      error_summary: null,
    },
    {
      id: 'literature',
      data: { unread_count: 1, updated_count: 1, papers: [{ paper_id: 'paper-transformers', title: 'Deterministic Research Interfaces' }] },
      data_cutoff_at: LATER_TIME,
      source_status: 'ok',
      attention_required: false,
      error_summary: null,
    },
    {
      id: 'continue',
      data: { items: [{ project_id: 'project-alpha', name: 'Alpha Research' }] },
      data_cutoff_at: LATER_TIME,
      source_status: 'ok',
      attention_required: false,
      error_summary: null,
    },
    {
      id: 'resources',
      data: { environment_count: 1, environments: [{ environment_id: 'env-localhost', status: 'ok' }] },
      data_cutoff_at: LATER_TIME,
      source_status: 'ok',
      attention_required: false,
      error_summary: null,
    },
  ];
}

function createState(): FrontendV2MockState {
  const defaultContext = makeContextVersion('default', 1, '# Default Project\n\nStable mock context.');
  const alphaContext = makeContextVersion('project-alpha', 1, '# Alpha Research\n\nInvestigate deterministic interfaces.');
  const paper: LiteraturePaperDetail = {
    paper_id: 'paper-transformers',
    provider: 'arxiv',
    external_id: '2607.00001',
    title: 'Deterministic Research Interfaces',
    authors: ['Ada Example', 'Lin Mock'],
    abstract: 'A fixture paper for exercising the complete Literature frontend flow without external services.',
    primary_category: 'cs.AI',
    categories: ['cs.AI', 'cs.SE'],
    published_at: BASE_TIME,
    updated_at: LATER_TIME,
    source_url: 'https://arxiv.org/abs/2607.00001',
    pdf_url: 'https://arxiv.org/pdf/2607.00001',
    current_version_id: 'paper-transformers-v2',
    matched_topics: [{ topic_id: 'topic-agents', label: 'Research agents', reasons: ['agent workflow'] }],
    user_state: {
      is_read: false,
      is_saved: true,
      is_ignored: false,
      first_seen_at: BASE_TIME,
      last_seen_at: LATER_TIME,
      latest_seen_version_id: 'paper-transformers-v1',
    },
    versions: [
      { version_id: 'paper-transformers-v1', provider_version: 'v1', published_at: BASE_TIME, updated_at: BASE_TIME, first_seen_at: BASE_TIME },
      { version_id: 'paper-transformers-v2', provider_version: 'v2', published_at: BASE_TIME, updated_at: LATER_TIME, first_seen_at: LATER_TIME },
    ],
  };
  const seedTask = makeTask(
    'task-seed',
    'project-alpha',
    'workspace-alpha',
    'Review seeded frontend flow',
    'Review the deterministic frontend fixture and report the result.',
    'succeeded',
  );
  const seedAttempt = makeAttempt('task-seed', 1, 'initial', 'succeeded');
  seedAttempt.context_version_id = alphaContext.context_version_id;
  const displayCards = makeOverviewCards();
  return {
    task_counter: 1,
    attempt_counter: 1,
    project_counter: 1,
    workspace_counter: 1,
    context_version_counter: 1,
    check_counter: 0,
    intent_counter: 0,
    projects: [
      makeProject('default', 'Default Project', 'workspace-default', 'Repository Default', true),
      makeProject('project-alpha', 'Alpha Research', 'workspace-alpha', 'Alpha Workspace', false),
    ],
    workspaces: [
      makeWorkspace('workspace-default', 'Repository Default', 'default', 'Default Project'),
      makeWorkspace('workspace-alpha', 'Alpha Workspace', 'project-alpha', 'Alpha Research'),
    ],
    tasks: [seedTask],
    attempts: { 'task-seed': [seedAttempt] },
    messages: {
      'task-seed': [
        {
          id: 'message-task-seed-1',
          type: 'user',
          content: seedTask.prompt,
          metadata: { timestamp: BASE_TIME, sequence: 1, sourceKind: 'message' },
        },
        {
          id: 'message-task-seed-2',
          type: 'assistant',
          content: 'The deterministic frontend flow is ready for inspection.',
          metadata: { timestamp: LATER_TIME, sequence: 2, sourceKind: 'message' },
        },
      ],
    },
    task_edges: [],
    contexts: {
      default: { project_id: 'default', active_version: defaultContext, draft: null },
      'project-alpha': {
        project_id: 'project-alpha',
        active_version: alphaContext,
        draft: {
          content: `${alphaContext.content}\n\nDraft: validate the complete browser flow.`,
          fingerprint: 'draft-project-alpha-1',
          updated_by_user_id: OWNER_ID,
          updated_at: LATER_TIME,
        },
      },
    },
    context_versions: { default: [defaultContext], 'project-alpha': [alphaContext] },
    context_candidates: {
      default: [],
      'project-alpha': [{
        candidate_id: 'candidate-alpha-1',
        project_id: 'project-alpha',
        content: 'Record browser acceptance evidence after each deterministic scenario.',
        status: 'pending',
        created_at: LATER_TIME,
        created_by_user_id: OWNER_ID,
        source_metadata: { source: 'task-seed' },
        source_task_id: 'task-seed',
        source_attempt_id: 'attempt-task-seed-1',
        accepted_by_user_id: null,
        accepted_at: null,
        rejected_by_user_id: null,
        rejected_at: null,
        rejection_reason: null,
      }],
    },
    project_members: {
      default: [],
      'project-alpha': [{
        user_id: 'mock-editor-user',
        username: 'mock-editor',
        display_name: 'Mock Editor',
        role: 'editor',
        can_publish: true,
      }],
    },
    topics: [{
      topic_id: 'topic-agents',
      user_id: OWNER_ID,
      label: 'Research agents',
      include_terms: ['agent', 'research workflow'],
      exclude_terms: [],
      categories: ['cs.AI'],
      status: 'active',
      is_active: true,
      created_at: BASE_TIME,
      updated_at: LATER_TIME,
      last_matched_at: LATER_TIME,
    }],
    papers: [paper],
    summaries: {
      [paper.paper_id]: {
        summary: { status: 'not_requested', text: null, practice_note: null, error: null, version_id: paper.current_version_id },
        poll_count: 0,
      },
    },
    checks: [],
    check_polls: {},
    intents: {},
    overview: {
      snapshot_id: 'overview-snapshot-1',
      owner_user_id: OWNER_ID,
      snapshot_date: '2026-07-16',
      data_cutoff_at: LATER_TIME,
      source_status: 'ok',
      attention_required: false,
      cards: displayCards,
      display_cards: displayCards,
      next_scheduled_at: '2026-07-17T06:00:00+08:00',
    },
    refresh_jobs: {},
    sessions: [{
      id: 'session-seed',
      project_id: 'project-alpha',
      title: 'Seeded research session',
      status: 'completed',
      task_count: 1,
      total_duration_ms: 300000,
      total_cost_usd: 0.42,
      created_at: BASE_TIME,
      updated_at: LATER_TIME,
      attempts: [{
        id: 'session-attempt-seed',
        session_id: 'session-seed',
        task_id: 'task-seed',
        parent_attempt_id: null,
        attempt_seq: 1,
        intervention_reason: null,
        status: 'completed',
        started_at: BASE_TIME,
        finished_at: LATER_TIME,
        duration_ms: 300000,
        token_usage_json: '{"input_tokens":120,"output_tokens":80}',
        created_at: BASE_TIME,
      }],
    }],
    admin_users: [
      { id: OWNER_ID, username: 'mock-owner', display_name: 'Mock Owner', role: 'member', status: 'active', created_at: BASE_TIME, last_login_at: LATER_TIME, is_online: true },
      { id: 'mock-editor-user', username: 'mock-editor', display_name: 'Mock Editor', role: 'member', status: 'active', created_at: BASE_TIME, last_login_at: BASE_TIME, is_online: false },
    ],
    collaborators: {
      'project-alpha': [{ user_id: 'mock-editor-user', username: 'mock-editor', display_name: 'Mock Editor', role: 'editor' }],
    },
    environment_access: {
      'env-localhost': [{ user_id: OWNER_ID, username: 'mock-owner', display_name: 'Mock Owner', max_concurrent_tasks: 2 }],
    },
    search_settings: {
      active_backend: 'builtin',
      available_backends: [
        { id: 'builtin', display_name: 'Built-in Search', description: 'Deterministic local search fixture.', requires_mcp: false },
        { id: 'exa', display_name: 'Exa MCP', description: 'External MCP-backed search.', requires_mcp: true },
      ],
      auto_start_mcp_servers: [],
    },
  };
}

let state = createState();

export function resetFrontendV2MockState(): void {
  state = createState();
}

function taskById(taskId: string): TaskRecord | undefined {
  return state.tasks.find((task) => task.task_id === taskId);
}

function projectById(projectId: string): DomainProjectProjection | undefined {
  return state.projects.find((project) => project.project_id === projectId);
}

function workspaceById(workspaceId: string): DomainWorkspaceProjection | undefined {
  return state.workspaces.find((workspace) => workspace.workspace_id === workspaceId);
}

function projectWithCounts(project: DomainProjectProjection): DomainProjectProjection {
  const tasks = state.tasks.filter((task) => task.project_id === project.project_id);
  const workspaces = state.workspaces.filter((workspace) => workspace.project_links.some(
    (link) => link.project_id === project.project_id && link.link_status === 'active',
  ));
  return {
    ...project,
    workspace_count: workspaces.length,
    executable_workspace_count: workspaces.filter((workspace) => workspace.can_execute).length,
    task_count: tasks.length,
    active_task_count: tasks.filter((task) => ['queued', 'starting', 'running', 'paused'].includes(task.status)).length,
    running_task_count: tasks.filter((task) => task.status === 'running').length,
  };
}

function workspaceWithCounts(workspace: DomainWorkspaceProjection): DomainWorkspaceProjection {
  const tasks = state.tasks.filter((task) => task.workspace_id === workspace.workspace_id);
  return {
    ...workspace,
    task_count: tasks.length,
    active_task_count: tasks.filter((task) => ['queued', 'starting', 'running', 'paused'].includes(task.status)).length,
  };
}

function legacyProject(project: DomainProjectProjection): ProjectRecord {
  return {
    project_id: project.project_id,
    name: project.name,
    description: project.description,
    default_workspace_id: project.primary_workspace?.workspace_id ?? null,
    default_environment_id: project.primary_workspace?.environment_id ?? null,
    created_at: project.created_at,
    updated_at: project.updated_at,
    owner_user_id: project.owner_user_id,
  };
}

function legacyWorkspace(workspace: DomainWorkspaceProjection): WorkspaceRecord {
  return {
    workspace_id: workspace.workspace_id,
    project_id: workspace.project_links.find((link) => link.link_status === 'active')?.project_id ?? 'default',
    label: workspace.label,
    description: workspace.description,
    default_workdir: workspace.canonical_path,
    workspace_prompt: workspace.workspace_context ?? '',
    created_at: workspace.created_at,
    updated_at: workspace.updated_at,
    owner_user_id: workspace.owner_user_id,
  };
}

function updateTaskStatus(task: TaskRecord, status: TaskStatus): TaskRecord {
  task.status = status;
  task.updated_at = LATER_TIME;
  if (status === 'running') {
    task.started_at ??= LATER_TIME;
    task.completed_at = null;
  }
  if (['succeeded', 'failed', 'cancelled'].includes(status)) {
    task.completed_at = LATER_TIME;
  }
  return task;
}

function currentLiteratureCheck(): LiteratureCheck | null {
  return [...state.checks].reverse().find((check) => ['planned', 'checking', 'partial', 'retrying'].includes(check.status)) ?? null;
}

function literatureOverview() {
  const active = currentLiteratureCheck();
  if (active) {
    state.check_polls[active.check_id] = (state.check_polls[active.check_id] ?? 0) + 1;
    if (state.check_polls[active.check_id] >= 2) completeCheck(active);
  }
  return {
    last_successful_check_at: state.checks.some((check) => check.status === 'completed') ? LATER_TIME : BASE_TIME,
    next_scheduled_check_at: '2026-07-17T06:00:00+08:00',
    active_check: currentLiteratureCheck(),
    counts: {
      today: state.papers.length,
      unread: state.papers.filter((paper) => !paper.user_state.is_read && !paper.user_state.is_ignored).length,
      saved: state.papers.filter((paper) => paper.user_state.is_saved).length,
      updated: state.papers.filter((paper) => paper.current_version_id !== paper.user_state.latest_seen_version_id).length,
    },
  };
}

function completeCheck(check: LiteratureCheck): LiteratureCheck {
  if (check.status === 'checking') {
    check.status = 'completed';
    check.completed_at = LATER_TIME;
    check.next_attempt_at = null;
  }
  return check;
}

function summaryForPaper(paperId: string, advance: boolean): LiteratureSummary | undefined {
  const record = state.summaries[paperId];
  if (!record) return undefined;
  if (advance && record.summary.status === 'queued') {
    record.poll_count += 1;
    record.summary = record.poll_count === 1
      ? { ...record.summary, status: 'generating' }
      : {
          ...record.summary,
          status: 'completed',
          text: 'The paper proposes deterministic contracts that shorten frontend feedback loops.',
          practice_note: 'Use the synthetic API for DevTools flows and MSW only for offline support.',
        };
  } else if (advance && record.summary.status === 'generating') {
    record.poll_count += 1;
    record.summary = {
      ...record.summary,
      status: 'completed',
      text: 'The paper proposes deterministic contracts that shorten frontend feedback loops.',
      practice_note: 'Use the synthetic API for DevTools flows and MSW only for offline support.',
    };
  }
  return record.summary;
}

function advanceIntent(record: MockIntent): LiteratureTaskIntent {
  record.poll_count += 1;
  if (record.intent.status === 'creating_task') {
    record.intent.status = 'completed';
    record.intent.task_id = 'task-seed';
    record.intent.attempt_count = 1;
    record.intent.heartbeat_at = LATER_TIME;
    record.intent.updated_at = LATER_TIME;
    record.intent.completed_at = LATER_TIME;
  }
  return record.intent;
}

function advanceRefreshJob(record: MockRefreshJob): OverviewRefreshJob {
  record.poll_count += 1;
  if (record.poll_count === 1) {
    record.job.status = 'running';
    record.job.started_at = LATER_TIME;
    record.job.heartbeat_at = LATER_TIME;
  } else {
    record.job.status = 'succeeded';
    record.job.snapshot_id = state.overview.snapshot_id;
    record.job.source_status = state.overview.source_status;
    record.job.finished_at = LATER_TIME;
    record.job.heartbeat_at = LATER_TIME;
  }
  return record.job;
}

export const frontendV2MockHandlers = [
  http.get('/api/domain/capabilities', () => HttpResponse.json(makeCapabilities())),

  http.get('/api/domain/projects/:projectId/context/versions/:contextVersionId/diff', ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    const contextVersionId = textParam(params, 'contextVersionId');
    const versions = state.context_versions[projectId];
    if (!versions) return notFound('Project', projectId);
    const after = versions.find((version) => version.context_version_id === contextVersionId);
    const against = new URL(request.url).searchParams.get('against') ?? '';
    const before = versions.find((version) => version.context_version_id === against);
    if (!after) return notFound('Context Version', contextVersionId);
    return HttpResponse.json({
      project_id: projectId,
      before_context_version_id: before?.context_version_id ?? against,
      after_context_version_id: after.context_version_id,
      diff: `--- ${before?.context_version_id ?? against}\n+++ ${after.context_version_id}\n+${after.content}`,
    });
  }),
  http.get('/api/domain/projects/:projectId/context/versions', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const versions = state.context_versions[projectId];
    return versions ? HttpResponse.json({ items: versions }) : notFound('Project', projectId);
  }),
  http.get('/api/domain/projects/:projectId/context/candidates', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const candidates = state.context_candidates[projectId];
    return candidates ? HttpResponse.json({ items: candidates }) : notFound('Project', projectId);
  }),
  http.post('/api/domain/projects/:projectId/context/candidates/:candidateId/accept', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const candidateId = textParam(params, 'candidateId');
    const candidate = state.context_candidates[projectId]?.find((item) => item.candidate_id === candidateId);
    const context = state.contexts[projectId];
    if (!candidate) return notFound('Context Candidate', candidateId);
    if (!context) return notFound('Project', projectId);
    candidate.status = 'accepted';
    candidate.accepted_by_user_id = OWNER_ID;
    candidate.accepted_at = LATER_TIME;
    const previous = context.draft?.content ?? context.active_version?.content ?? '';
    context.draft = {
      content: `${previous}\n\n${candidate.content}`.trim(),
      fingerprint: `draft-${projectId}-accepted-${candidateId}`,
      updated_by_user_id: OWNER_ID,
      updated_at: LATER_TIME,
    };
    return HttpResponse.json(candidate);
  }),
  http.post('/api/domain/projects/:projectId/context/candidates/:candidateId/reject', async ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    const candidateId = textParam(params, 'candidateId');
    const candidate = state.context_candidates[projectId]?.find((item) => item.candidate_id === candidateId);
    if (!candidate) return notFound('Context Candidate', candidateId);
    const payload = await requestJson<{ reason?: string }>(request);
    candidate.status = 'rejected';
    candidate.rejected_by_user_id = OWNER_ID;
    candidate.rejected_at = LATER_TIME;
    candidate.rejection_reason = payload.reason ?? null;
    return HttpResponse.json(candidate);
  }),
  http.get('/api/domain/projects/:projectId/context', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const context = state.contexts[projectId];
    return context ? HttpResponse.json(context) : notFound('Project', projectId);
  }),
  http.put('/api/domain/projects/:projectId/context/draft', async ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    const context = state.contexts[projectId];
    if (!context) return notFound('Project', projectId);
    const payload = await requestJson<{ content: string }>(request);
    context.draft = {
      content: payload.content,
      fingerprint: `draft-${projectId}-${payload.content.length}`,
      updated_by_user_id: OWNER_ID,
      updated_at: LATER_TIME,
    };
    return HttpResponse.json(context);
  }),
  http.post('/api/domain/projects/:projectId/context/publish', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const context = state.contexts[projectId];
    if (!context) return notFound('Project', projectId);
    if (!context.draft) return HttpResponse.json({ detail: 'No draft is available to publish' }, { status: 409 });
    state.context_version_counter += 1;
    for (const version of state.context_versions[projectId] ?? []) version.is_active = false;
    const version = makeContextVersion(projectId, state.context_version_counter, context.draft.content);
    state.context_versions[projectId] = [...(state.context_versions[projectId] ?? []), version];
    context.active_version = version;
    context.draft = null;
    return HttpResponse.json(version);
  }),
  http.get('/api/domain/projects', ({ request }) => {
    const includeArchived = new URL(request.url).searchParams.get('include_archived') === 'true';
    return HttpResponse.json({
      items: state.projects
        .filter((project) => includeArchived || project.status !== 'archived')
        .map(projectWithCounts),
    });
  }),
  http.post('/api/domain/projects', async ({ request }) => {
    const payload = await requestJson<{ name: string; description: string | null }>(request);
    state.project_counter += 1;
    const projectId = `project-mock-${state.project_counter}`;
    const project = makeProject(projectId, payload.name, '', '', false);
    project.description = payload.description;
    project.primary_workspace = null;
    project.workspace_count = 0;
    project.executable_workspace_count = 0;
    project.permissions.can_create_task = false;
    state.projects.push(project);
    const version = makeContextVersion(projectId, 1, `# ${payload.name}`);
    state.contexts[projectId] = { project_id: projectId, active_version: version, draft: null };
    state.context_versions[projectId] = [version];
    state.context_candidates[projectId] = [];
    state.project_members[projectId] = [];
    return HttpResponse.json({ project_id: projectId }, { status: 201 });
  }),
  http.get('/api/domain/projects/:projectId', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const project = projectById(projectId);
    return project ? HttpResponse.json(projectWithCounts(project)) : notFound('Project', projectId);
  }),

  http.get('/api/domain/workspaces', ({ request }) => {
    const includeUnregistered = new URL(request.url).searchParams.get('include_unregistered') === 'true';
    return HttpResponse.json({
      items: state.workspaces
        .filter((workspace) => includeUnregistered || workspace.status !== 'unregistered')
        .map(workspaceWithCounts),
    });
  }),
  http.post('/api/domain/workspaces', async ({ request }) => {
    const payload = await requestJson<{ environment_id: string; canonical_path: string; label: string }>(request);
    state.workspace_counter += 1;
    const workspaceId = `workspace-mock-${state.workspace_counter}`;
    const workspace = makeWorkspace(workspaceId, payload.label, 'default', 'Default Project');
    workspace.canonical_path = payload.canonical_path;
    workspace.environment.environment_id = payload.environment_id;
    workspace.project_links = [];
    state.workspaces.push(workspace);
    return HttpResponse.json({ workspace_id: workspaceId }, { status: 201 });
  }),
  http.get('/api/domain/workspaces/:workspaceId', ({ params }) => {
    const workspaceId = textParam(params, 'workspaceId');
    const workspace = workspaceById(workspaceId);
    return workspace ? HttpResponse.json(workspaceWithCounts(workspace)) : notFound('Workspace', workspaceId);
  }),
  http.post('/api/domain/projects/:projectId/workspaces/:workspaceId', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const workspaceId = textParam(params, 'workspaceId');
    const project = projectById(projectId);
    const workspace = workspaceById(workspaceId);
    if (!project) return notFound('Project', projectId);
    if (!workspace) return notFound('Workspace', workspaceId);
    const existing = workspace.project_links.find((link) => link.project_id === projectId);
    if (existing) existing.link_status = 'active';
    else workspace.project_links.push({
      project_id: projectId,
      project_name: project.name,
      project_status: project.status,
      current_user_role: project.current_user_role,
      link_status: 'active',
      is_primary: false,
      can_execute: workspace.can_execute,
      cannot_execute_reason: workspace.cannot_execute_reason,
    });
    return HttpResponse.json({ project_id: projectId, workspace_id: workspaceId, link_status: 'active' });
  }),
  http.put('/api/domain/projects/:projectId/primary-workspace/:workspaceId', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const workspaceId = textParam(params, 'workspaceId');
    const project = projectById(projectId);
    const workspace = workspaceById(workspaceId);
    if (!project) return notFound('Project', projectId);
    if (!workspace) return notFound('Workspace', workspaceId);
    for (const item of state.workspaces) {
      for (const link of item.project_links) {
        if (link.project_id === projectId) link.is_primary = item.workspace_id === workspaceId;
      }
    }
    project.primary_workspace = {
      workspace_id: workspace.workspace_id,
      label: workspace.label,
      canonical_path: workspace.canonical_path,
      environment_id: workspace.environment.environment_id,
      environment_alias: workspace.environment.alias,
      environment_display_name: workspace.environment.display_name,
      is_primary: true,
      can_execute: workspace.can_execute,
      cannot_execute_reason: workspace.cannot_execute_reason,
    };
    project.permissions.can_create_task = workspace.can_execute;
    return HttpResponse.json({ project_id: projectId, workspace_id: workspaceId, is_primary: true });
  }),

  http.get('/api/domain/tasks/:taskId/context', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    const context = state.contexts[task.project_id]?.active_version;
    return HttpResponse.json({
      context_snapshot_id: `snapshot-${taskId}`,
      context_version_id: task.project_context_version_id ?? context?.context_version_id ?? null,
      fingerprint: context?.fingerprint ?? null,
      content: context?.content ?? '',
      source_manifest: [],
      byte_budget: 65536,
      truncated: false,
      created_at: BASE_TIME,
    });
  }),

  http.get('/api/tasks/token-usage', () => HttpResponse.json({
    task_count: state.tasks.length,
    tasks_with_usage: 1,
    total_tokens: 200,
    total_cost_usd: 0.42,
    total_duration_ms: 300000,
    median_duration_ms: 300000,
    total: { input_tokens: 120, output_tokens: 80, cost_usd: 0.42 },
    by_model: { mock: { input_tokens: 120, output_tokens: 80, cost_usd: 0.42, tokens: 200 } },
    by_engine: { 'claude-code': { task_count: state.tasks.length, tasks_with_usage: 1, tokens: 200, cost_usd: 0.42 } },
    top_tasks: [{ task_id: 'task-seed', title: 'Review seeded frontend flow', status: 'succeeded', harness_engine: 'claude-code', total_tokens: 200, cost_usd: 0.42, duration_ms: 300000 }],
  })),
  http.get('/api/tasks/:taskId/attempts', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    return taskById(taskId) ? HttpResponse.json({ items: state.attempts[taskId] ?? [] }) : notFound('Task', taskId);
  }),
  http.get('/api/tasks/:taskId/messages', ({ params, request }) => {
    const taskId = textParam(params, 'taskId');
    if (!taskById(taskId)) return notFound('Task', taskId);
    const search = new URL(request.url).searchParams;
    const afterSeq = Number(search.get('after_seq') ?? 0);
    const limit = Number(search.get('limit') ?? 100);
    const messages = (state.messages[taskId] ?? [])
      .filter((message) => message.metadata.sequence > afterSeq)
      .slice(0, limit);
    return HttpResponse.json({ messages, has_more: false, next_sequence: messages.at(-1)?.metadata.sequence ?? null });
  }),
  http.get('/api/tasks/:taskId/output', ({ params, request }) => {
    const taskId = textParam(params, 'taskId');
    if (!taskById(taskId)) return notFound('Task', taskId);
    const afterSeq = Number(new URL(request.url).searchParams.get('after_seq') ?? 0);
    const items = (state.messages[taskId] ?? [])
      .filter((message) => message.metadata.sequence > afterSeq)
      .map((message) => ({
        task_id: taskId,
        seq: message.metadata.sequence,
        kind: message.metadata.sourceKind ?? 'message',
        content: typeof message.content === 'string' ? message.content : JSON.stringify(message.content),
        created_at: message.metadata.timestamp,
      }));
    return HttpResponse.json({ items, next_seq: items.at(-1)?.seq ?? afterSeq, has_more: false });
  }),
  http.get('/api/tasks/:taskId/stream', () => new HttpResponse('', {
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
  })),
  http.post('/api/tasks/:taskId/retry', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    const sequence = (state.attempts[taskId]?.length ?? 0) + 1;
    const attempt = makeAttempt(taskId, sequence, 'retry', 'queued');
    state.attempts[taskId] = [...(state.attempts[taskId] ?? []), attempt];
    updateTaskStatus(task, 'queued');
    task.completed_at = null;
    task.exit_code = null;
    return HttpResponse.json({
      new_task: task,
      archived_task_id: null,
      edge_id: `retry-${taskId}-${sequence}`,
      task,
      attempt,
      dispatch: attempt.dispatch,
    });
  }),
  http.post('/api/tasks/:taskId/archive', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    task.archived_at = LATER_TIME;
    task.archive_reason = 'Archived from frontend v2 mock scenario';
    return HttpResponse.json(task);
  }),
  http.post('/api/tasks/:taskId/unarchive', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    task.archived_at = null;
    task.archive_reason = null;
    return HttpResponse.json(task);
  }),
  http.post('/api/tasks/:taskId/cancel', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    return task ? HttpResponse.json(updateTaskStatus(task, 'cancelled')) : notFound('Task', taskId);
  }),
  http.post('/api/tasks/:taskId/pause', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    return task ? HttpResponse.json(updateTaskStatus(task, 'paused')) : notFound('Task', taskId);
  }),
  http.post('/api/tasks/:taskId/resume', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    const sequence = (state.attempts[taskId]?.length ?? 0) + 1;
    state.attempts[taskId] = [...(state.attempts[taskId] ?? []), makeAttempt(taskId, sequence, 'resume', 'running')];
    return HttpResponse.json(updateTaskStatus(task, 'running'));
  }),
  http.post('/api/tasks/:taskId/continue', async ({ params, request }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    const payload = await requestJson<{ prompt: string }>(request);
    const messages = state.messages[taskId] ?? [];
    const sequence = (messages.at(-1)?.metadata.sequence ?? 0) + 1;
    messages.push({
      id: `message-${taskId}-${sequence}`,
      type: 'user',
      content: payload.prompt,
      metadata: { timestamp: LATER_TIME, sequence, sourceKind: 'message' },
    });
    state.messages[taskId] = messages;
    return HttpResponse.json({ task_id: taskId, sequence });
  }),
  http.post('/api/tasks/:taskId/move', async ({ params, request }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    const payload = await requestJson<{ project_id: string; context_version_id: string }>(request);
    if (!projectById(payload.project_id)) return notFound('Project', payload.project_id);
    task.project_id = payload.project_id;
    task.project_context_version_id = payload.context_version_id;
    task.updated_at = LATER_TIME;
    return HttpResponse.json(task);
  }),
  http.post('/api/tasks/:taskId/fork', async ({ params, request }) => {
    const sourceTaskId = textParam(params, 'taskId');
    const source = taskById(sourceTaskId);
    if (!source) return notFound('Task', sourceTaskId);
    const payload = await requestJson<{ workspace_id: string; project_id?: string; prompt?: string; title?: string }>(request);
    if (!workspaceById(payload.workspace_id)) return notFound('Workspace', payload.workspace_id);
    state.task_counter += 1;
    const taskId = `task-mock-${state.task_counter}`;
    const task = makeTask(
      taskId,
      payload.project_id ?? source.project_id,
      payload.workspace_id,
      payload.title ?? `Fork of ${source.title}`,
      payload.prompt ?? source.prompt,
    );
    state.tasks.unshift(task);
    state.attempts[taskId] = [makeAttempt(taskId, 1, 'initial', 'queued')];
    state.messages[taskId] = [{
      id: `message-${taskId}-1`,
      type: 'user',
      content: task.prompt,
      metadata: { timestamp: BASE_TIME, sequence: 1, sourceKind: 'message' },
    }];
    state.task_edges.push({
      edge_id: `edge-${sourceTaskId}-${taskId}`,
      project_id: task.project_id,
      source_task_id: sourceTaskId,
      target_task_id: taskId,
      relationship_type: 'derived_from',
      created_at: LATER_TIME,
    });
    return HttpResponse.json(task, { status: 201 });
  }),
  http.patch('/api/tasks/:taskId/project', async ({ params, request }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    const payload = await requestJson<{ project_id: string }>(request);
    task.project_id = payload.project_id;
    task.updated_at = LATER_TIME;
    return HttpResponse.json(task);
  }),
  http.patch('/api/tasks/:taskId', async ({ params, request }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    if (!task) return notFound('Task', taskId);
    const payload = await requestJson<{ title?: string }>(request);
    if (payload.title) task.title = payload.title;
    task.updated_at = LATER_TIME;
    return HttpResponse.json(task);
  }),
  http.delete('/api/tasks/:taskId/permanent', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    if (!taskById(taskId)) return notFound('Task', taskId);
    state.tasks = state.tasks.filter((task) => task.task_id !== taskId);
    delete state.attempts[taskId];
    delete state.messages[taskId];
    return noContent();
  }),
  http.get('/api/tasks/:taskId', ({ params }) => {
    const taskId = textParam(params, 'taskId');
    const task = taskById(taskId);
    return task ? HttpResponse.json(task) : notFound('Task', taskId);
  }),
  http.get('/api/tasks', ({ request }) => {
    const search = new URL(request.url).searchParams;
    const includeArchived = search.get('include_archived') === 'true';
    const items = state.tasks.filter((task) => includeArchived || !task.archived_at);
    return HttpResponse.json({ items, total: items.length, has_more: false, next_cursor: null });
  }),
  http.post('/api/tasks', async ({ request }) => {
    const payload = await requestJson<TaskCreatePayload>(request);
    const workspace = workspaceById(payload.workspace_id);
    if (!workspace) return notFound('Workspace', payload.workspace_id);
    const project = projectById(payload.project_id);
    if (!project) return notFound('Project', payload.project_id);
    state.task_counter += 1;
    const taskId = `task-mock-${state.task_counter}`;
    const task = makeTask(
      taskId,
      payload.project_id,
      payload.workspace_id,
      payload.title ?? `Mock Task ${state.task_counter}`,
      payload.prompt,
    );
    task.researcher_type = payload.researcher_type;
    task.harness_engine = payload.harness_engine;
    task.project_context_version_id = state.contexts[payload.project_id]?.active_version?.context_version_id ?? null;
    const attempt = makeAttempt(taskId, 1, 'initial', 'queued');
    attempt.context_version_id = task.project_context_version_id ?? null;
    state.tasks.unshift(task);
    state.attempts[taskId] = [attempt];
    state.messages[taskId] = [{
      id: `message-${taskId}-1`,
      type: 'user',
      content: task.prompt,
      metadata: { timestamp: BASE_TIME, sequence: 1, sourceKind: 'message' },
    }];
    return HttpResponse.json(task, { status: 201 });
  }),

  http.get('/api/projects/:projectId/members', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    return projectById(projectId)
      ? HttpResponse.json({ items: state.project_members[projectId] ?? [] })
      : notFound('Project', projectId);
  }),
  http.put('/api/projects/:projectId/members/:userId', async ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    const userId = textParam(params, 'userId');
    if (!projectById(projectId)) return notFound('Project', projectId);
    const payload = await requestJson<{ role: 'viewer' | 'editor'; can_publish: boolean }>(request);
    const user = state.admin_users.find((item) => item.id === userId);
    const member: DomainProjectMember = {
      user_id: userId,
      username: user?.username ?? userId,
      display_name: user?.display_name ?? userId,
      role: payload.role,
      can_publish: payload.can_publish,
    };
    const members = state.project_members[projectId] ?? [];
    state.project_members[projectId] = [...members.filter((item) => item.user_id !== userId), member];
    return HttpResponse.json(member);
  }),
  http.delete('/api/projects/:projectId/members/:userId', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const userId = textParam(params, 'userId');
    if (!projectById(projectId)) return notFound('Project', projectId);
    state.project_members[projectId] = (state.project_members[projectId] ?? []).filter((item) => item.user_id !== userId);
    return noContent();
  }),
  http.post('/api/projects/:projectId/archive', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const project = projectById(projectId);
    if (!project) return notFound('Project', projectId);
    if (project.is_default) return HttpResponse.json({ detail: 'The default Project cannot be archived' }, { status: 409 });
    project.status = 'archived';
    project.permissions = { ...project.permissions, can_archive: false, can_unarchive: true, can_create_task: false };
    return noContent();
  }),
  http.post('/api/projects/:projectId/unarchive', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const project = projectById(projectId);
    if (!project) return notFound('Project', projectId);
    project.status = 'active';
    project.permissions = { ...project.permissions, can_archive: !project.is_default, can_unarchive: false, can_create_task: Boolean(project.primary_workspace?.can_execute) };
    return noContent();
  }),
  http.delete('/api/projects/:projectId/workspaces/:workspaceId', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const workspaceId = textParam(params, 'workspaceId');
    const workspace = workspaceById(workspaceId);
    const project = projectById(projectId);
    if (!project) return notFound('Project', projectId);
    if (!workspace) return notFound('Workspace', workspaceId);
    workspace.project_links = workspace.project_links.filter((link) => link.project_id !== projectId);
    if (project.primary_workspace?.workspace_id === workspaceId) project.primary_workspace = null;
    project.permissions.can_create_task = Boolean(project.primary_workspace?.can_execute);
    return noContent();
  }),
  http.put('/api/projects/:projectId/primary-workspace/:workspaceId', ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    const workspaceId = textParam(params, 'workspaceId');
    const project = projectById(projectId);
    const workspace = workspaceById(workspaceId);
    if (!project) return notFound('Project', projectId);
    if (!workspace) return notFound('Workspace', workspaceId);
    project.primary_workspace = {
      workspace_id: workspace.workspace_id,
      label: workspace.label,
      canonical_path: workspace.canonical_path,
      environment_id: workspace.environment.environment_id,
      environment_alias: workspace.environment.alias,
      environment_display_name: workspace.environment.display_name,
      is_primary: true,
      can_execute: workspace.can_execute,
      cannot_execute_reason: workspace.cannot_execute_reason,
    };
    return HttpResponse.json({
      project_id: projectId,
      workspace_id: workspaceId,
      previous_workspace_id: new URL(request.url).searchParams.get('previous_workspace_id'),
    });
  }),
  http.get('/api/projects/:projectId/tasks', ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    if (!projectById(projectId)) return notFound('Project', projectId);
    const includeArchived = new URL(request.url).searchParams.get('include_archived') === 'true';
    const items = state.tasks.filter((task) => task.project_id === projectId && (includeArchived || !task.archived_at));
    return HttpResponse.json({ items, total: items.length, has_more: false, next_cursor: null });
  }),
  http.get('/api/projects/:projectId/task-edges', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    return projectById(projectId)
      ? HttpResponse.json({ items: state.task_edges.filter((edge) => edge.project_id === projectId) })
      : notFound('Project', projectId);
  }),
  http.post('/api/projects/:projectId/task-edges', async ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    if (!projectById(projectId)) return notFound('Project', projectId);
    const payload = await requestJson<{ source_task_id: string; target_task_id: string; relationship_type?: string }>(request);
    const edge: TaskEdge = {
      edge_id: `edge-${state.task_edges.length + 1}`,
      project_id: projectId,
      source_task_id: payload.source_task_id,
      target_task_id: payload.target_task_id,
      relationship_type: payload.relationship_type ?? 'related_to',
      created_at: LATER_TIME,
    };
    state.task_edges.push(edge);
    return HttpResponse.json(edge, { status: 201 });
  }),
  http.delete('/api/task-edges/:edgeId', ({ params }) => {
    const edgeId = textParam(params, 'edgeId');
    state.task_edges = state.task_edges.filter((edge) => edge.edge_id !== edgeId);
    return noContent();
  }),
  http.get('/api/projects', () => HttpResponse.json({ items: state.projects.map((project) => legacyProject(projectWithCounts(project))) })),
  http.patch('/api/projects/:projectId', async ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    const project = projectById(projectId);
    if (!project) return notFound('Project', projectId);
    const payload = await requestJson<{ name?: string | null; description?: string | null }>(request);
    if (payload.name) project.name = payload.name;
    if (payload.description !== undefined) project.description = payload.description;
    project.updated_at = LATER_TIME;
    return HttpResponse.json(legacyProject(project));
  }),
  http.get('/api/projects/:projectId', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const project = projectById(projectId);
    return project ? HttpResponse.json(legacyProject(projectWithCounts(project))) : notFound('Project', projectId);
  }),

  http.post('/api/workspaces/:workspaceId/unregister', ({ params }) => {
    const workspaceId = textParam(params, 'workspaceId');
    const workspace = workspaceById(workspaceId);
    if (!workspace) return notFound('Workspace', workspaceId);
    workspace.status = 'unregistered';
    workspace.can_execute = false;
    workspace.cannot_execute_reason = 'Workspace is unregistered';
    return noContent();
  }),
  http.get('/api/workspaces', () => HttpResponse.json({ items: state.workspaces.map((workspace) => legacyWorkspace(workspaceWithCounts(workspace))) })),
  http.get('/api/workspaces/:workspaceId', ({ params }) => {
    const workspaceId = textParam(params, 'workspaceId');
    const workspace = workspaceById(workspaceId);
    return workspace ? HttpResponse.json(legacyWorkspace(workspaceWithCounts(workspace))) : notFound('Workspace', workspaceId);
  }),

  http.get('/api/literature/overview', () => HttpResponse.json(literatureOverview())),
  http.get('/api/literature/topics', () => HttpResponse.json({ items: state.topics })),
  http.post('/api/literature/topics', async ({ request }) => {
    const payload = await requestJson<{ label: string; include_terms: string[]; exclude_terms: string[]; categories: string[] }>(request);
    const topic: LiteratureTopic = {
      topic_id: `topic-mock-${state.topics.length + 1}`,
      user_id: OWNER_ID,
      ...payload,
      status: 'active',
      is_active: true,
      created_at: LATER_TIME,
      updated_at: LATER_TIME,
      last_matched_at: null,
    };
    state.topics.push(topic);
    return HttpResponse.json(topic, { status: 201 });
  }),
  http.post('/api/literature/topics/preview', () => HttpResponse.json({
    matched_count: state.papers.length,
    samples: state.papers.map(({ paper_id, title, primary_category }) => ({ paper_id, title, primary_category })),
    local_coverage: { paper_count: state.papers.length, complete: true },
    needs_check: false,
  })),
  http.patch('/api/literature/topics/:topicId', async ({ params, request }) => {
    const topicId = textParam(params, 'topicId');
    const topic = state.topics.find((item) => item.topic_id === topicId);
    if (!topic) return notFound('Literature Topic', topicId);
    Object.assign(topic, await requestJson<Partial<LiteratureTopic>>(request), { updated_at: LATER_TIME });
    return HttpResponse.json(topic);
  }),
  http.delete('/api/literature/topics/:topicId', ({ params }) => {
    const topicId = textParam(params, 'topicId');
    state.topics = state.topics.filter((topic) => topic.topic_id !== topicId);
    return noContent();
  }),
  http.get('/api/literature/papers/:paperId/summary', ({ params }) => {
    const paperId = textParam(params, 'paperId');
    const summary = summaryForPaper(paperId, true);
    return summary ? HttpResponse.json(summary) : notFound('Literature Paper', paperId);
  }),
  http.post('/api/literature/papers/:paperId/summary', ({ params }) => {
    const paperId = textParam(params, 'paperId');
    if (!state.papers.some((paper) => paper.paper_id === paperId)) return notFound('Literature Paper', paperId);
    const summary: LiteratureSummary = {
      summary_id: `summary-${paperId}`,
      status: 'queued',
      text: null,
      practice_note: null,
      error: null,
      version_id: state.papers.find((paper) => paper.paper_id === paperId)?.current_version_id ?? null,
    };
    state.summaries[paperId] = { summary, poll_count: 0 };
    return HttpResponse.json(summary, { status: 202 });
  }),
  http.patch('/api/literature/papers/:paperId/state', async ({ params, request }) => {
    const paperId = textParam(params, 'paperId');
    const paper = state.papers.find((item) => item.paper_id === paperId);
    if (!paper) return notFound('Literature Paper', paperId);
    Object.assign(paper.user_state, await requestJson<Partial<LiteraturePaperDetail['user_state']>>(request), { last_seen_at: LATER_TIME });
    return HttpResponse.json(paper);
  }),
  http.post('/api/literature/papers/:paperId/research-task', async ({ params, request }) => {
    const paperId = textParam(params, 'paperId');
    const paper = state.papers.find((item) => item.paper_id === paperId);
    if (!paper) return notFound('Literature Paper', paperId);
    const key = idempotencyKey(request);
    const existing = state.intents[key];
    if (existing) return HttpResponse.json(existing.intent);
    const payload = await requestJson<{ project_id: string; workspace_id: string; task_preset: string; title?: string }>(request);
    state.intent_counter += 1;
    const intent: LiteratureTaskIntent = {
      intent_id: `intent-mock-${state.intent_counter}`,
      paper_id: paperId,
      project_id: payload.project_id,
      workspace_id: payload.workspace_id,
      task_preset: payload.task_preset,
      title: payload.title ?? `Research: ${paper.title}`,
      task_id: null,
      status: 'creating_task',
      idempotency_key: key,
      work_item_id: `literature-work-${state.intent_counter}`,
      attempt_count: 0,
      last_error: null,
      next_retry_at: null,
      heartbeat_at: BASE_TIME,
      created_at: BASE_TIME,
      updated_at: BASE_TIME,
      completed_at: null,
    };
    state.intents[key] = { intent, poll_count: 0 };
    return HttpResponse.json(intent, { status: 202 });
  }),
  http.get('/api/literature/papers/:paperId/research-task', ({ params, request }) => {
    const paperId = textParam(params, 'paperId');
    const key = new URL(request.url).searchParams.get('idempotency_key') ?? '';
    const record = state.intents[key];
    return record && record.intent.paper_id === paperId
      ? HttpResponse.json(advanceIntent(record))
      : notFound('Literature Research Task Intent', key);
  }),
  http.get('/api/literature/papers/:paperId/research-tasks', ({ params }) => {
    const paperId = textParam(params, 'paperId');
    return HttpResponse.json({
      items: Object.values(state.intents)
        .filter((record) => record.intent.paper_id === paperId)
        .map((record) => record.intent),
    });
  }),
  http.get('/api/literature/papers/:paperId', ({ params }) => {
    const paperId = textParam(params, 'paperId');
    const paper = state.papers.find((item) => item.paper_id === paperId);
    return paper ? HttpResponse.json(paper) : notFound('Literature Paper', paperId);
  }),
  http.get('/api/literature/papers', ({ request }) => {
    const search = new URL(request.url).searchParams;
    const view = search.get('view') ?? 'today';
    const topicId = search.get('topic_id');
    const category = search.get('category');
    const items = state.papers.filter((paper) => {
      if (view === 'unread' && paper.user_state.is_read) return false;
      if (view === 'saved' && !paper.user_state.is_saved) return false;
      if (view === 'updated' && paper.current_version_id === paper.user_state.latest_seen_version_id) return false;
      if (topicId && !paper.matched_topics.some((topic) => topic.topic_id === topicId)) return false;
      if (category && !paper.categories.includes(category)) return false;
      return !paper.user_state.is_ignored;
    });
    return HttpResponse.json({ items, next_cursor: null, total: items.length });
  }),
  http.post('/api/literature/checks', ({ request }) => {
    const key = idempotencyKey(request);
    const existing = state.checks.find((check) => check.trigger === key);
    if (existing) return HttpResponse.json(existing);
    state.check_counter += 1;
    const check: LiteratureCheck = {
      check_id: `check-mock-${state.check_counter}`,
      status: 'checking',
      trigger: key,
      window_start: BASE_TIME,
      window_end: LATER_TIME,
      created_at: BASE_TIME,
      started_at: BASE_TIME,
      completed_at: null,
      next_attempt_at: null,
      error: null,
    };
    state.checks.push(check);
    state.check_polls[check.check_id] = 0;
    return HttpResponse.json(check, { status: 202 });
  }),
  http.get('/api/literature/checks/current', () => {
    const check = currentLiteratureCheck();
    return check ? HttpResponse.json(check) : HttpResponse.json(null);
  }),
  http.get('/api/literature/checks/:checkId', ({ params }) => {
    const checkId = textParam(params, 'checkId');
    const check = state.checks.find((item) => item.check_id === checkId);
    return check ? HttpResponse.json(completeCheck(check)) : notFound('Literature Check', checkId);
  }),
  http.get('/api/literature/checks', () => HttpResponse.json({ items: state.checks })),

  http.post('/api/domain/overview/today/refresh', ({ request }) => {
    const key = idempotencyKey(request);
    const jobId = `overview-refresh-${key.replace(/[^a-zA-Z0-9_-]/g, '-').slice(-40)}`;
    const existing = state.refresh_jobs[jobId];
    if (existing) return HttpResponse.json(existing.job);
    const job: OverviewRefreshJob = {
      job_id: jobId,
      owner_user_id: OWNER_ID,
      trigger: 'manual',
      scheduled_for_date: '2026-07-16',
      status: 'queued',
      attempt_count: 0,
      retry_count: 0,
      next_retry_at: null,
      last_failure_at: null,
      snapshot_id: null,
      source_status: null,
      error_summary: null,
      created_at: BASE_TIME,
      started_at: null,
      finished_at: null,
      heartbeat_at: null,
    };
    state.refresh_jobs[jobId] = { job, poll_count: 0 };
    return HttpResponse.json(job, { status: 202 });
  }),
  http.get('/api/domain/overview/refresh/:jobId', ({ params }) => {
    const jobId = textParam(params, 'jobId');
    const record = state.refresh_jobs[jobId];
    return record ? HttpResponse.json(advanceRefreshJob(record)) : notFound('Overview Refresh Job', jobId);
  }),
  http.get('/api/domain/overview/today', () => HttpResponse.json(state.overview)),

  http.get('/api/sessions/batch-detail', ({ request }) => {
    const ids = (new URL(request.url).searchParams.get('ids') ?? '').split(',').filter(Boolean);
    return HttpResponse.json({
      items: Object.fromEntries(ids.map((id) => [id, state.sessions.find((session) => session.id === id)?.attempts ?? []])),
    });
  }),
  http.get('/api/sessions', () => HttpResponse.json({
    items: state.sessions.map(({ attempts, ...session }) => {
      void attempts;
      return session;
    }),
    total: state.sessions.length,
    has_more: false,
    next_cursor: null,
  })),
  http.get('/api/sessions/:sessionId', ({ params }) => {
    const sessionId = textParam(params, 'sessionId');
    const session = state.sessions.find((item) => item.id === sessionId);
    return session ? HttpResponse.json(session) : notFound('Session', sessionId);
  }),
  http.get('/api/sessions/:sessionId/attempts', ({ params }) => {
    const sessionId = textParam(params, 'sessionId');
    const session = state.sessions.find((item) => item.id === sessionId);
    return session ? HttpResponse.json({ items: session.attempts }) : notFound('Session', sessionId);
  }),

  http.get('/api/admin/users', () => HttpResponse.json({ items: state.admin_users })),
  http.patch('/api/admin/users/:userId', async ({ params, request }) => {
    const userId = textParam(params, 'userId');
    const user = state.admin_users.find((item) => item.id === userId);
    if (!user) return notFound('User', userId);
    Object.assign(user, await requestJson<{ status?: string | null }>(request));
    return HttpResponse.json(user);
  }),
  http.put('/api/admin/users/:userId/password', ({ params }) => {
    const userId = textParam(params, 'userId');
    return state.admin_users.some((item) => item.id === userId) ? noContent() : notFound('User', userId);
  }),
  http.get('/api/projects/:projectId/collaborators', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    return HttpResponse.json({ items: state.collaborators[projectId] ?? [] });
  }),
  http.put('/api/projects/:projectId/collaborators', async ({ params, request }) => {
    const projectId = textParam(params, 'projectId');
    const payload = await requestJson<{ user_id: string; role: string }>(request);
    const user = state.admin_users.find((item) => item.id === payload.user_id);
    const collaborator: CollaboratorItem = {
      user_id: payload.user_id,
      username: user?.username ?? payload.user_id,
      display_name: user?.display_name ?? payload.user_id,
      role: payload.role,
    };
    state.collaborators[projectId] = [
      ...(state.collaborators[projectId] ?? []).filter((item) => item.user_id !== payload.user_id),
      collaborator,
    ];
    return HttpResponse.json(collaborator);
  }),
  http.delete('/api/projects/:projectId/collaborators/:userId', ({ params }) => {
    const projectId = textParam(params, 'projectId');
    const userId = textParam(params, 'userId');
    state.collaborators[projectId] = (state.collaborators[projectId] ?? []).filter((item) => item.user_id !== userId);
    return noContent();
  }),
  http.get('/api/admin/environments/:environmentId/access', ({ params }) => {
    const environmentId = textParam(params, 'environmentId');
    return HttpResponse.json({ items: state.environment_access[environmentId] ?? [] });
  }),
  http.put('/api/admin/environments/:environmentId/access', async ({ params, request }) => {
    const environmentId = textParam(params, 'environmentId');
    const payload = await requestJson<{ user_id: string; max_concurrent_tasks: number | null }>(request);
    const user = state.admin_users.find((item) => item.id === payload.user_id);
    const access: EnvAccessItem = {
      user_id: payload.user_id,
      username: user?.username ?? payload.user_id,
      display_name: user?.display_name ?? payload.user_id,
      max_concurrent_tasks: payload.max_concurrent_tasks,
    };
    state.environment_access[environmentId] = [
      ...(state.environment_access[environmentId] ?? []).filter((item) => item.user_id !== payload.user_id),
      access,
    ];
    return HttpResponse.json(access);
  }),
  http.delete('/api/admin/environments/:environmentId/access/:userId', ({ params }) => {
    const environmentId = textParam(params, 'environmentId');
    const userId = textParam(params, 'userId');
    state.environment_access[environmentId] = (state.environment_access[environmentId] ?? []).filter((item) => item.user_id !== userId);
    return noContent();
  }),
  http.get('/api/settings/search', () => HttpResponse.json(state.search_settings)),
  http.patch('/api/settings/search', async ({ request }) => {
    Object.assign(state.search_settings, await requestJson<Partial<SearchSettingsResponse>>(request));
    return HttpResponse.json(state.search_settings);
  }),
  http.post('/api/client-logs', () => noContent()),
  http.post('/api/client-metrics', () => noContent()),
];
