import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TasksPage from './TasksPage';
import { createTestQueryClient, renderWithProviders } from '../test/render';
import { createDefaultWebUiSettings, settingsStorageKey } from '../settings';
import type {
  EnvironmentRecord,
  TaskOutputEvent,
  TaskOutputListResponse,
  TaskRecord,
  TaskSummary,
  WorkspaceRecord,
} from '../types';
import {
  buildTaskStreamUrl,
  createTask,
  getEnvironments,
  getProjectEnvironmentReferences,
  getTask,
  getTaskOutput,
  getTasks,
  getWorkspaces,
} from '../api';
import { getNextOutputSeq, mergeOutputItems } from './tasks/output';

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

const secondaryEnvironment: EnvironmentRecord = {
  ...environment,
  id: 'env-2',
  alias: 'cpu-lab',
  display_name: 'CPU Lab',
  host: 'cpu.example.com',
};

const taskSummary: TaskSummary = {
  task_id: 'task-1',
  project_id: 'default',
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
    project_id: 'default',
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

vi.mock('../api', () => ({
  buildTaskStreamUrl: vi.fn(),
  createTask: vi.fn(),
  getEnvironments: vi.fn(),
  getProjectEnvironmentReferences: vi.fn(),
  getSkills: vi.fn(),
  getTask: vi.fn(),
  getTaskOutput: vi.fn(),
  getTasks: vi.fn(),
  getWorkspaces: vi.fn(),
}));

const mockBuildTaskStreamUrl = vi.mocked(buildTaskStreamUrl);
const mockCreateTask = vi.mocked(createTask);
const mockGetEnvironments = vi.mocked(getEnvironments);
const mockGetProjectEnvironmentReferences = vi.mocked(getProjectEnvironmentReferences);
const mockGetTask = vi.mocked(getTask);
const mockGetTaskOutput = vi.mocked(getTaskOutput);
const mockGetTasks = vi.mocked(getTasks);
const mockGetWorkspaces = vi.mocked(getWorkspaces);

afterEach(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource);
  window.localStorage.clear();

  mockBuildTaskStreamUrl.mockReset();
  mockCreateTask.mockReset();
  mockGetEnvironments.mockReset();
  mockGetProjectEnvironmentReferences.mockReset();
  mockGetTask.mockReset();
  mockGetTaskOutput.mockReset();
  mockGetTasks.mockReset();
  mockGetWorkspaces.mockReset();

  mockBuildTaskStreamUrl.mockImplementation(
    (taskId, afterSeq = 0) => `/api/tasks/${taskId}/stream?after_seq=${afterSeq}`
  );
  mockGetWorkspaces.mockResolvedValue({ items: [workspace] });
  mockGetEnvironments.mockResolvedValue({ items: [environment] });
  mockGetProjectEnvironmentReferences.mockResolvedValue({ items: [] });
  mockGetTasks.mockResolvedValue({ items: [taskSummary] });
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
});

describe('TasksPage', () => {
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
      prompt: {
        ...taskRecord.prompt!,
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
    await waitFor(() => expect(screen.getByLabelText('Environment')).toHaveValue('env-1'));

    fireEvent.change(screen.getByLabelText('Task input'), {
      target: { value: 'Implement harness\nMake it stream output.' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Create task' })).toBeEnabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() => {
      const payload = mockCreateTask.mock.calls[0]?.[0];
      expect(payload).toMatchObject({
        workspace_id: 'workspace-default',
        environment_id: 'env-1',
        task_profile: 'claude-code',
        task_input: 'Implement harness\nMake it stream output.',
        title: undefined,
        execution_engine: 'claude-code',
        research_agent_profile: {
          profile_id: 'claude-code-default',
          label: 'Claude Code Default',
        },
        task_configuration: {
          mode: 'raw_prompt',
          template_id: 'raw-prompt',
          raw_prompt: 'Implement harness\nMake it stream output.',
        },
      });
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
    const splitter = screen.getByRole('separator', { name: 'Resize task list' });
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
    expect(screen.getByText('输出时间线')).toBeInTheDocument();
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
    fireEvent.change(screen.getByLabelText('Task input'), { target: { value: 'Dialog task body' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

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

  it('closes the create dialog with Escape and focuses the task input on open', async () => {
    renderWithProviders(<TasksPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'New task' }));

    const dialog = screen.getByRole('dialog', { name: 'Create task' });
    expect(dialog).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('Task input')).toHaveFocus());

    fireEvent.keyDown(dialog, { key: 'Escape' });

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

    screen.getByLabelText('Close create task').focus();
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(screen.getByRole('button', { name: 'Reset draft' })).toHaveFocus();

    fireEvent.click(screen.getByLabelText('Close create task'));

    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('prefills the draft from environment settings and resets when the environment changes', async () => {
    const settings = createDefaultWebUiSettings();
    settings.projectDefaults.default.defaultEnvironmentId = 'env-1';
    settings.projectDefaults.default.environmentDefaults['env-1'] = {
      titleTemplate: 'GPU batch',
      taskInputTemplate: 'Run the GPU validation checklist.',
      researchAgentProfileId: 'claude-code-default',
      taskConfigurationId: 'raw-prompt',
    };
    settings.projectDefaults.default.environmentDefaults['env-2'] = {
      titleTemplate: 'CPU fallback',
      taskInputTemplate: 'Run the CPU fallback checklist.',
      researchAgentProfileId: 'claude-code-default',
      taskConfigurationId: 'raw-prompt',
    };
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
    mockGetEnvironments.mockResolvedValue({ items: [environment, secondaryEnvironment] });

    renderWithProviders(<TasksPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'New task' }));

    await waitFor(() => expect(screen.getByLabelText('Title')).toHaveValue('GPU batch'));
    expect(screen.getByLabelText('Task input')).toHaveValue('Run the GPU validation checklist.');

    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'edited title' },
    });

    fireEvent.change(screen.getByLabelText('Environment'), {
      target: { value: 'env-2' },
    });

    await waitFor(() => expect(screen.getByLabelText('Title')).toHaveValue('CPU fallback'));
    expect(screen.getByLabelText('Task input')).toHaveValue('Run the CPU fallback checklist.');

    fireEvent.change(screen.getByLabelText('Task input'), {
      target: { value: 'temporary override' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset draft' }));

    await waitFor(() =>
      expect(screen.getByLabelText('Task input')).toHaveValue('Run the CPU fallback checklist.')
    );
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

    expect(await screen.findByText('second line')).toBeInTheDocument();
    expect(screen.getAllByText('first line')).toHaveLength(1);
    expect(screen.queryByText('duplicate first line')).not.toBeInTheDocument();
    expect(screen.queryByText('older line')).not.toBeInTheDocument();
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
