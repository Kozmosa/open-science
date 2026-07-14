import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TaskHeaderBar from '../../../src/components/messages/TaskHeaderBar';
import { renderWithProviders } from '@/shared/test/render';
import type { TaskRecord } from '@/shared/types';
import { updateTask } from '@/shared/api';

vi.mock('@/shared/api', async () => {
  const actual = await vi.importActual('@/shared/api');
  return {
    ...actual,
    updateTask: vi.fn().mockResolvedValue({}),
  };
});

function makeTask(overrides?: Partial<TaskRecord>): TaskRecord {
  return {
    task_id: 'task-1',
    title: 'Research paper analysis',
    status: 'running',
    project_id: 'default',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as TaskRecord;
}

describe('TaskHeaderBar', () => {
  it('renders the task title', () => {
    renderWithProviders(<TaskHeaderBar task={makeTask()} />);
    expect(screen.getByText('Research paper analysis')).toBeInTheDocument();
  });

  it('renders the task status badge', () => {
    renderWithProviders(<TaskHeaderBar task={makeTask({ status: 'running' })} />);
    expect(screen.getByText(/running/i)).toBeInTheDocument();
  });

  it('enters edit mode when title is clicked and commits on Enter', async () => {
    renderWithProviders(<TaskHeaderBar task={makeTask()} />);

    const title = screen.getByText('Research paper analysis');

    // Click the title to enter edit mode — wrap in act for React state updates
    await act(async () => {
      fireEvent.click(title);
    });

    // After clicking, an input should appear with the title as its value
    const input = screen.getByDisplayValue('Research paper analysis');
    expect(input.tagName).toBe('INPUT');

    // Change the value and press Enter
    fireEvent.change(input, { target: { value: 'Updated title' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    // The mutation should have been called
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(
        'task-1',
        { title: 'Updated title' },
        expect.stringMatching(/^task\.rename\.task-1/),
      );
    });
  });

  it('cancels edit mode on Escape and restores original title', async () => {
    renderWithProviders(<TaskHeaderBar task={makeTask()} />);

    fireEvent.click(screen.getByText('Research paper analysis'));

    const input = screen.getByDisplayValue('Research paper analysis');
    fireEvent.change(input, { target: { value: 'Changed but escaped' } });
    fireEvent.keyDown(input, { key: 'Escape' });

    await waitFor(() => {
      expect(screen.getByText('Research paper analysis')).toBeInTheDocument();
    });
  });

  it('shows pause button when showPause is true', () => {
    renderWithProviders(
      <TaskHeaderBar task={makeTask()} showPause onPause={vi.fn()} />
    );
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument();
  });

  it('shows resume button when showResume is true', () => {
    renderWithProviders(
      <TaskHeaderBar task={makeTask()} showResume onResume={vi.fn()} />
    );
    expect(screen.getByRole('button', { name: /resume/i })).toBeInTheDocument();
  });

  it('calls onPause when pause button is clicked', () => {
    const onPause = vi.fn();
    renderWithProviders(
      <TaskHeaderBar task={makeTask()} showPause onPause={onPause} />
    );

    fireEvent.click(screen.getByRole('button', { name: /pause/i }));
    expect(onPause).toHaveBeenCalledTimes(1);
  });

  it('calls onResume when resume button is clicked', () => {
    const onResume = vi.fn();
    renderWithProviders(
      <TaskHeaderBar task={makeTask()} showResume onResume={onResume} />
    );

    fireEvent.click(screen.getByRole('button', { name: /resume/i }));
    expect(onResume).toHaveBeenCalledTimes(1);
  });

  it('renders toggle sidebar button when onToggleTaskSidebar is provided', () => {
    const toggle = vi.fn();
    renderWithProviders(
      <TaskHeaderBar
        task={makeTask()}
        taskSidebarCollapsed={false}
        onToggleTaskSidebar={toggle}
      />
    );

    const button = screen.getByRole('button', { name: /collapse/i });
    fireEvent.click(button);
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('renders metadata toggle button when onToggleMetadataSidebar is provided', () => {
    const toggle = vi.fn();
    renderWithProviders(
      <TaskHeaderBar
        task={makeTask()}
        metadataSidebarOpen
        onToggleMetadataSidebar={toggle}
      />
    );

    const button = screen.getByRole('button', { name: /collapse/i });
    fireEvent.click(button);
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('shows expand label when sidebar is collapsed', () => {
    renderWithProviders(
      <TaskHeaderBar
        task={makeTask()}
        taskSidebarCollapsed
        onToggleTaskSidebar={vi.fn()}
      />
    );

    expect(screen.getByRole('button', { name: /expand/i })).toBeInTheDocument();
  });
});
