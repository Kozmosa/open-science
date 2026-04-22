import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TerminalPage from './TerminalPage';
import { renderWithProviders } from '../test/render';
import type { TaskRecord, TaskTerminalBinding, TerminalAttachment } from '../types';
import { getTask, getTaskTerminal, openTaskTerminal, releaseTaskTerminal, takeoverTaskTerminal } from '../api';

vi.mock('./DashboardPage', () => ({
  default: () => <div data-testid="dashboard-page">dashboard-page</div>,
}));

vi.mock('../components', () => ({
  TerminalSessionConsole: ({
    attachmentId,
    mode,
    readonly,
    onDisconnected,
  }: {
    attachmentId: string | null;
    mode?: 'observe' | 'write';
    readonly?: boolean;
    onDisconnected?: () => void;
  }) => (
    <div data-testid="terminal-console">
      {attachmentId ?? 'no-attachment'} {mode ?? 'observe'} {readonly ? 'readonly' : 'write'}
      <button type="button" onClick={onDisconnected}>
        disconnect
      </button>
    </div>
  ),
}));

vi.mock('../api', () => ({
  getTask: vi.fn(),
  getTaskTerminal: vi.fn(),
  openTaskTerminal: vi.fn(),
  releaseTaskTerminal: vi.fn(),
  takeoverTaskTerminal: vi.fn(),
}));

const mockGetTask = vi.mocked(getTask);
const mockGetTaskTerminal = vi.mocked(getTaskTerminal);
const mockOpenTaskTerminal = vi.mocked(openTaskTerminal);
const mockTakeoverTaskTerminal = vi.mocked(takeoverTaskTerminal);
const mockReleaseTaskTerminal = vi.mocked(releaseTaskTerminal);

const observeBinding: TaskTerminalBinding = {
  task_id: 'task-1',
  binding_id: 'binding-1',
  environment_id: 'env-1',
  agent_session_name: 'ainrf:u:mock-browser-user:e:env-1:agent',
  window_id: '@1',
  window_name: 'train-task',
  binding_status: 'running_observe',
  mode: 'observe',
  readonly: true,
  ownership_user_id: null,
  agent_write_state: 'running',
  last_output_at: '2026-04-22T00:00:05Z',
};

const taskRecord: TaskRecord = {
  task_id: 'task-1',
  binding_id: 'binding-1',
  environment_id: 'env-1',
  environment_alias: 'gpu-lab',
  title: 'Train Task',
  command: 'python train.py',
  working_directory: '/workspace/project',
  status: 'running',
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:05Z',
  started_at: '2026-04-22T00:00:01Z',
  completed_at: null,
  exit_code: null,
  detail: null,
  terminal: observeBinding,
};

const takeoverAttachment: TerminalAttachment = {
  attachment_id: 'attach-1',
  terminal_ws_url: 'ws://127.0.0.1:8000/terminal/attachments/attach-1/ws?token=test-token',
  expires_at: '2026-04-22T00:10:00Z',
  binding_id: 'binding-1',
  session_id: '@1',
  session_name: 'ainrf:u:mock-browser-user:e:env-1:agent',
  environment_id: 'env-1',
  environment_alias: 'gpu-lab',
  target_kind: 'environment-ssh',
  working_directory: '/workspace/project',
  readonly: false,
  mode: 'write',
  window_id: '@1',
  window_name: 'train-task',
};

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem('ainrf.app_user_id', 'mock-browser-user');
  mockGetTask.mockReset();
  mockGetTaskTerminal.mockReset();
  mockOpenTaskTerminal.mockReset();
  mockTakeoverTaskTerminal.mockReset();
  mockReleaseTaskTerminal.mockReset();

  mockGetTask.mockResolvedValue(taskRecord);
  mockGetTaskTerminal.mockResolvedValue(observeBinding);
  mockTakeoverTaskTerminal.mockResolvedValue(takeoverAttachment);
  mockOpenTaskTerminal.mockResolvedValue({
    ...takeoverAttachment,
    attachment_id: 'attach-open',
    readonly: true,
    mode: 'observe',
  });
  mockReleaseTaskTerminal.mockResolvedValue({
    ...takeoverAttachment,
    attachment_id: 'attach-release',
    readonly: true,
    mode: 'observe',
  });
});

describe('TerminalPage', () => {
  it('falls back to the dashboard page when no task id is present', async () => {
    renderWithProviders(<TerminalPage />, { route: '/terminal' });

    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
  });

  it('attaches to a task window with takeover intent', async () => {
    renderWithProviders(<TerminalPage />, {
      route: '/terminal?environment_id=env-1&task_id=task-1&intent=takeover',
    });

    await waitFor(() => expect(mockTakeoverTaskTerminal).toHaveBeenCalledWith('task-1'));
    expect(await screen.findByText('Train Task')).toBeInTheDocument();
    expect(screen.getByTestId('terminal-console')).toHaveTextContent('attach-1 write write');
  });

  it('allows the current intent to attach again after a task-mode disconnect', async () => {
    renderWithProviders(<TerminalPage />, {
      route: '/terminal?environment_id=env-1&task_id=task-1&intent=open',
    });

    await waitFor(() => expect(mockOpenTaskTerminal).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('terminal-console')).toHaveTextContent(
      'attach-open observe readonly'
    );

    screen.getByRole('button', { name: 'disconnect' }).click();

    await waitFor(() => expect(mockOpenTaskTerminal).toHaveBeenCalledTimes(2));
  });
});
