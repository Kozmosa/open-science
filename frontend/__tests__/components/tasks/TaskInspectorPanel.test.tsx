import { fireEvent, screen } from '@testing-library/react';
import { vi } from 'vitest';
import TaskInspectorPanel from '@features/tasks/components/TaskInspectorPanel';
import { renderWithProviders } from '@/test-support/render';
import { getDomainTaskContext } from '@features/domain';
import { getTaskTurns } from '@features/tasks/api';
import type { TaskRecord } from '@/shared/types';
import { formatTaskDateTime, shortIdentifier } from '@features/tasks/utils/metadataPresentation';

vi.mock('@features/domain', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/domain')>();
  return {
    ...actual,
    getDomainTaskContext: vi.fn(),
  };
});

vi.mock('@features/tasks/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/tasks/api')>();
  return { ...actual, getTaskTurns: vi.fn() };
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
  vi.mocked(getTaskTurns).mockResolvedValue({
    items: [{
      turn_id: 'turn-1',
      task_id: 'task-1',
      turn_seq: 1,
      status: 'failed',
      context_snapshot_ref: 'snapshot-1',
      started_at: '2026-01-01T00:00:10Z',
      finished_at: '2026-01-01T00:01:00Z',
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
  it('shows durable Turn timing and canonical identifiers', async () => {
    const onViewChange = vi.fn();
    renderWithProviders(
      <TaskInspectorPanel task={task} view="turns" onViewChange={onViewChange} />,
    );

    expect(await screen.findByText('Turn 1')).toBeInTheDocument();
    expect(screen.getByText('snapshot-1')).toBeInTheDocument();
    expect(screen.getByText(formatTaskDateTime('2026-01-01T00:00:10Z', 'en'))).toBeInTheDocument();
    expect(screen.queryByText('2026-01-01T00:00:10Z')).not.toBeInTheDocument();
    expect(screen.getByText(shortIdentifier('turn-1'))).toHaveAttribute('title', 'turn-1');
    expect(screen.getByRole('button', { name: 'Copy Turn ID' })).toBeInTheDocument();

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
