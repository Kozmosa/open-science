import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import TaskActionsMenu from '@features/tasks/components/TaskActionsMenu';
import { renderWithProviders } from '@/test-support/render';
import type { TaskSummary } from '@features/tasks/types';

const task: TaskSummary = {
  task_id: 'task-1',
  project_id: 'project-1',
  workspace_id: 'workspace-1',
  environment_id: 'env-1',
  title: 'Failed Task',
  prompt: 'Retry me',
  status: 'failed',
  work_status: 'open',
  owner_user_id: 'u1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:01:00Z',
  started_at: '2026-01-01T00:00:10Z',
  completed_at: '2026-01-01T00:01:00Z',
  error_summary: 'failed',
};

function actions() {
  return {
    onArchive: vi.fn(),
    onUnarchive: vi.fn(),
    onComplete: vi.fn(),
    onReopen: vi.fn(),
    onInterrupt: vi.fn(),
    onRetry: vi.fn(),
    onMove: vi.fn(),
    onFork: vi.fn(),
  };
}

describe('TaskActionsMenu', () => {
  it('keeps core actions visible in a keyboard menu and retries the same Task', async () => {
    const user = userEvent.setup();
    const handlers = actions();
    renderWithProviders(
      <TaskActionsMenu task={task} canMutate disabledReason={null} {...handlers} />,
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Retry as new Turn' }));
    expect(handlers.onRetry).toHaveBeenCalledTimes(1);
  });

  it('disables execution actions when ownership or Project state denies them', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <TaskActionsMenu
        task={task}
        canMutate={false}
        disabledReason="Project archived"
        {...actions()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    expect(await screen.findByRole('menuitem', { name: 'Retry as new Turn' }))
      .toHaveAttribute('data-disabled');
  });

  it('disables the Turn interrupt action while it is pending', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <TaskActionsMenu
        task={{ ...task, status: 'running' }}
        canMutate
        disabledReason={null}
        interruptPending
        {...actions()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    expect(await screen.findByRole('menuitem', { name: 'Interrupt current Turn' }))
      .toHaveAttribute('data-disabled');
  });

  it('gates Complete and Reopen on explicit work status', async () => {
    const user = userEvent.setup();
    const handlers = actions();
    renderWithProviders(
      <TaskActionsMenu task={task} canMutate disabledReason={null} {...handlers} />,
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    expect(await screen.findByRole('menuitem', { name: 'Complete Task' }))
      .not.toHaveAttribute('data-disabled');
    expect(await screen.findByRole('menuitem', { name: 'Reopen Task' }))
      .toHaveAttribute('data-disabled');
  });

  it('keeps Complete available after a succeeded Turn until work is explicitly completed', async () => {
    const user = userEvent.setup();
    const handlers = actions();
    renderWithProviders(
      <TaskActionsMenu
        task={{ ...task, status: 'succeeded', work_status: 'open' }}
        canMutate
        disabledReason={null}
        {...handlers}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    expect(await screen.findByRole('menuitem', { name: 'Complete Task' }))
      .not.toHaveAttribute('data-disabled');
    expect(await screen.findByRole('menuitem', { name: 'Reopen Task' }))
      .toHaveAttribute('data-disabled');
  });

  it('disables the matching lifecycle action while its mutation is pending', async () => {
    const user = userEvent.setup();
    const handlers = actions();
    renderWithProviders(
      <TaskActionsMenu
        task={task}
        canMutate
        disabledReason={null}
        completePending
        {...handlers}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    expect(await screen.findByRole('menuitem', { name: 'Complete Task' }))
      .toHaveAttribute('data-disabled');
  });

  it('localizes lifecycle action labels', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <TaskActionsMenu
        task={{ ...task, work_status: 'completed' }}
        canMutate
        disabledReason={null}
        {...actions()}
      />,
      { locale: 'zh' },
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    expect(await screen.findByRole('menuitem', { name: '完成任务' }))
      .toHaveAttribute('data-disabled');
    expect(await screen.findByRole('menuitem', { name: '重新打开任务' }))
      .not.toHaveAttribute('data-disabled');
  });
});
