import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TasksPage from '../../src/pages/TasksPage';
import { createTestQueryClient, renderWithProviders } from '@/shared/test/render';
import type {
  EnvironmentRecord,
  TaskOutputEvent,
  TaskOutputListResponse,
  SkillItem,
  TaskRecord,
  TaskSummary,
  WorkspaceRecord,
} from '@/shared/types';
import {
  buildTaskStreamUrl,
  createTask,
  getCodexDefaults,
  getEnvironments,
  getProjectEnvironmentReferences,
  getProjects,
  getSkills,
  getTask,
  getTaskMessages,
  getTaskOutput,
  getTasks,
  getWorkspaces,
} from '@/shared/api';
import { convertOutputEventToMessage, mergeMessages } from '@/features/tasks/hooks/useTaskMessages';
import { getNextOutputSeq, mergeOutputItems } from '@features/tasks/utils/output';

class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
}

function stubTaskViewport(narrow: boolean): void {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    matches: query === '(max-width: 767px)' ? narrow : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia);
}

const project = {
  project_id: 'default',
  name: 'Default Project',
  description: '',
  default_workspace_id: 'workspace-default',
  default_environment_id: 'env-1',
  created_at: '2026-04-23T08:00:00Z',
  updated_at: '2026-04-23T08:00:00Z',
};

const workspace: WorkspaceRecord = {
  workspace_id: 'workspace-default',
  project_id: 'default',
  label: 'Repository Default',
  description: 'Seed workspace',
  default_workdir: '/workspace/project',
  workspace_prompt: 'Treat this workspace as the default repository context.',
  created_at: '2026-04-23T08:00:00Z',
  updated_at: '2026-04-23T08:00:00Z',
};

const environment: EnvironmentRecord = {
  id: 'env-1',
  alias: 'gpu-lab',
  display_name: 'GPU Lab',
  description: null,
  is_seed: false,
  tags: [],
  host: 'gpu.example.com',
  port: 22,
  user: 'root',
  auth_kind: 'ssh_key',
  identity_file: null,
  proxy_jump: null,
  proxy_command: null,
  ssh_options: {},
  default_workdir: '/workspace/project',
  preferred_python: null,
  preferred_env_manager: null,
  preferred_runtime_notes: null,
  task_harness_profile: 'Use the configured GPU environment.',
  created_at: '2026-04-23T08:00:00Z',
  updated_at: '2026-04-23T08:00:00Z',
  code_server_path: null,
  latest_detection: null,
};

const availableSkills: SkillItem[] = [
  {
    skill_id: 'analysis',
    label: 'Analysis',
    description: 'Analyze the task context before acting.',
    inject_mode: 'auto',
    dependencies: [],
    package: 'research',
  },
  {
    skill_id: 'code-review',
    label: 'Code Review',
    description: 'Review code changes before completion.',
    inject_mode: 'auto',
    dependencies: [],
    package: 'research',
  },
  {
    skill_id: 'docs',
    label: 'Docs',
    description: 'Update documentation where needed.',
    inject_mode: 'prompt_only',
    dependencies: [],
  },
];

const taskSummary: TaskSummary = {
  task_id: 'task-1',
  project_id: 'default',
  workspace_id: workspace.workspace_id,
  environment_id: environment.id,
  title: 'Train model',
  task_profile: 'claude-code',
  researcher_type: 'vanilla',
  harness_engine: 'claude-code',
  prompt: 'Train model\nUse three epochs.',
  owner_user_id: 'user-1',
  exit_code: null,
  status: 'running',
  workspace_summary: {
    workspace_id: workspace.workspace_id,
    label: workspace.label,
    description: workspace.description,
    default_workdir: workspace.default_workdir,
  },
  environment_summary: {
    environment_id: environment.id,
    alias: environment.alias,
    display_name: environment.display_name,
    host: environment.host,
    default_workdir: environment.default_workdir,
  },
  created_at: '2026-04-23T08:00:00Z',
  updated_at: '2026-04-23T08:01:00Z',
  started_at: '2026-04-23T08:00:10Z',
  completed_at: null,
  error_summary: null,
  latest_output_seq: 1,
};

const reviewTaskSummary: TaskSummary = {
  ...taskSummary,
  task_id: 'task-review',
  title: 'Review paper draft',
  status: 'queued',
  workspace_summary: {
    ...taskSummary.workspace_summary,
    label: 'Paper Workspace',
  },
  environment_summary: {
    ...taskSummary.environment_summary,
    alias: 'cpu-lab',
    display_name: 'CPU Lab',
  },
  created_at: '2026-04-23T09:00:00Z',
  updated_at: '2026-04-23T09:01:00Z',
  started_at: null,
  latest_output_seq: 4,
};

