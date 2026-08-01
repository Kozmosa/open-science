vi.mock('@features/terminal/components/TerminalSessionConsole', () => ({
  default: () => <div data-testid="terminal-console" />,
}));

import { StrictMode } from 'react';
import { QueryClient } from '@tanstack/react-query';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TerminalBenchCard from '@features/terminal/components/TerminalBenchCard';
import type { EnvironmentRecord, TerminalSession } from '@/shared/types';
import { renderWithProviders } from '@/test-support/render';
import {
  createTerminalSession,
  deleteTerminalSession,
  getTerminalSession,
  resetTerminalSession,
} from '@features/terminal/api';

vi.mock('@features/terminal/api', () => ({
  createTerminalSession: vi.fn(),
  deleteTerminalSession: vi.fn(),
  getTerminalSession: vi.fn(),
  resetTerminalSession: vi.fn(),
}));

const mockGetTerminalSession = vi.mocked(getTerminalSession);
const mockCreateTerminalSession = vi.mocked(createTerminalSession);
const mockDeleteTerminalSession = vi.mocked(deleteTerminalSession);
const mockResetTerminalSession = vi.mocked(resetTerminalSession);

const idleSession: TerminalSession = {
  session_id: null,
  provider: 'tmux',
  target_kind: 'environment-ssh',
  environment_id: 'env-1',
  environment_alias: 'gpu-lab',
  working_directory: '/workspace/project',
  status: 'idle',
  created_at: null,
  started_at: null,
  closed_at: null,
  terminal_ws_url: null,
  detail: null,
  binding_id: null,
  session_name: 'p-1234567890',
  attachment_id: null,
  attachment_expires_at: null,
};

const runningAttachedSession: TerminalSession = {
  session_id: 'p-1234567890',
  provider: 'tmux',
  target_kind: 'environment-ssh',
  environment_id: 'env-1',
  environment_alias: 'gpu-lab',
  working_directory: '/workspace/project',
  status: 'running',
  created_at: '2026-04-21T00:00:00Z',
  started_at: '2026-04-21T00:00:01Z',
  closed_at: null,
  terminal_ws_url: 'ws://127.0.0.1:8000/terminal/attachments/attach-1/ws?token=test-token',
  detail: null,
  binding_id: 'binding-1',
  session_name: 'p-1234567890',
  attachment_id: 'attach-1',
  attachment_expires_at: '2026-04-21T00:05:01Z',
};

const runningDetachedSession: TerminalSession = {
  ...runningAttachedSession,
  terminal_ws_url: null,
  attachment_id: null,
  attachment_expires_at: null,
};

const resetSession: TerminalSession = {
  ...runningAttachedSession,
  terminal_ws_url: 'ws://127.0.0.1:8000/terminal/attachments/attach-2/ws?token=test-token-2',
  attachment_id: 'attach-2',
  attachment_expires_at: '2026-04-21T00:10:01Z',
};

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
  task_harness_profile: null,
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  code_server_path: null,
  latest_detection: null,
};

beforeEach(() => {
  mockGetTerminalSession.mockReset();
  mockCreateTerminalSession.mockReset();
  mockDeleteTerminalSession.mockReset();
  mockResetTerminalSession.mockReset();
});

