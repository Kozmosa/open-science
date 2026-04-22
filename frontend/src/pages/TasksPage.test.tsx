import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TasksPage from './TasksPage';
import { renderWithProviders } from '../test/render';
import type { EnvironmentRecord, TaskRecord, TaskTerminalBinding, TerminalAttachment } from '../types';
import { cancelTask, createTask, getTask, getTasks, getTaskTerminal, releaseTaskTerminal } from '../api';

const mockNavigate = vi.fn();

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
  agent_session_name: 'ainrf:u:mock-browser-user:e:env-1:agent',
  window_id: '@1',
  window_name: 'train-task',
  binding_status: 'running_observe',
  mode: 'observe',
  readonly: true,
  ownership_user_id: null,
  agent_write_state: 'running',
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

const takenOverTerminal: TaskTerminalBinding = {
  ...runningTerminal,
  binding_status: 'taken_over',
  mode: 'write',
  readonly: false,
  ownership_user_id: 'mock-browser-user',
  agent_write_state: 'paused_by_user',
};

const cancelledTask: TaskRecord = {
  ...runningTask,
  status: 'cancelled',
  updated_at: '2026-04-22T00:00:05Z',
  completed_at: '2026-04-22T00:00:05Z',
  exit_code: 130,
  terminal: {
    ...runningTerminal,
    binding_status: 'completed',
    last_output_at: '2026-04-22T00:00:05Z',
  },
};

const archivedTask: TaskRecord = {
  ...runningTask,
  status: 'completed',
  completed_at: '2026-04-22T00:10:00Z',
  terminal: {
    ...runningTerminal,
    binding_status: 'archived',
  },
};

const releaseAttachment: TerminalAttachment = {
  attachment_id: 'attach-task-1',
  terminal_ws_url: 'ws://127.0.0.1:8000/terminal/attachments/attach-task-1/ws?token=test-token',
  expires_at: '2026-04-22T00:05:00Z',
  binding_id: 'binding-env-1',
  session_id: '@1',
  session_name: 'ainrf:u:mock-browser-user:e:env-1:agent',
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

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../api', () => ({
  cancelTask: vi.fn(),
  createTask: vi.fn(),
  getTask: vi.fn(),
  getTasks: vi.fn(),
  getTaskTerminal: vi.fn(),
  releaseTaskTerminal: vi.fn(),
}));

const mockGetTasks = vi.mocked(getTasks);
const mockGetTask = vi.mocked(getTask);
const mockGetTaskTerminal = vi.mocked(getTaskTerminal);
const mockCreateTask = vi.mocked(createTask);
const mockCancelTask = vi.mocked(cancelTask);
const mockReleaseTaskTerminal = vi.mocked(releaseTaskTerminal);

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem('ainrf.app_user_id', 'mock-browser-user');
  mockNavigate.mockReset();
  mockGetTasks.mockReset();
  mockGetTask.mockReset();
  mockGetTaskTerminal.mockReset();
  mockCreateTask.mockReset();
  mockCancelTask.mockReset();
  mockReleaseTaskTerminal.mockReset();

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

  it('navigates to the terminal route for open and takeover intents', async () => {
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('Train Task')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open terminal' }));
    expect(mockNavigate).toHaveBeenCalledWith(
      '/terminal?environment_id=env-1&task_id=task-1&intent=open'
    );

    fireEvent.click(screen.getByRole('button', { name: 'Take over' }));
    expect(mockNavigate).toHaveBeenCalledWith(
      '/terminal?environment_id=env-1&task_id=task-1&intent=takeover'
    );
  });

  it('releases a taken-over task from the detail panel', async () => {
    mockGetTasks.mockResolvedValue({ items: [{ ...runningTask, terminal: takenOverTerminal }] });
    mockGetTask.mockResolvedValue({ ...runningTask, terminal: takenOverTerminal });
    mockGetTaskTerminal.mockResolvedValue(takenOverTerminal);
    mockReleaseTaskTerminal.mockResolvedValue(releaseAttachment);

    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('Train Task')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Release' }));

    await waitFor(() => expect(mockReleaseTaskTerminal).toHaveBeenCalledWith('task-1'));
  });

  it('cancels the selected task and refreshes the status pill', async () => {
    mockCancelTask.mockResolvedValue(cancelledTask);

    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('Train Task')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(mockCancelTask).toHaveBeenCalledWith('task-1'));
    expect(await screen.findByText('Cancelled')).toBeInTheDocument();
  });

  it('disables terminal attach actions for archived tasks', async () => {
    mockGetTasks.mockResolvedValue({ items: [archivedTask] });
    mockGetTask.mockResolvedValue(archivedTask);
    mockGetTaskTerminal.mockResolvedValue(archivedTask.terminal as TaskTerminalBinding);

    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('Train Task')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open terminal' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Take over' })).toBeDisabled();
  });
});