const taskRecord: TaskRecord = {
  ...taskSummary,
  binding: {
    workspace: taskSummary.workspace_summary,
    environment: taskSummary.environment_summary,
    task_profile: 'claude-code',
    title: 'Train model',
    task_input: 'Train model\nUse three epochs.',
    resolved_workdir: '/workspace/project',
    snapshot_path: '.ainrf/runtime/task-harness/tasks/task-1/binding_snapshot.json',
  },
  prompt_detail: {
    rendered_prompt: '[Task input]\nTrain model',
    layer_order: ['global_harness_system', 'workspace', 'environment', 'task_profile', 'task_input'],
    layers: [
      {
        position: 1,
        name: 'task_input',
        label: 'Task input',
        content: 'Train model\nUse three epochs.',
        char_count: 28,
      },
    ],
    manifest_path: '.ainrf/runtime/task-harness/tasks/task-1/prompt_layer_manifest.json',
  },
  runtime: {
    runner_kind: 'local-process',
    working_directory: '/workspace/project',
    command: ['claude', '-p'],
    prompt_file: '.ainrf/runtime/task-harness/tasks/task-1/rendered_prompt.txt',
    helper_path: null,
    launch_payload_path: '.ainrf/runtime/task-harness/tasks/task-1/resolved_launch_payload.json',
  },
  result: {
    exit_code: null,
    failure_category: null,
    error_summary: null,
    completed_at: null,
  },
};

function createOutputEvent(
  seq: number,
  overrides: Partial<TaskOutputEvent> = {}
): TaskOutputEvent {
  return {
    task_id: 'task-1',
    seq,
    kind: 'stdout',
    content: `line ${seq}`,
    created_at: `2026-04-23T08:01:0${seq}Z`,
    ...overrides,
  };
}

function createOutputPage(
  items: TaskOutputEvent[],
  nextSeq: number = items.reduce((maxSeq, item) => Math.max(maxSeq, item.seq), 0)
): TaskOutputListResponse {
  return {
    items,
    next_seq: nextSeq,
  };
}

vi.mock('@/shared/api', () => ({
  buildTaskStreamUrl: vi.fn(),
  createTask: vi.fn(),
  getCodexDefaults: vi.fn(() => Promise.resolve({ codex_config_toml: null, codex_auth_json: null })),
  getEnvironments: vi.fn(),
  getProjectEnvironmentReferences: vi.fn(),
  getProjects: vi.fn(),
  getSkills: vi.fn(),
  getTask: vi.fn(),
  getTaskOutput: vi.fn(),
  getTaskMessages: vi.fn(),
  getTasks: vi.fn(),
  getWorkspaces: vi.fn(),
}));

vi.mock('@features/domain', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/domain')>();
  return {
    ...actual,
    getDomainCapabilities: vi.fn(() => Promise.resolve({
      domain_contract_version: 2,
      mode: 'v2',
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
        registered_participant_ids: ['dispatcher'],
        active_participant_ids: ['dispatcher'],
        fresh_participant_ids: ['dispatcher'],
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
    })),
    getDomainProjects: vi.fn(() => Promise.resolve({
      items: [{
        project_id: 'default',
        name: 'Default Project',
        description: '',
        status: 'active',
        is_default: true,
        owner_user_id: 'user-1',
        current_user_role: 'owner',
        created_at: '2026-04-23T08:00:00Z',
        updated_at: '2026-04-23T08:00:00Z',
        recent_activity_at: '2026-04-23T08:00:00Z',
        workspace_count: 1,
        executable_workspace_count: 1,
        task_count: 1,
        active_task_count: 1,
        running_task_count: 1,
        primary_workspace: null,
        attention_required: false,
        attention_reasons: [],
        permissions: {
          can_edit: true,
          can_publish: true,
          can_manage_members: true,
          can_archive: false,
          can_unarchive: false,
          can_create_task: true,
        },
      }],
    })),
    getDomainWorkspaces: vi.fn(() => Promise.resolve({
      items: [{
        workspace_id: 'workspace-default',
        label: 'Repository Default',
        description: 'Seed workspace',
        canonical_path: '/workspace/project',
        workspace_context: null,
        status: 'active',
        owner_user_id: 'user-1',
        created_at: '2026-04-23T08:00:00Z',
        updated_at: '2026-04-23T08:00:00Z',
        recent_activity_at: '2026-04-23T08:00:00Z',
        environment: {
          environment_id: 'env-1',
          alias: 'gpu-lab',
          display_name: 'GPU Lab',
          status: 'active',
        },
        project_links: [{
          project_id: 'default',
          project_name: 'Default Project',
          project_status: 'active',
          current_user_role: 'owner',
          link_status: 'active',
          is_primary: true,
          can_execute: true,
          cannot_execute_reason: null,
        }],
        task_count: 1,
        active_task_count: 1,
        can_execute: true,
        cannot_execute_reason: null,
        can_manage_registry: true,
        git_status: { state: 'not_collected', branch: null, is_dirty: null, observed_at: null },
      }],
    })),
  };
});

