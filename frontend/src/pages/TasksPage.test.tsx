import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TasksPage from './TasksPage';
import { renderWithProviders } from '../test/render';
import type {
  EnvironmentRecord,
  TaskRecord,
  TaskTerminalBinding,
  TerminalAttachment,
} from '../types';
import {
  cancelTask,
  createTask,
  getTask,
  getTasks,
  getTaskTerminal,
  openTaskTerminal,
} from '../api';

const selectedEnvironment: EnvironmentRecord = {
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
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:00Z',
  latest_detection: null,
};

const runningTerminal: TaskTerminalBinding = {
  task_id: 'task-1',
  binding_id: 'binding-env-1',
  environment_id: 'env-1',
  agent_session_name: 'ainrf:u:mock-daemon:e:env-1:agent',
  window_id: '@1',
  window_name: 'train-task',
  status: 'running',
  mode: 'observe',
  readonly: true,
  last_output_at: '2026-04-22T00:00:02Z',
};

const runningTask: TaskRecord = {
  task_id: 'task-1',
  binding_id: 'binding-env-1',
  environment_id: 'env-1',
  environment_alias: 'gpu-lab',
  title: 'Train Task',
  command: 'python train.py',
  working_directory: '/workspace/project',
  status: 'running',
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:02Z',
  started_at: '2026-04-22T00:00:01Z',
  completed_at: null,
  exit_code: null,
  detail: null,
  terminal: runningTerminal,
};

const cancelledTask: TaskRecord = {
  ...runningTask,
  status: 'cancelled',
  updated_at: '2026-04-22T00:00:05Z',
  completed_at: '2026-04-22T00:00:05Z',
  exit_code: 130,
  terminal: {
    ...runningTerminal,
    status: 'cancelled',
    last_output_at: '2026-04-22T00:00:05Z',
  },
};

const taskAttachment: TerminalAttachment = {
  attachment_id: 'attach-task-1',
  terminal_ws_url: 'ws://127.0.0.1:8000/terminal/attachments/attach-task-1/ws?token=test-token',
  expires_at: '2026-04-22T00:05:00Z',
  binding_id: 'binding-env-1',
  session_id: '@1',
  session_name: 'ainrf:u:mock-daemon:e:env-1:agent',
  environment_id: 'env-1',
  environment_alias: 'gpu-lab',
  target_kind: 'environment-ssh',
  working_directory: '/workspace/project',
  readonly: true,
  mode: 'observe',
  window_id: '@1',
  window_name: 'train-task',
};

vi.mock('../components', () => ({
  EnvironmentSelectorPanel: () => <div data-testid="environment-selector" />,
  TerminalSessionConsole: ({
    terminalWsUrl,
    readonly,
  }: {
    terminalWsUrl: string | null;
    readonly?: boolean;
  }) => (
    <div data-testid="terminal-console">
      {terminalWsUrl ?? 'no-terminal'} {readonly ? 'readonly' : 'interactive'}
    </div>
  ),
  useEnvironmentSelection: () => ({
    selectedEnvironment,
    selectedEnvironmentId: selectedEnvironment.id,
    selectedReference: null,
    isLoading: false,
    loadError: null,
    environments: [selectedEnvironment],
    onSelectEnvironment: vi.fn(),
  }),
}));

vi.mock('../api', () => ({
  cancelTask: vi.fn(),
  createTask: vi.fn(),
  getTask: vi.fn(),
  getTasks: vi.fn(),
  getTaskTerminal: vi.fn(),
  openTaskTerminal: vi.fn(),
}));

const mockGetTasks = vi.mocked(getTasks);
const mockGetTask = vi.mocked(getTask);
const mockGetTaskTerminal = vi.mocked(getTaskTerminal);
const mockCreateTask = vi.mocked(createTask);
const mockCancelTask = vi.mocked(cancelTask);
const mockOpenTaskTerminal = vi.mocked(openTaskTerminal);

beforeEach(() => {
  mockGetTasks.mockReset();
  mockGetTask.mockReset();
  mockGetTaskTerminal.mockReset();
  mockCreateTask.mockReset();
  mockCancelTask.mockReset();
  mockOpenTaskTerminal.mockReset();

  mockGetTasks.mockResolvedValue({ items: [runningTask] });
  mockGetTask.mockResolvedValue(runningTask);
  mockGetTaskTerminal.mockResolvedValue(runningTerminal);
});

describe('TasksPage', () => {
  it('creates a task and inserts it into the list', async () => {
    const createdTask: TaskRecord = {
      ...runningTask,
      task_id: 'task-2',
      title: 'Eval Task',
      command: 'python eval.py',
      terminal: {
        ...runningTerminal,
        task_id: 'task-2',
        window_id: '@2',
        window_name: 'eval-task',
      },
    };
    mockGetTasks.mockResolvedValueOnce({ items: [] });
    mockCreateTask.mockResolvedValue(createdTask);
    mockGetTaskTerminal.mockResolvedValue(createdTask.terminal as TaskTerminalBinding);

    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('No tasks have been created for this environment yet.')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Eval Task' } });
    fireEvent.change(screen.getByLabelText('Command'), { target: { value: 'python eval.py' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() =>
      expect(mockCreateTask).toHaveBeenCalledWith({
        environment_id: 'env-1',
        title: 'Eval Task',
        command: 'python eval.py',
        working_directory: undefined,
      })
    );
    expect(await screen.findByText('Eval Task')).toBeInTheDocument();
  });

  it('opens an observe-only terminal for the selected task', async () => {
    mockOpenTaskTerminal.mockResolvedValue(taskAttachment);

    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('Train Task')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open terminal' }));

    await waitFor(() => expect(mockOpenTaskTerminal).toHaveBeenCalledWith('task-1'));
    expect(await screen.findByTestId('terminal-console')).toHaveTextContent(
      `${taskAttachment.terminal_ws_url} readonly`
    );
  });

  it('cancels the selected task and refreshes the status pill', async () => {
    mockCancelTask.mockResolvedValue(cancelledTask);

    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('Train Task')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(mockCancelTask).toHaveBeenCalledWith('task-1'));
    expect(await screen.findByText('Cancelled')).toBeInTheDocument();
  });
});