describe('TerminalBenchCard', () => {
  it('renders localized terminal session copy without mixing CJK into English', async () => {
    mockGetTerminalSession.mockResolvedValue(idleSession);
    const { unmount } = renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />, {
      locale: 'en',
    });

    expect(await screen.findByRole('heading', { name: 'Personal terminal session' })).toBeInTheDocument();
    expect(screen.getByText('PERSONAL TERMINAL SESSION')).toBeInTheDocument();
    expect(screen.getByTestId('terminal-bench-content').tagName).toBe('DIV');
    expect(screen.queryByText(/Attach, detach, or reset the persistent personal terminal session/)).not.toBeInTheDocument();

    unmount();
    mockGetTerminalSession.mockResolvedValue(idleSession);
    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />, {
      locale: 'zh',
    });

    expect(await screen.findByRole('heading', { name: '个人终端会话' })).toBeInTheDocument();
    expect(screen.getByText('PERSONAL TERMINAL SESSION')).toBeInTheDocument();
    expect(screen.queryByText(/连接、脱离或重置当前环境的持久个人终端会话/)).not.toBeInTheDocument();
  });

  it('renders the idle state from the backend with attach controls', async () => {
    mockGetTerminalSession.mockResolvedValue(idleSession);

    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />);

    expect(await screen.findByText('Status: Idle')).toBeInTheDocument();
    expect(mockGetTerminalSession).toHaveBeenCalledWith('env-1');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open' })).not.toBeDisabled());
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeEnabled();
    expect(screen.getByTestId('terminal-session-controls')).toHaveTextContent('Status: Idle');
    expect(screen.queryByText('Session source')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Details' }));
    const details = screen.getByRole('dialog', { name: 'Session details' });
    expect(details).toHaveTextContent('Session name:');
    expect(details).toHaveTextContent('p-1234567890');
    expect(details).toHaveTextContent('WebSocket URL:');
    expect(screen.getByText('No personal terminal session has been created yet.')).toBeInTheDocument();
    expect(screen.getByTestId('terminal-console')).toBeInTheDocument();
  });

  it('shows changed backend detail in a toast and the details dialog', async () => {
    mockGetTerminalSession.mockResolvedValue({
      ...idleSession,
      status: 'failed',
      detail: 'ssh: Could not resolve hostname',
    });

    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />);

    expect(await screen.findByText('Terminal session details updated: ssh: Could not resolve hostname')).toBeInTheDocument();
    expect(screen.queryByText('Detail: ssh: Could not resolve hostname')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Details' }));
    expect(screen.getByRole('dialog', { name: 'Session details' })).toHaveTextContent('ssh: Could not resolve hostname');
  });

  it('attaches a personal terminal session when the user clicks Attach', async () => {
    mockGetTerminalSession.mockResolvedValue(idleSession);
    mockCreateTerminalSession.mockResolvedValue(runningAttachedSession);

    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />);

    await screen.findByText('Status: Idle');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open' })).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));

    await waitFor(() => expect(mockCreateTerminalSession).toHaveBeenCalledWith('env-1'));
    expect(await screen.findByText('Status: Running')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close' })).toBeEnabled();
  });

  it('keeps a detached running personal session detached until the user clicks Attach', async () => {
    mockGetTerminalSession.mockResolvedValue(runningDetachedSession);
    mockCreateTerminalSession.mockResolvedValue(runningAttachedSession);

    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />);

    expect(await screen.findByText('Status: Running')).toBeInTheDocument();
    expect(screen.getByText('The personal session is still running, but this page is currently detached.')).toBeInTheDocument();
    expect(mockCreateTerminalSession).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Open' }));

    await waitFor(() => expect(mockCreateTerminalSession).toHaveBeenCalledWith('env-1'));
    fireEvent.click(screen.getByRole('button', { name: 'Details' }));
    expect(await screen.findByRole('dialog', { name: 'Session details' })).toHaveTextContent('/terminal/attachments/attach-1/ws');
  });

  it('does not auto-reattach a detached personal session in StrictMode', async () => {
    mockGetTerminalSession.mockResolvedValue(runningDetachedSession);

    renderWithProviders(
      <StrictMode>
        <TerminalBenchCard selectedEnvironment={selectedEnvironment} />
      </StrictMode>
    );

    expect(await screen.findByText('Status: Running')).toBeInTheDocument();
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    });

    expect(mockCreateTerminalSession).not.toHaveBeenCalled();
  });

  it('does not poll or reattach an attached session when the global query client uses interval refetching', async () => {
    mockGetTerminalSession.mockResolvedValue(runningAttachedSession);

    const pollingClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: 0,
          refetchInterval: 10,
          refetchIntervalInBackground: true,
        },
        mutations: {
          retry: false,
        },
      },
    });

    const { unmount } = renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />, {
      client: pollingClient,
    });

    expect(await screen.findByText('Status: Running')).toBeInTheDocument();
    expect(mockGetTerminalSession).toHaveBeenCalledTimes(1);
    expect(mockCreateTerminalSession).not.toHaveBeenCalled();

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    });

    expect(mockGetTerminalSession).toHaveBeenCalledTimes(1);
    expect(mockCreateTerminalSession).not.toHaveBeenCalled();

    unmount();
    pollingClient.clear();
  });

  it('detaches a running attachment without immediately auto-reattaching', async () => {
    mockGetTerminalSession.mockResolvedValue(runningAttachedSession);
    mockDeleteTerminalSession.mockResolvedValue(runningDetachedSession);

    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />);

    expect(await screen.findByText('Status: Running')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    await waitFor(() =>
      expect(mockDeleteTerminalSession).toHaveBeenCalledWith({
        environmentId: 'env-1',
        attachmentId: 'attach-1',
      })
    );
    expect(await screen.findByText('The personal session is still running, but this page is currently detached.')).toBeInTheDocument();
    expect(mockCreateTerminalSession).not.toHaveBeenCalled();
  });

  it('resets the personal session and switches to the new attachment url', async () => {
    mockGetTerminalSession.mockResolvedValue(runningAttachedSession);
    mockResetTerminalSession.mockResolvedValue(resetSession);

    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />);

    expect(await screen.findByText('Status: Running')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));

    await waitFor(() =>
      expect(mockResetTerminalSession).toHaveBeenCalledWith('env-1', 'attach-1')
    );
    fireEvent.click(screen.getByRole('button', { name: 'Details' }));
    expect(await screen.findByRole('dialog', { name: 'Session details' })).toHaveTextContent('/terminal/attachments/attach-2/ws');
  });

  it('surfaces backend load errors', async () => {
    mockGetTerminalSession.mockRejectedValue(new Error('backend offline'));

    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />);

    expect(await screen.findByText('Load error: backend offline')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled();
  });

  it('requires a selected environment before enabling terminal actions', async () => {
    renderWithProviders(<TerminalBenchCard selectedEnvironment={null} />);

    expect(await screen.findByText('Status: Idle')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open' })).toBeDisabled();
    expect(screen.getByText('Select an environment before attaching the terminal session.')).toBeInTheDocument();
    expect(mockGetTerminalSession).not.toHaveBeenCalled();
  });

  it('renders translated Chinese terminal bench copy when locale is zh', async () => {
    mockGetTerminalSession.mockResolvedValue(idleSession);

    renderWithProviders(<TerminalBenchCard selectedEnvironment={selectedEnvironment} />, {
      locale: 'zh',
    });

    expect(await screen.findByText('个人终端会话')).toBeInTheDocument();
    expect(screen.getByText(/状态：\s*空闲/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '打开' })).toBeEnabled());
    expect(screen.getByRole('button', { name: '关闭' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '重置' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '详情' })).toBeEnabled();
    expect(screen.getByText('尚未创建个人终端会话。')).toBeInTheDocument();
  });
});
