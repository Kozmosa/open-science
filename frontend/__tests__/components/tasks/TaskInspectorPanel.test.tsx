import { fireEvent, screen } from '@testing-library/react';
import { vi } from 'vitest';
import TaskInspectorPanel from '@features/tasks/components/TaskInspectorPanel';
import { renderWithProviders } from '@/shared/test/render';
import { getDomainTaskAttempts, getDomainTaskContext } from '@features/domain';
import type { TaskRecord } from '@/shared/types';
import { formatTaskDateTime, shortIdentifier } from '@features/tasks/utils/metadataPresentation';

vi.mock('@features/domain', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/domain')>();
  return {
    ...actual,
    getDomainTaskAttempts: vi.fn(),
    getDomainTaskContext: vi.fn(),
  };
});

const task: TaskRecord = {
  task_id: 'task-1',
  project_id: 'project-1',
  workspace_id: 'workspace-1',
  environment_id: 'env-1',
  title: 'Inspect Attempts',
  prompt: 'Inspect Attempts',
  status: 'failed',
  owner_user_id: 'u1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:01:00Z',
  started_at: '2026-01-01T00:00:10Z',
  completed_at: '2026-01-01T00:01:00Z',
  error_summary: 'failed',
};

beforeEach(() => {
  vi.mocked(getDomainTaskAttempts).mockResolvedValue({
    items: [{
      attempt_id: 'attempt-1',
      task_id: 'task-1',
      attempt_seq: 1,
      trigger: 'initial',
      status: 'failed',
      context_snapshot_id: 'snapshot-1',
      context_version_id: 'context-1',
      created_at: '2026-01-01T00:00:00Z',
      started_at: '2026-01-01T00:00:10Z',
      finished_at: '2026-01-01T00:01:00Z',
      duration_ms: 50_000,
      token_usage_json: null,
      cost_usd: 0.0123,
      failure_reason: 'fixture failure',
      stop_reason: null,
      runtime_sessions: [{
        runtime_session_id: 'runtime-session-1234567890-abcdefghijklmnopqrstuvwxyz',
        attempt_id: 'attempt-1',
        status: 'failed',
        engine_name: 'claude-code',
        started_at: '2026-01-01T00:00:10Z',
        finished_at: '2026-01-01T00:01:00Z',
      }],
    }],
  });
  vi.mocked(getDomainTaskContext).mockResolvedValue({
    context_snapshot_id: 'snapshot-1',
    context_version_id: 'context-1',
    fingerprint: 'sha256:fixture',
    content: 'Pinned context',
    source_manifest: [],
    byte_budget: 4096,
    truncated: false,
  });
});

describe('TaskInspectorPanel', () => {
  it('shows durable Attempt trigger, cost, Context Version, and runtime summary', async () => {
    const onViewChange = vi.fn();
    renderWithProviders(
      <TaskInspectorPanel task={task} view="attempts" onViewChange={onViewChange} />,
    );

    expect(await screen.findByText('Attempt 1 · initial')).toBeInTheDocument();
    expect(screen.getByText('$0.0123')).toBeInTheDocument();
    expect(screen.getByText('context-1')).toBeInTheDocument();
    expect(screen.getByText(/claude-code:failed/)).toBeInTheDocument();
    expect(screen.getByText(formatTaskDateTime('2026-01-01T00:00:10Z', 'en'))).toBeInTheDocument();
    expect(screen.queryByText('2026-01-01T00:00:10Z')).not.toBeInTheDocument();
    const runtimeId = 'runtime-session-1234567890-abcdefghijklmnopqrstuvwxyz';
    expect(screen.getByText(shortIdentifier(runtimeId))).toHaveAttribute('title', runtimeId);
    expect(screen.getByRole('button', { name: 'Copy Runtime Session 1' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Context' }));
    expect(onViewChange).toHaveBeenCalledWith('context');
  });

  it('keeps Context identifiers in copyable Technical details', async () => {
    renderWithProviders(
      <TaskInspectorPanel task={task} view="context" onViewChange={vi.fn()} />,
    );

    expect(await screen.findByText('Pinned context')).toBeInTheDocument();
    expect(screen.getByText('Technical details')).toBeInTheDocument();
    expect(screen.getByText('context-1')).toHaveAttribute('title', 'context-1');
    expect(screen.getByRole('button', { name: 'Copy Context Version' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy Context Snapshot' })).toBeInTheDocument();
  });
});