const mockBuildTaskStreamUrl = vi.mocked(buildTaskStreamUrl);
const mockCreateTask = vi.mocked(createTask);
const mockGetCodexDefaults = vi.mocked(getCodexDefaults);
const mockGetEnvironments = vi.mocked(getEnvironments);
const mockGetProjectEnvironmentReferences = vi.mocked(getProjectEnvironmentReferences);
const mockGetProjects = vi.mocked(getProjects);
const mockGetTask = vi.mocked(getTask);
const mockGetTaskOutput = vi.mocked(getTaskOutput);
const mockGetTaskMessages = vi.mocked(getTaskMessages);
const mockGetSkills = vi.mocked(getSkills);
const mockGetTasks = vi.mocked(getTasks);
const mockGetWorkspaces = vi.mocked(getWorkspaces);

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  stubTaskViewport(false);
  MockEventSource.instances = [];
  vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource);
  window.localStorage.clear();

  mockBuildTaskStreamUrl.mockReset();
  mockCreateTask.mockReset();
  mockGetCodexDefaults.mockReset();
  mockGetEnvironments.mockReset();
  mockGetProjectEnvironmentReferences.mockReset();
  mockGetProjects.mockReset();
  mockGetTask.mockReset();
  mockGetTaskOutput.mockReset();
  mockGetSkills.mockReset();
  mockGetTasks.mockReset();
  mockGetTaskMessages.mockReset();
  mockGetWorkspaces.mockReset();

  mockBuildTaskStreamUrl.mockImplementation(
    (taskId, afterSeq = 0) => `/api/tasks/${taskId}/stream?after_seq=${afterSeq}`
  );
  mockGetCodexDefaults.mockResolvedValue({
    codex_config_toml: null,
    codex_auth_json: null,
  });
  mockGetWorkspaces.mockResolvedValue({ items: [workspace] });
  mockGetEnvironments.mockResolvedValue({ items: [environment] });
  mockGetSkills.mockResolvedValue({ items: availableSkills });
  mockGetProjects.mockResolvedValue({ items: [project] });
  mockGetProjectEnvironmentReferences.mockResolvedValue({ items: [] });
  mockGetTasks.mockResolvedValue({ items: [taskSummary] });
  mockGetTaskMessages.mockResolvedValue({ messages: [], has_more: false, next_sequence: null });
  mockGetTask.mockResolvedValue(taskRecord);
  mockGetTaskOutput.mockImplementation(async (taskId) =>
    createOutputPage([
      createOutputEvent(1, {
        task_id: taskId,
        content: 'first line',
        created_at: '2026-04-23T08:01:05Z',
      }),
    ])
  );
});

describe('task output helpers', () => {
  it('deduplicates output by seq and keeps ascending order', () => {
    const merged = mergeOutputItems(
      [createOutputEvent(3, { content: 'stale third line' }), createOutputEvent(1, { content: 'first line' })],
      [createOutputEvent(2, { content: 'second line' }), createOutputEvent(3, { content: 'fresh third line' })]
    );

    expect(merged.map((item) => item.seq)).toEqual([1, 2, 3]);
    expect(merged[2]?.content).toBe('fresh third line');
    expect(getNextOutputSeq([merged[1]!, merged[0]!], 3)).toBe(3);
  });

  it('suppresses agent-sdk thinking token lifecycle noise from message conversion', () => {
    const message = convertOutputEventToMessage(
      createOutputEvent(2, {
        kind: 'lifecycle',
        content:
          '{"event_type":"system","payload":{"subtype":"thinking_tokens","data":{"estimated_tokens":8,"estimated_tokens_delta":3}},"token_usage":null}',
      })
    );

    expect(message).toBeNull();
  });

  it('keeps streaming thinking blocks folded by default', () => {
    const message = convertOutputEventToMessage(
      createOutputEvent(3, {
        kind: 'thinking',
        content:
          '{"content":"working","block_id":"thinking-1","is_partial":true,"is_delta":true}',
      })
    );

    expect(message).not.toBeNull();
    expect(message?.type).toBe('thinking');
    expect(message?.metadata.isFolded).toBe(true);
    expect(message?.metadata.isStreaming).toBe(true);
  });

  it('merges thinking deltas sharing the same block_id into a single display block', () => {
    const merged = mergeMessages([
      {
        id: 'task-1-1',
        type: 'thinking',
        content: 'first pass',
        metadata: { sequence: 1, timestamp: '2026-01-01T00:00:00Z', isFolded: true, blockId: 'thinking-1', isDelta: true },
      },
      {
        id: 'task-1-2',
        type: 'thinking',
        content: 'second pass',
        metadata: { sequence: 2, timestamp: '2026-01-01T00:00:01Z', isFolded: true, blockId: 'thinking-1', isDelta: true, isStreaming: true },
      },
    ]);

    expect(merged).toHaveLength(1);
    expect(merged[0]?.content).toBe('first passsecond pass');
    expect(merged[0]?.metadata.sequence).toBe(2);
    expect(merged[0]?.metadata.isStreaming).toBe(true);
  });

  it('merges stream deltas back into a single block', () => {
    const initial = convertOutputEventToMessage(
      createOutputEvent(7, {
        kind: 'thinking',
        content:
          '{"content":"alpha","block_id":"thinking-2","is_partial":true,"is_delta":true}',
      })
    );
    const next = convertOutputEventToMessage(
      createOutputEvent(8, {
        kind: 'thinking',
        content:
          '{"content":"beta","block_id":"thinking-2","is_partial":true,"is_delta":true}',
      })
    );

    expect(initial).not.toBeNull();
    expect(next).not.toBeNull();

    const merged = mergeMessages([initial!, next!]);

    expect(merged).toHaveLength(1);
    expect(merged[0]?.content).toBe('alphabeta');
    expect(merged[0]?.metadata.sequence).toBe(8);
  });
});

