import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TasksPage from '../../src/pages/TasksPage';
import { createTestQueryClient, renderWithProviders } from '@/test-support/render';
import type {
  TaskOutputEvent,
  TaskOutputListResponse,
  TaskSummary,
  TaskSummary,
} from '@features/tasks/types';
import type { EnvironmentRecord } from '@features/environments/types';
import type { SkillItem } from '@features/settings/types';
import {
  createTask,
  forkTask,
  getTask,
  getTaskMessages,
  getTaskOutput,
  getTasks,
  listCanonicalTaskItems,
  retryTask,
  updateTask,
} from '@features/tasks/api';
import { getCodexDefaults, getSkills } from '@features/settings/api';
import { getEnvironments, getProjectEnvironmentReferences } from '@features/environments/api';
import { queryKeys } from '@/shared/api/queryKeys';
import { getDomainProjects } from '@features/domain';

function stubTaskViewport(narrow: boolean): void {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    matches: query === '(max-width: 1023px)' ? narrow : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia);
}

const workspace = {
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

const taskRecord: TaskSummary = {
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

vi.mock('@features/tasks/api', () => ({
  createTask: vi.fn(),
  forkTask: vi.fn(),
  getTask: vi.fn(),
  getTaskOutput: vi.fn(),
  getTaskMessages: vi.fn(),
  getTasks: vi.fn(),
  listCanonicalTaskItems: vi.fn(),
  retryTask: vi.fn(),
  updateTask: vi.fn(),
}));
vi.mock('@features/settings/api', () => ({
  getCodexDefaults: vi.fn(() => Promise.resolve({ codex_config_toml: null, codex_auth_json: null })),
  getSkills: vi.fn(),
}));
vi.mock('@features/environments/api', () => ({
  getEnvironments: vi.fn(),
  getProjectEnvironmentReferences: vi.fn(),
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

vi.mock('@features/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/auth')>();
  return {
    ...actual,
    useAuth: () => ({
      user: { id: 'user-1', username: 'user-1', display_name: 'User One', role: 'member', status: 'active' },
      loading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    }),
  };
});

const mockCreateTask = vi.mocked(createTask);
const mockUpdateTask = vi.mocked(updateTask);
const mockForkTask = vi.mocked(forkTask);
const mockGetCodexDefaults = vi.mocked(getCodexDefaults);
const mockGetEnvironments = vi.mocked(getEnvironments);
const mockGetProjectEnvironmentReferences = vi.mocked(getProjectEnvironmentReferences);
const mockGetTask = vi.mocked(getTask);
const mockGetTaskOutput = vi.mocked(getTaskOutput);
const mockGetTaskMessages = vi.mocked(getTaskMessages);
const mockGetSkills = vi.mocked(getSkills);
const mockGetTasks = vi.mocked(getTasks);
const mockListCanonicalTaskItems = vi.mocked(listCanonicalTaskItems);
const mockRetryTask = vi.mocked(retryTask);
const mockGetDomainProjects = vi.mocked(getDomainProjects);

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  stubTaskViewport(false);
  window.localStorage.clear();

  mockCreateTask.mockReset();
  mockUpdateTask.mockReset();
  mockForkTask.mockReset();
  mockGetCodexDefaults.mockReset();
  mockGetEnvironments.mockReset();
  mockGetProjectEnvironmentReferences.mockReset();
  mockGetTask.mockReset();
  mockGetTaskOutput.mockReset();
  mockGetSkills.mockReset();
  mockGetTasks.mockReset();
  mockListCanonicalTaskItems.mockReset();
  mockGetTaskMessages.mockReset();
  mockRetryTask.mockReset();

  mockGetCodexDefaults.mockResolvedValue({
    codex_config_toml: null,
    codex_auth_json: null,
  });
  mockGetEnvironments.mockResolvedValue({ items: [environment] });
  mockGetSkills.mockResolvedValue({ items: availableSkills });
  mockGetProjectEnvironmentReferences.mockResolvedValue({ items: [] });
  mockGetTasks.mockResolvedValue({ items: [taskSummary] });
  mockGetTaskMessages.mockResolvedValue({ messages: [], has_more: false, next_sequence: null });
  mockListCanonicalTaskItems.mockImplementation(async (taskId) => {
    const page = await mockGetTaskOutput(taskId);
    return page.items.map((item) => ({
      item_id: `${item.task_id}-${item.seq}`,
      task_id: item.task_id,
      turn_id: `turn-${item.task_id}`,
      task_item_seq: item.seq,
      turn_item_seq: item.seq,
      item_type: item.kind === 'message' ? 'agent_message' : item.kind === 'thinking' ? 'reasoning_summary' : item.kind === 'tool_call' ? 'tool_call' : item.kind === 'tool_result' ? 'tool_result' : 'system_notice',
      actor: item.kind === 'message' || item.kind === 'thinking' || item.kind === 'tool_call' ? 'agent' : item.kind === 'tool_result' ? 'tool' : 'system',
      payload: { text: item.content },
      native_provenance: { source: 'test' },
      occurred_at: item.created_at,
      ingested_at: item.created_at,
      persisted_at: item.created_at,
    }));
  });
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
  mockRetryTask.mockResolvedValue({
    submission_id: 'retry-submission', task_id: 'task-1', reserved_turn_id: 'retry-turn',
    status: 'queued', disposition: 'queued',
  });
  mockUpdateTask.mockImplementation(async (taskId, data) => ({
    ...taskSummary,
    task_id: taskId,
    title: data.title ?? taskSummary.title,
  }));
});

describe('TasksPage', () => {
  it('hides failed and cancelled Tasks by default and reveals them on request', async () => {
    const failedTask = { ...taskSummary, task_id: 'task-failed', title: 'Failed task', status: 'failed' as const };
    const cancelledTask = { ...taskSummary, task_id: 'task-cancelled', title: 'Cancelled task', status: 'cancelled' as const };
    mockGetTasks.mockResolvedValue({ items: [taskSummary, failedTask, cancelledTask] });

    renderWithProviders(<TasksPage />, { route: '/tasks?drawer=closed' });

    expect(await screen.findByRole('button', { name: 'Train model' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Failed task' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancelled task' })).not.toBeInTheDocument();
    expect(screen.getByText('1 total · canonical Item polling')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Show failed/cancelled'));

    expect(await screen.findByRole('button', { name: 'Failed task' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancelled task' })).toBeInTheDocument();
    expect(screen.getByText('3 total · canonical Item polling')).toBeInTheDocument();
  });

  it('renames a Task inline from its title and exposes the AI rename placeholder', async () => {
    const renamedTask = { ...taskSummary, title: 'Renamed task' };
    mockUpdateTask.mockResolvedValue(renamedTask);

    renderWithProviders(<TasksPage />, { route: '/tasks?drawer=closed' });

    fireEvent.click(await screen.findByRole('button', { name: 'Task name' }));
    const input = screen.getByRole('textbox', { name: 'Task name' });
    fireEvent.change(input, { target: { value: '  Renamed task  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(mockUpdateTask).toHaveBeenCalledWith(
      'task-1',
      { title: 'Renamed task' },
      expect.stringMatching(/^task\.rename/),
    ));
    expect(await screen.findByText('Renamed task')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh task name with AI' })).toHaveAttribute(
      'title',
      'AI task naming is coming soon',
    );
  });

  it('keeps a newly forked Task selected after the Task list refreshes', async () => {
    const user = userEvent.setup();
    const forkedTask = {
      ...taskSummary,
      task_id: 'task-forked',
      title: 'Forked task',
      status: 'queued' as const,
    };
    const forkedRecord = { ...taskRecord, ...forkedTask };
    mockGetTasks
      .mockResolvedValueOnce({ items: [taskSummary] })
      .mockResolvedValue({ items: [forkedTask, taskSummary] });
    mockGetTask.mockImplementation(async (taskId) => (
      taskId === forkedTask.task_id ? forkedRecord : taskRecord
    ));
    mockForkTask.mockResolvedValue(forkedTask);

    renderWithProviders(<TasksPage />, { route: '/tasks?task=task-1' });

    await screen.findByRole('heading', { name: 'Train model' });
    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Fork Task…' }));
    await user.click(await screen.findByRole('button', { name: 'Fork Task' }));

    expect(await screen.findByRole('heading', { name: 'Forked task' })).toBeInTheDocument();
    await waitFor(() => expect(mockGetTask).toHaveBeenCalledWith('task-forked'));
  });

  it('refreshes the same Task conversation caches after retry', async () => {
    const user = userEvent.setup();
    const failedTask = { ...taskSummary, status: 'failed' as const, project_id: 'project-retry' };
    const failedRecord = { ...taskRecord, ...failedTask };
    mockGetTasks.mockResolvedValue({ items: [failedTask] });
    mockGetTask.mockResolvedValue(failedRecord);
    mockGetDomainProjects.mockResolvedValueOnce({
      items: [{
        project_id: 'project-retry', name: 'Retry Project', description: null, status: 'active',
        is_default: false, owner_user_id: 'user-1', current_user_role: 'owner',
        created_at: '2026-04-23T08:00:00Z', updated_at: '2026-04-23T08:00:00Z',
        recent_activity_at: '2026-04-23T08:00:00Z', workspace_count: 1,
        executable_workspace_count: 1, task_count: 1, active_task_count: 0,
        running_task_count: 0, primary_workspace: null, attention_required: false,
        attention_reasons: [], permissions: {
          can_edit: true, can_publish: true, can_manage_members: true, can_archive: true,
          can_unarchive: false, can_create_task: true,
        },
      }],
    });
    mockRetryTask.mockResolvedValue({
      submission_id: 'retry-submission', task_id: 'task-1', reserved_turn_id: 'retry-turn',
      status: 'queued', disposition: 'queued',
    });
    const client = createTestQueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    renderWithProviders(<TasksPage />, { client, route: '/tasks?task=task-1' });

    await user.click(await screen.findByLabelText('Show failed/cancelled'));
    await screen.findByRole('heading', { name: 'Train model' });
    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Retry as new Turn' }));

    await waitFor(() => expect(mockRetryTask).toHaveBeenCalledWith('task-1', expect.stringMatching(/^task\.retry/)));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.tasks.detail('task-1') });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.tasks.messages('task-1') });
  });

  it('uses a list-first task flow on narrow screens and opens the inspector as a sheet', async () => {
    stubTaskViewport(true);

    renderWithProviders(<TasksPage />, { route: '/tasks' });

    expect(await screen.findByTestId('task-mobile-list')).toHaveClass('w-full', 'flex-1');
    expect(screen.queryByRole('heading', { name: 'Train model' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-metadata-sidebar')).not.toBeInTheDocument();
    expect(screen.queryByRole('separator')).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: /Train model/ }));

    const detailHeading = await screen.findByRole('heading', { name: 'Train model' });
    expect(detailHeading).toBeInTheDocument();
    expect(detailHeading.closest('section')).toHaveClass('w-full', 'flex-1');
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
    expect(sidebar).toHaveClass('bg-[var(--osci-color-surface)]');
    expect(sidebar.querySelector('.p-3')).not.toBeNull();
    expect(sidebar.parentElement?.querySelector('main')).toHaveClass('bg-[var(--osci-color-surface)]');
    expect(await screen.findByTestId('task-metadata-sidebar')).toHaveClass('bg-[var(--osci-color-surface)]');
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
    const createdRecord: TaskSummary = {
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

    mockGetTasks.mockResolvedValueOnce({ items: [] }).mockResolvedValue({ items: [createdSummary] });
    mockCreateTask.mockResolvedValue(createdSummary);
    mockGetTasks
      .mockResolvedValueOnce({ items: [taskSummary] })
      .mockResolvedValue({ items: [createdSummary, taskSummary] });
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
        projectId: 'default',
        workspaceId: 'workspace-default',
        researcherType: 'vanilla',
        harnessEngine: 'claude-code',
        prompt: 'Implement harness\nMake it stream output.',
        skills: ['analysis', 'code-review'],
        mcpServers: [],
        title: undefined,
      });
      expect(payload).not.toHaveProperty('environment_id');
    });
    expect(await screen.findByRole('heading', { name: 'Implement harness' })).toBeInTheDocument();
    expect((await screen.findAllByText('/workspace/created')).length).toBeGreaterThan(0);
    expect(await screen.findByText('created line')).toBeInTheDocument();
    await waitFor(() => expect(mockListCanonicalTaskItems).toHaveBeenCalledWith('task-2'));

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
        projectId: 'default',
        workspaceId: 'workspace-default',
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
        researcherType: 'vanilla',
        harnessEngine: 'codex-app-server',
        prompt: 'Reproduce the baseline experiment.',
      });
    });
  });

  it('selects a task from the task query param and keeps selection in the URL', async () => {
    const reviewRecord: TaskSummary = {
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

    expect(await screen.findByText('TASKS')).toHaveClass('text-[var(--osci-color-primary)]');
    expect(await screen.findByText('Agent 任务')).toBeInTheDocument();
    expect(screen.queryByText('Inspect the current Task conversation and its durable Turn history.')).not.toBeInTheDocument();
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
    const createdRecord: TaskSummary = {
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
          harnessEngine: 'agent-sdk',
          researcherType: 'vanilla',
        }),
        expect.stringMatching(/^task\.create/),
      );
    });

    expect(screen.queryByRole('dialog', { name: 'Create task' })).not.toBeInTheDocument();
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
          researcherType: 'aris-researcher',
          harnessEngine: 'codex-app-server',
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
    expect(mockListCanonicalTaskItems).toHaveBeenCalledWith('task-1');
  });




});
