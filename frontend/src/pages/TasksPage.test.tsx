import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TasksPage from './TasksPage';
import { renderWithProviders } from '../test/render';
import type {
  EnvironmentRecord,
  TaskOutputListResponse,
  TaskRecord,
  TaskSummary,
  WorkspaceRecord,
} from '../types';
import {
  buildTaskStreamUrl,
  createTask,
  getEnvironments,
  getTask,
  getTaskOutput,
  getTasks,
  getWorkspaces,
} from '../api';

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

const workspace: WorkspaceRecord = {
  workspace_id: 'workspace-default',
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
  latest_detection: null,
};

const taskSummary: TaskSummary = {
  task_id: 'task-1',
  title: 'Train model',
  task_profile: 'claude-code',
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
  prompt: {
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

vi.mock('../api', () => ({
  buildTaskStreamUrl: vi.fn(),
  createTask: vi.fn(),
  getEnvironments: vi.fn(),
  getTask: vi.fn(),
  getTaskOutput: vi.fn(),
  getTasks: vi.fn(),
  getWorkspaces: vi.fn(),
}));

const mockBuildTaskStreamUrl = vi.mocked(buildTaskStreamUrl);
const mockCreateTask = vi.mocked(createTask);
const mockGetEnvironments = vi.mocked(getEnvironments);
const mockGetTask = vi.mocked(getTask);
const mockGetTaskOutput = vi.mocked(getTaskOutput);
const mockGetTasks = vi.mocked(getTasks);
const mockGetWorkspaces = vi.mocked(getWorkspaces);

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource);

  mockBuildTaskStreamUrl.mockReset();
  mockCreateTask.mockReset();
  mockGetEnvironments.mockReset();
  mockGetTask.mockReset();
  mockGetTaskOutput.mockReset();
  mockGetTasks.mockReset();
  mockGetWorkspaces.mockReset();

  mockBuildTaskStreamUrl.mockImplementation((taskId, afterSeq = 0) => `/api/tasks/${taskId}/stream?after_seq=${afterSeq}`);
  mockGetWorkspaces.mockResolvedValue({ items: [workspace] });
  mockGetEnvironments.mockResolvedValue({ items: [environment] });
  mockGetTasks.mockResolvedValue({ items: [taskSummary] });
  mockGetTask.mockResolvedValue(taskRecord);
  mockGetTaskOutput.mockResolvedValue({
    items: [
      {
        task_id: 'task-1',
        seq: 1,
        kind: 'stdout',
        content: 'first line',
        created_at: '2026-04-23T08:01:05Z',
      },
    ],
    next_seq: 1,
  });
});

describe('TasksPage', () => {
  it('creates a task with derived title semantics when title is blank', async () => {
    const created: TaskSummary = {
      ...taskSummary,
      task_id: 'task-2',
      title: 'Implement harness',
      status: 'queued',
    };
    mockGetTasks.mockResolvedValueOnce({ items: [] });
    mockCreateTask.mockResolvedValue(created);

    renderWithProviders(<TasksPage />);

    fireEvent.change(screen.getByLabelText('Task input'), {
      target: { value: 'Implement harness\nMake it stream output.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() =>
      expect(mockCreateTask).toHaveBeenCalledWith({
        workspace_id: 'workspace-default',
        environment_id: 'env-1',
        task_profile: 'claude-code',
        task_input: 'Implement harness\nMake it stream output.',
        title: undefined,
      })
    );
    expect(await screen.findByText('Implement harness')).toBeInTheDocument();
  });

  it('renders prompt and replayed output for the selected task', async () => {
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('Train model')).toBeInTheDocument();
    expect(await screen.findByText('Resolved workdir:')).toBeInTheDocument();
    expect(screen.getByText('Task input')).toBeInTheDocument();
    expect(screen.getByText('first line')).toBeInTheDocument();
    expect(mockBuildTaskStreamUrl).toHaveBeenCalledWith('task-1', 1);
  });

  it('fills SSE gaps by replaying missing output before continuing', async () => {
    mockGetTaskOutput
      .mockResolvedValueOnce({
        items: [
          {
            task_id: 'task-1',
            seq: 1,
            kind: 'stdout',
            content: 'first line',
            created_at: '2026-04-23T08:01:05Z',
          },
        ],
        next_seq: 1,
      })
      .mockResolvedValueOnce({
        items: [
          {
            task_id: 'task-1',
            seq: 2,
            kind: 'stdout',
            content: 'second line',
            created_at: '2026-04-23T08:01:06Z',
          },
        ],
        next_seq: 2,
      } satisfies TaskOutputListResponse);

    renderWithProviders(<TasksPage />);
    await screen.findByText('Train model');

    const source = MockEventSource.instances[0];
    source.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({
          task_id: 'task-1',
          seq: 3,
          kind: 'stdout',
          content: 'third line',
          created_at: '2026-04-23T08:01:07Z',
        }),
      })
    );

    expect(await screen.findByText('second line')).toBeInTheDocument();
    expect(await screen.findByText('third line')).toBeInTheDocument();
    await waitFor(() => expect(mockGetTaskOutput).toHaveBeenLastCalledWith('task-1', 1));
  });
});