describe('TasksPage', () => {
  it('uses a list-first task flow on narrow screens and opens the inspector as a sheet', async () => {
    stubTaskViewport(true);

    renderWithProviders(<TasksPage />, { route: '/tasks' });

    expect(await screen.findByTestId('task-mobile-list')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Train model' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-metadata-sidebar')).not.toBeInTheDocument();
    expect(screen.queryByRole('separator')).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: /Train model/ }));

    expect(await screen.findByRole('heading', { name: 'Train model' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back to task list' })).toBeInTheDocument();
    expect(screen.queryByTestId('task-mobile-list')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show details' }));
    expect(await screen.findByRole('dialog', { name: 'Task inspector' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Task inspector' })).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Back to task list' }));
    expect(await screen.findByTestId('task-mobile-list')).toBeInTheDocument();
  });

  it('opens an explicit task deep link directly on narrow screens', async () => {
    stubTaskViewport(true);

    renderWithProviders(<TasksPage />, { route: '/tasks?task=task-1&drawer=closed' });

    expect(await screen.findByRole('heading', { name: 'Train model' })).toBeInTheDocument();
    expect(screen.queryByTestId('task-mobile-list')).not.toBeInTheDocument();
  });

  it('applies the standard page inset around the split layout', async () => {
    const { container } = renderWithProviders(<TasksPage />);

    const sidebar = await screen.findByTestId('task-sidebar');
    expect(sidebar).toHaveClass('bg-[var(--surface)]');
    expect(sidebar.parentElement?.querySelector('main')).toHaveClass('bg-[var(--surface)]');
    expect(await screen.findByTestId('task-metadata-sidebar')).toHaveClass('bg-[var(--surface)]');
    expect(container.firstElementChild).toHaveClass('p-3');
  });

  it('creates a task with derived title semantics and keeps it selected after list refresh', async () => {
    const createdSummary: TaskSummary = {
      ...taskSummary,
      task_id: 'task-2',
      title: 'Implement harness',
      status: 'queued',
      updated_at: '2026-04-23T08:02:00Z',
    };
    const createdRecord: TaskRecord = {
      ...taskRecord,
      ...createdSummary,
      binding: {
        ...taskRecord.binding!,
        title: 'Implement harness',
        task_input: 'Implement harness\nMake it stream output.',
        resolved_workdir: '/workspace/created',
        snapshot_path: '.ainrf/runtime/task-harness/tasks/task-2/binding_snapshot.json',
      },
      prompt_detail: {
        ...taskRecord.prompt_detail!,
        rendered_prompt: '[Task input]\nImplement harness',
        manifest_path: '.ainrf/runtime/task-harness/tasks/task-2/prompt_layer_manifest.json',
        layers: [
          {
            position: 1,
            name: 'task_input',
            label: 'Task input',
            content: 'Implement harness\nMake it stream output.',
            char_count: 35,
          },
        ],
      },
      runtime: {
        ...taskRecord.runtime!,
        working_directory: '/workspace/created',
        prompt_file: '.ainrf/runtime/task-harness/tasks/task-2/rendered_prompt.txt',
        launch_payload_path: '.ainrf/runtime/task-harness/tasks/task-2/resolved_launch_payload.json',
      },
    };

    mockGetTasks.mockResolvedValueOnce({ items: [] });
    mockCreateTask.mockResolvedValue(createdSummary);
    mockGetTask.mockImplementation(async (taskId) => (taskId === 'task-2' ? createdRecord : taskRecord));
    mockGetTaskOutput.mockImplementation(async (taskId) =>
      createOutputPage([
        createOutputEvent(1, {
          task_id: taskId,
          content: taskId === 'task-2' ? 'created line' : 'first line',
        }),
      ])
    );
    const client = createTestQueryClient();

    renderWithProviders(<TasksPage />, { client });
    fireEvent.click(await screen.findByRole('button', { name: 'New task' }));
    await waitFor(() => expect(screen.getByLabelText('Execution Engine')).toHaveValue('claude-code'));

    fireEvent.click(await screen.findByRole('button', { name: 'Show skills in research' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select Analysis' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select Code Review' }));
    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: 'Implement harness\nMake it stream output.' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Create task' })).toBeEnabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() => {
      const payload = mockCreateTask.mock.calls[0]?.[0];
      expect(payload).toMatchObject({
        project_id: 'default',
        workspace_id: 'workspace-default',
        researcher_type: 'vanilla',
        harness_engine: 'claude-code',
        prompt: 'Implement harness\nMake it stream output.',
        skills: ['analysis', 'code-review'],
        mcp_servers: [],
        title: undefined,
      });
      expect(payload).not.toHaveProperty('environment_id');
    });
    expect(await screen.findByRole('heading', { name: 'Implement harness' })).toBeInTheDocument();
    expect((await screen.findAllByText('/workspace/created')).length).toBeGreaterThan(0);
    expect(await screen.findByText('created line')).toBeInTheDocument();
    await waitFor(() => expect(mockBuildTaskStreamUrl).toHaveBeenCalledWith('task-2', 1));

    act(() => {
      client.setQueryData(['tasks'], { items: [taskSummary, createdSummary] });
    });

    await waitFor(() => expect(screen.getByText('created line')).toBeInTheDocument());
    expect(screen.getByRole('heading', { name: 'Implement harness' })).toBeInTheDocument();
  });

  it('shows grouped skill chips and toggles selected skills without using raw comma input', async () => {
    mockGetTasks.mockResolvedValueOnce({ items: [] });
    const client = createTestQueryClient();

    mockCreateTask.mockResolvedValue({
      ...taskSummary,
      task_id: 'task-skill-picker',
      title: 'Use selected skills for this task',
      status: 'queued',
    });
    renderWithProviders(<TasksPage />, { client });
    fireEvent.click(await screen.findByRole('button', { name: 'New task' }));

    expect(await screen.findByText('research')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('analysis, code-review')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show skills in research' }));
    const analysisButton = screen.getByRole('button', { name: 'Select Analysis' });
    fireEvent.click(analysisButton);
    expect(screen.getByRole('button', { name: 'Deselect Analysis' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: 'Use selected skills for this task.' },
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create task' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() => {
      expect(mockCreateTask.mock.calls[0]?.[0]).toMatchObject({
        skills: ['analysis'],
      });
    });
  });

  it('derives the environment from the selected executable workspace', async () => {
    mockGetTasks.mockResolvedValueOnce({ items: [] });
    mockCreateTask.mockResolvedValue({
      ...taskSummary,
      task_id: 'task-selected-bindings',
      title: 'Selected bindings',
      status: 'queued',
    });

    renderWithProviders(<TasksPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'New task' }));

    await waitFor(() => expect(screen.getByLabelText('Project')).toHaveValue('default'));
    expect(screen.getByLabelText('Environment')).toHaveValue('GPU Lab (gpu-lab)');
    expect(screen.getByLabelText('Environment')).toHaveAttribute('readonly');
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Run with selected bindings.' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create task' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() => {
      expect(mockCreateTask.mock.calls[0]?.[0]).toMatchObject({
        project_id: 'default',
        workspace_id: 'workspace-default',
        prompt: 'Run with selected bindings.',
      });
      expect(mockCreateTask.mock.calls[0]?.[0]).not.toHaveProperty('environment_id');
    });
  });

  it('applies the selected task preset when creating a task', async () => {
    mockGetTasks.mockResolvedValueOnce({ items: [] });
    mockCreateTask.mockResolvedValue({
      ...taskSummary,
      task_id: 'task-reproduce-preset',
      title: 'Reproduce baseline',
      status: 'queued',
      harness_engine: 'codex-app-server',
    });

    renderWithProviders(<TasksPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'New task' }));

    const presetSelect = await screen.findByLabelText('Task preset');
    expect(within(presetSelect).getAllByRole('option')).toHaveLength(4);
    fireEvent.change(presetSelect, { target: { value: 'reproduce-baseline-default' } });
    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: 'Reproduce the baseline experiment.' },
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create task' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() => {
      expect(mockCreateTask.mock.calls[0]?.[0]).toMatchObject({
        researcher_type: 'vanilla',
        harness_engine: 'codex-app-server',
        prompt: 'Reproduce the baseline experiment.',
      });
    });
  });

  it('selects a task from the task query param and keeps selection in the URL', async () => {
    const reviewRecord: TaskRecord = {
      ...taskRecord,
      ...reviewTaskSummary,
      binding: {
        ...taskRecord.binding!,
        title: reviewTaskSummary.title,
        task_input: 'Review paper draft',
        resolved_workdir: '/workspace/paper',
      },
      runtime: {
        ...taskRecord.runtime!,
        working_directory: '/workspace/paper',
      },
    };
    mockGetTasks.mockResolvedValue({ items: [taskSummary, reviewTaskSummary] });
    mockGetTask.mockImplementation(async (taskId) =>
      taskId === 'task-review' ? reviewRecord : taskRecord
    );
    mockGetTaskOutput.mockImplementation(async (taskId) =>
      createOutputPage([
        createOutputEvent(1, {
          task_id: taskId,
          content: taskId === 'task-review' ? 'review output' : 'train output',
        }),
      ])
    );

    renderWithProviders(<TasksPage />, { route: '/tasks?task=task-review' });

    expect(await screen.findByRole('heading', { name: 'Review paper draft' })).toBeInTheDocument();
    expect((await screen.findAllByText('/workspace/paper')).length).toBeGreaterThan(0);
    expect(await screen.findByText('review output')).toBeInTheDocument();
    await waitFor(() => expect(mockGetTask).toHaveBeenCalledWith('task-review'));

    fireEvent.click(screen.getByRole('button', { name: /Train model/ }));

    await waitFor(() => expect(mockGetTask).toHaveBeenCalledWith('task-1'));
    expect(await screen.findByRole('heading', { name: 'Train model' })).toBeInTheDocument();
  });

  it('filters tasks from the sidebar search without changing the active task', async () => {
    mockGetTasks.mockResolvedValue({ items: [taskSummary, reviewTaskSummary] });

    renderWithProviders(<TasksPage />, { route: '/tasks?task=task-1' });
    expect(await screen.findByRole('heading', { name: 'Train model' })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Search tasks'), {
      target: { value: 'paper' },
    });

    expect(screen.getByRole('button', { name: /Review paper draft/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Train model/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Train model' })).toBeInTheDocument();
  });

  it('resizes the task sidebar by dragging the splitter', async () => {
    renderWithProviders(<TasksPage />);

    await screen.findByRole('heading', { name: 'Train model' });
    const splitter = screen.getAllByRole('separator', { name: 'Resize sidebar' })[0];
    const sidebar = screen.getByTestId('task-sidebar');

    expect(sidebar).toHaveStyle({ width: '320px' });

    fireEvent.pointerDown(splitter, { pointerId: 1, clientX: 320 });
    fireEvent.pointerMove(window, { pointerId: 1, clientX: 420 });
    fireEvent.pointerUp(window, { pointerId: 1 });

    expect(sidebar).toHaveStyle({ width: '420px' });
    expect(splitter).toHaveAttribute('aria-valuenow', '420');
  });

  it('renders task page copy from Chinese i18n messages', async () => {
    renderWithProviders(<TasksPage />, { locale: 'zh' });

    expect(await screen.findByRole('heading', { name: 'Agent 任务' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新建任务' })).toBeInTheDocument();
    expect(screen.getByLabelText('搜索任务')).toBeInTheDocument();
    expect(await screen.findByText('任务工作区')).toBeInTheDocument();
    expect(screen.getByText('摘要')).toBeInTheDocument();
    expect(screen.getByText('工作目录')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '新建任务' }));
    expect(screen.getByRole('dialog', { name: '创建任务' })).toBeInTheDocument();
    expect(screen.getByLabelText('研究员类型')).toBeInTheDocument();
    expect(screen.getByLabelText('执行引擎')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('可选任务标题')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('输入研究任务提示词…')).toBeInTheDocument();
  });

  it('creates a task from a dialog and selects it through the URL', async () => {
    const createdSummary: TaskSummary = {
      ...taskSummary,
      task_id: 'task-created-dialog',
      title: 'Dialog task',
      status: 'queued',
    };
    const createdRecord: TaskRecord = {
      ...taskRecord,
      ...createdSummary,
      binding: {
        ...taskRecord.binding!,
        title: 'Dialog task',
        task_input: 'Dialog task body',
        resolved_workdir: '/workspace/dialog',
      },
    };
    mockCreateTask.mockResolvedValue(createdSummary);
    mockGetTask.mockImplementation(async (taskId) =>
      taskId === 'task-created-dialog' ? createdRecord : taskRecord
    );
    mockGetTaskOutput.mockImplementation(async (taskId) =>
      createOutputPage([
        createOutputEvent(1, {
          task_id: taskId,
          content: taskId === 'task-created-dialog' ? 'dialog output' : 'first line',
        }),
      ])
    );

    renderWithProviders(<TasksPage />);
    await screen.findByRole('heading', { name: 'Train model' });

    fireEvent.click(screen.getByRole('button', { name: 'New task' }));
    expect(screen.getByRole('dialog', { name: 'Create task' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Dialog task' } });
    fireEvent.change(screen.getByLabelText('Execution Engine'), { target: { value: 'agent-sdk' } });
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Dialog task body' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create task' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() => {
      expect(mockCreateTask).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Dialog task',
          prompt: 'Dialog task body',
          harness_engine: 'agent-sdk',
          researcher_type: 'vanilla',
        }),
        expect.stringMatching(/^task\.create/),
      );
    });

    await waitFor(() => expect(mockGetTask).toHaveBeenCalledWith('task-created-dialog'));
    expect(screen.queryByRole('dialog', { name: 'Create task' })).not.toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Dialog task' })).toBeInTheDocument();
    expect(await screen.findByText('dialog output')).toBeInTheDocument();
  });

  it('clears old output and binds a fresh stream when switching tasks', async () => {
    const reviewRecord: TaskRecord = {
      ...taskRecord,
      ...reviewTaskSummary,
    };
    mockGetTasks.mockResolvedValue({ items: [taskSummary, reviewTaskSummary] });
    mockGetTask.mockImplementation(async (taskId) =>
      taskId === 'task-review' ? reviewRecord : taskRecord
    );
    mockGetTaskOutput.mockImplementation(async (taskId) =>
      createOutputPage([
        createOutputEvent(1, {
          task_id: taskId,
          content: taskId === 'task-review' ? 'review output' : 'train output',
        }),
      ])
    );

    renderWithProviders(<TasksPage />);
    expect(await screen.findByText('train output')).toBeInTheDocument();
    const firstSource = MockEventSource.instances[0];

    fireEvent.click(screen.getByRole('button', { name: /Review paper draft/ }));

    await waitFor(() => expect(firstSource.close).toHaveBeenCalled());
    expect(await screen.findByText('review output')).toBeInTheDocument();
    expect(screen.queryByText('train output')).not.toBeInTheDocument();
    await waitFor(() => expect(mockBuildTaskStreamUrl).toHaveBeenCalledWith('task-review', 1));
  });

  it('closes the create dialog with Escape', async () => {
    renderWithProviders(<TasksPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'New task' }));

    const dialog = screen.getByRole('dialog', { name: 'Create task' });
    expect(dialog).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('Close')).toHaveFocus());

    fireEvent.keyDown(dialog, { key: 'Escape' });
    fireEvent.transitionEnd(dialog, { propertyName: 'opacity' });

    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Create task' })).not.toBeInTheDocument()
    );
  });

  it('retains only the latest output events in the rendered stream', async () => {
    mockGetTaskOutput.mockResolvedValue(
      createOutputPage(
        Array.from({ length: 505 }, (_, index) =>
          createOutputEvent(index + 1, {
            content: `retained line ${index + 1}`,
          })
        ),
        505
      )
    );

    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('retained line 505')).toBeInTheDocument();
    expect(screen.queryByText('retained line 1')).not.toBeInTheDocument();
  });

  it('renders codex user echoes and wrapped tool events with normalized chat roles', async () => {
    mockGetTaskOutput.mockResolvedValue(
      createOutputPage([
        createOutputEvent(1, { kind: 'message', content: 'hello codex' }),
        createOutputEvent(2, {
          kind: 'message',
          content: '{"role":"user","content":"tell me the time"}',
        }),
        createOutputEvent(3, { kind: 'message', content: 'tell me the time' }),
        createOutputEvent(4, {
          kind: 'tool_call',
          content: '{"event_type":"tool_call","payload":{"id":"call-1","name":"commandExecution","arguments":{"command":"date"}},"token_usage":null}',
        }),
        createOutputEvent(5, {
          kind: 'tool_result',
          content: '{"event_type":"tool_result","payload":{"tool_use_id":"call-1","content":{"status":"failed"},"is_error":true},"token_usage":null}',
        }),
      ])
    );

    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('hello codex')).toBeInTheDocument();
    expect(screen.getAllByText('tell me the time')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'commandExecution' }));
    expect(await screen.findByText(/commandExecution/)).toBeInTheDocument();
  });

  it('coalesces repeated stream gaps into one replay request while refill is in flight', async () => {
    let resolveReplay: (page: TaskOutputListResponse) => void = () => {};
    mockGetTaskOutput
      .mockResolvedValueOnce(createOutputPage([createOutputEvent(1, { content: 'first line' })]))
      .mockImplementationOnce(
        () =>
          new Promise<TaskOutputListResponse>((resolve) => {
            resolveReplay = resolve;
          })
      );

    renderWithProviders(<TasksPage />);
    await screen.findByText('first line');

    const source = MockEventSource.instances[0];
    await act(async () => {
      source.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify(createOutputEvent(4, { content: 'fourth line' })),
        })
      );
      source.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify(createOutputEvent(5, { content: 'fifth line' })),
        })
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockGetTaskOutput).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveReplay(createOutputPage([createOutputEvent(2, { content: 'second line' })], 2));
      await Promise.resolve();
    });

    expect(await screen.findByText('second line')).toBeInTheDocument();
  });

  it('traps focus in the create dialog and restores focus to the opener on close', async () => {
    renderWithProviders(<TasksPage />);

    const opener = await screen.findByRole('button', { name: 'New task' });
    fireEvent.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Create task' });

    // Wait for focus trap to activate and auto-focus the first element
    await waitFor(() => expect(screen.getByLabelText('Close')).toHaveFocus());

    // Shift+Tab from first focusable should cycle to last
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();

    fireEvent.click(screen.getByLabelText('Close'));
    fireEvent.transitionEnd(dialog, { propertyName: 'opacity' });

    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('creates ARIS tasks without vanilla-only skills', async () => {
    renderWithProviders(<TasksPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'New task' }));

    fireEvent.click(screen.getByLabelText('ARIS Researcher'));
    fireEvent.change(screen.getByLabelText('Execution Engine'), {
      target: { value: 'codex-app-server' },
    });
    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: 'Run the ARIS checklist.' },
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create task' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() =>
      expect(mockCreateTask).toHaveBeenCalledWith(
        expect.objectContaining({
          researcher_type: 'aris-researcher',
          harness_engine: 'codex-app-server',
          prompt: 'Run the ARIS checklist.',
          skills: [],
        }),
        expect.stringMatching(/^task\.create/),
      )
    );
    expect(screen.queryByLabelText('Skills')).not.toBeInTheDocument();
  });

  it('renders prompt and replayed output for the selected task', async () => {
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('Train model')).toBeInTheDocument();
    expect(await screen.findByText('Workdir')).toBeInTheDocument();
    expect(screen.getAllByText('Task input')).not.toHaveLength(0);
    expect(screen.getByText('first line')).toBeInTheDocument();
    expect(mockBuildTaskStreamUrl).toHaveBeenCalledWith('task-1', 1);
  });

  it('ignores duplicate and out-of-order stream events', async () => {
    renderWithProviders(<TasksPage />);
    await screen.findByText('Train model');

    const source = MockEventSource.instances[0];
    act(() => {
      source.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify(createOutputEvent(1, { content: 'duplicate first line' })),
        })
      );
      source.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify(createOutputEvent(0, { content: 'older line' })),
        })
      );
      source.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify(createOutputEvent(2, { content: 'second line' })),
        })
      );
    });

    expect(await screen.findByText('second line')).toBeInTheDocument();
    expect(screen.getAllByText('first line')).toHaveLength(1);
    expect(screen.queryByText('duplicate first line')).not.toBeInTheDocument();
    expect(screen.queryByText('older line')).not.toBeInTheDocument();
  });

  it('does not refetch task metadata for non-status lifecycle stream events', async () => {
    renderWithProviders(<TasksPage />);
    await screen.findByText('Train model');
    const source = MockEventSource.instances[0];
    const taskCallsAfterInitialLoad = mockGetTask.mock.calls.length;
    const listCallsAfterInitialLoad = mockGetTasks.mock.calls.length;

    await act(async () => {
      source.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify(
            createOutputEvent(2, {
              kind: 'lifecycle',
              content: '{"event_type":"system","payload":{"subtype":"turn_started"},"token_usage":null}',
            })
          ),
        })
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockGetTask).toHaveBeenCalledTimes(taskCallsAfterInitialLoad);
    expect(mockGetTasks).toHaveBeenCalledTimes(listCallsAfterInitialLoad);
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it('fills SSE gaps by replaying missing output before continuing', async () => {
    mockGetTaskOutput
      .mockResolvedValueOnce(
        createOutputPage([
          createOutputEvent(1, {
            content: 'first line',
            created_at: '2026-04-23T08:01:05Z',
          }),
        ])
      )
      .mockResolvedValueOnce(
        createOutputPage(
          [
            createOutputEvent(2, {
              content: 'second line',
              created_at: '2026-04-23T08:01:06Z',
            }),
          ],
          2
        )
      );

    renderWithProviders(<TasksPage />);
    await screen.findByText('Train model');

    const source = MockEventSource.instances[0];
    await act(async () => {
      source.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify(
            createOutputEvent(3, {
              content: 'third line',
              created_at: '2026-04-23T08:01:07Z',
            })
          ),
        })
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(await screen.findByText('second line')).toBeInTheDocument();
    expect(await screen.findByText('third line')).toBeInTheDocument();
    await waitFor(() => expect(mockGetTaskOutput).toHaveBeenLastCalledWith('task-1', 1));
  });

  it('replays output after stream errors before reconnecting', async () => {
    mockGetTaskOutput
      .mockResolvedValueOnce(
        createOutputPage([
          createOutputEvent(1, {
            content: 'first line',
          }),
        ])
      )
      .mockResolvedValueOnce(
        createOutputPage(
          [
            createOutputEvent(2, {
              content: 'second line',
            }),
          ],
          2
        )
      );

    renderWithProviders(<TasksPage />);
    await screen.findByText('Train model');
    vi.useFakeTimers();

    const source = MockEventSource.instances[0];
    await act(async () => {
      source.onerror?.();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('second line')).toBeInTheDocument();
    expect(mockGetTaskOutput).toHaveBeenLastCalledWith('task-1', 1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(MockEventSource.instances).toHaveLength(2);
    expect(mockBuildTaskStreamUrl).toHaveBeenLastCalledWith('task-1', 2);
  });
});
